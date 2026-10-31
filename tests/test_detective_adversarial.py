"""Controles adversariales aislados sobre evidencia, exportación y decisiones.

Las métricas extremas de un fixture solo comprueban que no determinen el
veredicto. No se incorporan a ningún expediente ni informe de la aplicación.
"""

from copy import deepcopy
import json

import pytest
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score

import data_crime_scene.detective as detective


@pytest.fixture(scope="module")
def cases():
    session = detective.new_session(42)
    return {key: detective.build_case(key, detective.case_seed(session, key)) for key in detective.TEMPLATES}


def opened(cases, template_id):
    session = detective.new_session(42)
    detective.activate_case(session, template_id)
    return session, deepcopy(cases[template_id])


def conclusion_from_observations(view):
    """Regla independiente: columnas e índices visibles, sin verdad de plantilla."""
    evidence = view["evidence"]
    if evidence["availability"] is not None:
        values = [item["available_at_prediction"] for item in evidence["availability"]]
        if None in values:
            return "insufficient", "missing_time", "request_time"
        return ("contaminated", "timing", "remove_feature") if False in values else ("defensible", "timing", "maintain")
    if evidence["groups"] is not None:
        groups = evidence["groups"]
        shared = set(groups["train_entities"]) & set(groups["test_entities"])
        return ("contaminated", "group_overlap", "group_split") if shared else ("defensible", "group_overlap", "maintain")
    fitting = evidence["fitting"]
    if fitting["fit_row_ids"] is None or fitting["label_row_ids"] is None:
        return "insufficient", "missing_fit", "request_fit"
    consulted = (set(fitting["fit_row_ids"]) | set(fitting["label_row_ids"])) & set(view["experiment"]["test_row_ids"])
    return ("contaminated", "fit_scope", "train_selector") if consulted else ("defensible", "fit_scope", "maintain")


def no_private_keys(value):
    forbidden = {"_source", "_source_case", "_variant", "_missing", "expected", "expected_diagnosis",
                 "correct_option", "solution", "explanation", "fit_scope", "leakage_detected", "generator_params"}
    if isinstance(value, dict):
        assert forbidden.isdisjoint(value)
        for child in value.values():
            no_private_keys(child)
    elif isinstance(value, list):
        for child in value:
            no_private_keys(child)


@pytest.mark.parametrize("template_id", list(detective.TEMPLATES))
def test_initial_public_download_has_no_solution_raw_flags_or_unopened_hints(cases, template_id):
    session, case = opened(cases, template_id)
    record = detective.get_record(session, case)
    public = detective.public_case(case, record)
    exported = json.loads(detective.export_investigation(session, case))
    no_private_keys(public)
    no_private_keys(exported)
    assert public["hints"] == []
    assert exported["evidence"] == public
    assert "reembolso_tramitado" not in json.dumps(exported)
    assert "intervention" not in exported
    assert detective.visible_solution(case, record) is None


def test_hint_exports_only_opened_text_and_counts_at_most_two(cases):
    session, case = opened(cases, "d01")
    first = detective.use_hint(session, case)
    first_export = detective.export_investigation(session, case)
    second = detective.use_hint(session, case)
    assert first != second
    assert json.loads(first_export)["evidence"]["hints"] == [first]
    assert second not in first_export
    assert detective.use_hint(session, case) == second
    assert detective.session_summary(session)["hints_used"] == 2
    assert detective.get_record(session, case)["hints_used"] == 2


@pytest.mark.parametrize("template_id", ["d07", "d08"])
def test_initial_incomplete_rubric_and_solution_use_only_available_information(cases, template_id):
    session, case = opened(cases, template_id)
    view = detective.public_case(case, detective.get_record(session, case))
    diagnosis, evidence, request = conclusion_from_observations(view)
    assert diagnosis == "insufficient"
    feedback = detective.confirm_answer(session, case, diagnosis, [evidence], request)
    assert all(feedback[key] for key in ("diagnosis_correct", "evidence_correct", "action_correct", "independent"))
    # Confirmar proporciona feedback, no autoriza una descarga de la solución.
    assert "solution" not in json.loads(detective.export_investigation(session, case))
    solution = detective.reveal_solution(session, case)
    assert solution["diagnosis"] == "insufficient"
    assert solution["actions"] == [request]
    assert detective.public_case(case, detective.get_record(session, case))["phase"] == "initial"
    if template_id == "d07":
        assert any(item["available_at_prediction"] is None for item in view["evidence"]["availability"])
    else:
        assert view["evidence"]["fitting"]["fit_row_ids"] is None
        assert view["evidence"]["fitting"]["label_row_ids"] is None


@pytest.mark.parametrize("template_id", ["d07", "d08"])
def test_request_adds_evidence_without_double_counting_an_investigation(cases, template_id):
    session, case = opened(cases, template_id)
    initial = detective.public_case(case, detective.get_record(session, case))
    diagnosis, evidence, request = conclusion_from_observations(initial)
    detective.confirm_answer(session, case, diagnosis, [evidence], request)
    assert detective.session_summary(session)["completed"] == 1
    assert detective.request_evidence(session, case, request)["performed"]
    record = detective.get_record(session, case)
    assert record["phase"] == "expanded"
    assert detective.visible_solution(case, record) is None
    expanded = detective.public_case(case, record)
    diagnosis, evidence, action = conclusion_from_observations(expanded)
    assert diagnosis in ("contaminated", "defensible")
    feedback = detective.confirm_answer(session, case, diagnosis, [evidence], action)
    assert all(feedback.values())
    first_summary = detective.session_summary(session)
    assert first_summary["completed"] == first_summary["independent_correct"] == 1
    assert detective.confirm_answer(session, case, "insufficient", [], "maintain", notes="otra nota") == feedback
    assert detective.session_summary(session) == first_summary
    repeated_request = detective.request_evidence(session, case, request)
    assert not repeated_request["performed"]
    assert detective.public_case(case, record) == expanded


def test_revealing_initial_incomplete_solution_prevents_later_independent_credit(cases):
    session, case = opened(cases, "d07")
    detective.reveal_solution(session, case)
    detective.request_evidence(session, case, "request_time")
    diagnosis, evidence, action = conclusion_from_observations(detective.public_case(case, detective.get_record(session, case)))
    feedback = detective.confirm_answer(session, case, diagnosis, [evidence], action)
    assert feedback["diagnosis_correct"]
    assert feedback["evidence_correct"]
    assert feedback["action_correct"]
    assert not feedback["independent"]
    summary = detective.session_summary(session)
    assert summary["completed"] == 1
    assert summary["independent_correct"] == 0
    assert summary["solutions_consulted"] == 1


def test_notes_are_inert_and_do_not_change_grading_or_duplicate_progress(cases, tmp_path):
    session, case = opened(cases, "d04")
    target = tmp_path / "must-not-exist.txt"
    notes = f"__import__('pathlib').Path({str(target)!r}).write_text('executed')"
    view = detective.public_case(case, detective.get_record(session, case))
    diagnosis, evidence, action = conclusion_from_observations(view)
    feedback = detective.confirm_answer(session, case, diagnosis, [evidence], action, notes=notes)
    assert all(feedback.values())
    assert not target.exists()
    exported = json.loads(detective.export_investigation(session, case))
    assert exported["investigation"]["answers"]["initial"]["notes"] == notes
    summary = detective.session_summary(session)
    detective.confirm_answer(session, case, diagnosis, [evidence], action, notes="palabras distintas")
    assert detective.session_summary(session) == summary


@pytest.mark.parametrize("template_id", ["d04", "d05", "d06"])
@pytest.mark.parametrize("perfect", [False, True])
def test_legitimate_control_decision_does_not_depend_on_metric_extremes(cases, template_id, perfect):
    session, case = opened(cases, template_id)
    # Mutación solo del fixture: conserva columnas, particiones y entradas de
    # ajuste. Sirve para desafiar un posible umbral de puntuación del corrector.
    variant = case._source["variants"][case._variant]
    y = variant["y_true"]
    pred = list(y) if perfect else [1 - item for item in y]
    variant["y_pred"] = pred
    variant["metrics"] = {"accuracy": float(accuracy_score(y, pred)),
                          "balanced_accuracy": float(balanced_accuracy_score(y, pred)),
                          "f1": float(f1_score(y, pred, zero_division=0))}
    variant["confusion_matrix"] = confusion_matrix(y, pred, labels=[0, 1]).tolist()
    view = detective.public_case(case, detective.get_record(session, case))
    diagnosis, evidence, action = conclusion_from_observations(view)
    assert diagnosis == "defensible"
    assert view["experiment"]["metrics"]["accuracy"] == int(perfect)
    assert all(detective.confirm_answer(session, case, diagnosis, [evidence], action).values())


def test_unrelated_action_does_not_fit_fall_back_or_change_investigation(cases, monkeypatch):
    session, case = opened(cases, "d01")
    detective.confirm_answer(session, case, "contaminated", ["timing"], "remove_feature")
    before = deepcopy(detective.get_record(session, case))

    def forbidden(*args, **kwargs):
        raise AssertionError("No debe entrenar una operación no aplicable")

    monkeypatch.setattr(detective, "run_experiment", forbidden)
    result = detective.execute_intervention(session, case, "group_split")
    assert not result["performed"]
    assert result["status"] == "not_applicable"
    assert detective.get_record(session, case) == before


def test_maintaining_a_legitimate_control_does_not_claim_a_repair_or_fit(cases, monkeypatch):
    session, case = opened(cases, "d05")
    detective.confirm_answer(session, case, "defensible", ["group_overlap"], "maintain")

    def forbidden(*args, **kwargs):
        raise AssertionError("Mantener no necesita volver a ajustar")

    monkeypatch.setattr(detective, "run_experiment", forbidden)
    result = detective.execute_intervention(session, case, "maintain")
    assert result["status"] == "maintained"
    assert not result["performed"]
    assert result["before"] == result["after"]


@pytest.mark.parametrize("template_id,action", [("d05", "group_split"), ("d06", "train_selector")])
def test_valid_reexecution_of_a_legitimate_procedure_is_labelled_as_reconfirmation(cases, template_id, action, monkeypatch):
    session, case = opened(cases, template_id)
    view = detective.public_case(case, detective.get_record(session, case))
    diagnosis, evidence, _ = conclusion_from_observations(view)
    detective.confirm_answer(session, case, diagnosis, [evidence], action)
    calls = []
    original = detective.run_experiment

    def tracked(source_case, seed):
        calls.append((source_case, seed))
        return original(source_case, seed)

    monkeypatch.setattr(detective, "run_experiment", tracked)
    result = detective.execute_intervention(session, case, action)
    assert calls == [(case._source_case, case.seed)]
    assert result["status"] == "reconfirmed"
    assert result["before"] == result["after"]
    assert "ya" in result["changed"].lower()


def test_foreign_context_cannot_reuse_answers_hints_or_intervention(cases):
    session, first = opened(cases, "d01")
    detective.use_hint(session, first)
    detective.confirm_answer(session, first, "contaminated", ["timing"], "remove_feature")
    first_record = deepcopy(detective.get_record(session, first))
    second = deepcopy(cases["d04"])
    detective.activate_case(session, second.template_id)
    with pytest.raises(ValueError, match="activa"):
        detective.export_investigation(session, first)
    second_record = detective.get_record(session, second)
    assert second_record["answers"] == {}
    assert second_record["hints_used"] == 0
    with pytest.raises(ValueError, match="otro expediente"):
        detective.public_case(second, first_record)
    foreign_seed = detective.build_case(second.template_id, second.seed ^ 1)
    with pytest.raises(ValueError, match="semilla"):
        detective.get_record(session, foreign_seed)
    detective.reset_session(session, seed=7)
    summary = detective.session_summary(session)
    assert summary["completed"] == summary["hints_used"] == summary["solutions_consulted"] == 0
