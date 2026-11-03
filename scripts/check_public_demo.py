"""Two-browser-context QA of the public entrypoint on loopback; never deploys."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def verify_predictions(value):
    y, pred = value["y_true"], value["y_pred"]
    tn, fp, fn, tp = (sum(a == i and b == j for a, b in zip(y, pred))
                      for i, j in ((0, 0), (0, 1), (1, 0), (1, 1)))
    recalls = [hit / total for hit, total in ((tn, tn + fp), (tp, tp + fn)) if total]
    scores = {"accuracy": (tn + tp) / len(y), "balanced_accuracy": sum(recalls) / len(recalls),
              "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0}
    assert all(abs(value["metrics"][k] - v) < 1e-12 for k, v in scores.items())
    assert value["confusion_matrix"] == [[tn, fp], [fn, tp]]


def assert_public(value):
    if isinstance(value, dict):
        assert not {"solution", "explanation", "expected", "correct_option", "_source", "_variant"}.intersection(value)
        for child in value.values():
            assert_public(child)
    elif isinstance(value, list):
        for child in value:
            assert_public(child)


class Visit:
    def __init__(self, page, output, report, width):
        self.page, self.output, self.report, self.width = page, output, report, width
        page.set_default_timeout(30000)
        page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
        page.on("console", lambda m: report["console_errors"].append(m.text) if m.type == "error" else None)

    def settle(self):
        self.page.wait_for_timeout(250)
        expect(self.page.get_by_test_id("stApp")).to_have_attribute("data-test-script-state", "notRunning")
        assert self.page.get_by_test_id("stException").count() == 0

    def sidebar(self, opened=True):
        side = self.page.get_by_test_id("stSidebar")
        collapsed = side.get_attribute("data-collapsed") == "true"
        if opened == collapsed:
            self.page.get_by_role("button", name="Expand sidebar" if opened else "Collapse sidebar", exact=True).click()
            self.page.wait_for_timeout(350)

    def mode(self, name):
        self.sidebar()
        self.page.get_by_test_id("stSidebar").get_by_text(name, exact=True).click()
        self.settle()
        if self.width == 390:
            self.sidebar(False)

    def choose(self, label, option):
        control = self.page.get_by_role("combobox", name=label, exact=True)
        control.click()
        control.press("ArrowDown")
        self.page.get_by_role("option", name=option, exact=True).click()
        self.settle()

    def click(self, label):
        started = time.perf_counter()
        self.page.get_by_role("button", name=label, exact=True).click()
        self.settle()
        self.report["operations"].append({"viewport": self.width, "operation": label,
                                           "seconds": time.perf_counter() - started})

    def download(self, label, name):
        with self.page.expect_download() as received:
            self.page.get_by_role("button", name=label, exact=True).click()
        path = self.output / f"{self.width}-{name}.json"
        received.value.save_as(path)
        self.settle()
        return json.loads(path.read_text())

    def shot(self, name):
        if self.width == 390:
            self.sidebar(False)
        self.page.get_by_test_id("stMain").evaluate("el => el.scrollTop = 0")
        self.settle()
        overflow = self.page.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
        assert not overflow
        path = self.output / f"{self.width}-{name}.png"
        self.page.screenshot(path=str(path))
        self.report["screenshots"].append(path.name)

    def answer(self, note):
        self.page.get_by_text("Hay contaminación en uno de los mecanismos investigados", exact=True).click()
        self.settle()
        evidence = self.page.get_by_role("combobox", name="Evidencia que sostiene tu diagnóstico", exact=True)
        evidence.click()
        evidence.press("ArrowDown")
        self.page.get_by_role("option", name="Momento de disponibilidad de las variables", exact=True).click()
        self.page.keyboard.press("Escape")
        self.settle()
        self.choose("Acción propuesta", "Retirar del modelo la variable que no existe al predecir")
        self.page.get_by_role("textbox", name="Notas de investigación · no se califican", exact=True).fill(note)
        self.page.keyboard.press("Tab")
        self.settle()
        self.click("Confirmar respuesta")
        expect(self.page.get_by_role("button", name="Confirmar respuesta", exact=True)).to_be_disabled()

    def summary(self, name):
        box = self.page.get_by_test_id("stExpander").filter(has_text="Resumen de la sesión")
        header = box.locator("summary")
        if not header.evaluate("el => el.parentElement.open"):
            header.click()
        return self.download("↓ Descargar resumen de sesión · JSON", name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8502")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if urlparse(args.url).hostname not in {"127.0.0.1", "localhost"}:
        parser.error("Use a loopback server; this script does not test or create a deployment.")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    report = {"url": args.url, "at": datetime.now(timezone.utc).isoformat(), "checks": [],
              "operations": [], "screenshots": [], "page_errors": [], "console_errors": [],
              "external_requests": [], "measurement_scope": "Local browser and server; includes UI/network waiting, not cloud performance"}
    expect.set_options(timeout=30000)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=shutil.which("google-chrome") or shutil.which("chromium"), headless=True)
            visits = []
            for width in (1440, 390):
                context = browser.new_context(viewport={"width": width, "height": 1000 if width == 1440 else 844}, accept_downloads=True)
                def local_only(route):
                    if urlparse(route.request.url).hostname in {"127.0.0.1", "localhost"}:
                        route.continue_()
                    else:
                        report["external_requests"].append(route.request.url)
                        route.abort()
                context.route("**/*", local_only)
                page = context.new_page()
                visit = Visit(page, args.output_dir, report, width)
                visits.append(visit)
                started = time.perf_counter()
                assert page.goto(args.url).status == 200
                expect(page.get_by_role("heading", name="Data Crime Scene", exact=True)).to_be_visible()
                visit.settle()
                report["operations"].append({"viewport": width, "operation": "open first page", "seconds": time.perf_counter() - started})
                visit.sidebar()
                visit.click("Ejecutar experimento")
                if width == 390:
                    visit.sidebar(False)
                assert page.get_by_role("button", name="↓ Descargar informe completo · JSON").count() == 0
                assert page.get_by_text("04 / EXPEDIENTE", exact=False).count() == 0
                visit.shot("guided")
                visit.click("Revelar explicación y comparar")
                guided = visit.download("↓ Descargar informe completo · JSON", "guided")
                for variant in guided["variants"].values():
                    verify_predictions(variant)
                assert page.get_by_test_id("stMetricValue").first.inner_text() == f"{guided['variants']['incorrect']['metrics']['accuracy']:.1%}"
                report["checks"].append(f"{width}: guided calculation, reveal, metrics and JSON")

                visit.mode("Laboratorio")
                assert page.get_by_role("textbox", name="Archivo local del estudio").count() == 0
                assert page.get_by_role("button", name="Cargar estudio local").count() == 0
                assert ".venv/bin" not in page.content()
                expect(page.get_by_text("Esta demo no incluye un estudio agregado.", exact=False)).to_be_visible()
                visit.sidebar()
                visit.choose("Caso de laboratorio", "El mismo sospechoso en ambos lados")
                visit.click("Ejecutar configuración")
                if width == 390:
                    visit.sidebar(False)
                lab = visit.download("↓ Descargar ejecución puntual · JSON", "lab-groups")
                assert lab["config"]["case_id"] == "groups"
                for value in list(lab["variants"].values()) + list(lab["cohort"].values()):
                    verify_predictions(value)
                assert page.get_by_test_id("stDataFrame").count() >= 2
                visit.shot("laboratory")
                report["checks"].append(f"{width}: laboratory real groups/cohort, absent study, no paths or commands, exported metrics recomputed")

                visit.mode("Modo Detective")
                visit.sidebar()
                visit.choose("Expediente de la sesión", "La mesa norte")
                visit.click("Abrir expediente")
                if width == 390:
                    visit.sidebar(False)
                evidence = visit.download("↓ Descargar evidencia disponible · JSON", "detective-evidence")
                assert evidence["template_id"] == "d01"
                verify_predictions(evidence["experiment"])
                assert_public(evidence)
                initial = visit.download("↓ Descargar investigación · JSON", "detective-before")
                assert_public(initial)
                assert page.get_by_text("Diagnóstico del expediente:", exact=False).count() == 0
                assert page.get_by_test_id("stMetricValue").first.inner_text() == f"{evidence['experiment']['metrics']['accuracy']:.1%}"
                visit.shot("detective")
                visit.click("Consultar pista 1")
                visit.answer(f"Private note for context {width}")
                confirmed = visit.download("↓ Descargar investigación · JSON", "detective-confirmed")
                assert "solution" not in confirmed
                report["checks"].append(f"{width}: detective evidence, hint, answer and downloads before reveal")

            first, second = visits
            first.click("Revelar solución y explicación")
            first.click("Ejecutar la acción elegida")
            result = first.download("↓ Descargar investigación · JSON", "detective-after")
            assert result["solution"]["diagnosis"] == "contaminated"
            assert result["intervention"]["performed"]
            for key in ("before", "after"):
                verify_predictions(result["intervention"][key])
            assert "registro_c17" in result["intervention"]["before"]["feature_names"]
            assert "registro_c17" not in result["intervention"]["after"]["feature_names"]
            first.click("Ejecutar la acción elegida")
            assert first.download("↓ Descargar investigación · JSON", "detective-idempotent") == result
            other = second.download("↓ Descargar investigación · JSON", "second-unrevealed")
            assert "solution" not in other and other["investigation"]["answers"]["initial"]["notes"] == "Private note for context 390"
            # Include tooltips and accessible labels via DOM, and the accessibility tree.
            explanation = result["solution"]["explanation"]
            assert explanation not in second.page.content()
            assert explanation not in second.page.locator("body").aria_snapshot()
            first.sidebar()
            first.click("Reiniciar sesión")
            if first.width == 390:
                first.sidebar(False)
            reset = first.summary("reset")
            assert reset["completed"] == reset["hints_used"] == reset["solutions_consulted"] == 0
            assert second.download("↓ Descargar investigación · JSON", "second-after-first-reset") == other
            report["checks"].append("Two independent contexts: notes, answers, reveal, real intervention and reset isolated; repeat intervention idempotent")
            assert not report["page_errors"] and not report["console_errors"] and not report["external_requests"]
            report["status"] = "passed"
            browser.close()
    except Exception as error:
        report["status"] = "failed"
        report["error"] = repr(error)
        raise
    finally:
        (args.output_dir / "browser.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
