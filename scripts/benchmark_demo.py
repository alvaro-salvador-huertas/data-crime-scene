"""Local browser benchmark. Owns its server; never targets a deployment.

Uses existing Playwright/Chrome and stdlib /proc sampling; no production extras.
Every trial starts a fresh public-entrypoint process with its original budgets.
The optional worker observes admissions/engine calls without changing their rules.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import signal
import shutil
import socket
import statistics
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CASES = ("future", "groups", "selection")
LIMITS = ("Hay un cálculo en curso", "Espera 3 segundos", "presupuesto compartido")


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_jsonl(path):
    if not Path(path).exists():
        return []
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line]


def local_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.username or parsed.password or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment):
        raise ValueError("URL must be http://127.0.0.1:PORT; this script owns a new local server")
    port = parsed.port or 80
    if not 1024 <= port <= 65535:
        raise ValueError("Use an unprivileged local port >=1024")
    return f"http://127.0.0.1:{port}", port


def instrumentation_worker(trace):
    """A transparent observer, confined to this child process and trace file."""
    sys.path.insert(0, str(ROOT))
    from data_crime_scene import experiments
    from ui import public_limits
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    lock = threading.Lock()

    def emit(kind, **fields):
        ctx = get_script_run_ctx(suppress_warning=True)
        sid = hashlib.sha256(ctx.session_id.encode()).hexdigest()[:12] if ctx else None
        event = dict(event=kind, mono=time.monotonic(), wall=time.time(), pid=os.getpid(),
                     thread=threading.get_ident(), session=sid, **fields)
        with lock, Path(trace).open("a") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    original_engine = experiments.run_experiment

    @wraps(original_engine)
    def observed_engine(case_id, seed=42):
        started = time.monotonic()
        emit("engine_start", case=case_id, seed=seed)
        try:
            result = original_engine(case_id, seed)
        except BaseException as error:
            emit("engine_error", case=case_id, seed=seed, error=type(error).__name__)
            raise
        emit("engine_end", case=case_id, seed=seed, seconds=time.monotonic()-started,
             generator_params=result.generator_params, protocol=result.protocol)
        return result

    original_action = public_limits.PublicBudget.action

    @contextmanager
    def observed_action(self, session):
        emit("request")
        try:
            with original_action(self, session):
                emit("admitted")
                try:
                    yield
                finally:
                    emit("action_end")
        except public_limits.PublicLimitError as error:
            emit("denied", reason=str(error))
            raise

    experiments.run_experiment = observed_engine
    public_limits.PublicBudget.action = observed_action
    from streamlit.web import cli
    emit("observer_ready")
    sys.argv = ["streamlit", "run", str(ROOT / "demo/streamlit_app.py"),
                "--server.address=127.0.0.1", f"--server.port={os.environ['DCS_BENCH_PORT']}",
                "--server.headless=true", "--browser.gatherUsageStats=false"]
    cli.main()


def memory_info():
    values = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        values[key] = int(value.split()[0]) * 1024
    return values


def cgroup_limits():
    result = {"membership": Path("/proc/self/cgroup").read_text(), "ancestors": []}
    relative = result["membership"].split("::", 1)[-1].strip().lstrip("/")
    base = Path("/sys/fs/cgroup")
    current = base / relative
    while current == base or base in current.parents:
        row = {"path": str(current)}
        for name in ("cpu.max", "memory.max", "memory.current", "memory.events"):
            try:
                row[name] = (current/name).read_text().strip()
            except OSError:
                pass
        if len(row) > 1:
            result["ancestors"].append(row)
        if current == base:
            break
        current = current.parent
    return result


def process_snapshot():
    """pid -> (parent, accumulated user+system seconds, RSS bytes)."""
    rows = {}
    ticks, page = os.sysconf("SC_CLK_TCK"), os.sysconf("SC_PAGE_SIZE")
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            text = path.read_text()
            data = text[text.rfind(")")+2:].split()
            rows[int(path.parent.name)] = (int(data[1]), (int(data[11])+int(data[12]))/ticks,
                                           max(0, int(data[21]))*page)
        except (OSError, ValueError, IndexError):
            continue
    return rows


def descendants(rows, root):
    found = {root} if root in rows else set()
    while True:
        new = {pid for pid, row in rows.items() if row[0] in found} - found
        if not new:
            return found
        found |= new


class Monitor:
    def __init__(self, output, server_pid):
        self.path, self.server_pid = output, server_pid
        self.stop = threading.Event()
        self.pressure = None
        self.samples = []
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        previous = {}
        last = time.monotonic()
        with self.path.open("w") as stream:
            while not self.stop.is_set():
                now = time.monotonic()
                rows = process_snapshot()
                server = descendants(rows, self.server_pid)
                client = descendants(rows, os.getpid()) - server - {os.getpid()}
                item = {"mono": now, "wall": time.time()}
                for label, pids in (("server", server), ("client", client), ("controller", {os.getpid()})):
                    seconds = sum(max(0, rows[p][1]-previous.get(p, rows[p][1])) for p in pids if p in rows)
                    item[label+"_cpu_pct"] = 100*seconds/max(now-last, .001)
                    item[label+"_rss_bytes"] = sum(rows[p][2] for p in pids if p in rows)
                    item[label+"_pids"] = sorted(pids)
                mem = memory_info()
                item["host_available_bytes"] = mem["MemAvailable"]
                if mem["MemAvailable"] < max(2*1024**3, .10*mem["MemTotal"]):
                    self.pressure = "host_available_memory_below_threshold"
                if item["client_rss_bytes"] > 6*1024**3:
                    self.pressure = "browser_driver_rss_above_6GiB"
                for row in cgroup_limits()["ancestors"]:
                    maximum, used = row.get("memory.max"), row.get("memory.current")
                    if maximum and maximum != "max" and used and int(used) > .85*int(maximum):
                        self.pressure = "cgroup_memory_above_85pct"
                item["pressure"] = self.pressure
                self.samples.append(item)
                stream.write(json.dumps(item)+"\n")
                stream.flush()
                previous = {pid: row[1] for pid, row in rows.items()}
                last = now
                self.stop.wait(.25)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=3)


def verify_download(value, case, seed):
    if value.get("case_id") != case or value.get("seed") != seed:
        raise ValueError("Downloaded JSON belongs to a different requested configuration")
    for variant in value["variants"].values():
        y, pred = variant["y_true"], variant["y_pred"]
        if not y or len(y) != len(pred):
            raise ValueError("Missing predictions")
        tn, fp, fn, tp = (sum(a == i and b == j for a, b in zip(y, pred))
                          for i, j in ((0, 0), (0, 1), (1, 0), (1, 1)))
        recalls = [hit/total for hit, total in ((tn, tn+fp), (tp, tp+fn)) if total]
        metrics = {"accuracy": (tn+tp)/len(y), "balanced_accuracy": sum(recalls)/len(recalls),
                   "f1": 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.0}
        if variant["confusion_matrix"] != [[tn, fp], [fn, tp]] or any(
                abs(variant["metrics"][key]-val) > 1e-12 for key, val in metrics.items()):
            raise ValueError("Downloaded metrics do not match predictions")


def execution_row(case, seed, user, requested):
    """An unobserved click is unknown, including after an interrupted dispatch."""
    return {"case": case, "seed": seed, "user": user, "requested_concurrency": requested,
            "status": "incomplete", "clicked": None, "observation": "action_unconfirmed"}


def summarize(rows, events):
    successes = [row["latency_seconds"] for row in rows if row["status"] == "success"]
    counts = Counter(row["status"] for row in rows)
    engine = [event for event in events if event["event"] == "engine_start"]
    admitted = sum(event["event"] == "admitted" for event in events)
    return {"attempts": len(rows), "clicked": sum(row.get("clicked") is True for row in rows),
            "click_unconfirmed": sum(row.get("clicked") is None for row in rows),
            "outcomes": dict(counts), "successes": len(successes),
            "timeouts": counts["timeout"],
            "failures_excluding_limits": sum(n for key, n in counts.items() if key not in ("success", "limit", "incomplete")),
            "incomplete": counts["incomplete"],
            "limited": counts["limit"], "success_median_seconds": statistics.median(successes) if successes else None,
            "success_max_seconds": max(successes) if successes else None,
            "response_max_seconds": max((r["latency_seconds"] for r in rows if "latency_seconds" in r), default=None),
            "admitted": admitted, "engine_calls": len(engine),
            "cache_hits_inferred": max(0, admitted-len(engine)),
            "denied_reasons": dict(Counter(e["reason"] for e in events if e["event"] == "denied"))}


async def settled(page):
    await page.wait_for_function("""() => {
        const a = document.querySelector('[data-testid="stApp"]');
        return a && a.getAttribute('data-test-script-state') === 'notRunning';
    }""")


async def prepare(browser, url, case, seed, index, timeout, errors):
    context = await browser.new_context(viewport={"width": 1280, "height": 900},
                                        accept_downloads=True, service_workers="block")
    async def route(request):
        parsed = urlsplit(request.request.url)
        if parsed.hostname == "127.0.0.1" and parsed.port == urlsplit(url).port:
            await request.continue_()
        else:
            errors.append({"kind": "external_request_blocked", "url": request.request.url})
            await request.abort()
    await context.route("**/*", route)
    page = await context.new_page()
    page.set_default_timeout(timeout*1000)
    page.on("pageerror", lambda error: errors.append({"kind": "pageerror", "message": str(error)}))
    page.on("websocket", lambda ws: ws.on("socketerror", lambda error: errors.append(
        {"kind": "socketerror", "message": str(error)})))
    started = time.monotonic()
    try:
        response = await page.goto(url)
        if not response or response.status != 200:
            raise ValueError("Local page did not return HTTP 200")
        await page.get_by_role("heading", name="Data Crime Scene", exact=True).wait_for()
        await settled(page)
        if case != "future":
            combo = page.get_by_role("combobox", name="Expediente", exact=True)
            await combo.click()
            await page.get_by_role("option").nth(CASES.index(case)).click()
            await settled(page)
        if seed != 42:
            spin = page.get_by_role("spinbutton", name="Semilla del experimento", exact=True)
            await spin.fill(str(seed))
            await spin.press("Enter")
            await settled(page)
        await page.get_by_text(f"semilla {seed}", exact=False).first.wait_for()
        if await page.get_by_test_id("stMetricValue").count():
            raise ValueError("Stale result present before action")
        await page.evaluate("""() => document.addEventListener('click', e => {
            if (e.target.closest('button')?.innerText.includes('Ejecutar experimento'))
                window.__benchmarkClick = Date.now();
        }, {capture:true})""")
        return {"context": context, "page": page, "case": case, "seed": seed, "user": index,
                "prepare_seconds": time.monotonic()-started, "errors": errors}
    except BaseException:
        await context.close()
        raise


async def execute(user, gate, timeout, requested, row=None):
    page = user["page"]
    if row is None:
        row = execution_row(user["case"], user["seed"], user["user"], requested)
    row["prepare_seconds"] = user["prepare_seconds"]
    row["errors"] = user["errors"]
    started = None
    try:
        await gate.wait()
        started = time.monotonic()
        row["action_start_mono"] = started
        async with asyncio.timeout(timeout):
            await page.get_by_role("button", name="Ejecutar experimento", exact=True).click()
            click = await page.evaluate("window.__benchmarkClick || null")
            if click is not None:
                row["clicked"] = True
                row["click_wall_seconds"] = click/1000
                row["observation"] = "click_confirmed"
            result = await page.wait_for_function("""() => {
                if (document.querySelector('[data-testid="stException"]')) return 'ui_error';
                const text = document.body.innerText;
                if (text.includes('No se ha podido ejecutar el experimento')) return 'engine_error';
                if (['Hay un cálculo en curso','Espera 3 segundos','presupuesto compartido. Espera']
                    .some(message => text.includes(message))) return 'limit';
                return document.querySelectorAll('[data-testid="stMetricValue"]').length >= 3
                    && text.includes('Cálculo real · caso') ? 'success' : null;
            }""")
            outcome = await result.json_value()
            row["observed_status"] = outcome
            row["observation"] = "outcome_obtained"
            row["usable_wall_seconds"] = time.time()
            row["latency_seconds"] = row["usable_wall_seconds"]-row["click_wall_seconds"] if click is not None else time.monotonic()-started
            await settled(page)
            if outcome == "success":
                await page.get_by_text(f"Cálculo real · caso {user['case']} · semilla {user['seed']} ·", exact=False).wait_for()
                row["visible_accuracy"] = await page.get_by_test_id("stMetricValue").first.inner_text()
            else:
                row["ui_message"] = await page.get_by_test_id("stAlert").all_inner_texts()
            row["status"] = outcome
    except asyncio.CancelledError:
        row["cancelled"] = True
        raise
    except Exception as error:
        name = type(error).__name__
        row["status"] = ("timeout" if "Timeout" in name else
                         "session_lost" if page.is_closed() or "closed" in str(error).lower() else "ui_error")
        row["error"] = f"{name}: {error}"
    finally:
        row["end_mono"] = time.monotonic()
        if started is not None:
            row["elapsed_seconds"] = row["end_mono"]-started
            if not row.get("cancelled"):
                row.setdefault("latency_seconds", row["elapsed_seconds"])
        row["errors"] = list(user["errors"])
    return row


async def download(user, row, output, timeout):
    page = user["page"]
    async with asyncio.timeout(timeout):
        await page.get_by_role("button", name="Revelar explicación y comparar", exact=True).click()
        async with page.expect_download() as received:
            await page.get_by_role("button", name="↓ Descargar informe completo · JSON", exact=True).click()
        artifact = await received.value
        path = output/f"user-{user['user']}-download.json"
        await artifact.save_as(path)
        value = json.loads(path.read_text())
        verify_download(value, user["case"], user["seed"])
        if row["visible_accuracy"] != f"{value['variants']['incorrect']['metrics']['accuracy']:.1%}":
            raise ValueError("Visible accuracy does not match downloaded execution")
        row["download"] = {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "verified": True}


async def trial(browser, args, output, concurrency, repeat, phase="wave", results=None):
    output.mkdir()
    trace = output/"server-events.jsonl"
    url, port = local_url(args.url)
    with socket.socket() as check:
        check.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        check.bind(("127.0.0.1", port))  # refuse an existing instance; own server only
    env = dict(os.environ, DCS_BENCH_PORT=str(port), PYTHONDONTWRITEBYTECODE="1")
    logfile = (output/"server.log").open("w")
    started = time.monotonic()
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", str(trace)],
                            cwd=ROOT, env=env, stdout=logfile, stderr=subprocess.STDOUT, start_new_session=True)
    monitor = Monitor(output/"resources.jsonl", proc.pid)
    monitor.thread.start()
    configs = [(args.case, args.seed + (i if args.seed_policy == "distinct" else 0)) for i in range(concurrency)]
    if phase == "isolation":
        configs = [("future", 7), ("groups", 2026)]
    users = []
    rows = [execution_row(case, seed, index, concurrency) for index, (case, seed) in enumerate(configs)]
    info = {"phase": phase, "concurrency": concurrency, "repeat": repeat, "url": url,
            "server_pid": proc.pid, "start_mono": started, "rows": rows,
            "seed_policy": args.seed_policy, "cold_process": True}
    if results is not None:
        results.append(info)  # Keep the partial trial in the campaign summary too.
    write_json(output/"config.json", vars(args) | {"trial": info.copy()})
    try:
        async with asyncio.timeout(args.timeout*3):
            while True:
                if proc.poll() is not None:
                    raise RuntimeError("Owned server exited before health")
                try:
                    with urllib.request.urlopen(url+"/_stcore/health", timeout=.3) as response:
                        if response.status == 200:
                            break
                except OSError:
                    await asyncio.sleep(.1)
                if time.monotonic()-started > args.timeout:
                    raise TimeoutError("Local startup exceeded timeout")
            info["startup_to_health_seconds"] = time.monotonic()-started
            prepared = await asyncio.gather(*(prepare(browser, url, case, seed, i, args.timeout, [])
                         for i, (case, seed) in enumerate(configs)), return_exceptions=True)
            for i, user in enumerate(prepared):
                if isinstance(user, BaseException):
                    rows[i].update(status="prepare_error", error=repr(user))
                else:
                    users.append(user)
            info["sessions_ready"] = len(users)
            if len(users) != concurrency:
                info["stop_reason"] = "session_preparation_failed"
            elif monitor.pressure:
                info["stop_reason"] = monitor.pressure
            else:
                if phase == "isolation":
                    for user in users:
                        gate = asyncio.Event(); gate.set()
                        await execute(user, gate, args.timeout, 1, rows[user["user"]])
                else:
                    gate = asyncio.Event()
                    tasks = [asyncio.create_task(execute(user, gate, args.timeout, concurrency,
                                                        rows[user["user"]])) for user in users]
                    await asyncio.sleep(0)
                    info["release_mono"] = time.monotonic()
                    gate.set()
                    await asyncio.gather(*tasks)
                info["wave_end_mono"] = time.monotonic()
                wave_events = [e for e in read_jsonl(trace) if e["mono"] >= info.get("release_mono", started)]
                info["summary"] = summarize(rows, wave_events)
                click_times = [r["click_wall_seconds"] for r in rows if r.get("click_wall_seconds")]
                info["click_spread_seconds"] = max(click_times)-min(click_times) if click_times else None
                for user, row in ((u, next(r for r in rows if r["user"] == u["user"])) for u in users):
                    if row["status"] != "success":
                        continue
                    # Isolation checks every successful context; waves sample at most 3.
                    if phase != "isolation" and sum("download" in r for r in rows) >= args.download_sample:
                        break
                    try:
                        await download(user, row, output, args.timeout)
                    except Exception as error:
                        row["download_error"] = repr(error)
                        info["stop_reason"] = "download_verification_failed"
                if phase == "isolation":
                    for user in users:
                        await user["page"].get_by_text(f"Cálculo real · caso {user['case']} · semilla {user['seed']} ·", exact=False).wait_for()
                    info["isolation_verified"] = all(r.get("download", {}).get("verified") for r in rows)
                # A new context proves a warm cache response is not another engine execution.
                if phase == "wave" and concurrency == 1 and rows[0]["status"] == "success":
                    warm = await prepare(browser, url, args.case, args.seed, 100, args.timeout, [])
                    users.append(warm)
                    gate = asyncio.Event(); gate.set()
                    warm_start = time.monotonic()
                    warm_row = execution_row(warm["case"], warm["seed"], warm["user"], 1)
                    info["warm_probe"] = {"row": warm_row}
                    try:
                        await execute(warm, gate, args.timeout, 1, warm_row)
                    finally:
                        info["warm_probe"]["summary"] = summarize([warm_row],
                            [e for e in read_jsonl(trace) if e["mono"] >= warm_start])
    except Exception as error:
        info["stop_reason"] = type(error).__name__+": "+str(error)
    finally:
        # Persist partial rows even after a timeout, cancellation, or browser failure.
        # End owned compute immediately on cancellation/deadline, before browser cleanup.
        cancelled = asyncio.current_task().cancelling() > 0
        if cancelled:
            info["stop_reason"] = "cancelled_by_deadline_or_interrupt"
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL if cancelled else signal.SIGTERM)
        try:
            await asyncio.to_thread(proc.wait, timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            await asyncio.to_thread(proc.wait, timeout=3)
        try:
            await asyncio.wait_for(asyncio.gather(*(user["context"].close() for user in users),
                                                 return_exceptions=True), timeout=5)
        except Exception:
            pass
        monitor.close()
        logfile.close()
        info["server_exit"] = proc.returncode
        info["duration_seconds"] = time.monotonic()-started
        info.setdefault("summary", summarize(rows, read_jsonl(trace)))
        if monitor.pressure:
            info["stop_reason"] = monitor.pressure
        if any(r["status"] not in ("success", "limit") or r.get("errors") for r in rows):
            info.setdefault("stop_reason", "unexpected_outcome_or_client_error")
        info["resources"] = {key: max((s[key] for s in monitor.samples), default=0)
            for key in ("server_rss_bytes", "client_rss_bytes", "server_cpu_pct", "client_cpu_pct", "controller_cpu_pct")}
        info["wave_resources"] = {key: max((s[key] for s in monitor.samples
            if info.get("release_mono", float("inf")) <= s["mono"] <= info.get("wave_end_mono", 0)), default=None)
            for key in ("server_rss_bytes", "client_rss_bytes", "server_cpu_pct", "client_cpu_pct")}
        info["host_available_min_bytes"] = min((s["host_available_bytes"] for s in monitor.samples), default=None)
        write_json(output/"result.json", info)
        (output/"executions.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False)+"\n" for row in rows))
    return info


def environment():
    versions = {}
    for name in ("streamlit", "numpy", "pandas", "scipy", "scikit-learn", "plotly", "uvicorn",
                 "starlette", "websockets", "python-dateutil", "playwright", "pyee", "threadpoolctl"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    limits = cgroup_limits()
    sources = [ROOT/"app.py", ROOT/"requirements.txt", ROOT/"requirements-browser.txt", Path(__file__).resolve()]
    for folder in ("data_crime_scene", "ui", "demo"):
        sources.extend((ROOT/folder).glob("*.py"))
    return {"at": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
            "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
            "os_release": Path("/etc/os-release").read_text(), "cpuinfo": Path("/proc/cpuinfo").read_text(),
            "python": sys.version, "executable": sys.executable, "versions": versions,
            "cpu_affinity": sorted(os.sched_getaffinity(0)), "memory": memory_info(), "cgroup": limits,
            "native_thread_env": {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")},
            "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "git_status": subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=ROOT, text=True),
            "resource_method": "Linux /proc sampled every 250ms; server tree separate from Playwright/Chrome tree and controller; CPU 100%=one logical CPU; sum RSS double counts shared pages; short peaks/exited processes may be missed"}


async def run(args):
    from playwright.async_api import async_playwright
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_json(output/"config.json", vars(args))
    write_json(output/"environment.json", environment())
    deadline = time.monotonic()+args.budget_seconds
    results = []
    final = {"trials": results, "maximum_load_budget_seconds": args.budget_seconds}
    try:
        async with async_playwright() as playwright:
            chrome = shutil.which("google-chrome") or shutil.which("chromium")
            browser = await playwright.chromium.launch(executable_path=chrome, headless=True)
            final["browser"] = browser.version
            try:
                async with asyncio.timeout(max(1, deadline-time.monotonic())):
                    levels = [2] if args.isolation_only else args.concurrency
                    for level in levels:
                        for repeat in range(1, (1 if args.isolation_only else args.repetitions)+1):
                            name = f"n{level:02d}-r{repeat:02d}"
                            print(json.dumps({"starting": name, "remaining_budget": deadline-time.monotonic()}), flush=True)
                            result = await trial(browser, args, output/name, level, repeat,
                                                 "isolation" if args.isolation_only else "wave", results=results)
                            print(json.dumps({"finished": name, "summary": result["summary"],
                                              "stop_reason": result.get("stop_reason")}), flush=True)
                            write_json(output/"summary.json", final)
                            if result.get("stop_reason"):
                                final["stop_reason"] = result["stop_reason"]
                                return final
            finally:
                await asyncio.wait_for(browser.close(), timeout=10)
    except Exception as error:
        final["stop_reason"] = type(error).__name__+": "+str(error)
    finally:
        final["budget_used_seconds"] = args.budget_seconds-(deadline-time.monotonic())
        final["deadline_expired"] = time.monotonic() >= deadline
        write_json(output/"summary.json", final)
    return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 5, 10, 20])
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--budget-seconds", type=float, default=1200)
    parser.add_argument("--output-dir")
    parser.add_argument("--case", choices=CASES, default="future")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--seed-policy", choices=("fixed", "distinct"), default="fixed")
    parser.add_argument("--download-sample", type=int, default=3)
    parser.add_argument("--isolation-only", action="store_true")
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        instrumentation_worker(args.worker)
        return
    try:
        local_url(args.url)
    except ValueError as error:
        parser.error(str(error))
    if not args.output_dir or any(n < 1 or n > 20 for n in args.concurrency):
        parser.error("output-dir is required; concurrency must be 1..20")
    if not (1 <= args.repetitions <= 3 and 0 < args.timeout <= 90 and 0 < args.budget_seconds <= 1200):
        parser.error("repetitions 1..3, timeout <=90s and budget <=1200s required")
    if not 0 <= args.seed <= 2**32-21 or not 0 <= args.download_sample <= 20:
        parser.error("seed/sample outside supported range")
    result = asyncio.run(run(args))
    if result.get("stop_reason"):
        print(f"Stopped: {result['stop_reason']}. Raw evidence: {args.output_dir}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
