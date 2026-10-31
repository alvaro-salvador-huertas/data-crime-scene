"""Mutaciones aisladas: cada defensa acepta el control y rechaza su error.

No se activan fallos mediante parámetros de producción. Las mutaciones viven
solo en copias de fixtures; los diagnósticos declarados se dejan intactos.
"""

from copy import deepcopy
import json
from pathlib import Path

import pytest
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score
from streamlit.testing.v1 import AppTest

from data_crime_scene.experiments import AuditedSelectKBest, run_experiment
from data_crime_scene.generators import generate_groups, generate_selection
from data_crime_scene.validation import assert_training_scope, validate_export, validate_result


@pytest.fixture(scope="module")
def originals():
    return {case: run_experiment(case, 42) for case in ("future", "groups", "selection")}


def _refresh_prediction_summaries(variant):
    """Impide que una mutación de partición falle solo por métricas viejas."""
    variant.metrics = {
        "accuracy": float(accuracy_score(variant.y_true, variant.y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(variant.y_true, variant.y_pred)),
        "f1": float(f1_score(variant.y_true, variant.y_pred, zero_division=0)),
    }
    variant.confusion_matrix = confusion_matrix(variant.y_true, variant.y_pred, labels=[0, 1]).tolist()
    variant.baseline_metrics = {
        "accuracy": float(accuracy_score(variant.y_true, variant.baseline_predictions)),
        "balanced_accuracy": float(balanced_accuracy_score(variant.y_true, variant.baseline_predictions)),
        "f1": float(f1_score(variant.y_true, variant.baseline_predictions, zero_division=0)),
    }


@pytest.mark.parametrize("case_id", ["future", "groups", "selection"])
def test_unmodified_controls_pass_all_integrity_checks(originals, case_id):
    result = originals[case_id]
    validate_result(result, expected_case_id=case_id, expected_seed=42)
    validate_result(result.to_dict(), expected_case_id=case_id, expected_seed=42)
    validate_export(result.to_json(), result)


def test_group_intrusion_is_detected_from_rows_even_when_flags_say_clean(originals):
    bad = deepcopy(originals["groups"])
    clean = bad.variants["correct"]
    data = generate_groups(42)
    # Intercambiar filas conserva tamaños y disyunción de filas, pero mezcla
    # dos máquinas: sus otros cinco registros permanecen en el conjunto previo.
    old_train, old_test = clean.train_row_ids[0], clean.test_row_ids[0]
    clean.train_row_ids[0], clean.test_row_ids[0] = old_test, old_train
    clean.y_true = [int(value) for value in data.y.loc[clean.test_row_ids]]
    majority = int(data.y.loc[clean.train_row_ids].value_counts().idxmax())
    clean.baseline_predictions = [majority] * len(clean.y_true)
    for stage in clean.fit_stages:
        stage["row_ids"] = list(clean.train_row_ids)
        stage["n_rows"] = len(clean.train_row_ids)
        if "label_row_ids" in stage:
            stage["label_row_ids"] = list(clean.train_row_ids)
    _refresh_prediction_summaries(clean)
    assert set(clean.train_row_ids).isdisjoint(clean.test_row_ids)
    assert set(data.groups.loc[clean.train_row_ids]) & set(data.groups.loc[clean.test_row_ids])
    assert clean.diagnostics["leakage_detected"] is False
    assert clean.diagnostics["shared_entity_count"] == 0
    with pytest.raises(ValueError):
        validate_result(bad)


def test_future_column_in_legitimate_variant_is_rejected_despite_clean_flag(originals):
    bad = deepcopy(originals["future"])
    bad.variants["correct"].feature_names.append("reembolso_tramitado")
    assert bad.variants["correct"].diagnostics["leakage_detected"] is False
    with pytest.raises(ValueError):
        validate_result(bad)


def test_selector_scope_mutation_is_rejected_without_trusting_diagnostic(originals):
    bad = deepcopy(originals["selection"])
    clean = bad.variants["correct"]
    stage = clean.fit_stages[0]
    stage["row_ids"].append(clean.test_row_ids[0])
    stage["n_rows"] += 1
    assert clean.diagnostics["selector_test_rows_seen"] == 0
    with pytest.raises(ValueError):
        validate_result(bad)


def test_real_selector_fit_with_test_labels_is_rejected():
    data = generate_selection(42, n_samples=80, n_features=100)
    train = list(data.X.index[:60])
    test = list(data.X.index[60:])
    clean = AuditedSelectKBest(k=25).fit(data.X.loc[train], data.y.loc[train])
    assert_training_scope(clean.fit_row_ids_, clean.fit_label_row_ids_, train, test)
    # Este selector sí recibe físicamente todas las filas y etiquetas.
    contaminated = AuditedSelectKBest(k=25).fit(data.X, data.y)
    with pytest.raises(ValueError):
        assert_training_scope(contaminated.fit_row_ids_, contaminated.fit_label_row_ids_, train, test)
    # El mismo número de etiquetas no basta: se verifica su identidad/orden.
    wrong_labels = data.y.loc[train].copy()
    wrong_labels.index = train[1:] + [test[0]]
    mismatched = AuditedSelectKBest(k=25).fit(data.X.loc[train], wrong_labels)
    with pytest.raises(ValueError):
        assert_training_scope(mismatched.fit_row_ids_, mismatched.fit_label_row_ids_, train, test)
    # También se rechaza desalineación posicional aunque ambos conjuntos de
    # índices sean exactamente train: scikit-learn no alinea por índice pandas.
    reversed_labels = AuditedSelectKBest(k=25).fit(data.X.loc[train], data.y.loc[train[::-1]])
    with pytest.raises(ValueError):
        assert_training_scope(reversed_labels.fit_row_ids_, reversed_labels.fit_label_row_ids_, train, test)


def test_changed_prediction_with_stale_metrics_is_rejected_before_export(originals):
    bad = deepcopy(originals["future"])
    clean = bad.variants["correct"]
    clean.y_pred[0] = 1 - clean.y_pred[0]
    with pytest.raises(ValueError):
        validate_result(bad)
    with pytest.raises(ValueError):
        bad.to_json()


def test_changed_raw_label_cannot_be_hidden_by_recomputing_metrics(originals):
    bad = deepcopy(originals["future"])
    clean = bad.variants["correct"]
    clean.y_true[0] = 1 - clean.y_true[0]
    _refresh_prediction_summaries(clean)
    with pytest.raises(ValueError):
        validate_result(bad)


def test_stale_context_and_foreign_json_are_rejected(originals):
    shown = originals["future"]
    validate_result(shown, expected_case_id="future", expected_seed=42)
    with pytest.raises(ValueError):
        validate_result(shown, expected_case_id="future", expected_seed=7)
    with pytest.raises(ValueError):
        validate_result(shown, expected_case_id="groups", expected_seed=42)
    foreign = run_experiment("future", 7)
    with pytest.raises(ValueError):
        validate_export(foreign.to_json(), shown)
    # Coinciden caso, semilla y accuracy; cambia información menos visible.
    payload = json.loads(shown.to_json())
    payload["teaching_notes"].append("Contenido ajeno al objeto mostrado")
    with pytest.raises(ValueError):
        validate_export(json.dumps(payload), shown)


@pytest.fixture
def isolated_streamlit_cache():
    import streamlit as st

    st.cache_data.clear()
    try:
        yield
    finally:
        # El resultado deliberadamente erróneo tampoco debe escapar de esta
        # prueba si una aserción falla antes de finalizar la navegación.
        st.cache_data.clear()


def test_guided_ui_rejects_stale_cache_result(monkeypatch, originals, isolated_streamlit_cache):
    import data_crime_scene.experiments as experiments

    monkeypatch.setattr(experiments, "run_experiment", lambda case_id, seed: deepcopy(originals["future"]))
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    app.number_input(key="seed_input").set_value(7).run()
    app.button(key="run_experiment").click().run()
    assert not app.exception
    assert app.error
    assert len(app.metric) == 0
    assert "result" not in app.session_state or app.session_state["result"] is None
