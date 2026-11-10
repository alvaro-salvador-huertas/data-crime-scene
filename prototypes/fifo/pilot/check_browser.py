"""Owned local Streamlit + FIFO, two Chrome contexts, no capacity campaign."""
import argparse
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
import time
from urllib.parse import urlsplit
import urllib.request

from playwright.sync_api import expect, sync_playwright

from prototypes.fifo.pilot.fixtures import Fixture
from scripts.benchmark_demo import read_jsonl, verify_download

ROOT = Path(__file__).resolve().parents[3]


def wait_until(check, timeout=15):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(.05)
    raise AssertionError("Condition did not become true")


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    fixture = Fixture(output/"fifo-events.jsonl")
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    report = {"at": datetime.now(timezone.utc).isoformat(), "url": url, "checks": [],
              "screenshots": [], "page_errors": [], "console_errors": [],
              "unexpected_requests": [], "controlled_cases": ["engine_gate", "budget", "failure", "expiry"],
              "status": "incomplete"}
    frames = []  # memory only; never save network payloads or tokens
    log = (output/"streamlit.log").open("w")
    proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run",
                             "prototypes/fifo/pilot/streamlit_app.py", "--server.address=127.0.0.1",
                             f"--server.port={port}", "--server.headless=true", "--browser.gatherUsageStats=false"],
                            cwd=ROOT, env=dict(os.environ, DCS_FIFO_URL=fixture.url, PYTHONDONTWRITEBYTECODE="1"),
                            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

    def events(kind):
        return [e for e in read_jsonl(output/"fifo-events.jsonl") if e["event"] == kind]

    def shot(page, name):
        # Keep the status in view rather than the much longer teaching sections.
        page.mouse.move(20, 20)  # avoid covering the evidence with a button tooltip
        alert = (page.get_by_text("Terminado.", exact=False) if name.startswith(("03-", "04-", "09-"))
                 else page.get_by_test_id("stAlert").last)
        if alert.count():
            alert.scroll_into_view_if_needed()
        page.screenshot(path=str(output/(name+".png")), full_page=False)
        report["screenshots"].append(name+".png")

    def seed(page, value):
        control = page.get_by_role("spinbutton", name="Semilla del experimento", exact=True)
        control.fill(str(value))
        control.press("Enter")
        expect(control).to_have_value(str(value))
        expect(page.get_by_test_id("stApp")).to_have_attribute("data-test-script-state", "notRunning")

    def drained(page):
        # UI assertions can see the first click's old text before the second
        # click has reached Python. Drain it before jumping the *test* clock
        # by minutes; otherwise that late click legitimately submits after TTL.
        page.wait_for_timeout(500)
        expect(page.get_by_test_id("stApp")).to_have_attribute("data-test-script-state", "notRunning")

    def download(page, name, case, expected_seed):
        page.get_by_role("button", name="Revelar explicación y comparar", exact=True).click()
        button = page.get_by_role("button", name="↓ Descargar informe completo · JSON", exact=True)
        with page.expect_download() as received:
            button.click()
        artifact = received.value
        assert artifact.suggested_filename == f"data-crime-scene_{case}_seed-{expected_seed}.json"
        path = output/(name+".json")
        artifact.save_as(path)
        raw = path.read_bytes()
        value = json.loads(raw)
        verify_download(value, case, expected_seed)
        expect(page.get_by_test_id("stMetricValue").first).to_have_text(
            f"{value['variants']['incorrect']['metrics']['accuracy']:.1%}")
        return raw

    try:
        def ready():
            assert proc.poll() is None, "Streamlit exited"
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(url+"/_stcore/health", timeout=.3) as response:
                    return response.status == 200
            except OSError:
                return False
        wait_until(ready, 30)
        expect.set_options(timeout=20000)
        with sync_playwright() as playwright:
            chrome = shutil.which("google-chrome")
            assert chrome, "Real Chrome must already be installed"
            browser = playwright.chromium.launch(executable_path=chrome, headless=True)
            report["chrome"] = browser.version
            contexts, pages = [], []
            for i in range(2):
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
                def route_handler(route):
                    parts = urlsplit(route.request.url)
                    allowed = parts.scheme in {"data", "blob"} or (parts.hostname == "127.0.0.1" and parts.port == port)
                    if not allowed:
                        report["unexpected_requests"].append(route.request.url)
                        route.abort()
                    else:
                        route.continue_()
                context.route("**/*", route_handler)
                page = context.new_page()
                page.set_default_timeout(20000)
                page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
                page.on("console", lambda m: report["console_errors"].append(m.text) if m.type == "error" else None)
                page.on("websocket", lambda ws: ws.on("framereceived", lambda payload: frames.append(payload)))
                assert page.goto(url).status == 200
                expect(page.get_by_role("heading", name="Data Crime Scene", exact=True)).to_be_visible()
                expect(page.get_by_text("Sesión nueva.", exact=False)).to_be_visible()
                contexts.append(context)
                pages.append(page)
            a, b = pages
            fixture.gate.clear()
            seed(a, 7)
            a.get_by_role("button", name="Ejecutar experimento", exact=True).dblclick(delay=15)
            expect(a.get_by_text("Calculándose.", exact=False)).to_be_visible()
            wait_until(lambda: len(events("admitted")) == 1)
            first = events("admitted")[0]["job"]
            b.get_by_role("combobox", name="Expediente", exact=True).click()
            b.get_by_role("option").nth(1).click()
            seed(b, 2026)
            b.get_by_role("button", name="Ejecutar experimento", exact=True).dblclick(delay=15)
            expect(b.get_by_text("En cola · posición 1.", exact=False)).to_be_visible()
            wait_until(lambda: len(events("admitted")) == 2)
            second = events("admitted")[1]["job"]
            assert fixture.scheduler.jobs[first]["owner"] != fixture.scheduler.jobs[second]["owner"]
            for page in pages:
                page.get_by_role("button", name="Actualizar estado", exact=True).click()
                expect(page.get_by_text("Referencia del trabajo:", exact=False)).to_be_visible()
                assert page.get_by_test_id("stMetricValue").count() == 0
            seed(b, 2027)
            b.get_by_role("button", name="Ejecutar experimento", exact=True).click()
            expect(b.get_by_text("Ya tienes un trabajo pendiente.", exact=False)).to_be_visible()
            expect(b.get_by_text("Solicitud enviada · caso groups · semilla 2026", exact=True)).to_be_visible()
            assert len(events("admitted")) == 2
            assert all(e["seed"] != 2027 for e in events("request"))
            shot(a, "01-calculandose-sesion-a")
            shot(b, "02-cola-seleccion-cambiada-sesion-b")
            fixture.gate.set()
            for page in pages:
                expect(page.get_by_text("Terminado.", exact=False)).to_be_visible()
            assert fixture.real_calls == [("future", 7), ("groups", 2026)]
            raw_a = download(a, "sesion-a-future-7", "future", 7)
            raw_b = download(b, "sesion-b-groups-2026", "groups", 2026)
            assert raw_a != raw_b
            assert raw_a.decode() == fixture.scheduler.jobs[first]["result"]
            assert raw_b.decode() == fixture.scheduler.jobs[second]["result"]
            from prototypes.fifo.pilot.client import Client, ServiceError
            for jid, wrong_owner in ((first, fixture.scheduler.jobs[second]["owner"]),
                                     (second, fixture.scheduler.jobs[first]["owner"])):
                for suffix in ("", "/result"):
                    try:
                        Client(fixture.url).call("GET", "/jobs/"+jid+suffix, wrong_owner)
                    except ServiceError as error:
                        assert error.status == 404
                    else:
                        raise AssertionError("Cross-session access succeeded")
            shot(a, "03-resultado-sesion-a")
            shot(b, "04-resultado-enviado-sesion-b")
            for page in pages:
                page.get_by_role("button", name="Actualizar estado", exact=True).click()
            assert len(events("engine_start")) == 2
            report["checks"].append("Two independent contexts: genuine double clicks, full reruns, running/queued states, pending draft seed change blocked; one real calculation and matching download per session")
            # Same completed request in A stays the same; B's download survives A reruns.
            a.get_by_role("button", name="Ejecutar experimento", exact=True).click()
            expect(a.get_by_text("Esta solicitud ya está aceptada.", exact=False)).to_be_visible()
            drained(a)
            assert len(events("admitted")) == 2
            assert len(fixture.real_calls) == 2
            expect(b.get_by_text("Cálculo real · caso groups · semilla 2026", exact=True)).to_be_visible()
            report["checks"].append("Completed request and download do not recompute or change the other session")
            # Controlled rolling-budget wait, without a capacity campaign.
            fixture.advance(4)
            fixture.full_budget()
            seed(a, 8)
            a.get_by_role("button", name="Ejecutar experimento", exact=True).click()
            expect(a.get_by_text("Esperando cupo.", exact=False)).to_be_visible()
            expect(a.get_by_text("no hace falta volver a pulsar", exact=False)).to_be_visible()
            budget_job = events("admitted")[-1]["job"]
            a.get_by_role("button", name="Actualizar estado", exact=True).click()
            a.get_by_role("button", name="Ejecutar experimento", exact=True).dblclick(delay=15)
            expect(a.get_by_text("Esperando cupo.", exact=False)).to_be_visible()
            drained(a)
            assert events("admitted")[-1]["job"] == budget_job and len(events("admitted")) == 3
            shot(a, "05-esperando-cupo-aceptado")
            fixture.advance(61)
            expect(a.get_by_text("Terminado.", exact=False)).to_be_visible()
            expect(a.get_by_text("Cálculo real · caso future · semilla 8", exact=True)).to_be_visible()
            download(a, "sesion-a-cupo-future-8", "future", 8)
            report["checks"].append("Controlled quota recovery reaches the real result automatically, without another click")
            # A separate accepted job remains pending for the reload check.
            fixture.advance(4)
            fixture.full_budget()
            seed(a, 11)
            a.get_by_role("button", name="Ejecutar experimento", exact=True).click()
            expect(a.get_by_text("Esperando cupo.", exact=False)).to_be_visible()
            reload_job = events("admitted")[-1]["job"]
            # Reload while waiting loses st.session_state, but does not re-submit.
            a.reload()
            expect(a.get_by_text("Sesión nueva.", exact=False)).to_be_visible()
            expect(a.get_by_text("la sesión anterior se ha perdido", exact=False)).to_be_visible()
            assert a.get_by_text("Referencia del trabajo:", exact=False).count() == 0
            assert a.get_by_test_id("stMetricValue").count() == 0
            assert len(events("admitted")) == 4
            assert fixture.scheduler.jobs[reload_job]["state"] == "waiting_budget"
            shot(a, "06-recarga-sesion-perdida")
            fixture.advance(61)
            wait_until(lambda: fixture.scheduler.jobs[reload_job]["state"] == "succeeded")
            expect(a.get_by_text("Sesión nueva.", exact=False)).to_be_visible()
            assert a.get_by_test_id("stMetricValue").count() == 0
            report["checks"].append("Controlled 12/minute exhaustion: accepted waiting, double clicks and reruns keep one job; reloading loses UI session and explains it, does not resubmit, old accepted job still completes")
            # New UI session after reload explicitly submits a controlled failure.
            fixture.fail_next = True
            seed(a, 9)
            a.get_by_role("button", name="Ejecutar experimento", exact=True).click()
            expect(a.get_by_text("El cálculo ha fallado.", exact=False)).to_be_visible()
            failed = events("admitted")[-1]["job"]
            a.get_by_role("button", name="Ejecutar experimento", exact=True).dblclick(delay=15)
            expect(a.get_by_text("El cálculo ha fallado.", exact=False)).to_be_visible()
            drained(a)
            assert len(events("admitted")) == 5
            assert fixture.scheduler.jobs[failed]["state"] == "failed"
            assert a.get_by_role("button", name="↓ Descargar informe completo · JSON", exact=True).count() == 0
            shot(a, "07-fallo-controlado")
            report["checks"].append("Injected engine failure has no metrics/download, repeated request stays failed and does not execute again")
            # Expire existing results and failed jobs via clock, not real waiting.
            fixture.advance(301)
            b.get_by_role("button", name="Actualizar estado", exact=True).click()
            expect(b.get_by_text("Este trabajo ya no está disponible", exact=False)).to_be_visible()
            assert b.get_by_role("button", name="↓ Descargar informe completo · JSON", exact=True).count() == 0
            assert b.get_by_test_id("stMetricValue").count() == 0
            shot(b, "08-resultado-caducado")
            assert len(events("admitted")) == 5
            report["checks"].append("Controlled result expiry clears a previously displayed result/download, explains expiry, and does not submit again")
            # Explicit recovery with a new requested configuration after failure.
            seed(a, 10)
            a.get_by_role("button", name="Ejecutar experimento", exact=True).click()
            expect(a.get_by_text("Terminado.", exact=False)).to_be_visible()
            download(a, "sesion-nueva-future-10", "future", 10)
            a.set_viewport_size({"width": 390, "height": 844})
            a.get_by_test_id("stMain").evaluate("el => el.scrollTop = 0")
            assert a.evaluate("document.documentElement.scrollWidth <= innerWidth+1")
            shot(a, "09-recuperacion-movil")
            report["checks"].append("Explicit new configuration after failure succeeds; narrow viewport has no horizontal overflow")
            # Scan UI DOM, URLs, websocket payloads and on-disk logs for all tokens.
            tokens = list(fixture.scheduler.sessions)
            rendered = [page.content().encode() for page in pages]
            wire = [f.encode() if isinstance(f, str) else f for f in frames]
            disk = [p.read_bytes() for p in output.iterdir() if p.is_file()]
            for token in tokens:
                needle = token.encode()
                assert all(needle not in content for content in rendered+wire+disk)
                assert all(token not in page.url for page in pages)
            assert all(not page.get_by_test_id("stException").count() for page in pages)
            assert not report["page_errors"] and not report["console_errors"] and not report["unexpected_requests"]
            report["checks"].append("Other-session status/result return 404; browser made no FIFO requests; tokens absent from URLs, DOM, received WebSocket frames and generated logs/artifacts")
            report["real_engine_calls"] = [dict(case=c, seed=s) for c, s in fixture.real_calls]
            report["admissions"] = len(events("admitted"))
            report["engine_starts_including_injected_failure"] = len(events("engine_start"))
            report["downloads_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob("sesion*.json")}
            report["status"] = "passed"
            browser.close()
    except Exception as error:
        # Assertion messages contain no session objects or HTTP headers.
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        fixture.close()
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=3)
        log.close()
        report["server_stopped"] = proc.poll() is not None
        (output/"browser.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    report = run(args.output_dir.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
