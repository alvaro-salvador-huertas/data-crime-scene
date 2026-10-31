"""Propiedades de los ocho expedientes y sus intervenciones reales."""

from copy import deepcopy
import json

import pytest
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score

import data_crime_scene.detective as detective
from data_crime_scene.generators import generate_groups


EXPECTED = {
    "d01": ("contaminated", "timing", "remove_feature"),
    "d02": ("contaminated", "group_overlap", "group_split"),
    "d03": ("contaminated", "fit_scope", "train_selector"),
    "d04": ("defensible", "timing", "maintain"),
    "d05": ("defensible", "group_overlap", "maintain"),
    "d06": ("defensible", "fit_scope", "maintain"),
    "d07": ("insufficient", "missing_time", "request_time"),
    "d08": ("insufficient", "missing_fit", "request_fit"),
}


@pytest.fixture(scope="module")
def prepared():
    session = detective.new_session(42)
    cases = {key: detective.build_case(key, detective.case_seed(session, key)) for key in detective.TEMPLATES}
    return session, cases


def opened(prepared, template_id):
    original_session, cases = prepared
    session = deepcopy(original_session)
    detective.activate_case(session, template_id)
    return session, cases[template_id]


@pytest.mark.parametrize("template_id", EXPECTED)
def test_each_template_verdict_matches_actual_procedure_and_predictions(prepared, template_id):
    session, case = opened(prepared, template_id)
    record = detective.get_record(session, case)
    public = detective.public_case(case, record)
    raw = case._source["variants"][case._variant]
    assert public["experiment"]["y_true"] == raw["y_true"]
    assert public["experiment"]["y_pred"] == raw["y_pred"]
    assert public["experiment"]["metrics"]["accuracy"] == accuracy_score(raw["y_true"], raw["y_pred"])
    assert public["experiment"]["confusion_matrix"] == confusion_matrix(raw["y_true"], raw["y_pred"], labels=[0, 1]).tolist()
    assert detective.visible_solution(case, record) is None
    diagnosis, evidence_id, action = EXPECTED[template_id]
    feedback = detective.confirm_answer(session, case, diagnosis, [evidence_id], action)
    assert feedback == {"diagnosis_correct": True, "evidence_correct": True, "action_correct": True, "independent": True}
    assert detective.visible_solution(case, record) is None  # Confirmar no revela.
    assert "solution" not in json.loads(detective.export_investigation(session, case))
    assert detective.reveal_solution(session, case)["diagnosis"] == diagnosis

    if case._source_case == "future":
        assert ("reembolso_tramitado" in raw["feature_names"]) == (template_id != "d04")
        availability = public["evidence"]["availability"]
        posterior = [item for item in availability if item["available_at_prediction"] is False]
        unknown = [item for item in availability if item["available_at_prediction"] is None]
        assert bool(posterior) == (template_id == "d01")
        assert bool(unknown) == (template_id == "d07")
    elif case._source_case == "groups":
        groups = generate_groups(case.seed).groups
        shared = set(groups.loc[raw["train_row_ids"]]) & set(groups.loc[raw["test_row_ids"]])
        assert bool(shared) == (template_id == "d02")
        assert public["evidence"]["groups"]["shared_entities"] == sorted(shared)
        assert "maquina_id" not in raw["feature_names"]
        assert "fila_id" not in raw["feature_names"]
    else:
        stage = raw["fit_stages"][0]
        actual_test_seen = (set(stage["row_ids"]) | set(stage["label_row_ids"])) & set(raw["test_row_ids"])
        assert bool(actual_test_seen) == (template_id == "d03")
        assert bool(public["evidence"]["fitting"]["fit_row_ids"] is None) == (template_id == "d08")
        selected = set(public["experiment"]["feature_names"])
        preview_features = {name for name in public["data_preview"][0] if name.startswith("medicion_")}
        assert len(preview_features) == 6
        assert preview_features <= selected


@pytest.mark.parametrize("template_id,action", [("d01", "remove_feature"), ("d02", "group_split"), ("d03", "train_selector")])
def test_repairs_execute_the_real_engine_once_and_remove_the_specific_mechanism(prepared, monkeypatch, template_id, action):
    session, case = opened(prepared, template_id)
    diagnosis, evidence_id, _ = EXPECTED[template_id]
    detective.confirm_answer(session, case, diagnosis, [evidence_id], action)
    actual = detective.run_experiment
    calls = []

    def tracked(case_id, seed):
        calls.append((case_id, seed))
        return actual(case_id, seed)

    monkeypatch.setattr(detective, "run_experiment", tracked)
    repair = detective.execute_intervention(session, case, action)
    assert calls == [(case._source_case, case.seed)]
    assert repair["status"] == "applied" and repair["performed"]
    assert detective.execute_intervention(session, case, action) == repair
    assert len(calls) == 1
    before, after = repair["before"], repair["after"]
    assert after["y_pred"] == case._source["variants"]["correct"]["y_pred"]
    assert after["model"]["params"] == before["model"]["params"]
    for value in (before, after):
        assert value["metrics"]["balanced_accuracy"] == balanced_accuracy_score(value["y_true"], value["y_pred"])
        assert value["metrics"]["f1"] == f1_score(value["y_true"], value["y_pred"], zero_division=0)
    if template_id == "d01":
        assert "registro_c17" in before["feature_names"]
        assert "registro_c17" not in after["feature_names"]
        assert before["test_row_ids"] == after["test_row_ids"]
        assert before["train_row_ids"] == after["train_row_ids"]
    elif template_id == "d02":
        groups = generate_groups(case.seed).groups
        assert (set(groups.loc[after["train_row_ids"]]) & set(groups.loc[after["test_row_ids"]])) == set()
        assert after["diagnostics"]["entidades_compartidas"] == 0
        assert before["test_row_ids"] != after["test_row_ids"]
    else:
        assert after["diagnostics"]["filas_test_consultadas_por_selector"] == 0
        assert before["train_row_ids"] == after["train_row_ids"]
        assert before["test_row_ids"] == after["test_row_ids"]
    exported = json.loads(detective.export_investigation(session, case))
    assert exported["intervention"] == repair
    assert "solution" not in exported  # La explicación sigue siendo explícita.
    detective.reveal_solution(session, case)
    assert json.loads(detective.export_investigation(session, case))["solution"]["diagnosis"] == "contaminated"


@pytest.mark.parametrize("template_id,action", [("d05", "group_split"), ("d06", "train_selector")])
def test_valid_alternative_rechecks_a_legitimate_protocol_without_claiming_a_new_repair(prepared, template_id, action):
    session, case = opened(prepared, template_id)
    diagnosis, evidence_id, _ = EXPECTED[template_id]
    assert detective.confirm_answer(session, case, diagnosis, [evidence_id, "objective"], action)["action_correct"]
    repeated = detective.execute_intervention(session, case, action)
    assert repeated["status"] == "reconfirmed"
    assert repeated["performed"] is True  # Reentrenamiento real, sin cambio metodológico.
    assert repeated["before"] == repeated["after"]
    assert "ya aplicaba" in repeated["changed"]


@pytest.mark.parametrize("template_id", ["d04", "d05", "d06"])
def test_maintain_is_an_honest_no_change_on_legitimate_controls(prepared, monkeypatch, template_id):
    session, case = opened(prepared, template_id)
    diagnosis, evidence_id, action = EXPECTED[template_id]
    detective.confirm_answer(session, case, diagnosis, [evidence_id], action)

    def forbidden(*args, **kwargs):
        raise AssertionError("Mantener no debe fingir una reparación o reentrenamiento")

    monkeypatch.setattr(detective, "run_experiment", forbidden)
    result = detective.execute_intervention(session, case, "maintain")
    assert result["status"] == "maintained"
    assert result["performed"] is False
    assert result["before"] == result["after"]


@pytest.mark.parametrize("template_id,request_action,expected,proof,action", [
    ("d07", "request_time", "contaminated", "timing", "remove_feature"),
    ("d08", "request_fit", "defensible", "fit_scope", "maintain"),
])
def test_missing_information_creates_a_new_visible_phase_without_double_counting(prepared, template_id, request_action, expected, proof, action):
    session, case = opened(prepared, template_id)
    initial_diagnosis, initial_proof, _ = EXPECTED[template_id]
    detective.confirm_answer(session, case, initial_diagnosis, [initial_proof], request_action)
    initial_solution = detective.reveal_solution(session, case)
    assert initial_solution["diagnosis"] == "insufficient"
    assert detective.session_summary(session)["completed"] == 1
    response = detective.request_evidence(session, case, request_action)
    assert response["status"] == "evidence_requested"
    record = detective.get_record(session, case)
    assert record["phase"] == "expanded"
    assert detective.visible_solution(case, record) is None
    assert detective.session_summary(session)["completed"] == 0
    assert detective.request_evidence(session, case, request_action)["status"] == "already_available"
    final_feedback = detective.confirm_answer(session, case, expected, [proof], action)
    assert all(final_feedback[key] for key in ("diagnosis_correct", "evidence_correct", "action_correct"))
    assert set(record["answers"]) == {"initial", "expanded"}
    assert detective.session_summary(session)["completed"] == 1
    assert detective.reveal_solution(session, case)["diagnosis"] == expected


def test_truth_does_not_depend_on_leakage_flags_or_metric_thresholds(prepared):
    session, original = opened(prepared, "d02")
    case = deepcopy(original)
    # El indicador declarado contradice los índices. No se usa para calificar.
    case._source["variants"]["incorrect"]["diagnostics"]["leakage_detected"] = False
    case._source["variants"]["incorrect"]["diagnostics"]["shared_entity_count"] = 0
    view = detective.public_case(case, detective.get_record(session, case))
    assert view["evidence"]["groups"]["shared_entity_count"] > 0
    feedback = detective.confirm_answer(session, case, "contaminated", ["group_overlap"], "group_split")
    assert feedback["diagnosis_correct"]
    assert detective.confirm_answer(session, case, "defensible", ["metric"], "maintain") == feedback


def test_session_seed_order_data_and_case_context_are_reproducible(prepared):
    first = detective.new_session(42)
    assert first == detective.new_session(42)
    other = detective.new_session(7)
    assert first["order"] != other["order"]
    assert len(first["order"]) == len(set(first["order"])) == 8
    for template_id in detective.TEMPLATES:
        assert detective.case_seed(first, template_id) != detective.case_seed(other, template_id)
    session, case = opened(prepared, "d01")
    detective.activate_case(session, "d02")
    with pytest.raises(ValueError, match="activa"):
        detective.confirm_answer(session, case, "contaminated", ["timing"], "remove_feature")
    detective.reset_session(session, 7)
    detective.activate_case(session, "d01")
    with pytest.raises(ValueError, match="semilla"):
        detective.get_record(session, case)


@pytest.mark.parametrize("template,seed", [("missing", 42), ("d01", -1), ("d01", True), ("d01", 0.5)])
def test_invalid_case_parameters_fail_clearly(template, seed):
    with pytest.raises(ValueError):
        detective.build_case(template, seed)
