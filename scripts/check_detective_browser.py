"""QA local de los tres modos sin sobrescribir evidencias históricas.

Requiere Chrome, requirements-browser.txt y Streamlit en 127.0.0.1:8501.
Por defecto guarda cada revisión en un directorio nuevo de artifacts/.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score


ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8501"
DIAGNOSES = {
    "contaminated": "Hay contaminación en uno de los mecanismos investigados",
    "defensible": "No identifico esa contaminación con la evidencia disponible",
    "insufficient": "La información es insuficiente para concluir",
}
ACTIONS = {
    "remove_feature": "Retirar del modelo la variable que no existe al predecir",
    "maintain": "Mantener el procedimiento respecto a los mecanismos investigados",
    "request_time": "Solicitar cuándo está disponible cada variable",
}
PROOFS = {"timing": "Momento de disponibilidad de las variables", "missing_time": "No consta cuándo existe registro_c17"}
TITLES = {"d01": "La mesa norte", "d04": "El cuaderno azul", "d07": "El archivo diecisiete"}


def verify_predictions(value):
    y, pred = value["y_true"], value["y_pred"]
    assert value["metrics"] == {
        "accuracy": accuracy_score(y, pred), "balanced_accuracy": balanced_accuracy_score(y, pred),
        "f1": f1_score(y, pred, zero_division=0),
    }
    assert value["confusion_matrix"] == confusion_matrix(y, pred, labels=[0, 1]).tolist()


def assert_public(value):
    forbidden = {"solution", "explanation", "expected", "correct_option", "_source", "_source_case", "_variant",
                 "fit_scope", "leakage_detected", "generator_params"}
    if isinstance(value, dict):
        assert not forbidden.intersection(value)
        for child in value.values():
            assert_public(child)
    elif isinstance(value, list):
        for child in value:
            assert_public(child)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--screenshots-dir", type=Path)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output = args.output_dir or ROOT / "artifacts" / f"detective-browser-{stamp}"
    shots = args.screenshots_dir or output / "screenshots"
    output.mkdir(parents=True, exist_ok=True)
    shots.mkdir(parents=True, exist_ok=True)
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        raise SystemExit("Se requiere Chrome/Chromium del sistema. No se descarga desde este script.")
    errors, external, checks = [], [], []
    expect.set_options(timeout=30000)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome, headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)

        def local_only(route):
            if urlparse(route.request.url).hostname in {"127.0.0.1", "localhost"}:
                route.continue_()
            else:
                external.append(route.request.url)
                route.abort()

        context.route("**/*", local_only)
        page = context.new_page()
        page.set_default_timeout(30000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        assert page.goto(URL).status == 200

        def settle():
            # Los widgets envían cambios por WebSocket y algunos aplican debounce.
            # Esperar su actualización evita operar sobre el menú de un rerun previo.
            page.wait_for_timeout(250)
            expect(page.get_by_test_id("stApp")).to_have_attribute("data-test-script-state", "notRunning")

        def download(label, name):
            settle()
            button = page.get_by_role("button", name=label, exact=True)
            with page.expect_download() as received:
                button.click()
            path = output / name
            received.value.save_as(path)
            return json.loads(path.read_text(encoding="utf-8"))

        def mode(label):
            page.get_by_test_id("stSidebar").get_by_text(label, exact=True).click()
            settle()

        def choose_combobox(label, option):
            settle()
            control = page.get_by_role("combobox", name=label, exact=True)
            control.click()
            # Un selectbox sin selección enfoca su buscador al hacer clic;
            # ArrowDown abre las opciones también en ese estado.
            control.press("ArrowDown")
            page.get_by_role("option", name=option, exact=True).click()
            settle()

        # Regresión guiada: una ejecución y explicación sobre el motor existente.
        expect(page.get_by_role("heading", name="Data Crime Scene", exact=True)).to_be_visible()
        page.get_by_role("button", name="Ejecutar experimento", exact=True).click()
        page.get_by_role("button", name="Revelar explicación y comparar", exact=True).click()
        guided = download("↓ Descargar informe completo · JSON", "guided-current.json")
        for variant in guided["variants"].values():
            verify_predictions(variant)
        checks.append("Recorrido guiado: cálculo, explicación y exportación actuales")

        # Laboratorio: cálculo puntual y visualización del estudio histórico, sin reejecutarlo.
        mode("Laboratorio")
        choose_combobox("Caso de laboratorio", "El mismo sospechoso en ambos lados")
        page.get_by_role("button", name="Ejecutar configuración", exact=True).click()
        lab = download("↓ Descargar ejecución puntual · JSON", "laboratory-current.json")
        assert lab["config"]["case_id"] == "groups"
        for variant in list(lab["variants"].values()) + list(lab["cohort"].values()):
            verify_predictions(variant)
        if (ROOT / "artifacts" / "laboratory-study.json").exists():
            page.get_by_role("button", name="Cargar estudio local", exact=True).click()
            expect(page.get_by_role("heading", name="Estudio cargado · resultados calculados anteriormente", exact=True)).to_be_visible()
            expect(page.get_by_test_id("stPlotlyChart")).to_have_count(3)
            page.get_by_test_id("stPlotlyChart").nth(1).scroll_into_view_if_needed()
            page.screenshot(path=str(shots / "12-laboratorio-v03.png"))
            checks.append("Laboratorio: ejecución actual y carga explícita del estudio histórico compatible")
        else:
            checks.append("Laboratorio: ejecución puntual actual; no había estudio histórico para cargar")

        mode("Modo Detective")
        expect(page.get_by_role("heading", name="Modo Detective", exact=True)).to_be_visible()
        assert page.get_by_role("button", name="↓ Descargar evidencia disponible · JSON").count() == 0

        def open_case(template):
            choose_combobox("Expediente de la sesión", TITLES[template])
            page.get_by_role("button", name="Abrir expediente", exact=True).click()
            expect(page.get_by_role("heading", name="01 · Panel de pruebas", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="Confirmar respuesta", exact=True)).to_be_enabled()
            assert page.get_by_text("Diagnóstico del expediente:", exact=False).count() == 0
            public = download("↓ Descargar evidencia disponible · JSON", f"{template}-evidence.json")
            assert public["template_id"] == template
            assert_public(public)
            assert "reembolso_tramitado" not in json.dumps(public)
            verify_predictions(public["experiment"])
            return public

        def answer(diagnosis, proof, action):
            page.get_by_text(DIAGNOSES[diagnosis], exact=True).click()
            settle()
            page.get_by_role("combobox", name="Evidencia que sostiene tu diagnóstico", exact=True).click()
            page.get_by_role("option", name=PROOFS[proof], exact=True).click()
            page.keyboard.press("Escape")
            settle()
            choose_combobox("Acción propuesta", ACTIONS[action])
            page.get_by_role("textbox", name="Notas de investigación · no se califican", exact=True).fill("Observación de QA: el mecanismo importa más que el signo de la diferencia de métricas.")
            page.keyboard.press("Tab")
            settle()
            page.get_by_role("button", name="Confirmar respuesta", exact=True).click()
            expect(page.get_by_role("button", name="Confirmar respuesta", exact=True)).to_be_disabled()

        initial = open_case("d01")
        assert initial["hints"] == []
        page.get_by_role("heading", name="Modo Detective", exact=True).scroll_into_view_if_needed()
        page.screenshot(path=str(shots / "09-detective-expediente.png"))
        page.get_by_role("button", name="Consultar pista 1", exact=True).click()
        expect(page.get_by_role("button", name="Consultar pista 1", exact=True)).to_be_disabled()
        answer("contaminated", "timing", "remove_feature")
        confirmed = download("↓ Descargar investigación · JSON", "d01-confirmed-no-solution.json")
        assert "solution" not in confirmed
        assert all(confirmed["investigation"]["answers"]["initial"]["feedback"].values())
        page.get_by_role("button", name="Revelar solución y explicación", exact=True).click()
        expect(page.get_by_text("Diagnóstico del expediente:", exact=False)).to_be_visible()
        page.get_by_role("button", name="Ejecutar la acción elegida", exact=True).click()
        expect(page.get_by_text("Resultado de la intervención", exact=True)).to_be_visible()
        repaired = download("↓ Descargar investigación · JSON", "d01-repaired.json")
        assert repaired["solution"]["diagnosis"] == "contaminated"
        assert repaired["intervention"]["performed"]
        assert "registro_c17" in repaired["intervention"]["before"]["feature_names"]
        assert "registro_c17" not in repaired["intervention"]["after"]["feature_names"]
        for key in ("before", "after"):
            verify_predictions(repaired["intervention"][key])
        page.get_by_text("Resultado de la intervención", exact=True).scroll_into_view_if_needed()
        page.screenshot(path=str(shots / "10-detective-intervencion.png"))
        checks.append("Detective d01: evidencia sin solución, pista, confirmación, revelación explícita y reparación real")

        open_case("d04")
        answer("defensible", "timing", "maintain")
        page.get_by_role("button", name="Revelar solución y explicación", exact=True).click()
        page.get_by_role("button", name="Ejecutar la acción elegida", exact=True).click()
        expect(page.get_by_text("Resultado de la intervención", exact=True)).to_be_visible()
        control = download("↓ Descargar investigación · JSON", "d04-legitimate.json")
        assert control["solution"]["diagnosis"] == "defensible"
        assert control["intervention"]["status"] == "maintained" and not control["intervention"]["performed"]
        assert control["intervention"]["before"] == control["intervention"]["after"]
        checks.append("Detective d04: control legítimo mantenido sin fingir una reparación")

        incomplete = open_case("d07")
        assert any(row["available_at_prediction"] is None for row in incomplete["evidence"]["availability"])
        answer("insufficient", "missing_time", "request_time")
        first_phase = download("↓ Descargar investigación · JSON", "d07-incomplete.json")
        assert all(first_phase["investigation"]["answers"]["initial"]["feedback"].values())
        page.get_by_role("button", name="Solicitar la información elegida", exact=True).click()
        expect(page.get_by_text("Has recibido nueva evidencia.", exact=False)).to_be_visible()
        expect(page.get_by_role("button", name="Confirmar respuesta", exact=True)).to_be_enabled()
        answer("contaminated", "timing", "remove_feature")
        expanded = download("↓ Descargar investigación · JSON", "d07-expanded.json")
        assert expanded["investigation"]["phase"] == "expanded"
        assert set(expanded["investigation"]["answers"]) == {"initial", "expanded"}
        assert "solution" not in expanded
        summary = download("↓ Descargar resumen de sesión · JSON", "session-before-reset.json")
        assert summary["completed"] == 3 and summary["diagnoses_correct"] == 3
        assert summary["hints_used"] == 1
        checks.append("Detective d07: insuficiencia reconocida, evidencia solicitada y dos fases sin doble cómputo")

        page.get_by_role("button", name="Reiniciar sesión", exact=True).click()
        expect(page.get_by_role("button", name="↓ Descargar evidencia disponible · JSON")).to_have_count(0)
        summary_box = page.get_by_test_id("stExpander").filter(has_text="Resumen de la sesión")
        summary_header = summary_box.locator("summary")
        if not summary_header.evaluate("el => el.parentElement.open"):
            summary_header.click()
        reset = download("↓ Descargar resumen de sesión · JSON", "session-after-reset.json")
        assert reset["completed"] == reset["hints_used"] == reset["solutions_consulted"] == 0
        checks.append("Reinicio: progreso, pistas, soluciones y expedientes abiertos retirados")

        seed = page.get_by_role("spinbutton", name="Semilla de sesión", exact=True)
        seed.fill("7")
        seed.press("Enter")
        mobile_case = open_case("d07")
        assert mobile_case["seed"] != incomplete["seed"]
        page.set_viewport_size({"width": 390, "height": 844})
        sidebar = page.get_by_test_id("stSidebar")
        expect(sidebar).to_have_attribute("data-collapsed", "true")
        page.get_by_role("button", name="Expand sidebar", exact=True).click()
        expect(page.get_by_role("button", name="Reiniciar sesión", exact=True)).to_be_visible()
        page.get_by_role("button", name="Collapse sidebar", exact=True).click()
        page.wait_for_function("document.querySelector('[data-testid=stSidebar]').getBoundingClientRect().right <= 0")
        hint = page.get_by_role("button", name="Consultar pista 1", exact=True)
        hint.focus()
        page.keyboard.press("Enter")
        expect(hint).to_be_disabled()
        page.get_by_role("heading", name="Modo Detective", exact=True).scroll_into_view_if_needed()
        page.screenshot(path=str(shots / "11-detective-movil.png"))
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert page.get_by_test_id("stException").count() == 0
        assert not errors and not external, (errors, external)
        checks.append("Pantalla estrecha, cambio de semilla y activación de una pista mediante teclado")
        report = {"url": URL, "viewports": [[1440, 1000], [390, 844]], "checks": checks,
                  "page_errors": errors, "external_requests": external,
                  "screenshots": [str(shots / name) for name in ("09-detective-expediente.png", "10-detective-intervencion.png", "11-detective-movil.png", "12-laboratorio-v03.png")]}
        (output / "browser-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        browser.close()


if __name__ == "__main__":
    main()
