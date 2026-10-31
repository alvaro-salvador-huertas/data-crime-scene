"""Interacciones y defensas del laboratorio mediante AppTest, sin estudio masivo."""

from copy import deepcopy
import json
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from data_crime_scene.laboratory import LAB_CASES, run_lab_experiment


APP = Path(__file__).resolve().parents[1] / "app.py"


def laboratory_app():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.radio(key="mode_selector").set_value("Laboratorio").run()
    assert not app.exception
    return app


@pytest.mark.parametrize("case_id", ["future", "groups", "selection"])
def test_lab_cases_export_the_same_result_as_displayed(case_id, monkeypatch):
    downloads = {}
    original = st.download_button

    def capture(*args, **kwargs):
        data = kwargs.get("data", args[1] if len(args) > 1 else None)
        downloads[kwargs["key"]] = data
        return original(*args, **kwargs)

    monkeypatch.setattr(st, "download_button", capture)
    app = laboratory_app()
    app.selectbox(key="lab_case_selector").set_value(case_id).run()
    assert "lab_result" not in app.session_state
    app.button(key="lab_run").click().run()
    assert not app.exception
    result = app.session_state["lab_result"]
    assert result["config"]["case_id"] == case_id
    assert json.loads(downloads["lab_download_run"]) == result
    metrics = app.dataframe[0].value
    observed = [f"{v['metrics']['balanced_accuracy']:.1%}" for v in result["variants"].values()]
    assert all(value in metrics["Balanced accuracy"].tolist() for value in observed)
    if case_id == "groups":
        assert result["cohort"]["incorrect"]["row_ids"] == result["cohort"]["correct"]["row_ids"]
        assert result["variants"]["correct"]["diagnostics"]["shared_entity_count"] == 0


def test_lab_case_seed_and_level_each_invalidate_previous_execution():
    app = laboratory_app()
    app.button(key="lab_run").click().run()
    first = deepcopy(app.session_state["lab_result"])
    app.select_slider(key="lab_level_future").set_value(0.5).run()
    assert "lab_result" not in app.session_state
    assert len(app.get("download_button")) == 0
    app.button(key="lab_run").click().run()
    assert app.session_state["lab_result"]["config"]["level"] == 0.5
    assert app.session_state["lab_result"] != first
    app.number_input(key="lab_seed_input").set_value(7).run()
    assert "lab_result" not in app.session_state
    app.button(key="lab_run").click().run()
    assert app.session_state["lab_result"]["config"]["seed"] == 7
    app.selectbox(key="lab_case_selector").set_value("selection").run()
    assert "lab_result" not in app.session_state
    assert not app.exception


def test_opening_lab_and_changing_controls_do_not_train(monkeypatch):
    import data_crime_scene.laboratory as laboratory

    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("No debe entrenar al abrir o cambiar controles")

    monkeypatch.setattr(laboratory, "run_lab_experiment", forbidden)
    # ui ya puede estar importado por otra prueba: parcheamos también su referencia.
    import ui.laboratory as interface
    monkeypatch.setattr(interface, "run_lab_experiment", forbidden)
    app = laboratory_app()
    app.selectbox(key="lab_case_selector").set_value("groups").run()
    app.number_input(key="lab_seed_input").set_value(7).run()
    app.select_slider(key="lab_level_groups").set_value(1.0).run()
    assert calls == []
    assert not app.exception


def test_cache_includes_level_seed_case_and_reuses_identical_request(monkeypatch):
    import ui.laboratory as interface

    st.cache_data.clear()
    original = interface.run_lab_experiment
    calls = []

    def tracked(case_id, seed, level):
        calls.append((case_id, seed, level))
        return original(case_id, seed, level)

    monkeypatch.setattr(interface, "run_lab_experiment", tracked)
    app = laboratory_app()
    app.button(key="lab_run").click().run()
    app.button(key="lab_run").click().run()
    app.selectbox(key="lab_study_metric").set_value("accuracy").run()
    assert calls == [("future", 42, .25)]
    app.select_slider(key="lab_level_future").set_value(.5).run()
    app.button(key="lab_run").click().run()
    app.number_input(key="lab_seed_input").set_value(7).run()
    app.button(key="lab_run").click().run()
    app.selectbox(key="lab_case_selector").set_value("selection").run()
    app.button(key="lab_run").click().run()
    assert calls == [("future", 42, .25), ("future", 42, .5), ("future", 7, .5), ("selection", 7, 500)]
    assert not app.exception


def test_stale_cached_configuration_is_rejected_before_display(monkeypatch):
    import ui.laboratory as interface

    stale = run_lab_experiment("future", 42, .25)
    monkeypatch.setattr(interface, "cached_lab_experiment", lambda *args: deepcopy(stale))
    app = laboratory_app()
    app.number_input(key="lab_seed_input").set_value(7).run()
    app.button(key="lab_run").click().run()
    assert not app.exception
    assert "lab_result" not in app.session_state
    assert len(app.error) >= 1
    assert len(app.get("download_button")) == 0


def test_corrupted_session_result_is_rejected_on_next_render():
    app = laboratory_app()
    app.button(key="lab_run").click().run()
    broken = deepcopy(app.session_state["lab_result"])
    wrong = broken["variants"]["correct"]
    wrong["y_pred"][0] = 1 - wrong["y_pred"][0]
    app.session_state["lab_result"] = broken
    app.selectbox(key="lab_study_metric").set_value("accuracy").run()
    assert not app.exception
    assert "lab_result" not in app.session_state
    assert len(app.error) >= 1
    assert len(app.get("download_button")) == 0


def test_lab_cache_refuses_a_foreign_engine_fingerprint():
    from ui.laboratory import cached_lab_experiment

    with pytest.raises(ValueError, match="versión del motor"):
        cached_lab_experiment("future", 42, .25, "motor-ajeno")


@pytest.fixture
def limited_study():
    """Un resultado real; las otras entradas son errores explícitos de fixture.

    No se ejecuta un estudio de 90 combinaciones para probar un botón de carga.
    """
    from data_crime_scene.study import _manifest, planned_configs, validate_study

    study = {**_manifest(), "entries": []}
    for config in planned_configs():
        entry = {"config": config, "seconds": 0.0}
        if config["case_id"] == "future" and config["seed"] == 42 and config["level"] == .25:
            entry.update(status="ok", result=run_lab_experiment("future", 42, .25))
        else:
            entry.update(status="error", error={"type": "FixtureNotExecuted", "message": "Ejecución omitida deliberadamente solo en este fixture de interfaz."})
        study["entries"].append(entry)
    validate_study(study)
    return study


def test_loading_study_preserves_provenance_errors_points_and_export(limited_study, tmp_path, monkeypatch):
    import ui.laboratory as interface

    path = tmp_path / "study.json"
    path.write_text(json.dumps(limited_study), encoding="utf-8")
    monkeypatch.setattr(interface, "PROJECT", tmp_path)
    downloads = {}
    original = st.download_button

    def capture(*args, **kwargs):
        downloads[kwargs["key"]] = kwargs.get("data", args[1] if len(args) > 1 else None)
        return original(*args, **kwargs)

    monkeypatch.setattr(st, "download_button", capture)
    app = laboratory_app()
    app.text_input(key="lab_study_path").set_value("study.json").run()
    app.button(key="lab_load_study").click().run()
    assert not app.exception
    assert "lab_result" not in app.session_state
    assert app.session_state["lab_study_source"] == str(path)
    assert app.session_state["lab_study"] == limited_study
    assert json.loads(downloads["lab_download_study"]) == limited_study
    assert len(app.get("plotly_chart")) == 2
    assert any("89 errores" in error.value for error in app.error)
    assert any("calculados anteriormente" in item.value for item in app.markdown)
    observed_result = next(entry["result"] for entry in limited_study["entries"] if entry["status"] == "ok")
    rows_table = next(frame.value for frame in app.dataframe if "balanced_accuracy" in frame.value.columns)
    assert len(rows_table) == 3
    assert sorted(rows_table["balanced_accuracy"].tolist()) == sorted(value["metrics"]["balanced_accuracy"] for value in observed_result["variants"].values())
    app.number_input(key="lab_seed_input").set_value(7).run()
    assert app.session_state["lab_study"] == limited_study
    assert "lab_result" not in app.session_state
    app.text_input(key="lab_study_path").set_value("otro.json").run()
    assert "lab_study" not in app.session_state
    assert len(app.get("download_button")) == 0


def test_study_with_foreign_provenance_is_rejected(limited_study, tmp_path, monkeypatch):
    import ui.laboratory as interface

    broken = deepcopy(limited_study)
    broken["engine_fingerprint"] = "motor-ajeno"
    (tmp_path / "study.json").write_text(json.dumps(broken), encoding="utf-8")
    monkeypatch.setattr(interface, "PROJECT", tmp_path)
    app = laboratory_app()
    app.text_input(key="lab_study_path").set_value("study.json").run()
    app.button(key="lab_load_study").click().run()
    assert not app.exception
    assert "lab_study" not in app.session_state
    assert len(app.error) >= 1
    assert len(app.get("download_button")) == 0


def test_distribution_chart_has_one_point_per_seed_variant(limited_study):
    from data_crime_scene.study import study_rows
    from ui.laboratory import distribution_chart

    rows = study_rows(limited_study, "future")
    chart = distribution_chart(rows, "future", "balanced_accuracy", "internal")
    assert sum(len(group) for trace in chart.data for group in trace.y) == len(rows) == 3
    expected = sorted(row["balanced_accuracy"] for row in rows)
    assert sorted(value for trace in chart.data for group in trace.y for value in group) == expected
    assert all(text == "Semilla 42" for trace in chart.data for group in trace.text for text in group)


def test_chart_quartiles_match_tables_using_ten_uneven_seed_scores():
    from ui.laboratory import distribution_chart, differences_chart, differences_summary, summary_table

    scores = [0, .01, .02, .03, .05, .08, .13, .21, .34, .55]
    rows = [{"seed": seed, "level": .25, "variant": "correct", "evaluation": "internal", "balanced_accuracy": value} for seed, value in enumerate(scores)]
    chart = distribution_chart(rows, "future", "balanced_accuracy", "internal")
    table = summary_table(rows, "balanced_accuracy", "future")
    delta_rows = [{"seed": seed, "level": .25, "comparison": "Posterior − legítimas", "evaluation": "internal", "delta": value - .2} for seed, value in enumerate(scores)]
    delta_chart = differences_chart(delta_rows, "future")
    delta_table = differences_summary(delta_rows)
    for figure, summary, original in ((chart, table, scores), (delta_chart, delta_table, [value - .2 for value in scores])):
        trace = figure.data[0]
        assert trace.q1[0] == pytest.approx(summary.iloc[0]["Q1"])
        assert trace.median[0] == pytest.approx(summary.iloc[0]["Mediana"])
        assert trace.q3[0] == pytest.approx(summary.iloc[0]["Q3"])
        assert trace.lowerfence[0] == min(original)
        assert trace.upperfence[0] == max(original)
        assert list(trace.y[0]) == original
        assert len(trace.text[0]) == 10
    assert chart.data[0].q1[0] == pytest.approx(.0225)
    assert chart.data[0].q3[0] == pytest.approx(.19)
    # Plotly's default 'linear' would give Q1=.02 for this ten-value fixture.
    assert chart.data[0].q1[0] != .02


@pytest.mark.parametrize("mode", ["guided", "laboratory"])
def test_rejected_cached_payload_can_be_retried(mode, monkeypatch):
    """La defensa rechaza una entrada ajena y permite recalcular esa misma clave."""
    st.cache_data.clear()
    calls = []
    if mode == "guided":
        import data_crime_scene.experiments as engine

        original = engine.run_experiment

        def once_stale(case_id, seed):
            calls.append((case_id, seed))
            return original(case_id, 42 if len(calls) == 1 else seed)

        monkeypatch.setattr(engine, "run_experiment", once_stale)
        app = AppTest.from_file(str(APP), default_timeout=30).run()
        seed_key, run_key, result_key = "seed_input", "run_experiment", "result"
    else:
        import ui.laboratory as interface

        original = interface.run_lab_experiment

        def once_stale(case_id, seed, level):
            calls.append((case_id, seed, level))
            return original(case_id, 42 if len(calls) == 1 else seed, level)

        monkeypatch.setattr(interface, "run_lab_experiment", once_stale)
        app = laboratory_app()
        seed_key, run_key, result_key = "lab_seed_input", "lab_run", "lab_result"
    try:
        app.number_input(key=seed_key).set_value(7).run()
        app.button(key=run_key).click().run()
        assert not app.exception
        assert result_key not in app.session_state
        assert len(app.error) >= 1
        app.button(key=run_key).click().run()
        assert not app.exception
        assert result_key in app.session_state
        result = app.session_state[result_key]
        assert (result.seed if mode == "guided" else result["config"]["seed"]) == 7
        assert len(calls) == 2
    finally:
        st.cache_data.clear()
