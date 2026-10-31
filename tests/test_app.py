"""Comprobaciones funcionales con el simulador oficial; no son revisión visual."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.mark.parametrize("case_id", ["future", "groups", "selection"])
def test_every_case_can_be_investigated_and_exported(case_id, monkeypatch):
    import streamlit as st

    downloads = []
    original_download = st.download_button

    def capture_download(*args, **kwargs):
        downloads.append(kwargs["data"])
        return original_download(*args, **kwargs)

    monkeypatch.setattr(st, "download_button", capture_download)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.selectbox(key="case_selector").set_value(case_id).run()
    assert not app.exception
    assert len(app.metric) == 0
    app.button(key="run_experiment").click().run()
    assert not app.exception
    result = app.session_state["result"]
    assert result.case_id == case_id
    assert len(app.metric) == 3
    assert app.metric[0].value == f"{result.variants['incorrect'].metrics['accuracy']:.1%}"
    assert not app.session_state["revealed"]
    assert all("Procedencia" not in frame.value.columns for frame in app.dataframe)
    assert downloads == []
    app.button(key="reveal_answer").click().run()
    assert not app.exception
    assert app.session_state["revealed"]
    assert json.loads(result.to_json()) == result.to_dict()
    assert json.loads(downloads[-1]) == result.to_dict()
    # El botón utiliza directamente el mismo objeto, sin reconstruir las métricas.
    assert len(app.get("download_button")) == 1


def test_case_and_seed_changes_hide_previous_results_and_solution():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.button(key="run_experiment").click().run()
    first = app.session_state["result"].to_dict()
    app.button(key="reveal_answer").click().run()
    app.number_input(key="seed_input").set_value(7).run()
    assert not app.exception
    assert "result" not in app.session_state
    assert not app.session_state["revealed"]
    assert len(app.metric) == 0
    app.button(key="run_experiment").click().run()
    second = app.session_state["result"].to_dict()
    assert second["seed"] == 7
    assert second != first
    app.selectbox(key="case_selector").set_value("groups").run()
    assert "result" not in app.session_state
    app.button(key="run_experiment").click().run()
    assert app.session_state["result"].case_id == "groups"
    assert app.session_state["result"].seed == 7
    assert not app.exception


def test_interactions_reuse_training_result(monkeypatch):
    import streamlit as st
    import data_crime_scene.experiments as experiments

    st.cache_data.clear()
    original = experiments.run_experiment
    calls = []

    def tracked(case_id, seed):
        calls.append((case_id, seed))
        return original(case_id, seed)

    monkeypatch.setattr(experiments, "run_experiment", tracked)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.button(key="run_experiment").click().run()
    hypothesis = app.radio(key="hypothesis_future_42")
    hypothesis.set_value(hypothesis.options[0]).run()
    app.button(key="reveal_answer").click().run()
    app.button(key="run_experiment").click().run()
    assert not app.exception
    assert calls == [("future", 42)]
    app.number_input(key="seed_input").set_value(2026).run()
    app.button(key="run_experiment").click().run()
    assert calls == [("future", 42), ("future", 2026)]
