"""Control experimental y coherencia del laboratorio, sin lanzar el estudio completo."""

from copy import deepcopy
import json

import numpy as np
import pandas as pd
import pytest
from sklearn.feature_selection import SelectKBest
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score
from sklearn.preprocessing import StandardScaler

from data_crime_scene.generators import generate_future, generate_groups, generate_selection_nested
from data_crime_scene.laboratory import LAB_CASES, generate_lab_data, run_lab_experiment, validate_lab_result


LEVELS = {"future": [0.0, 0.25, 0.5], "groups": [0.035, 0.35, 1.0], "selection": [50, 500, 1800]}


@pytest.fixture(scope="module")
def lab_results():
    # Nueve combinaciones para cobertura estructural; el estudio de 90 requiere
    # un comando explícito y se ejecuta fuera de la batería de pruebas.
    return {(case, level): run_lab_experiment(case, 42, level)
            for case, levels in LEVELS.items() for level in levels}


def _assert_predictions(value):
    y, pred = value["y_true"], value["y_pred"]
    assert value["metrics"]["accuracy"] == accuracy_score(y, pred)
    assert value["metrics"]["balanced_accuracy"] == balanced_accuracy_score(y, pred)
    assert value["metrics"]["f1"] == f1_score(y, pred, zero_division=0)
    assert value["confusion_matrix"] == confusion_matrix(y, pred, labels=[0, 1]).tolist()
    baseline = value["baseline_predictions"]
    assert value["baseline_metrics"]["accuracy"] == accuracy_score(y, baseline)
    assert value["baseline_metrics"]["balanced_accuracy"] == balanced_accuracy_score(y, baseline)
    assert value["baseline_metrics"]["f1"] == f1_score(y, baseline, zero_division=0)


def test_three_levels_are_predeclared_and_all_lab_results_are_consistent(lab_results):
    assert set(LAB_CASES) == set(LEVELS)
    for case, levels in LEVELS.items():
        assert list(LAB_CASES[case]["levels"]) == levels
    for (case, level), result in lab_results.items():
        validate_lab_result(result, case_id=case, seed=42, level=level)
        assert result["config"]["case_id"] == case
        assert result["config"]["seed"] == 42
        assert result["config"]["level"] == level
        assert result["config"]["factor"]
        assert result["config"]["protocol_version"]
        for variant in result["variants"].values():
            assert set(variant["train_row_ids"]).isdisjoint(variant["test_row_ids"])
            assert variant["train_size"] == len(variant["train_row_ids"])
            assert variant["test_size"] == len(variant["test_row_ids"])
            _assert_predictions(variant)
        if case == "groups":
            for evaluation in result["cohort"].values():
                _assert_predictions(evaluation)


def test_future_factor_changes_only_future_signal_and_preserves_paired_rows(lab_results):
    data = [generate_future(42, refund_flip_probability=level) for level in LEVELS["future"]]
    legitimate = ["importe", "producto_fragil", "cliente_nuevo"]
    for other in data[1:]:
        pd.testing.assert_frame_equal(data[0].X[legitimate], other.X[legitimate])
        pd.testing.assert_series_equal(data[0].y, other.y)
    assert not data[0].X["reembolso_tramitado"].equals(data[-1].X["reembolso_tramitado"])
    first = lab_results[("future", 0.0)]
    for level in LEVELS["future"]:
        result = lab_results[("future", level)]
        assert set(result["variants"]) == {"incorrect", "correct", "control"}
        clean = result["variants"]["correct"]
        for variant in result["variants"].values():
            assert variant["train_row_ids"] == clean["train_row_ids"]
            assert variant["test_row_ids"] == clean["test_row_ids"]
            assert variant["y_true"] == clean["y_true"]
            assert variant["model"]["params"] == clean["model"]["params"]
        assert clean["y_pred"] == first["variants"]["correct"]["y_pred"]
        assert result["variants"]["control"]["y_pred"] == first["variants"]["control"]["y_pred"]
        assert "reembolso_tramitado" not in result["variants"]["control"]["feature_names"]
        assert not result["variants"]["control"]["diagnostics"]["leakage_detected"]


def test_baselines_use_each_models_training_majority(lab_results):
    for (case, level), result in lab_results.items():
        data, _ = generate_lab_data(case, 42, level)
        for key, variant in result["variants"].items():
            train_y = data.y.loc[variant["train_row_ids"]].to_numpy()
            expected = int(np.bincount(train_y, minlength=2).argmax())
            assert variant["baseline_predictions"] == [expected] * len(variant["y_true"])
            if case == "groups":
                evaluation = result["cohort"][key]
                assert evaluation["baseline_predictions"] == [expected] * len(evaluation["y_true"])


def test_future_fit_columns_match_real_pipeline_inputs(monkeypatch):
    observed = []
    original_fit = StandardScaler.fit

    def spy(self, X, y=None, *args, **kwargs):
        observed.append((list(X.columns), list(X.index)))
        return original_fit(self, X, y, *args, **kwargs)

    monkeypatch.setattr(StandardScaler, "fit", spy)
    result = run_lab_experiment("future", 7, 0.25)
    expected = sorted((tuple(value["feature_names"]), tuple(value["train_row_ids"]))
                      for value in result["variants"].values())
    assert sorted((tuple(columns), tuple(rows)) for columns, rows in observed) == expected


def test_groups_noise_retains_labels_and_cohort_is_common_and_unseen(lab_results):
    data = [generate_groups(42, measurement_noise_std=level) for level in LEVELS["groups"]]
    for other in data[1:]:
        pd.testing.assert_series_equal(data[0].y, other.y)
        pd.testing.assert_series_equal(data[0].groups, other.groups)
    assert not data[0].X.equals(data[-1].X)
    for level in LEVELS["groups"]:
        result = lab_results[("groups", level)]
        raw = generate_groups(42, measurement_noise_std=level)
        clean, wrong = result["variants"]["correct"], result["variants"]["incorrect"]
        clean_train = set(raw.groups.loc[clean["train_row_ids"]])
        clean_test = set(raw.groups.loc[clean["test_row_ids"]])
        wrong_train = set(raw.groups.loc[wrong["train_row_ids"]])
        wrong_test = set(raw.groups.loc[wrong["test_row_ids"]])
        assert clean_train.isdisjoint(clean_test)
        assert wrong_train & wrong_test
        assert wrong["diagnostics"]["shared_entity_count"] == len(wrong_train & wrong_test)
        assert clean["diagnostics"]["shared_entity_count"] == 0
        cohort_wrong, cohort_clean = result["cohort"]["incorrect"], result["cohort"]["correct"]
        assert cohort_wrong["row_ids"] == cohort_clean["row_ids"]
        assert cohort_wrong["entity_ids"] == cohort_clean["entity_ids"]
        assert cohort_wrong["y_true"] == cohort_clean["y_true"]
        assert set(cohort_clean["entity_ids"]).isdisjoint(set(raw.groups))
        assert cohort_clean["n_entities"] == len(set(cohort_clean["entity_ids"])) == 30
        assert cohort_clean["n_samples"] == len(cohort_clean["y_true"]) == 180


def test_selection_levels_preserve_raw_labels_and_feature_prefixes(lab_results):
    data = [generate_selection_nested(42, n_features=level) for level in LEVELS["selection"]]
    for other in data[1:]:
        pd.testing.assert_series_equal(data[0].y, other.y)
        pd.testing.assert_frame_equal(data[0].X, other.X.iloc[:, :50])
    first = lab_results[("selection", 50)]["variants"]["correct"]
    for level in LEVELS["selection"]:
        result = lab_results[("selection", level)]
        wrong, clean = result["variants"]["incorrect"], result["variants"]["correct"]
        assert clean["train_row_ids"] == wrong["train_row_ids"] == first["train_row_ids"]
        assert clean["test_row_ids"] == wrong["test_row_ids"] == first["test_row_ids"]
        assert clean["y_true"] == wrong["y_true"] == first["y_true"]
        assert len(clean["feature_names"]) == len(wrong["feature_names"]) == 25
        assert clean["model"]["params"] == wrong["model"]["params"] == first["model"]["params"]


def test_selection_observes_real_supervised_fit_inputs(monkeypatch):
    observed = []
    original_fit = SelectKBest.fit

    def spy(self, X, y):
        observed.append((list(X.index), list(y.index)))
        return original_fit(self, X, y)

    monkeypatch.setattr(SelectKBest, "fit", spy)
    result = run_lab_experiment("selection", 7, 50)
    clean = result["variants"]["correct"]
    assert len(observed) == 2
    assert set(observed[0][0]) == set(clean["train_row_ids"] + clean["test_row_ids"])
    assert observed[0][0] == observed[0][1]
    assert observed[1][0] == observed[1][1] == clean["train_row_ids"]
    assert set(observed[1][0]).isdisjoint(clean["test_row_ids"])


@pytest.mark.parametrize("case,level", [("future", 0.25), ("groups", 0.35), ("selection", 50)])
def test_lab_reproducible_and_requested_context_is_checked(case, level):
    first = run_lab_experiment(case, 7, level)
    assert first == run_lab_experiment(case, 7, level)
    validate_lab_result(first, case_id=case, seed=7, level=level)
    with pytest.raises(ValueError):
        validate_lab_result(first, case_id=case, seed=42, level=level)
    with pytest.raises(ValueError):
        validate_lab_result(first, case_id=case, seed=7, level=LEVELS[case][-1])


def test_lab_corrupted_prediction_and_config_are_rejected(lab_results):
    bad = deepcopy(lab_results[("future", 0.25)])
    bad["variants"]["correct"]["y_pred"][0] ^= 1
    with pytest.raises(ValueError):
        validate_lab_result(bad)
    wrong_config = deepcopy(lab_results[("selection", 50)])
    wrong_config["config"]["protocol_version"] = "incompatible"
    with pytest.raises(ValueError):
        validate_lab_result(wrong_config)
    contaminated_cohort = deepcopy(lab_results[("groups", 0.35)])
    known_entity = generate_groups(42).groups.iloc[0]
    contaminated_cohort["cohort"]["correct"]["entity_ids"][0] = known_entity
    with pytest.raises(ValueError):
        validate_lab_result(contaminated_cohort)


@pytest.mark.parametrize("case,seed,level", [
    ("unknown", 42, 0), ("future", -1, 0), ("future", 42, -0.1),
    ("groups", 42, -1), ("selection", 42, 5), ("future", 42, float("nan")),
])
def test_invalid_lab_parameters_fail_before_fit(case, seed, level):
    with pytest.raises(ValueError):
        run_lab_experiment(case, seed, level)


@pytest.fixture(scope="module")
def failed_study():
    from data_crime_scene import study

    def deliberate_failure(case_id, seed, level):
        raise RuntimeError(f"Fallo deliberado aislado: {case_id}/{seed}/{level}")

    # Las 90 entradas se registran, pero no se ajusta ningún modelo.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(study, "run_lab_experiment", deliberate_failure)
        return study.run_study()


def test_study_keeps_every_planned_error_and_never_treats_errors_as_scores(failed_study):
    from data_crime_scene.study import planned_configs, study_rows, summarize, validate_study

    assert len(failed_study["entries"]) == 90
    assert [entry["config"] for entry in failed_study["entries"]] == planned_configs()
    assert len({(entry["config"]["case_id"], entry["config"]["seed"], entry["config"]["level"])
                for entry in failed_study["entries"]}) == 90
    for entry in failed_study["entries"]:
        assert entry["status"] == "error"
        assert entry["error"]["type"] == "RuntimeError"
        assert "Fallo deliberado aislado" in entry["error"]["message"]
        assert "result" not in entry
    validate_study(failed_study)
    assert summarize(failed_study) == []
    assert all(study_rows(failed_study, case) == [] for case in LEVELS)


def test_study_loading_rejects_incompatible_or_incomplete_results(failed_study, tmp_path):
    from data_crime_scene.study import load_study

    path = tmp_path / "study.json"
    path.write_text(json.dumps(failed_study), encoding="utf-8")
    assert load_study(path) == failed_study
    for mutate in (
        lambda value: value.update(protocol_hash="different-protocol"),
        lambda value: value.update(engine_fingerprint="different-code"),
        lambda value: value["runtime"].update(scikit_learn="different-version"),
        lambda value: value["entries"].pop(),
    ):
        bad = deepcopy(failed_study)
        mutate(bad)
        path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError):
            load_study(path)


def test_summaries_count_seeds_and_paired_differences_require_same_evaluation_rows(lab_results):
    from data_crime_scene.study import paired_differences, summarize

    first = lab_results[("future", 0.0)]
    second = run_lab_experiment("future", 7, 0.0)
    subset = {"entries": [{"status": "ok", "config": item["config"], "result": item}
                          for item in (first, second)]}
    summary = summarize(subset)
    assert len(summary) == 3
    for row in summary:
        scores = [item["variants"][row["variant"]]["metrics"]["balanced_accuracy"] for item in (first, second)]
        assert row["n_seeds"] == 2
        assert row["median"] == np.median(scores)
        assert row["q1"] == np.quantile(scores, 0.25)
        assert row["q3"] == np.quantile(scores, 0.75)
    deltas = paired_differences(subset, "future")
    assert len(deltas) == 4  # Dos comparaciones por cada semilla.
    for item in (first, second):
        score = item["variants"]["incorrect"]["metrics"]["balanced_accuracy"]
        clean = item["variants"]["correct"]["metrics"]["balanced_accuracy"]
        assert any(row["seed"] == item["config"]["seed"] and row["delta"] == score - clean for row in deltas)

    groups = lab_results[("groups", 0.35)]
    group_subset = {"entries": [{"status": "ok", "config": groups["config"], "result": groups}]}
    assert paired_differences(group_subset, "groups")[0]["evaluation"] == "cohort"
    bad = deepcopy(group_subset)
    bad["entries"][0]["result"]["cohort"]["incorrect"]["y_true"][0] ^= 1
    with pytest.raises(ValueError):
        paired_differences(bad, "groups")
