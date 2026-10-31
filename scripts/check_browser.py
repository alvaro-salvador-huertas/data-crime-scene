"""Revisión local opcional. Requiere Streamlit en 127.0.0.1:8501 y Chrome.

Instala requirements-browser.txt y ejecuta con .venv/bin/python scripts/check_browser.py.
No instala navegadores. Bloquea todas las peticiones HTTP fuera de loopback.
"""

import json
from pathlib import Path
import shutil
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS = ROOT / "docs" / "screenshots"
ARTIFACTS = ROOT / "artifacts"
URL = "http://127.0.0.1:8501"


def main():
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    ARTIFACTS.mkdir(exist_ok=True)
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if chrome is None:
        raise SystemExit("No se encuentra Chrome/Chromium del sistema. AppTest no requiere navegador.")
    errors, external_requests, checked = [], [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome, headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)

        def local_only(route):
            if urlparse(route.request.url).hostname in {"127.0.0.1", "localhost"}:
                route.continue_()
            else:
                external_requests.append(route.request.url)
                route.abort()

        context.route("**/*", local_only)
        page = context.new_page()
        page.set_default_timeout(15000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        response = page.goto(URL)
        assert response.status == 200
        expect(page.get_by_role("heading", name="Data Crime Scene", exact=True)).to_be_visible()
        expect(page.get_by_text("El expediente está preparado.", exact=False)).to_be_visible()

        def select_case(index):
            page.get_by_test_id("stSidebar").get_by_role("combobox").click()
            page.get_by_role("option").nth(index).click()

        def execute_and_reveal(case_id, seed):
            page.get_by_role("button", name="Ejecutar experimento", exact=True).click()
            expect(page.get_by_text(f"Cálculo real · caso {case_id} · semilla {seed}", exact=False)).to_be_visible()
            page.get_by_text("Pista 1", exact=True).click()
            expect(page.get_by_role("button", name="Revelar explicación y comparar")).to_be_visible()
            page.get_by_role("button", name="Revelar explicación y comparar").click()
            expect(page.get_by_role("heading", name="La comparación", exact=True)).to_be_visible()
            assert page.get_by_test_id("stException").count() == 0
            with page.expect_download() as download:
                page.get_by_role("button", name="↓ Descargar informe completo · JSON").click()
            path = ARTIFACTS / f"browser-{case_id}-{seed}.json"
            download.value.save_as(path)
            report = json.loads(path.read_text(encoding="utf-8"))
            assert report["case_id"] == case_id and report["seed"] == seed
            for variant in report["variants"].values():
                assert variant["train_size"] == len(variant["train_row_ids"])
                assert variant["test_size"] == len(variant["test_row_ids"])
            expect(page.get_by_test_id("stMetricValue").first).to_have_text(
                f"{report['variants']['incorrect']['metrics']['accuracy']:.1%}"
            )
            checked.append({"case_id": case_id, "seed": seed, "download_matches_visible_accuracy": True})

        execute_and_reveal("future", 42)
        page.get_by_role("heading", name="Data Crime Scene", exact=True).scroll_into_view_if_needed()
        page.screenshot(path=str(SCREENSHOTS / "01-escritorio.png"))
        page.get_by_role("heading", name="La comparación", exact=True).scroll_into_view_if_needed()
        page.get_by_test_id("stPlotlyChart").scroll_into_view_if_needed()
        page.screenshot(path=str(SCREENSHOTS / "02-comparacion.png"))
        select_case(1)
        expect(page.get_by_text("Has cambiado el caso o la semilla.", exact=False)).to_be_visible()
        assert page.get_by_test_id("stMetric").count() == 0
        execute_and_reveal("groups", 42)
        select_case(2)
        seed = page.get_by_role("spinbutton", name="Semilla del experimento")
        seed.fill("7")
        seed.press("Enter")
        expect(page.get_by_text("Has cambiado el caso o la semilla.", exact=False)).to_be_visible()
        assert page.get_by_test_id("stMetric").count() == 0
        execute_and_reveal("selection", 7)

        page.set_viewport_size({"width": 390, "height": 844})
        # Comprueba que los controles siguen accesibles en el panel móvil.
        sidebar = page.get_by_test_id("stSidebar")
        expect(sidebar).to_have_attribute("data-collapsed", "true")
        page.get_by_role("button", name="Expand sidebar").click()
        expect(sidebar).to_have_attribute("data-collapsed", "false")
        expect(page.get_by_role("button", name="Ejecutar experimento", exact=True)).to_be_visible()
        page.get_by_role("button", name="Collapse sidebar").click()
        expect(sidebar).to_have_attribute("data-collapsed", "true")
        expect(page.get_by_role("button", name="Expand sidebar")).to_be_visible()
        page.wait_for_function("document.querySelector('[data-testid=stSidebar]').getBoundingClientRect().right <= 0")
        page.get_by_role("heading", name="Data Crime Scene", exact=True).scroll_into_view_if_needed()
        page.evaluate("() => document.fonts.ready")
        page.screenshot(path=str(SCREENSHOTS / "03-movil.png"))
        page.get_by_role("heading", name="La comparación", exact=True).scroll_into_view_if_needed()
        page.get_by_test_id("stPlotlyChart").scroll_into_view_if_needed()
        page.screenshot(path=str(SCREENSHOTS / "04-movil-comparacion.png"))
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert page.get_by_test_id("stException").count() == 0
        assert not errors, errors
        summary = {
            "url": URL, "desktop": [1440, 1000], "narrow": [390, 844],
            "checked": checked, "page_errors": errors,
            "external_requests_blocked": external_requests,
            "screenshots": sorted(path.name for path in SCREENSHOTS.glob("*.png")),
        }
        (ARTIFACTS / "browser-check.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        browser.close()


if __name__ == "__main__":
    main()
