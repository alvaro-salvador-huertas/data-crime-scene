"""Small deterministic reports: no fitting, archived results or metric oracle."""

from copy import deepcopy
import json

import pandas as pd
import pytest

from data_crime_scene import laboratory as lab
from data_crime_scene.generators import SyntheticDataset
from data_crime_scene.study import _manifest, load_study, planned_configs
from data_crime_scene.validation import validate_prediction_dict


HISTORICAL_ENGINE = "ec9f68561a319618c8f301b2462be4f7166704afcb69bc24996d4cff96d0b28e"


def scores(y, predictions):
    """Independent arithmetic for fixture metrics, never for choosing a majority."""
    tn, fp, fn, tp = (sum(a == i and b == j for a, b in zip(y, predictions))
                      for i, j in ((0, 0), (0, 1), (1, 0), (1, 1)))
    recalls = [hit / total for hit, total in ((tn, tn + fp), (tp, tp + fn)) if total]
    return {"accuracy": (tn + tp) / len(y), "balanced_accuracy": sum(recalls) / len(recalls),
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0}


def distribution(y):
    return {"count0": y.count(0), "count1": y.count(1), "positive_rate": y.count(1) / len(y)}


def prediction(y, majority):
    return {"y_true": y, "y_pred": y.copy(), "metrics": scores(y, y),
            "confusion_matrix": [[y.count(0), 0], [0, y.count(1)]],
            "baseline_predictions": [majority] * len(y),
            "baseline_metrics": scores(y, [majority] * len(y))}


@pytest.fixture
def small_report(monkeypatch):
    def make(tie=False):
        rows = list("abcdefgh")
        # Correct train: 0001 (or 0011 for a tie); incorrect train: 0111 (or 1111).
        # Correct test and cohort both have majority 1, opposite to correct train.
        labels = [0, 0, int(tie), 1, 1, 1, 1, 0]
        data = SyntheticDataset(pd.DataFrame({"sensor": range(8)}, index=rows),
                                pd.Series(labels, index=rows), {}, pd.Series(rows, index=rows))
        cohort_rows = list("wxyz")
        cohort = SyntheticDataset(pd.DataFrame({"sensor": range(4)}, index=cohort_rows),
                                  pd.Series([0, 1, 1, 1], index=cohort_rows), {},
                                  pd.Series(cohort_rows, index=cohort_rows))
        monkeypatch.setattr(lab, "generate_lab_data", lambda *args: (data, cohort))
        variants, evaluations = {}, {}
        for key, train, majority in (("correct", rows[:4], 0), ("incorrect", rows[2:6], 1)):
            test = [row for row in rows if row not in train]
            train_y, test_y = data.y.loc[train].tolist(), data.y.loc[test].tolist()
            variants[key] = {**prediction(test_y, majority), "train_row_ids": train,
                             "test_row_ids": test, "feature_names": ["sensor"],
                             "train_size": len(train), "test_size": len(test),
                             "diagnostics": {"shared_entity_count": 0, "shared_entities": [],
                                             "leakage_detected": False,
                                             "class_distribution": {"train": distribution(train_y),
                                                                    "test": distribution(test_y)}}}
            # The validator checks every key returned by group_diagnostic.
            variants[key]["diagnostics"].update(lab.group_diagnostic(data.groups.loc[train], data.groups.loc[test]))
            evaluations[key] = {**prediction([0, 1, 1, 1], majority), "row_ids": cohort_rows,
                                "entity_ids": cohort_rows, "n_samples": 4, "n_entities": 4,
                                "class_distribution": {"count0": 1, "count1": 3, "positive_rate": .75}}
        return {**_manifest(), "schema_version": "lab-run/1", "config": lab.lab_config("groups", 42, .35),
                "generator_params": {}, "variants": variants, "cohort": evaluations}
    return make


def study_with(result):
    return {**_manifest(), "entries": [
        {"config": config, "status": "ok", "result": deepcopy(result)} if config == result["config"] else
        {"config": config, "status": "error", "error": {"type": "FixtureNotRun", "message": "Synthetic fixture"}}
        for config in planned_configs()]}


@pytest.mark.parametrize("tie", [False, True])
def test_valid_cohort_uses_each_training_partition(small_report, tie):
    report = small_report(tie)
    lab.validate_lab_result(report)
    assert report["cohort"]["correct"]["baseline_predictions"] == [0, 0, 0, 0]
    assert report["cohort"]["incorrect"]["baseline_predictions"] == [1, 1, 1, 1]


@pytest.mark.parametrize("key,wrong,metrics", [
    ("correct", 1, {"accuracy": .75, "balanced_accuracy": .5, "f1": 6 / 7}),
    ("incorrect", 0, {"accuracy": .25, "balanced_accuracy": .5, "f1": 0.0}),
])
@pytest.mark.parametrize("recalculate", [False, True])
def test_wrong_cohort_baseline_rejected_even_with_coherent_metrics(small_report, key, wrong, metrics, recalculate):
    report = small_report()
    lab.validate_lab_result(report)
    value = report["cohort"][key]
    value["baseline_predictions"] = [wrong] * 4
    if recalculate:
        value["baseline_metrics"] = metrics
        validate_prediction_dict(value)  # Numeric consistency alone cannot establish provenance.
    with pytest.raises(ValueError, match="baseline"):
        lab.validate_lab_result(report)


def test_tied_training_rejects_one_even_when_cohort_majority_is_one(small_report):
    report = small_report(tie=True)
    value = report["cohort"]["correct"]
    value["baseline_predictions"] = [1] * 4
    value["baseline_metrics"] = {"accuracy": .75, "balanced_accuracy": .5, "f1": 6 / 7}
    with pytest.raises(ValueError, match="baseline"):
        lab.validate_lab_result(report)


@pytest.mark.parametrize("zero", [0, 0.0, False])
def test_existing_binary_numeric_types_remain_accepted(small_report, zero):
    report = small_report()
    report["cohort"]["correct"]["baseline_predictions"] = [zero] * 4
    lab.validate_lab_result(report)


@pytest.mark.parametrize("invalid", [["0"] * 4, [2] * 4, [], [0] * 3])
def test_invalid_baseline_values_and_lengths_rejected(small_report, invalid):
    report = small_report()
    report["cohort"]["correct"]["baseline_predictions"] = invalid
    with pytest.raises(ValueError, match="baseline"):
        lab.validate_lab_result(report)


@pytest.mark.parametrize("historical", [False, True])
def test_load_study_validates_current_and_historical_cohorts(small_report, tmp_path, historical):
    result = small_report()
    study = study_with(result)
    if historical:
        study["engine_fingerprint"] = HISTORICAL_ENGINE
        for entry in study["entries"]:
            if entry["status"] == "ok":
                entry["result"]["engine_fingerprint"] = HISTORICAL_ENGINE
    path = tmp_path / "study.json"
    path.write_text(json.dumps(study))
    assert load_study(path) == study
    value = next(e["result"] for e in study["entries"] if e["status"] == "ok")["cohort"]["correct"]
    value["baseline_predictions"] = [1] * 4
    value["baseline_metrics"] = {"accuracy": .75, "balanced_accuracy": .5, "f1": 6 / 7}
    path.write_text(json.dumps(study))
    with pytest.raises(ValueError, match="baseline"):
        load_study(path)


@pytest.mark.parametrize("field,value", [
    ("engine_fingerprint", "unreviewed-engine"), ("protocol_hash", "other-protocol"),
    ("runtime", {}), ("generator_params", {"invented": True}),
])
def test_historical_compatibility_does_not_skip_other_checks(small_report, field, value):
    report = small_report()
    report["engine_fingerprint"] = HISTORICAL_ENGINE
    report[field] = value
    with pytest.raises(ValueError):
        lab.validate_lab_result(report)


def test_ui_loads_historical_study_and_refuses_coherent_baseline_mutation(small_report, tmp_path, monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    import ui.laboratory as interface

    result = small_report()
    result["engine_fingerprint"] = HISTORICAL_ENGINE
    study = study_with(result)
    study["engine_fingerprint"] = HISTORICAL_ENGINE
    path = tmp_path / "study.json"
    path.write_text(json.dumps(study))
    monkeypatch.setattr(interface, "PROJECT", tmp_path)

    def no_training(*args, **kwargs):
        raise AssertionError("Loading an archived study must not fit models")

    monkeypatch.setattr(lab, "run_lab_experiment", no_training)
    monkeypatch.setattr(interface, "run_lab_experiment", no_training)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30).run()
    app.radio(key="mode_selector").set_value("Laboratorio").run()
    app.selectbox(key="lab_case_selector").set_value("groups").run()
    app.text_input(key="lab_study_path").set_value("study.json").run()
    app.button(key="lab_load_study").click().run()
    assert not app.exception
    assert app.session_state["lab_study"] == study
    assert len(app.get("download_button")) == 1
    rows = next(frame.value for frame in app.dataframe if "balanced_accuracy" in frame.value.columns)
    cohort_rows = rows.loc[rows["evaluation"] == "cohort"]
    assert set(cohort_rows["variant"]) == {"correct", "incorrect"}
    assert cohort_rows["balanced_accuracy"].tolist() == [1.0, 1.0]

    value = next(e["result"] for e in study["entries"] if e["status"] == "ok")["cohort"]["correct"]
    value["baseline_predictions"] = [1] * 4
    value["baseline_metrics"] = {"accuracy": .75, "balanced_accuracy": .5, "f1": 6 / 7}
    path.write_text(json.dumps(study))
    app.button(key="lab_load_study").click().run()
    assert not app.exception
    assert "lab_study" not in app.session_state
    assert len(app.get("download_button")) == 0
    assert any("baseline de cohorte" in item.value for item in app.error)
