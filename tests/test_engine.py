"""Propiedades de los protocolos; nunca exigen una caída o un umbral de métricas."""

import json

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score

from data_crime_scene.cases import CASES
from data_crime_scene.experiments import AuditedSelectKBest, future_feature_diagnostic, group_diagnostic, run_experiment
from data_crime_scene.generators import generate_future, generate_groups, generate_selection


@pytest.fixture(scope="module", params=[(case, seed) for case in CASES for seed in (7, 42, 2026)])
def result(request):
    return run_experiment(*request.param)


def test_all_cases_complete_without_row_overlap(result):
    assert result.case_id in CASES
    assert result.data_preview
    for variant in result.variants.values():
        assert set(variant.train_row_ids).isdisjoint(variant.test_row_ids)
        assert len(variant.y_true) == len(variant.y_pred) == len(variant.test_row_ids)
        assert len(variant.train_row_ids) + len(variant.test_row_ids) == result.generator_params["n_samples"]
        assert sum(map(sum, variant.confusion_matrix)) == len(variant.test_row_ids)


def test_metrics_and_confusion_match_actual_predictions(result):
    for variant in result.variants.values():
        assert variant.metrics["accuracy"] == accuracy_score(variant.y_true, variant.y_pred)
        assert variant.metrics["balanced_accuracy"] == balanced_accuracy_score(variant.y_true, variant.y_pred)
        assert variant.metrics["f1"] == f1_score(variant.y_true, variant.y_pred, zero_division=0)
        assert variant.confusion_matrix == confusion_matrix(variant.y_true, variant.y_pred, labels=[0, 1]).tolist()
        assert variant.baseline_metrics["accuracy"] == accuracy_score(variant.y_true, variant.baseline_predictions)
        assert variant.baseline_metrics["balanced_accuracy"] == balanced_accuracy_score(variant.y_true, variant.baseline_predictions)
        assert variant.baseline_metrics["f1"] == f1_score(variant.y_true, variant.baseline_predictions, zero_division=0)


def test_export_is_complete_same_result_object(result):
    exported = json.loads(result.to_json())
    assert exported == result.to_dict()
    for name, variant in result.variants.items():
        assert exported["variants"][name]["train_size"] == len(variant.train_row_ids)
        assert exported["variants"][name]["test_size"] == len(variant.test_row_ids)
        assert exported["variants"][name]["metrics"] == variant.metrics
        assert exported["variants"][name]["confusion_matrix"] == variant.confusion_matrix
        assert exported["variants"][name]["y_pred"] == variant.y_pred


def test_case_specific_mechanism_and_control(result):
    wrong, clean = result.variants["incorrect"], result.variants["correct"]
    assert wrong.diagnostics["leakage_detected"] is True
    assert clean.diagnostics["leakage_detected"] is False
    if result.case_id in ("future", "selection"):
        assert wrong.train_row_ids == clean.train_row_ids
        assert wrong.test_row_ids == clean.test_row_ids
        assert wrong.y_true == clean.y_true
        assert wrong.model["params"] == clean.model["params"]
    if result.case_id == "future":
        assert "reembolso_tramitado" in wrong.feature_names
        assert "reembolso_tramitado" not in clean.feature_names
        assert set(wrong.feature_names) - set(clean.feature_names) == {"reembolso_tramitado"}
        assert wrong.model["preprocessing"] == clean.model["preprocessing"]
    if result.case_id == "groups":
        data = generate_groups(result.seed)
        wrong_overlap = set(data.groups.loc[wrong.train_row_ids]) & set(data.groups.loc[wrong.test_row_ids])
        clean_overlap = set(data.groups.loc[clean.train_row_ids]) & set(data.groups.loc[clean.test_row_ids])
        assert len(wrong_overlap) == wrong.diagnostics["shared_entity_count"] > 0
        assert len(clean_overlap) == clean.diagnostics["shared_entity_count"] == 0
        assert wrong.model == clean.model
        assert wrong.feature_names == clean.feature_names
        assert "maquina_id" not in wrong.feature_names
        assert "fila_id" not in wrong.feature_names
    if result.case_id == "selection":
        assert result.generator_params["labels_independent_of_features"] is True
        assert clean.diagnostics["selector_test_rows_seen"] == 0
        assert wrong.diagnostics["selector_test_rows_seen"] == len(wrong.test_row_ids)
        assert set(clean.fit_stages[0]["row_ids"]) == set(clean.train_row_ids)
        assert set(wrong.fit_stages[0]["row_ids"]) == set(wrong.train_row_ids + wrong.test_row_ids)
        assert len(wrong.feature_names) == len(clean.feature_names) == 25


@pytest.mark.parametrize("case_id", list(CASES))
def test_fixed_seed_is_reproducible(case_id):
    assert run_experiment(case_id, 42).to_dict() == run_experiment(case_id, 42).to_dict()


@pytest.mark.parametrize("generator", [generate_future, generate_groups, generate_selection])
def test_seed_changes_data(generator):
    first, second = generator(7), generator(42)
    assert not first.X.equals(second.X)
    assert not first.y.equals(second.y)


def test_generator_parameters_have_effect():
    assert len(generate_future(42, n_samples=80).X) == 80
    grouped = generate_groups(42, n_entities=20, observations_per_entity=3)
    assert len(grouped.X) == 60
    assert grouped.groups.nunique() == 20
    assert generate_selection(42, n_samples=80, n_features=100).X.shape == (80, 100)


def test_selector_fit_calls_observe_only_training_in_pipeline(monkeypatch):
    observed = []
    original_fit = AuditedSelectKBest.fit

    def spy(self, X, y):
        assert isinstance(X, pd.DataFrame)
        observed.append((list(X.index), list(y.index)))
        return original_fit(self, X, y)

    monkeypatch.setattr(AuditedSelectKBest, "fit", spy)
    result = run_experiment("selection", 42)
    assert len(observed) == 2
    wrong, clean = result.variants["incorrect"], result.variants["correct"]
    assert set(observed[0][0]) == set(wrong.train_row_ids + wrong.test_row_ids)
    assert observed[0][0] == observed[0][1]
    assert observed[1][0] == clean.train_row_ids
    assert observed[1][1] == clean.train_row_ids
    assert set(observed[1][0]).isdisjoint(clean.test_row_ids)


def test_diagnostics_do_not_accuse_legitimate_features_or_separated_entities():
    assert future_feature_diagnostic(["importe", "cliente_nuevo"])["leakage_detected"] is False
    assert group_diagnostic(["a", "a", "b"], ["c", "c"])["leakage_detected"] is False
    assert group_diagnostic(["a", "b"], ["b", "c"])["shared_entity_count"] == 1


@pytest.mark.parametrize("seed", [-1, 2**32, True, 4.2, "42", None])
def test_invalid_seeds_fail_clearly(seed):
    with pytest.raises(ValueError, match="semilla"):
        run_experiment("future", seed)


@pytest.mark.parametrize("case_id", ["unknown", "", None, []])
def test_invalid_cases_fail_clearly(case_id):
    with pytest.raises(ValueError, match="Caso desconocido"):
        run_experiment(case_id, 42)


@pytest.mark.parametrize("generator,kwargs", [
    (generate_future, {"n_samples": 1}),
    (generate_future, {"n_samples": True}),
    (generate_groups, {"n_entities": -4}),
    (generate_groups, {"observations_per_entity": 1}),
    (generate_selection, {"n_features": 5}),
    (generate_selection, {"n_samples": 4.5}),
])
def test_invalid_generator_parameters_fail_clearly(generator, kwargs):
    with pytest.raises(ValueError, match="debe ser un entero"):
        generator(42, **kwargs)
