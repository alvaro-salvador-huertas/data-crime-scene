"""Paired HTTP bursts against owned loopback processes; no browser or deployment."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from scripts.benchmark_demo import Monitor, environment, read_jsonl, verify_download, write_json

ROOT = Path(__file__).resolve().parents[2]


def request(url, method, path, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer "+token
    req = urllib.request.Request(url+path, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    # Explicitly bypass ambient proxy configuration, including on localhost.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        response = opener.open(req, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read()
        return response.status, json.loads(raw), raw


def invariant_checks(events):
    admitted = [e["job"] for e in events if e["event"] == "admitted"]
    started = [e["job"] for e in events if e["event"] == "started"]
    assert started == admitted, "FIFO/start/admission mismatch"
    active, peak = 0, 0
    times = []
    for event in events:
        if event["event"] == "engine_start":
            active += 1
            peak = max(peak, active)
        if event["event"] in ("engine_end", "engine_error"):
            active -= 1
        assert 0 <= active <= 1, "Overlapping engine calls"
        if event["event"] == "started":
            times.append(event["budget_mono"])
    assert active == 0
    assert all(sum(t-60 < other <= t for other in times[:i+1]) <= 12
               for i, t in enumerate(times)), "Rolling budget exceeded"
    return {"fifo_verified": True, "max_active_engine": peak, "rolling_12_per_60_verified": True}


def summarize(rows, events):
    accepted = [r for r in rows if r.get("admitted")]
    successes = [r for r in rows if r["state"] == "succeeded"]
    def med_max(values, prefix):
        return {prefix+"_median": statistics.median(values) if values else None,
                prefix+"_max": max(values) if values else None}
    return dict(attempts=len(rows), admitted=len(accepted), results=len(successes),
                rejected=sum(r["state"] == "rejected" for r in rows),
                rejection_reasons=dict(Counter(r["reason"] for r in rows if r["state"] == "rejected")),
                engine_calls=sum(e["event"] == "engine_start" for e in events),
                cache_hits=sum(r.get("cache_hit") is True for r in successes),
                duplicates_verified=sum(r.get("duplicate_verified", False) for r in rows),
                outcomes=dict(Counter(r["state"] for r in rows)),
                **med_max([r["wait_seconds"] for r in successes], "wait_seconds"),
                **med_max([r["result_seconds"] for r in successes], "server_result_seconds"),
                **med_max([r["client_result_seconds"] for r in successes], "client_result_seconds"),
                **med_max([r["response_seconds"] for r in rows if "response_seconds" in r], "response_seconds"))


def trial(output, policy, case, seeds, deadline, *, queue_size=19):
    output.mkdir()
    rows = [dict(user=i, case=case, seed=seed, state="incomplete") for i, seed in enumerate(seeds)]
    result = dict(policy=policy, case=case, n=len(seeds), queue_size=queue_size, rows=rows)
    log = (output/"server.log").open("w")
    proc = subprocess.Popen([sys.executable, "-m", "prototypes.fifo.service", "--policy", policy,
                             "--queue-size", str(queue_size), "--trace", str(output/"events.jsonl")],
                            cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    monitor = Monitor(output/"resources.jsonl", proc.pid)
    monitor.thread.start()
    def check():
        if time.monotonic() >= deadline:
            raise TimeoutError("campaign_deadline")
        if monitor.pressure:
            raise RuntimeError(monitor.pressure)
        if proc.poll() is not None:
            raise RuntimeError("server_exited")
    started = time.monotonic()
    try:
        while True:
            check()
            lines = (output/"server.log").read_text().splitlines()
            ready = [json.loads(line) for line in lines if line.startswith('{"port":')]
            if ready:
                url = f"http://127.0.0.1:{ready[0]['port']}"
                break
            if time.monotonic()-started > 30:
                raise TimeoutError("startup")
            time.sleep(.05)
        result["startup_seconds"] = time.monotonic()-started
        tokens = []
        for _ in seeds:
            code, value, _ = request(url, "POST", "/sessions")
            assert code == 201
            tokens.append(value["token"])
        barrier = threading.Barrier(len(seeds))
        def submit(i):
            row = rows[i]
            barrier.wait(timeout=10)
            begin = time.monotonic()
            row["client_submit_mono"] = begin
            code, value, _ = request(url, "POST", "/jobs", tokens[i], {"case": case, "seed": seeds[i]})
            row["response_seconds"] = time.monotonic()-begin
            if code == 429:
                row.update(state="rejected", reason=value["error"], admitted=False)
            else:
                assert code == 202, (code, value)
                row.update(value, admitted=True)
        with ThreadPoolExecutor(max_workers=len(seeds)) as pool:
            list(pool.map(submit, range(len(seeds))))
        result["submit_spread_seconds"] = max(r["client_submit_mono"] for r in rows)-min(r["client_submit_mono"] for r in rows)
        # Probes happen after the entire primary burst; no extra contention in it.
        for i, row in enumerate(rows):
            if not row.get("admitted"):
                continue
            code, again, _ = request(url, "POST", "/jobs", tokens[i], {"case": case, "seed": seeds[i]})
            assert code == 200 and again["duplicate"] and again["id"] == row["id"]
            row["duplicate_verified"] = True
        waiting = {i for i, row in enumerate(rows) if row.get("admitted")}
        while waiting:
            check()
            for i in list(waiting):
                row = rows[i]
                code, state, _ = request(url, "GET", "/jobs/"+row["id"], tokens[i])
                assert code == 200
                if state["state"] == "failed":
                    row.update(state)
                    raise RuntimeError("engine_failed: "+str(state))
                if state["state"] != "succeeded":
                    continue
                code, value, raw = request(url, "GET", "/jobs/"+row["id"]+"/result", tokens[i])
                assert code == 200
                row["client_result_seconds"] = time.monotonic()-row["client_submit_mono"]
                verify_download(value, case, seeds[i])
                row.update(state)
                row["sha256"] = hashlib.sha256(raw).hexdigest()
                (output/f"result-{i:02}.json").write_bytes(raw)
                # Repeat retrieval and submission of completed work; neither recomputes.
                code, _, raw_again = request(url, "GET", "/jobs/"+row["id"]+"/result", tokens[i])
                assert code == 200 and raw_again == raw
                code, again, _ = request(url, "POST", "/jobs", tokens[i], {"case": case, "seed": seeds[i]})
                assert code == 200 and again["id"] == row["id"]
                other = tokens[(i+1) % len(tokens)] if len(tokens) > 1 else request(url, "POST", "/sessions")[1]["token"]
                for suffix in ("", "/result"):
                    assert request(url, "GET", "/jobs/"+row["id"]+suffix, other)[0] == 404
                row["isolation_verified"] = True
                waiting.remove(i)
            write_json(output/"partial.json", result)
            if waiting:
                time.sleep(.05)
        events = read_jsonl(output/"events.jsonl")
        result["checks"] = invariant_checks(events)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=3)
        monitor.close()
        log.close()
        result["summary"] = summarize(rows, read_jsonl(output/"events.jsonl"))
        result["elapsed_seconds"] = time.monotonic()-started
        result["resources"] = {key: max((s[key] for s in monitor.samples), default=0)
                               for key in ("server_rss_bytes", "controller_rss_bytes", "server_cpu_pct", "controller_cpu_pct")}
        result["server_stopped"] = proc.poll() is not None
        write_json(output/"trial.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cases", nargs="+", choices=("future", "groups", "selection"), default=["future"])
    parser.add_argument("--seed-policies", nargs="+", choices=("fixed", "distinct"), default=["fixed", "distinct"])
    parser.add_argument("--levels", nargs="+", type=int, default=[1, 5, 10, 20])
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--budget-seconds", type=float, default=1200)
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 3 or not 0 < args.budget_seconds <= 1200 or any(n not in (1, 5, 10, 20) for n in args.levels):
        parser.error("repetitions 1..3, levels 1/5/10/20, budget (0,1200]")
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_json(output/"config.json", vars(args))
    env = environment()
    env["resource_method"] = "Linux /proc 250ms: server tree vs controller (HTTP threads in controller); no Chrome. Sum RSS, 100% CPU=one logical CPU; short peaks may be missed."
    for path in Path(__file__).parent.glob("*.py"):
        env["source_sha256"][str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(output/"environment.json", env)
    deadline = time.monotonic()+args.budget_seconds
    final = {"trials": [], "complete": False}
    try:
        for case in args.cases:
            for seed_policy in args.seed_policies:
                for n in args.levels:
                    seeds = [42+(i if seed_policy == "distinct" else 0) for i in range(n)]
                    for repeat in range(1, args.repetitions+1):
                        # Alternate order to reduce a systematic warm-machine bias.
                        for policy in (("reject", "fifo") if repeat % 2 else ("fifo", "reject")):
                            name = f"{case}-{seed_policy}-n{n:02}-r{repeat}-{policy}"
                            print(json.dumps({"starting": name, "remaining": deadline-time.monotonic()}), flush=True)
                            result = trial(output/name, policy, case, seeds, deadline)
                            result.update(name=name, seed_policy=seed_policy, repeat=repeat)
                            final["trials"].append(result)
                            write_json(output/"summary.json", final)
                            print(json.dumps({"finished": name, **result["summary"]}), flush=True)
        # Real-engine saturation probe, separate from paired capacity results.
        result = trial(output/"overflow-q1", "fifo", "future", list(range(100, 120)), deadline, queue_size=1)
        assert result["summary"]["rejection_reasons"].get("queue_full", 0) > 0
        final["overflow_probe"] = result
        # Every configuration's JSON must be stable across policies and repeats.
        digests = {}
        for item in final["trials"]:
            for row in item["rows"]:
                if row["state"] == "succeeded":
                    key = (row["case"], row["seed"])
                    assert digests.setdefault(key, row["sha256"]) == row["sha256"]
        final["cross_policy_json_verified"] = True
        final["complete"] = True
    except Exception as error:
        final["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        final["elapsed_seconds"] = args.budget_seconds-(deadline-time.monotonic())
        write_json(output/"summary.json", final)
        with (output/"trials.csv").open("w") as stream:
            fields = ["name", "policy", "case", "seed_policy", "n", "repeat"]
            metrics = list(final["trials"][0]["summary"]) if final["trials"] else []
            writer = csv.DictWriter(stream, fieldnames=fields+metrics)
            writer.writeheader()
            for item in final["trials"]:
                writer.writerow({k: item[k] for k in fields} | item["summary"])
    print(str(output), flush=True)


if __name__ == "__main__":
    main()
