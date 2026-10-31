"""QA real de la vista Laboratorio sobre loopback; no ejecuta el estudio.

Requiere app.py sirviendo en 127.0.0.1:8501 y el estudio previamente calculado.
Las capturas no sustituyen a las pruebas metodológicas ni a AppTest.
"""

import json
from pathlib import Path
import shutil
from urllib.parse import urlparse

import numpy as np
from playwright.sync_api import expect, sync_playwright
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
SHOTS = ROOT / "docs" / "screenshots"
URL = "http://127.0.0.1:8501"


def main():
    expect.set_options(timeout=30000)
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        raise SystemExit("Instala Chrome/Chromium del sistema para repetir esta revisión opcional.")
    ARTIFACTS.mkdir(exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    errors, external, checks = [], [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome, headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)

        def local_only(route):
            if urlparse(route.request.url).hostname in {"localhost", "127.0.0.1"}:
                route.continue_()
            else:
                external.append(route.request.url)
                route.abort()

        context.route("**/*", local_only)
        page = context.new_page()
        page.set_default_timeout(30000)
        page.on("pageerror", lambda value: errors.append(str(value)))
        assert page.goto(URL).status == 200
        expect(page.get_by_role("heading", name="Data Crime Scene", exact=True)).to_be_visible()
        page.get_by_test_id("stSidebar").get_by_text("Laboratorio", exact=True).click()
        expect(page.get_by_role("heading", name="Laboratorio", exact=True)).to_be_visible()
        expect(page.get_by_text("No hay un estudio cargado.", exact=False)).to_be_visible()
        assert page.get_by_role("button", name="↓ Descargar ejecución puntual · JSON").count() == 0

        def select_case(index):
            page.get_by_test_id("stSidebar").get_by_role("combobox").click()
            page.get_by_role("option").nth(index).click()

        def download_run(case_id, seed, level):
            page.get_by_role("button", name="Ejecutar configuración", exact=True).click()
            expect(page.get_by_role("heading", name="Resultado de la configuración", exact=True)).to_be_visible()
            expect(page.get_by_text(f"semilla {seed} · nivel {level}", exact=False)).to_be_visible()
            with page.expect_download() as download:
                page.get_by_role("button", name="↓ Descargar ejecución puntual · JSON").click()
            path = ARTIFACTS / f"browser-lab-{case_id}-{seed}-{level}.json"
            download.value.save_as(path)
            report = json.loads(path.read_text(encoding="utf-8"))
            assert report["config"]["case_id"] == case_id
            assert report["config"]["seed"] == seed and report["config"]["level"] == level
            for variant in list(report["variants"].values()) + list(report["cohort"].values()):
                y, pred = variant["y_true"], variant["y_pred"]
                scores = {"accuracy": accuracy_score(y, pred), "balanced_accuracy": balanced_accuracy_score(y, pred),
                          "f1": f1_score(y, pred, zero_division=0)}
                assert scores == variant["metrics"]
                assert variant["confusion_matrix"] == confusion_matrix(y, pred, labels=[0, 1]).tolist()
            assert page.get_by_test_id("stException").count() == 0
            checks.append({"case_id": case_id, "seed": seed, "level": level, "download_metrics_recalculated": True})

        download_run("future", 42, 0.25)
        page.get_by_role("slider").press("End")
        expect(page.get_by_role("heading", name="Resultado de la configuración", exact=True)).to_have_count(0)
        download_run("future", 42, 0.5)
        select_case(1)
        expect(page.get_by_role("heading", name="Resultado de la configuración", exact=True)).to_have_count(0)
        download_run("groups", 42, 0.35)
        page.get_by_role("button", name="Cargar estudio local", exact=True).click()
        expect(page.get_by_role("heading", name="Estudio cargado · resultados calculados anteriormente", exact=True)).to_be_visible()
        expect(page.get_by_text("Combinaciones previstas:", exact=False)).to_be_visible()
        expect(page.get_by_test_id("stPlotlyChart")).to_have_count(3)
        assert page.get_by_test_id("stException").count() == 0
        with page.expect_download() as download:
            page.get_by_role("button", name="↓ Descargar estudio cargado completo · JSON").click()
        study_path = ARTIFACTS / "browser-lab-study.json"
        download.value.save_as(study_path)
        shown = json.loads(study_path.read_text(encoding="utf-8"))
        source = json.loads((ARTIFACTS / "laboratory-study.json").read_text(encoding="utf-8"))
        assert shown == source
        assert len(shown["entries"]) == 90 and all(item["status"] == "ok" for item in shown["entries"])

        def check_js_quartiles():
            # Se inspecciona el cálculo real del motor JS, no solo el JSON enviado.
            plots = page.locator(".js-plotly-plot")
            expect(plots).to_have_count(3 if page.get_by_role("heading", name="El mismo sospechoso en ambos lados", exact=True).count() else 2)
            computed = plots.first.evaluate("el => el.calcdata.map(trace => trace.map(box => ({q1:box.q1, median:box.med,q3:box.q3, points:box.pts.map(point=>point.v)})))")
            total = 0
            for trace in computed:
                for box in trace:
                    values = box["points"]
                    assert len(values) == 10
                    assert np.isclose(box["q1"], np.quantile(values, .25))
                    assert np.isclose(box["median"], np.median(values))
                    assert np.isclose(box["q3"], np.quantile(values, .75))
                    total += len(values)
            return total

        group_points = check_js_quartiles()
        assert group_points == 60
        page.get_by_test_id("stPlotlyChart").nth(1).scroll_into_view_if_needed()
        page.screenshot(path=str(SHOTS / "05-laboratorio-escritorio.png"))
        select_case(2)
        seed = page.get_by_role("spinbutton", name="Semilla puntual")
        seed.fill("7")
        seed.press("Enter")
        expect(page.get_by_role("heading", name="Resultado de la configuración", exact=True)).to_have_count(0)
        download_run("selection", 7, 500)
        expect(page.get_by_test_id("stPlotlyChart")).to_have_count(2)
        selection_points = check_js_quartiles()
        assert selection_points == 90

        page.set_viewport_size({"width": 390, "height": 844})
        sidebar = page.get_by_test_id("stSidebar")
        expect(sidebar).to_have_attribute("data-collapsed", "true")
        page.get_by_role("button", name="Expand sidebar").click()
        expect(sidebar).to_have_attribute("data-collapsed", "false")
        expect(page.get_by_role("button", name="Ejecutar configuración", exact=True)).to_be_visible()
        page.get_by_role("button", name="Collapse sidebar").click()
        page.wait_for_function("document.querySelector('[data-testid=stSidebar]').getBoundingClientRect().right <= 0")
        page.get_by_role("heading", name="Laboratorio", exact=True).scroll_into_view_if_needed()
        page.screenshot(path=str(SHOTS / "06-laboratorio-movil.png"))
        page.get_by_test_id("stPlotlyChart").first.scroll_into_view_if_needed()
        page.screenshot(path=str(SHOTS / "07-laboratorio-distribucion-movil.png"))
        page.get_by_test_id("stPlotlyChart").last.scroll_into_view_if_needed()
        page.screenshot(path=str(SHOTS / "08-laboratorio-diferencias-movil.png"))
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not errors and not external, (errors, external)
        summary = {"url": URL, "viewports": [[1440, 1000], [390, 844]], "runs": checks,
                   "study_export_matches_source": True, "group_internal_js_points": group_points,
                   "selection_internal_js_points": selection_points,
                   "js_quartiles_match_numpy": True, "page_errors": errors, "external_requests": external}
        (ARTIFACTS / "browser-lab-check.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        browser.close()


if __name__ == "__main__":
    main()
