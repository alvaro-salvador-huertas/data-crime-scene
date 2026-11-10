"""Local Chrome QA of the public entrypoint, FIFO on/off; no load campaign.

The private child worker has stdin-only test controls. It exposes no test HTTP
routes and starts only the ordinary Streamlit server on loopback.
"""
import argparse
from collections import Counter, deque
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def read_events(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def worker(args):
    import streamlit as st
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    from ui import public_limits as limits
    import app
    import ui.laboratory as laboratory
    import ui.detective as detective

    trace, lock, offset = Path(args.trace), threading.RLock(), [0.0]
    budget = limits.get_public_budget()
    budget._clock = lambda: time.monotonic()+offset[0]
    gates = {name: threading.Event() for name in ("guided", "laboratory", "detective")}
    for gate in gates.values():
        gate.set()

    def emit(event, **fields):
        with lock, trace.open("a") as stream:
            stream.write(json.dumps(dict(event=event, wall=time.time(), **fields))+"\n")

    original_action = limits.PublicBudget.action
    @contextmanager
    def observed_action(self, session):
        ctx = get_script_run_ctx(suppress_warning=True)
        origin = st.session_state.get("mode_selector", "legacy") if ctx else "guided"
        emit("budget_request", origin=origin)
        try:
            with original_action(self, session):
                emit("budget_admitted", origin=origin, shared=self is budget)
                try:
                    yield
                finally:
                    emit("budget_end", origin=origin)
        except limits.PublicLimitError as error:
            emit("budget_rejected", origin=origin, reason=str(error))
            raise
    limits.PublicBudget.action = observed_action
    active = [0]

    def observe(original, origin):
        def calculation(*values, **kwargs):
            with lock:
                active[0] += 1
                emit("engine_start", origin=origin, case=str(values[0]), seed=int(values[1]), active=active[0])
            try:
                if active[0] != 1:
                    raise RuntimeError("QA detected overlapping engines")
                if not gates[origin].wait(90):
                    raise TimeoutError("QA gate not released")
                return original(*values, **kwargs)
            finally:
                with lock:
                    active[0] -= 1
                    emit("engine_end", origin=origin)
        return calculation
    app.run_experiment = observe(app.run_experiment, "guided")
    laboratory.run_lab_experiment = observe(laboratory.run_lab_experiment, "laboratory")
    detective.build_case = observe(detective.build_case, "detective")
    scheduler = None
    if args.fifo == "1":
        from ui import guided_fifo
        scheduler = guided_fifo.get_guided_scheduler()
        scheduler.engine = observe(scheduler.engine, "guided")
        original_emit = scheduler.emit
        def queue_emit(event, **fields):
            emit("fifo_"+event, **fields)
            return original_emit(event, **fields)
        scheduler.emit = queue_emit

    def commands():
        for line in sys.stdin:
            command = json.loads(line)
            op = command["op"]
            try:
                if op == "hold":
                    gates[command["mode"]].clear()
                elif op == "release":
                    gates[command["mode"]].set()
                elif op == "advance":
                    with budget._lock:
                        offset[0] += command["seconds"]
                    if scheduler:
                        with scheduler.cv:
                            scheduler.cv.notify_all()
                elif op == "full_budget":
                    with budget._lock:
                        if budget._active:
                            raise RuntimeError("Cannot fill an active test budget")
                        now = budget._clock()
                        budget._admitted = deque([now]*12)
                    if scheduler:
                        with scheduler.cv:
                            scheduler.starts.clear()
                elif op == "isolation":
                    from prototypes.fifo.service import Refusal
                    with scheduler.cv:
                        jobs = list(scheduler.jobs.values())[:2]
                        assert len(jobs) == 2 and jobs[0]["owner"] != jobs[1]["owner"]
                        for a, b in ((jobs[0], jobs[1]), (jobs[1], jobs[0])):
                            for result in (False, True):
                                try:
                                    scheduler.get(a["owner"], b["id"], result)
                                except Refusal as error:
                                    assert error.status == 404
                                else:
                                    raise AssertionError("Foreign result visible")
                elif op == "privacy":
                    if scheduler:
                        with scheduler.cv:
                            tokens = list(scheduler.sessions)
                        blobs = command["blobs"]+[p.read_bytes().decode("latin1") for p in trace.parent.iterdir() if p.is_file()]
                        assert all(token not in blob for token in tokens for blob in blobs)
                else:
                    raise ValueError("Unknown private test command")
                emit("control_ack", request=command["request"], op=op, ok=True)
            except Exception:
                # Never serialize command payloads, session objects or tokens.
                emit("control_ack", request=command["request"], op=op, ok=False)
    threading.Thread(target=commands, daemon=True).start()
    from streamlit.web import cli
    sys.argv = ["streamlit", "run", str(ROOT/"demo/streamlit_app.py"),
                "--server.address=127.0.0.1", f"--server.port={args.port}",
                "--server.headless=true", "--browser.gatherUsageStats=false", "--server.fileWatcherType=none"]
    try:
        cli.main()
    finally:
        for gate in gates.values():
            gate.set()
        if scheduler:
            scheduler.close()


class Owned:
    def __init__(self, output, fifo):
        self.output, self.trace, self.serial = output, output/"events.jsonl", 0
        output.mkdir()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.log = (output/"server.log").open("w")
        self.proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", "--fifo", fifo,
                                      "--port", str(self.port), "--trace", str(self.trace)], cwd=ROOT,
                                     env=dict(os.environ, DCS_GUIDED_FIFO=fifo, PYTHONDONTWRITEBYTECODE="1"),
                                     stdin=subprocess.PIPE, stdout=self.log, stderr=subprocess.STDOUT,
                                     text=True, start_new_session=True)

    def events(self, kind):
        return [e for e in read_events(self.trace) if e["event"] == kind]

    def control(self, op, **kwargs):
        self.serial += 1
        self.proc.stdin.write(json.dumps(dict(op=op, request=self.serial, **kwargs))+"\n")
        self.proc.stdin.flush()
        deadline = time.monotonic()+10
        while time.monotonic() < deadline:
            matching = [e for e in self.events("control_ack") if e["request"] == self.serial]
            if matching:
                assert matching[-1]["ok"], "Private QA control failed: "+op
                return
            time.sleep(.05)
        raise TimeoutError("Private QA control timeout")

    def start(self):
        deadline = time.monotonic()+30
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while time.monotonic() < deadline:
            assert self.proc.poll() is None, "Owned Streamlit exited"
            try:
                with opener.open(self.url+"/_stcore/health", timeout=.3) as response:
                    if response.status == 200:
                        return
            except OSError:
                pass
            time.sleep(.05)
        raise TimeoutError("Owned Streamlit startup")

    def close(self):
        if self.proc.poll() is None:
            for mode in ("guided", "laboratory", "detective"):
                self.control("release", mode=mode)
            os.killpg(self.proc.pid, signal.SIGTERM)
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait(timeout=3)
        self.proc.stdin.close()
        self.log.close()


def visit(playwright, owned, enabled):
    from playwright.sync_api import expect
    from scripts.benchmark_demo import verify_download
    report = dict(enabled=enabled, checks=[], screenshots=[], page_errors=[], unexpected_requests=[])
    frames, pages, contexts = [], [], []
    chrome = shutil.which("google-chrome")
    assert chrome, "Installed Chrome required"
    browser = playwright.chromium.launch(executable_path=chrome, headless=True)
    report["chrome"] = browser.version

    def settled(page):
        page.wait_for_timeout(500)
        expect(page.get_by_test_id("stApp")).to_have_attribute("data-test-script-state", "notRunning")

    def seed(page, value, label="Semilla del experimento"):
        widget = page.get_by_role("spinbutton", name=label, exact=True)
        widget.fill(str(value)); widget.press("Enter")
        expect(widget).to_have_value(str(value))
        settled(page)

    def mode(page, name):
        page.get_by_test_id("stSidebar").get_by_text(name, exact=True).click()
        settled(page)

    def shot(page, name, marker=None):
        page.mouse.move(20, 20)
        locator = page.get_by_text(marker, exact=False) if marker else page.get_by_test_id("stAlert").last
        if locator.count():
            locator.scroll_into_view_if_needed()
        page.screenshot(path=str(owned.output/(name+".png")))
        report["screenshots"].append(name+".png")

    def download(page, name, case, value):
        page.get_by_role("button", name="Revelar explicación y comparar", exact=True).click()
        with page.expect_download() as received:
            page.get_by_role("button", name="↓ Descargar informe completo · JSON", exact=True).click()
        artifact = received.value
        assert artifact.suggested_filename == f"data-crime-scene_{case}_seed-{value}.json"
        target = owned.output/(name+".json")
        artifact.save_as(target)
        payload = json.loads(target.read_text())
        verify_download(payload, case, value)
        expect(page.get_by_test_id("stMetricValue").first).to_have_text(
            f"{payload['variants']['incorrect']['metrics']['accuracy']:.1%}")

    def wait_engines(count):
        deadline = time.monotonic()+20
        while len(owned.events("engine_start")) < count and time.monotonic() < deadline:
            time.sleep(.05)
        assert len(owned.events("engine_start")) == count

    try:
        expect.set_options(timeout=25000)
        for _ in range(2):
            context = browser.new_context(viewport={"width":1440,"height":1000}, accept_downloads=True)
            def route(route):
                parts = urlsplit(route.request.url)
                if parts.scheme in ("data", "blob") or (parts.hostname=="127.0.0.1" and parts.port==owned.port):
                    route.continue_()
                else:
                    report["unexpected_requests"].append(route.request.url)
                    route.abort()
            context.route("**/*", route)
            page = context.new_page()
            page.set_default_timeout(25000)
            page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
            page.on("websocket", lambda ws: ws.on("framereceived", lambda payload: frames.append(payload)))
            assert page.goto(owned.url).status == 200
            expect(page.get_by_role("heading", name="Data Crime Scene", exact=True)).to_be_visible()
            contexts.append(context); pages.append(page)
        a,b = pages
        seed(a,7)
        b.get_by_role("combobox", name="Expediente", exact=True).click()
        b.get_by_role("option").nth(1).click()
        seed(b,2026)
        owned.control("hold",mode="guided")
        button = a.get_by_role("button", name="Ejecutar experimento", exact=True)
        button.dblclick(delay=15) if enabled else button.click()
        wait_engines(1)
        b.get_by_role("button", name="Ejecutar experimento", exact=True).click()
        if not enabled:
            expect(b.get_by_text("Hay un cálculo en curso.",exact=False)).to_be_visible()
            shot(b,"01-rechazo-original")
            assert not owned.events("fifo_admitted")
            owned.control("release",mode="guided")
            expect(a.get_by_text("Cálculo real · caso future · semilla 7",exact=False)).to_be_visible()
            b.get_by_role("button",name="Ejecutar experimento",exact=True).click()
            expect(b.get_by_text("Cálculo real · caso groups · semilla 2026",exact=False)).to_be_visible()
            download(a,"a-future-7","future",7)
            download(b,"b-groups-2026","groups",2026)
            report["checks"].append("FIFO off: original immediate rejection, explicit retry, two real results and matching JSON")
        else:
            expect(a.get_by_text("Calculándose.",exact=False)).to_be_visible()
            expect(b.get_by_text("En cola · posición 1.",exact=False)).to_be_visible()
            for page in pages:
                page.get_by_role("button",name="Actualizar estado",exact=True).click()
                settled(page)
            seed(b,2027)
            b.get_by_role("button",name="Ejecutar experimento",exact=True).dblclick(delay=15)
            expect(b.get_by_text("Ya tienes un trabajo pendiente.",exact=False)).to_be_visible()
            assert len(owned.events("fifo_admitted")) == 2
            shot(b,"01-cola-configuracion-enviada")
            for selected,label in (("Laboratorio","Ejecutar configuración"),("Modo Detective","Abrir expediente")):
                mode(b,selected)
                b.get_by_role("button",name=label,exact=True).click()
                expect(b.get_by_text("Hay un cálculo en curso.",exact=False)).to_be_visible()
                assert len(owned.events("engine_start"))==1
                shot(b,"02-bloqueo-"+("lab" if selected=="Laboratorio" else "detective"))
            mode(b,"Recorrido guiado")
            owned.control("release",mode="guided")
            for page in pages:
                expect(page.get_by_text("Terminado.",exact=False)).to_be_visible()
            download(a,"a-future-7","future",7)
            download(b,"b-groups-2026","groups",2026)
            owned.control("isolation")
            shot(b,"03-resultado-b","Terminado.")
            report["checks"].append("FIFO on: two sessions, double click/reruns, changed pending seed, correct JSON, ownership isolation, original Lab/Detective rejection while Guided holds the same budget")
            owned.control("advance",seconds=4)
            owned.control("full_budget")
            seed(a,8)
            a.get_by_role("button",name="Ejecutar experimento",exact=True).click()
            expect(a.get_by_text("Esperando cupo.",exact=False)).to_be_visible()
            a.get_by_role("button",name="Ejecutar experimento",exact=True).dblclick(delay=15)
            settled(a)
            assert len(owned.events("fifo_admitted"))==3
            shot(a,"04-esperando-cupo")
            for selected,label in (("Laboratorio","Ejecutar configuración"),("Modo Detective","Abrir expediente")):
                mode(b,selected)
                b.get_by_role("button",name=label,exact=True).click()
                expect(b.get_by_text("presupuesto compartido",exact=False).last).to_be_visible()
            owned.control("advance",seconds=61)
            expect(a.get_by_text("Terminado.",exact=False)).to_be_visible()
            download(a,"a-future-8","future",8)
            report["checks"].append("Shared 12/minute budget: Guided accepted/waits, Lab and Detective reject; advancing the controlled clock completes Guided automatically")
            owned.control("advance",seconds=4)
            owned.control("full_budget")
            seed(a,9)
            a.get_by_role("button",name="Ejecutar experimento",exact=True).click()
            expect(a.get_by_text("Esperando cupo.",exact=False)).to_be_visible()
            before = len(owned.events("fifo_admitted"))
            a.reload()
            expect(a.get_by_text("Sesión nueva.",exact=False)).to_be_visible()
            expect(a.get_by_text("has perdido el acceso al trabajo anterior",exact=False)).to_be_visible()
            assert not a.get_by_test_id("stMetricValue").count()
            assert len(owned.events("fifo_admitted"))==before
            shot(a,"05-recarga-sin-reenvio")
            owned.control("advance",seconds=61)
            wait_engines(4)
            # Check the reverse direction with a real Laboratory call held active.
            mode(b,"Laboratorio")
            seed(b,321,"Semilla puntual")
            owned.control("hold",mode="laboratory")
            b.get_by_role("button",name="Ejecutar configuración",exact=True).click()
            wait_engines(5)
            seed(a,10)
            a.get_by_role("button",name="Ejecutar experimento",exact=True).click()
            expect(a.get_by_text("Otro cálculo ocupa el turno compartido",exact=False)).to_be_visible()
            assert len(owned.events("engine_start"))==5
            shot(a,"06-guiado-espera-laboratorio")
            owned.control("release",mode="laboratory")
            expect(a.get_by_text("Terminado.",exact=False)).to_be_visible()
            download(a,"a-nueva-future-10","future",10)
            report["checks"].append("Reload loses access and explains it without resubmission; real Lab calculation then blocks Guided until the same global executor is released")
        settled(a)
        before = len(owned.events("engine_start"))
        b.reload()
        expect(b.get_by_role("heading",name="Data Crime Scene",exact=True)).to_be_visible()
        settled(b)
        assert not b.get_by_test_id("stMetricValue").count()
        assert len(owned.events("engine_start"))==before
        blobs = [p.content() for p in pages]+[p.url for p in pages]+[f.decode("latin1") if isinstance(f,bytes) else f for f in frames]
        owned.control("privacy",blobs=blobs)
        engine = owned.events("engine_start")
        assert all(e["active"]==1 for e in engine)
        assert all(e["shared"] for e in owned.events("budget_admitted"))
        assert not report["page_errors"] and not report["unexpected_requests"]
        assert not any(p.get_by_test_id("stException").count() for p in pages)
        report.update(status="passed",engine_calls=[{k:e[k] for k in ("origin","case","seed")} for e in engine],
                      max_active_engine=1, all_admissions_same_budget=True,
                      fifo_admissions=len(owned.events("fifo_admitted")),
                      downloads={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in owned.output.glob("*-*.json")})
    finally:
        browser.close()
        (owned.output/"browser.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",type=Path)
    parser.add_argument("--worker",action="store_true",help=argparse.SUPPRESS)
    parser.add_argument("--fifo",choices=("0","1"),default="0",help=argparse.SUPPRESS)
    parser.add_argument("--port",type=int,help=argparse.SUPPRESS)
    parser.add_argument("--trace",help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.worker:
        worker(args)
        return
    if not args.output_dir:
        parser.error("--output-dir required")
    output=args.output_dir.resolve()
    output.mkdir(parents=True,exist_ok=False)
    from playwright.sync_api import sync_playwright
    summary=dict(at=datetime.now(timezone.utc).isoformat(),trials=[])
    try:
        with sync_playwright() as playwright:
            for flag in ("0","1"):
                owned=Owned(output/("fifo-"+flag),flag)
                try:
                    owned.start()
                    result=visit(playwright,owned,flag=="1")
                    summary["trials"].append(result)
                finally:
                    owned.close()
        summary["status"]="passed"
    finally:
        (output/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
