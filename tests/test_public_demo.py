"""Public presentation over the unchanged engine; no historical files required."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from data_crime_scene import detective, study
from data_crime_scene.detective import TEMPLATES, public_case, session_summary
from test_detective_app import choose, contains_key, current_case, record

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo/streamlit_app.py"


def open_demo(mode="Recorrido guiado", template=None):
    app = AppTest.from_file(str(DEMO), default_timeout=30).run()
    app.radio(key="mode_selector").set_value(mode).run()
    if template:
        app.selectbox(key="detective_case_selector").set_value(template).run()
        app.button(key="detective_open").click().run()
    assert not app.exception
    return app


@pytest.fixture
def downloads(monkeypatch):
    values = {}
    original = st.download_button
    def capture(*args, **kwargs):
        values[kwargs["key"]] = json.loads(kwargs.get("data", args[1] if len(args) > 1 else None))
        return original(*args, **kwargs)
    monkeypatch.setattr(st, "download_button", capture)
    return values


def test_public_navigation_never_fits_and_local_controls_remain(monkeypatch, tmp_path):
    import app as guided
    import ui.laboratory as lab
    import ui.detective as investigation
    def forbidden(*args, **kwargs):
        raise AssertionError("Navigation must not start any experiment")
    for module, name in ((guided, "run_experiment"), (lab, "run_lab_experiment"),
                         (investigation, "build_case"), (study, "run_study")):
        monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(lab, "PUBLIC_STUDY", tmp_path / "missing.json")
    app = open_demo()
    for mode in ("Laboratorio", "Modo Detective", "Recorrido guiado"):
        app.radio(key="mode_selector").set_value(mode).run()
        app.run()
        assert not app.exception
        assert not app.text_input
        assert not any(".venv" in item.value for item in app.code)
    app.radio(key="mode_selector").set_value("Laboratorio").run()
    assert any("no incluye un estudio" in item.value for item in app.info)
    local = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    local.radio(key="mode_selector").set_value("Laboratorio").run()
    assert local.text_input(key="lab_study_path").value == "artifacts/laboratory-study.json"
    assert local.button(key="lab_load_study")
    assert not local.exception


@pytest.mark.parametrize("kind", ["malformed", "python_patch"])
def test_incompatible_public_study_is_explicit_without_paths_or_commands(kind, monkeypatch, tmp_path):
    import ui.laboratory as lab
    path = tmp_path / "private-server-directory.json"
    if kind == "malformed":
        path.write_text("not JSON")
    else:
        value = {**study._manifest(), "entries": [
            {"config": config, "status": "error", "error": {"type": "Fixture", "message": "not executed"}}
            for config in study.planned_configs()]}
        value["runtime"]["python"] = "3.12.999"
        path.write_text(json.dumps(value))
    monkeypatch.setattr(lab, "PUBLIC_STUDY", path)
    app = open_demo("Laboratorio")
    app.button(key="lab_load_public_study").click().run()
    assert not app.exception and "lab_study" not in app.session_state
    assert any("no es compatible" in item.value for item in app.warning)
    text = " ".join(item.value for item in list(app.warning) + list(app.error) + list(app.markdown))
    assert str(tmp_path) not in text and "Ejecuta el estudio" not in text
    assert not app.text_input
    app.button(key="lab_run").click().run()
    assert not app.exception and "lab_result" in app.session_state


@pytest.mark.parametrize("template", list(TEMPLATES))
def test_public_eight_cases_export_actual_evidence_without_solution(template, downloads):
    app = open_demo("Modo Detective", template)
    case = current_case(app)
    view = public_case(case, record(app))
    assert downloads["detective_download_evidence"] == view
    assert app.metric[0].value == f"{view['experiment']['metrics']['accuracy']:.1%}"
    assert not contains_key(downloads["detective_download_investigation"],
                            {"solution", "expected", "_source", "_variant"})
    solution = detective._solution_from_public(view)
    # Proto content includes component properties/help/accessibility labels, not session data.
    rendered = " ".join(str(element.proto) for element in app if hasattr(element, "proto"))
    assert solution["explanation"] not in rendered
    assert not record(app)["revealed_phases"]


def test_two_sessions_reset_reveal_download_and_intervention_are_isolated(monkeypatch, downloads):
    calls = []
    original = detective.run_experiment
    def tracked(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)
    monkeypatch.setattr(detective, "run_experiment", tracked)
    first = open_demo("Modo Detective", "d01")
    second = open_demo("Modo Detective", "d01")
    assert len(calls) == 2
    second_before = deepcopy(second.session_state["detective_session"])
    first.button(key="detective_hint_1").click().run()
    choose(first, "contaminated", ["timing"], "remove_feature", "Only first session")
    first.button(key="detective_confirm").click().run()
    assert "solution" not in downloads["detective_download_investigation"]
    first.button(key="detective_reveal").click().run()
    assert "solution" in downloads["detective_download_investigation"]
    first.run()
    assert len(calls) == 2
    first.button(key="detective_intervene").click().run()
    assert len(calls) == 3
    expected = deepcopy(record(first)["intervention"])
    assert downloads["detective_download_investigation"]["intervention"] == expected
    first.button(key="detective_intervene").click().run()
    first.radio(key="mode_selector").set_value("Laboratorio").run()
    first.radio(key="mode_selector").set_value("Modo Detective").run()
    assert record(first)["intervention"] == expected and len(calls) == 3
    second.run()
    assert second.session_state["detective_session"] == second_before
    assert "solution" not in downloads["detective_download_investigation"]
    choose(second, "contaminated", ["timing"], "remove_feature", "Only second session")
    second.button(key="detective_confirm").click().run()
    second_saved = deepcopy(second.session_state["detective_session"])
    first.button(key="detective_reset").click().run()
    assert session_summary(first.session_state["detective_session"])["completed"] == 0
    second.run()
    assert second.session_state["detective_session"] == second_saved
    assert record(second)["answers"]["initial"]["notes"] == "Only second session"
    assert len(calls) == 3


def test_public_guided_and_lab_cache_return_independent_copies(monkeypatch, downloads):
    import app as guided
    import ui.laboratory as lab
    st.cache_data.clear()
    calls = []
    def spy(module, name):
        original = getattr(module, name)
        def tracked(*args):
            calls.append((name, args))
            return original(*args)
        monkeypatch.setattr(module, name, tracked)
    spy(guided, "run_experiment")
    spy(lab, "run_lab_experiment")
    first, second = open_demo(), open_demo()
    first.button(key="run_experiment").click().run()
    second.button(key="run_experiment").click().run()
    assert len(calls) == 1
    first.button(key="reveal_answer").click().run()
    assert downloads["download_report"] == first.session_state["result"].to_dict()
    assert not second.session_state["revealed"]
    from data_crime_scene.laboratory import engine_fingerprint
    value = guided.cached_experiment("future", 42, engine_fingerprint())
    value.variants["correct"].y_pred[0] ^= 1
    assert second.session_state["result"].to_dict() == downloads["download_report"]
    for app in (first, second):
        app.radio(key="mode_selector").set_value("Laboratorio").run()
        app.button(key="lab_run").click().run()
        app.selectbox(key="lab_study_metric").set_value("f1").run()
        app.run()
        assert not app.exception
        assert downloads["lab_download_run"] == app.session_state["lab_result"]
    assert len(calls) == 2
    first.session_state["lab_result"]["variants"]["correct"]["y_pred"][0] ^= 1
    assert first.session_state["lab_result"] != second.session_state["lab_result"]
    st.cache_data.clear()


def test_demo_starts_from_publication_files_only(tmp_path):
    import shutil
    files = (ROOT / "docs/archivos-publicacion.txt").read_text().splitlines()
    for name in files:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    assert not (tmp_path / "artifacts").exists()
    assert not (tmp_path / ".env").exists()
    code = '''from streamlit.testing.v1 import AppTest
app = AppTest.from_file("demo/streamlit_app.py", default_timeout=30).run()
for mode in ("Laboratorio", "Modo Detective", "Recorrido guiado"):
    app.radio(key="mode_selector").set_value(mode).run()
    assert not app.exception
    assert not app.text_input
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_public_additional_evidence_and_case_changes_do_not_refit(monkeypatch, downloads):
    calls = []
    original = detective.run_experiment
    def tracked(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)
    monkeypatch.setattr(detective, "run_experiment", tracked)
    app = open_demo("Modo Detective", "d07")
    choose(app, "insufficient", ["missing_time"], "request_time")
    app.button(key="detective_confirm").click().run()
    app.button(key="detective_request_evidence").click().run()
    assert record(app)["phase"] == "expanded"
    choose(app, "contaminated", ["timing"], "remove_feature")
    app.button(key="detective_confirm").click().run()
    assert session_summary(app.session_state["detective_session"])["completed"] == 1
    assert "solution" not in downloads["detective_download_investigation"]
    saved = deepcopy(record(app))
    app.selectbox(key="detective_case_selector").set_value("d01").run()
    app.selectbox(key="detective_case_selector").set_value("d07").run()
    app.run()
    assert record(app) == saved and len(calls) == 1
    app.number_input(key="detective_session_seed").set_value(7).run()
    assert not app.exception and app.session_state["detective_cases"] == {}
    assert session_summary(app.session_state["detective_session"])["completed"] == 0
    assert len(calls) == 1
