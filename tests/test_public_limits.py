"""Public resource controls: real admission, deterministic time, real app state."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
from threading import Barrier, Event

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from data_crime_scene.detective import export_investigation
from test_detective_app import choose, current_case, record, widget
from ui import public_limits as limits

ROOT = Path(__file__).resolve().parents[1]


def test_cached_resource_is_shared_within_process():
    limits.get_public_budget.clear()
    try:
        assert limits.get_public_budget() is limits.get_public_budget()
    finally:
        limits.get_public_budget.clear()


@pytest.fixture
def budget(monkeypatch):
    time = [100.0]
    controller = limits.PublicBudget(clock=lambda: time[0])
    monkeypatch.setattr(limits, "get_public_budget", lambda: controller)
    return controller, time


def open_app(mode="Recorrido guiado", *, public=True):
    path = ROOT / ("demo/streamlit_app.py" if public else "app.py")
    app = AppTest.from_file(str(path), default_timeout=30).run()
    app.radio(key="mode_selector").set_value(mode).run()
    assert not app.exception
    return app


def open_detective():
    app = open_app("Modo Detective")
    app.selectbox(key="detective_case_selector").set_value("d01").run()
    app.button(key="detective_open").click().run()
    assert not app.exception
    return app


def test_threaded_admission_allows_one_worker_without_queue():
    budget = limits.PublicBudget(clock=lambda: 100)
    start, release, winner = Barrier(8), Event(), Event()

    def attempt():
        start.wait(timeout=5)
        try:
            with budget.action({}):
                winner.set()
                if not release.wait(timeout=5):
                    raise AssertionError("worker was not released")
                return "admitted"
        except limits.PublicLimitError:
            return "denied"

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(attempt) for _ in range(8)]
        try:
            assert winner.wait(timeout=5)
            # Wait for all seven refusals while the admitted worker is held.
            from concurrent.futures import as_completed
            results = []
            for future in as_completed(futures, timeout=5):
                results.append(future.result())
                if len(results) == 7:
                    break
            assert results == ["denied"] * 7
        finally:
            release.set()
        assert [f.result() for f in futures].count("admitted") == 1


def test_rolling_budget_is_shared_bounded_and_recovers_at_boundary(budget):
    controller, time = budget
    for _ in range(limits.MAX_ACTIONS_PER_WINDOW):
        with controller.action({}):
            pass
    for _ in range(30):
        with pytest.raises(limits.PublicLimitError, match="compartido"):
            with controller.action({}):
                pytest.fail("fresh sessions must not bypass the process budget")
    time[0] += 59.999
    with pytest.raises(limits.PublicLimitError):
        with controller.action({}):
            pytest.fail("window has not expired")
    time[0] += .001
    with controller.action({}):
        pass
    assert len(controller._admitted) == 1


def test_session_interval_and_denials_do_not_consume_admissions(budget):
    controller, time = budget
    session = {}
    with controller.action(session):
        pass
    before = deepcopy(session)
    for offset in (0, 2.999):
        time[0] = 100 + offset
        with pytest.raises(limits.PublicLimitError, match="3 segundos"):
            with controller.action(session):
                pytest.fail("too early")
    assert session == before and len(controller._admitted) == 1
    time[0] = 103
    with controller.action(session):
        pass


@pytest.mark.parametrize("exception", [ValueError, KeyboardInterrupt])
def test_exception_releases_worker_but_still_charges_budget(exception, budget):
    controller, _ = budget
    with pytest.raises(exception):
        with controller.action({}):
            raise exception("test failure")
    with controller.action({}):
        pass
    assert len(controller._admitted) == 2


@pytest.mark.parametrize("value", ["", "á" * 2000, "🔎" * 2000])
def test_public_notes_valid_boundary(value):
    limits.validate_public_notes(value, True)


@pytest.mark.parametrize("value", ["a" * 2001, "🔎" * 2001, 2000, None])
def test_public_notes_reject_invalid_values(value):
    with pytest.raises(limits.PublicLimitError, match="2000"):
        limits.validate_public_notes(value, True)


def test_local_action_does_not_consult_public_resource(monkeypatch):
    def forbidden():
        pytest.fail("local workflow must not use a public resource")
    monkeypatch.setattr(limits, "get_public_budget", forbidden)
    with limits.public_action(False):
        limits.validate_public_notes("a" * 2001, False)


@pytest.mark.parametrize("mode,key,result_key,module_name,operation", [
    ("Recorrido guiado", "run_experiment", "result", "app", "cached_experiment"),
    ("Laboratorio", "lab_run", "lab_result", "ui.laboratory", "cached_lab_experiment"),
])
def test_denied_repeat_preserves_real_result_without_calling_work(
        mode, key, result_key, module_name, operation, budget, monkeypatch):
    import importlib
    app = open_app(mode)
    app.button(key=key).click().run()
    assert not app.exception and result_key in app.session_state
    before = deepcopy(app.session_state[result_key])
    module = importlib.import_module(module_name)
    def forbidden(*args, **kwargs):
        pytest.fail("refused work must not call cache or experiment")
    monkeypatch.setattr(module, operation, forbidden)
    app.button(key=key).click().run()
    assert not app.exception
    assert any("3 segundos" in item.value for item in app.warning)
    after = app.session_state[result_key]
    assert (after.to_dict() if hasattr(after, "to_dict") else after) == (
        before.to_dict() if hasattr(before, "to_dict") else before)


def test_all_modes_and_new_sessions_share_process_budget(budget):
    controller, _ = budget
    for _ in range(limits.MAX_ACTIONS_PER_WINDOW):
        with controller.action({}):
            pass
    for mode, button, result in (("Recorrido guiado", "run_experiment", "result"),
                                 ("Laboratorio", "lab_run", "lab_result"),
                                 ("Modo Detective", "detective_open", None)):
        app = open_app(mode)
        app.button(key=button).click().run()
        assert not app.exception
        assert any("presupuesto compartido" in item.value for item in app.warning)
        if result:
            assert result not in app.session_state
        else:
            assert app.session_state["detective_cases"] == {}


def test_detective_reset_seed_mode_and_rerun_keep_session_interval(budget):
    app = open_detective()
    deadline = app.session_state[limits.SESSION_BUDGET_KEY]
    app.run()
    app.button(key="detective_reset").click().run()
    app.number_input(key="detective_session_seed").set_value(7).run()
    app.radio(key="mode_selector").set_value("Laboratorio").run()
    app.button(key="lab_run").click().run()
    assert "lab_result" not in app.session_state
    assert app.session_state[limits.SESSION_BUDGET_KEY] == deadline
    assert any("3 segundos" in item.value for item in app.warning)
    assert not app.exception


def test_intervention_denial_preserves_answer_and_later_runs_once(budget, monkeypatch):
    from data_crime_scene import detective
    _, time = budget
    app = open_detective()
    choose(app, "contaminated", ["timing"], "remove_feature", "Evidence retained")
    app.button(key="detective_confirm").click().run()
    before = deepcopy(record(app))
    calls = []
    original = detective.run_experiment
    def tracked(*args):
        calls.append(args)
        return original(*args)
    monkeypatch.setattr(detective, "run_experiment", tracked)
    app.button(key="detective_intervene").click().run()
    assert record(app) == before and calls == [] and not app.exception
    time[0] += 3
    app.button(key="detective_intervene").click().run()
    assert len(calls) == 1 and record(app)["intervention"]["performed"]
    after = deepcopy(record(app))
    app.button(key="detective_intervene").click().run()
    assert record(app) == after and len(calls) == 1
    assert not app.exception


def test_notes_widget_and_server_reject_oversize_without_mutation(budget, monkeypatch):
    import ui.detective as interface
    app = open_detective()
    choose(app, "contaminated", ["timing"], "remove_feature", "previous draft")
    notes_widget = widget(app, "text_area", "_notes")
    assert notes_widget.proto.max_chars == limits.MAX_NOTES_CHARS
    before_record = deepcopy(record(app))
    before_drafts = deepcopy(app.session_state["detective_drafts"])
    original = st.text_area
    # A hostile client can bypass an HTML maxlength. Supply that server value.
    def manipulated(*args, **kwargs):
        original(*args, **kwargs)
        return "🔎" * 2001
    monkeypatch.setattr(st, "text_area", manipulated)
    def forbidden(*args, **kwargs):
        pytest.fail("oversized notes must not reach confirmation")
    monkeypatch.setattr(interface, "confirm_answer", forbidden)
    app.button(key="detective_confirm").click().run()
    assert not app.exception
    assert any("2000 caracteres" in item.value for item in app.error)
    assert record(app) == before_record
    assert app.session_state["detective_drafts"] == before_drafts
    report = export_investigation(app.session_state["detective_session"], current_case(app))
    assert "🔎" * 2001 not in report


def test_public_maximum_notes_survive_confirmation_and_export(budget):
    app = open_detective()
    notes = "á" * limits.MAX_NOTES_CHARS
    choose(app, "contaminated", ["timing"], "remove_feature", notes)
    app.button(key="detective_confirm").click().run()
    assert not app.exception
    assert record(app)["answers"]["initial"]["notes"] == notes
    payload = json.loads(export_investigation(app.session_state["detective_session"], current_case(app)))
    assert payload["investigation"]["answers"]["initial"]["notes"] == notes


def test_local_app_works_while_public_budget_is_exhausted(budget):
    controller, _ = budget
    for _ in range(limits.MAX_ACTIONS_PER_WINDOW):
        with controller.action({}):
            pass
    app = open_app(public=False)
    app.button(key="run_experiment").click().run()
    assert not app.exception and "result" in app.session_state
    assert limits.SESSION_BUDGET_KEY not in app.session_state


def test_public_study_load_respects_budget(budget, monkeypatch, tmp_path):
    from ui import laboratory
    controller, _ = budget
    for _ in range(limits.MAX_ACTIONS_PER_WINDOW):
        with controller.action({}):
            pass
    path = tmp_path / "study.json"
    path.write_text("{}")
    monkeypatch.setattr(laboratory, "PUBLIC_STUDY", path)
    def forbidden(*args):
        pytest.fail("refused load must not read or validate a study")
    monkeypatch.setattr(laboratory, "load_study", forbidden)
    app = open_app("Laboratorio")
    app.button(key="lab_load_public_study").click().run()
    assert not app.exception
    assert any("presupuesto compartido" in item.value for item in app.warning)
    assert "lab_study" not in app.session_state
