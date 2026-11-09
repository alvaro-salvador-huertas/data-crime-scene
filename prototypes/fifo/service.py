"""Loopback-only JSON prototype, with one executor and process-local state."""
from __future__ import annotations

import argparse
from collections import OrderedDict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import time

from data_crime_scene.experiments import run_experiment
from data_crime_scene.laboratory import engine_fingerprint
from ui.public_limits import (PublicBudget, PublicLimitError, MAX_ACTIONS_PER_WINDOW,
                              WINDOW_SECONDS, SESSION_INTERVAL_SECONDS)


class Refusal(Exception):
    def __init__(self, status, reason):
        self.status, self.reason = status, reason


class Scheduler:
    """FIFO admission with 19 waiting slots + one reserved execution slot.

    In reject mode the *original* PublicBudget is entered at admission, and
    remains entered until completion. In FIFO mode it is entered at execution.
    Duplicate (session, case, seed) submissions reuse a job, including failures.
    State is bounded, in memory, and expires only after terminal completion.
    """
    def __init__(self, policy="fifo", queue_size=19, *, engine=run_experiment,
                 clock=time.monotonic, retention=300, trace=None):
        if policy not in ("fifo", "reject") or not 0 <= queue_size <= 19:
            raise ValueError("policy fifo/reject; queue_size 0..19")
        self.policy, self.queue_size = policy, queue_size
        self.engine, self.clock, self.retention = engine, clock, retention
        self.trace = Path(trace) if trace else None
        self.cv = threading.Condition(threading.RLock())
        self.sessions, self.jobs, self.keys = {}, {}, {}
        self.pending, self.starts, self.cache = deque(), deque(), OrderedDict()
        self.active = None
        self.closed = False
        self.budget = PublicBudget(clock=clock)
        self.fingerprint = engine_fingerprint()
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def emit(self, event, **fields):
        # Called under cv; tokens are never written to logs.
        if self.trace:
            with self.trace.open("a") as stream:
                stream.write(json.dumps(dict(event=event, mono=self.clock(), **fields))+"\n")

    def _purge(self):
        now = self.clock()
        for jid, job in list(self.jobs.items()):
            if job.get("finished") is not None and now-job["finished"] >= self.retention:
                del self.keys[(job["owner"], job["case"], job["seed"])]
                del self.jobs[jid]
        owners = {j["owner"] for j in self.jobs.values()}
        for token, session in list(self.sessions.items()):
            if token not in owners and now-session["seen"] >= 900:
                del self.sessions[token]

    def new_session(self):
        with self.cv:
            self._purge()
            if len(self.sessions) >= 64:
                raise Refusal(429, "session_capacity")
            token = secrets.token_urlsafe(32)
            self.sessions[token] = {"seen": self.clock(), "next": 0, "execution": {}}
            return token

    def _session(self, token):
        self._purge()
        if token not in self.sessions:
            raise Refusal(401, "invalid_session")
        session = self.sessions[token]
        session["seen"] = self.clock()
        return session

    def submit(self, token, case, seed):
        if case not in ("future", "groups", "selection") or type(seed) is not int or not 0 <= seed < 2**32:
            raise Refusal(400, "invalid_configuration")
        with self.cv:
            session = self._session(token)
            key = (token, case, seed)
            self.emit("request", case=case, seed=seed)
            if key in self.keys:
                job = self.jobs[self.keys[key]]
                self.emit("duplicate", job=job["id"])
                return self._view(job), True
            if self.closed:
                raise Refusal(503, "stopped")
            context = None
            reason = None
            if self.policy == "reject":
                context = self.budget.action(session["execution"])
                try:
                    context.__enter__()
                except PublicLimitError as error:
                    reason = ("busy" if "en curso" in str(error) else
                              "session_interval" if "3 segundos" in str(error) else "rate_limit")
            elif self.clock() < session["next"]:
                reason = "session_interval"
            elif self.active is not None and len(self.pending) >= self.queue_size:
                reason = "queue_full"
            if reason is None and (len(self.jobs) >= 128 or
                    sum(j["owner"] == token for j in self.jobs.values()) >= 4):
                reason = "retained_job_capacity"
                if context:
                    context.__exit__(None, None, None)
            if reason:
                self.emit("rejected", case=case, seed=seed, reason=reason)
                raise Refusal(429, reason)
            jid = secrets.token_hex(16)
            job = dict(id=jid, owner=token, case=case, seed=seed, state="queued",
                       admitted=self.clock(), started=None, finished=None, context=context)
            self.jobs[jid], self.keys[key] = job, jid
            session["next"] = self.clock()+SESSION_INTERVAL_SECONDS
            if self.active is None:
                self.active = jid  # reserve executor slot before waking worker
            else:
                self.pending.append(jid)
            self.emit("admitted", job=jid, case=case, seed=seed)
            self.cv.notify_all()
            return self._view(job), False

    def _view(self, job):
        # Never exposes owner tokens or mutable result objects.
        position = (list(self.pending).index(job["id"])+1
                    if job["id"] in self.pending else 0)
        return {k: job[k] for k in ("id", "case", "seed", "state", "admitted", "started", "finished")} | {
            "position": position, "error": job.get("error"),
            "cache_hit": job.get("cache_hit"),
            "wait_seconds": job["started"]-job["admitted"] if job["started"] is not None else None,
            "result_seconds": job["finished"]-job["admitted"] if job["finished"] is not None else None}

    def get(self, token, jid, result=False):
        with self.cv:
            self._session(token)
            job = self.jobs.get(jid)
            if not job or job["owner"] != token:
                raise Refusal(404, "job_not_found")
            if result:
                if job["state"] != "succeeded":
                    raise Refusal(409, "result_not_ready" if job["state"] != "failed" else "job_failed")
                return job["result"]  # immutable JSON str, serialized by real engine
            return self._view(job)

    def _run(self):
        while True:
            with self.cv:
                self.cv.wait_for(lambda: self.closed or self.active is not None)
                if self.closed:
                    return
                job = self.jobs[self.active]
                if self.policy == "fifo":
                    now = self.clock()
                    while self.starts and self.starts[0] <= now-WINDOW_SECONDS:
                        self.starts.popleft()
                    if len(self.starts) >= MAX_ACTIONS_PER_WINDOW:
                        job["state"] = "waiting_budget"
                        self.cv.wait(timeout=min(.25, max(.001, self.starts[0]+WINDOW_SECONDS-now)))
                        continue
                    context = self.budget.action(self.sessions[job["owner"]]["execution"])
                    # The acceptance interval and FIFO imply >=3s between the
                    # same session's starts unless earlier work was backlogged.
                    # In that case wait as well, preserving the original guard.
                    try:
                        context.__enter__()
                    except PublicLimitError:
                        job["state"] = "waiting_budget"
                        self.cv.wait(timeout=.05)
                        continue
                    job["context"] = context
                    self.starts.append(self.budget._admitted[-1])
                job["started"], job["state"] = self.clock(), "running"
                self.emit("started", job=job["id"], budget_mono=self.budget._admitted[-1])
            try:
                key = (job["case"], job["seed"], self.fingerprint)
                hit = key in self.cache
                if hit:
                    result = self.cache.pop(key)
                else:
                    with self.cv:
                        self.emit("engine_start", job=job["id"], case=job["case"], seed=job["seed"])
                    result = self.engine(job["case"], job["seed"]).to_json()
                    with self.cv:
                        self.emit("engine_end", job=job["id"])
                self.cache[key] = result
                if len(self.cache) > 24:
                    self.cache.popitem(last=False)
                outcome = dict(state="succeeded", result=result, cache_hit=hit)
            except Exception as error:
                outcome = dict(state="failed", error=type(error).__name__)
                with self.cv:
                    self.emit("engine_error", job=job["id"], error=type(error).__name__)
            finally:
                with self.cv:
                    job["context"].__exit__(None, None, None)
                    job["context"] = None
                    job["finished"] = self.clock()
                    job.update(outcome)
                    self.emit("finished", job=job["id"], state=job["state"])
                    self.active = self.pending.popleft() if self.pending else None
                    self.cv.notify_all()

    def close(self):
        with self.cv:
            self.closed = True
            self.cv.notify_all()
        self.worker.join(timeout=5)


class Server(ThreadingHTTPServer):
    request_queue_size = 128
    daemon_threads = True


def make_server(scheduler, port=0):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def handle_request(self):
            try:
                if self.headers.get("Origin") is not None:
                    raise Refusal(403, "browser_origin_forbidden")
                token = self.headers.get("Authorization", "").removeprefix("Bearer ")
                path = self.path.split("/")
                if self.command == "POST" and self.path == "/sessions":
                    return 201, {"token": scheduler.new_session()}
                if self.command == "POST" and self.path == "/jobs":
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 1024:
                        raise Refusal(400, "body_size")
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict) or set(body) != {"case", "seed"}:
                        raise Refusal(400, "invalid_configuration")
                    job, duplicate = scheduler.submit(token, body["case"], body["seed"])
                    return (200 if duplicate else 202), job | {"duplicate": duplicate}
                if self.command == "GET" and len(path) in (3, 4) and path[1] == "jobs":
                    if len(path) == 4 and path[3] != "result":
                        raise Refusal(404, "not_found")
                    return 200, scheduler.get(token, path[2], result=len(path) == 4)
                raise Refusal(404, "not_found")
            except Refusal as error:
                return error.status, {"error": error.reason}
            except (ValueError, TypeError):
                return 400, {"error": "invalid_request"}

        def dispatch(self):
            self.connection.settimeout(5)
            try:
                status, value = self.handle_request()
                raw = (value if isinstance(value, str) else json.dumps(value)).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)
            except (OSError, TimeoutError):
                pass

        do_GET = do_POST = dispatch

    return Server(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", choices=("reject", "fifo"), default="fifo")
    parser.add_argument("--queue-size", type=int, default=19)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--trace", required=True)
    args = parser.parse_args()
    if Path(args.trace).exists():
        parser.error("trace must be a new path")
    scheduler = Scheduler(args.policy, args.queue_size, trace=args.trace)
    server = make_server(scheduler, args.port)
    print(json.dumps({"port": server.server_port}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        scheduler.close()


if __name__ == "__main__":
    main()
