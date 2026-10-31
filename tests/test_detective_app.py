"""Flujos reales del modo Detective mediante AppTest; no sustituyen navegador."""

from copy import deepcopy
import json
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from data_crime_scene.detective import (
    TEMPLATES,
    export_investigation,
    public_case,
    session_summary,
)


APP = Path(__file__).resolve().parents[1] / "app.py"


def detective_app(template_id=None, open_case=True):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.radio(key="mode_selector").set_value("Modo Detective").run()
    if template_id is not None:
        app.selectbox(key="detective_case_selector").set_value(template_id).run()
    if open_case:
        app.button(key="detective_open").click().run()
    assert not app.exception
    return app


def current_case(app):
    return app.session_state["detective_cases"][app.session_state["detective_context"]]


def record(app):
    case = current_case(app)
    return app.session_state["detective_session"]["records"][case.template_id]


def widget(app, element_type, suffix):
    return next(element for element in getattr(app, element_type) if (element.key or "").startswith("detective_answer_") and element.key.endswith(suffix))


def choose(app, diagnosis, evidence, action, notes=""):
    widget(app, "radio", "_diagnosis").set_value(diagnosis)
    widget(app, "multiselect", "_evidence").set_value(evidence)
    widget(app, "selectbox", "_action").set_value(action)
    widget(app, "text_area", "_notes").set_value(notes)
    app.run()
    assert not app.exception


def contains_key(value, forbidden):
    if isinstance(value, dict):
        return bool(set(value) & forbidden) or any(contains_key(item, forbidden) for item in value.values())
    if isinstance(value, list):
        return any(contains_key(item, forbidden) for item in value)
    return False


@pytest.mark.parametrize("template_id", list(TEMPLATES))
def test_all_eight_open_with_real_public_metrics_and_no_solution(template_id, monkeypatch):
    downloads = {}
    original = st.download_button

    def capture(*args, **kwargs):
        downloads[kwargs["key"]] = kwargs.get("data", args[1] if len(args) > 1 else None)
        return original(*args, **kwargs)

    monkeypatch.setattr(st, "download_button", capture)
    app = detective_app(template_id)
    case = current_case(app)
    view = public_case(case, record(app))
    assert case.template_id == template_id
    assert app.metric[0].value == f"{view['experiment']['metrics']['accuracy']:.1%}"
    assert app.metric[1].value == f"{view['experiment']['metrics']['balanced_accuracy']:.1%}"
    assert json.loads(downloads["detective_download_evidence"]) == view
    investigation = json.loads(downloads["detective_download_investigation"])
    assert investigation == json.loads(export_investigation(app.session_state["detective_session"], case))
    assert not contains_key(view, {"solution", "expected", "_source", "_variant", "leakage_detected"})
    assert not contains_key(investigation, {"solution", "expected", "_source", "_variant"})
    assert "reembolso_tramitado" not in downloads["detective_download_evidence"]
    assert record(app)["hints_used"] == 0
    assert record(app)["revealed_phases"] == []
    assert not any("Diagnóstico del expediente:" in item.value for item in app.markdown)


def test_opening_mode_and_selecting_another_case_do_not_train(monkeypatch):
    import ui.detective as interface

    calls = []

    def forbidden(*args):
        calls.append(args)
        raise AssertionError("Solo abrir explícitamente debe construir un expediente")

    monkeypatch.setattr(interface, "build_case", forbidden)
    app = detective_app("d01", open_case=False)
    app.selectbox(key="detective_case_selector").set_value("d03").run()
    assert calls == []
    assert app.session_state["detective_cases"] == {}
    assert not app.exception


def test_hints_are_progressive_and_consulted_once():
    app = detective_app("d01")
    assert not app.button(key="detective_hint_1").disabled
    assert app.button(key="detective_hint_2").disabled
    app.button(key="detective_hint_1").click().run()
    assert record(app)["hints_used"] == 1
    assert app.button(key="detective_hint_1").disabled
    assert not app.button(key="detective_hint_2").disabled
    app.button(key="detective_hint_2").click().run()
    app.run()
    assert record(app)["hints_used"] == 2
    assert app.button(key="detective_hint_2").disabled
    assert session_summary(app.session_state["detective_session"])["hints_used"] == 2


def test_confirmation_is_idempotent_and_reveal_is_explicit(monkeypatch):
    downloads = {}
    original = st.download_button

    def capture(*args, **kwargs):
        downloads[kwargs["key"]] = kwargs.get("data", args[1] if len(args) > 1 else None)
        return original(*args, **kwargs)

    monkeypatch.setattr(st, "download_button", capture)
    app = detective_app("d01")
    choose(app, "contaminated", ["timing"], "remove_feature", "Nota libre sin calificación automática.")
    app.button(key="detective_confirm").click().run()
    assert not app.exception
    summary = session_summary(app.session_state["detective_session"])
    assert summary["completed"] == summary["independent_correct"] == 1
    assert record(app)["answers"]["initial"]["notes"] == "Nota libre sin calificación automática."
    assert record(app)["revealed_phases"] == []
    assert app.button(key="detective_confirm").disabled
    assert "solution" not in json.loads(downloads["detective_download_investigation"])
    app.run()
    app.radio(key="mode_selector").set_value("Recorrido guiado").run()
    app.radio(key="mode_selector").set_value("Modo Detective").run()
    assert current_case(app).template_id == "d01"
    assert session_summary(app.session_state["detective_session"])["completed"] == 1
    app.button(key="detective_reveal").click().run()
    assert not app.exception
    assert "solution" in json.loads(downloads["detective_download_investigation"])
    assert record(app)["revealed_phases"] == ["initial"]
    assert session_summary(app.session_state["detective_session"])["solutions_consulted"] == 1


def test_solution_before_answer_is_recorded_as_assisted():
    app = detective_app("d04")
    app.button(key="detective_reveal").click().run()
    choose(app, "defensible", ["timing"], "maintain")
    app.button(key="detective_confirm").click().run()
    assert not app.exception
    assert record(app)["revealed_before_answer"]
    summary = session_summary(app.session_state["detective_session"])
    assert summary["completed"] == summary["diagnoses_correct"] == 1
    assert summary["independent_correct"] == 0


@pytest.mark.parametrize("template_id,missing,requested_action,final_diagnosis,final_evidence,final_action", [
    ("d07", "missing_time", "request_time", "contaminated", "timing", "remove_feature"),
    ("d08", "missing_fit", "request_fit", "defensible", "fit_scope", "maintain"),
])
def test_missing_evidence_can_be_requested_and_completed_without_double_count(template_id, missing, requested_action, final_diagnosis, final_evidence, final_action):
    app = detective_app(template_id)
    choose(app, "insufficient", [missing], requested_action)
    app.button(key="detective_confirm").click().run()
    assert record(app)["answers"]["initial"]["feedback"]["diagnosis_correct"]
    assert session_summary(app.session_state["detective_session"])["completed"] == 1
    app.button(key="detective_request_evidence").click().run()
    assert not app.exception
    assert record(app)["phase"] == "expanded"
    assert "initial" in record(app)["answers"]
    assert widget(app, "radio", "_diagnosis").value is None
    assert session_summary(app.session_state["detective_session"])["completed"] == 0
    choose(app, final_diagnosis, [final_evidence], final_action)
    app.button(key="detective_confirm").click().run()
    assert not app.exception
    summary = session_summary(app.session_state["detective_session"])
    assert summary["completed"] == summary["diagnoses_correct"] == summary["actions_correct"] == 1
    assert set(record(app)["answers"]) == {"initial", "expanded"}
    assert record(app)["revealed_phases"] == []


def test_real_intervention_and_unsuitable_action_are_distinguished():
    app = detective_app("d01")
    app.button(key="detective_reveal").click().run()
    choose(app, "contaminated", ["timing"], "group_split")
    app.button(key="detective_intervene").click().run()
    assert not app.exception
    assert record(app)["intervention"] is None
    assert any("no corresponde" in element.value for element in app.info)
    choose(app, "contaminated", ["timing"], "remove_feature")
    app.button(key="detective_intervene").click().run()
    assert not app.exception
    result = record(app)["intervention"]
    assert result["performed"]
    assert "registro_c17" in result["before"]["feature_names"]
    assert "registro_c17" not in result["after"]["feature_names"]
    assert result["after"]["diagnostics"]["variables_indisponibles_al_predecir"] == []
    first = deepcopy(result)
    app.button(key="detective_intervene").click().run()
    assert record(app)["intervention"] == first


def test_selection_change_clears_form_and_reset_clears_progress():
    app = detective_app("d01")
    choose(app, "contaminated", ["timing"], "remove_feature")
    app.button(key="detective_confirm").click().run()
    app.selectbox(key="detective_case_selector").set_value("d05").run()
    assert not app.exception
    assert len(app.multiselect) == 0
    app.button(key="detective_open").click().run()
    assert widget(app, "radio", "_diagnosis").value is None
    assert record(app)["answers"] == {}
    assert session_summary(app.session_state["detective_session"])["completed"] == 1
    app.button(key="detective_reset").click().run()
    assert not app.exception
    assert app.session_state["detective_cases"] == {}
    summary = session_summary(app.session_state["detective_session"])
    assert summary["completed"] == summary["hints_used"] == summary["solutions_consulted"] == 0
    app.button(key="detective_open").click().run()
    assert widget(app, "radio", "_diagnosis").value is None


def test_new_session_seed_resets_state_and_has_reproducible_order():
    app = detective_app("d01")
    first_order = list(app.session_state["detective_session"]["order"])
    first_seed = current_case(app).seed
    app.number_input(key="detective_session_seed").set_value(7).run()
    assert not app.exception
    assert app.session_state["detective_cases"] == {}
    assert app.session_state["detective_session"]["seed"] == 7
    assert app.session_state["detective_session"]["order"] != first_order
    app.selectbox(key="detective_case_selector").set_value("d01").run()
    app.button(key="detective_open").click().run()
    assert current_case(app).seed != first_seed
    app.number_input(key="detective_session_seed").set_value(42).run()
    assert app.session_state["detective_session"]["order"] == first_order
