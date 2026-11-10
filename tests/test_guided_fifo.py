"""Opt-in integration: original gate shared across all modes, no HTTP service."""
from contextlib import contextmanager
import json
from pathlib import Path
from threading import Event
import time

import pytest
from streamlit.testing.v1 import AppTest

from data_crime_scene.experiments import run_experiment
from ui import guided_fifo as fifo
from ui import public_limits as limits

ENTRY = Path(__file__).resolve().parents[1]/"demo/streamlit_app.py"


class Result:
    def __init__(self, case, seed):
        self.case, self.seed = case, seed

    def to_json(self):
        return json.dumps({"case_id": self.case, "seed": self.seed})


def wait_state(scheduler, token, jid, states=("succeeded",)):
    deadline = time.monotonic()+3
    while time.monotonic() < deadline:
        value = scheduler.get(token, jid)
        if value["state"] in states:
            return value
        time.sleep(.005)
    raise AssertionError(value)


@contextmanager
def scheduler_fixture(engine=Result):
    clock = [100.0]
    budget = limits.PublicBudget(clock=lambda: clock[0])
    scheduler = fifo.SharedScheduler(budget, engine=engine)
    try:
        yield scheduler, budget, clock
    finally:
        scheduler.close()


@pytest.mark.parametrize("setting", [None, "0"])
def test_default_and_explicit_off_use_original_rejection(monkeypatch, setting):
    if setting is None:
        monkeypatch.delenv("DCS_GUIDED_FIFO", raising=False)
    else:
        monkeypatch.setenv("DCS_GUIDED_FIFO", setting)
    def forbidden():
        pytest.fail("FIFO initialized with option disabled")
    monkeypatch.setattr(fifo, "get_guided_scheduler", forbidden)
    app = AppTest.from_file(str(ENTRY), default_timeout=30).run()
    assert not app.exception and "guided_fifo_session" not in app.session_state
    budget = limits.get_public_budget()
    with budget.action({}):
        app.button(key="run_experiment").click().run()
    assert not app.exception
    assert any("Hay un cálculo en curso" in w.value for w in app.warning)
    assert "result" not in app.session_state


def test_local_entrypoint_ignores_public_fifo_option(monkeypatch):
    monkeypatch.setenv("DCS_GUIDED_FIFO", "1")
    def forbidden():
        pytest.fail("Local app initialized the public FIFO")
    monkeypatch.setattr(fifo, "get_guided_scheduler", forbidden)
    app = AppTest.from_file(str(ENTRY.parents[1]/"app.py"), default_timeout=30).run()
    assert not app.exception and "guided_fifo_session" not in app.session_state
    assert app.button(key="run_experiment")


def test_resource_is_one_queue_using_original_global_budget(monkeypatch):
    fifo.get_guided_scheduler.clear()
    budget = limits.PublicBudget()
    monkeypatch.setattr(fifo, "get_public_budget", lambda: budget)
    scheduler = fifo.get_guided_scheduler()
    try:
        assert fifo.get_guided_scheduler() is scheduler and scheduler.budget is budget
        a, b = fifo.InProcessClient(scheduler, {}), fifo.InProcessClient(scheduler, {})
        assert a.scheduler is b.scheduler
    finally:
        scheduler.close()
        fifo.get_guided_scheduler.clear()


def test_transport_uses_direct_calls_and_never_starts_http(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("HTTP was used by the production adapter")
    monkeypatch.setattr("prototypes.fifo.service.make_server", forbidden)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", forbidden)
    with scheduler_fixture() as (scheduler, _, _):
        client = fifo.InProcessClient(scheduler, {})
        token = json.loads(client.call("POST", "/sessions"))["token"]
        job = json.loads(client.call("POST", "/jobs", token, {"case": "future", "seed": 7}))
        wait_state(scheduler, token, job["id"])
        assert json.loads(client.call("GET", "/jobs/"+job["id"]+"/result", token))["seed"] == 7


@pytest.mark.parametrize("mode,button", [("Laboratorio", "lab_run"), ("Modo Detective", "detective_open")])
def test_guided_active_prevents_legacy_mode_admission_in_real_ui(monkeypatch, mode, button):
    entered, release = Event(), Event()
    def engine(case, seed):
        entered.set()
        assert release.wait(30)
        return Result(case, seed)
    monkeypatch.setenv("DCS_GUIDED_FIFO", "1")
    with scheduler_fixture(engine) as (scheduler, budget, _):
        monkeypatch.setattr(limits, "get_public_budget", lambda: budget)
        monkeypatch.setattr(fifo, "get_guided_scheduler", lambda: scheduler)
        token = scheduler.new_session()
        scheduler.submit(token, "future", 7)
        try:
            assert entered.wait(1)
            app = AppTest.from_file(str(ENTRY), default_timeout=30).run()
            app.radio(key="mode_selector").set_value(mode).run()
            if mode == "Modo Detective":
                app.selectbox(key="detective_case_selector").set_value("d01").run()
            app.button(key=button).click().run()
            assert not app.exception
            assert any("Hay un cálculo en curso" in w.value for w in app.warning)
            assert len(budget._admitted) == 1
        finally:
            release.set()


def test_legacy_shared_gate_makes_guided_wait_without_starting():
    with scheduler_fixture() as (scheduler, budget, _):
        token = scheduler.new_session()
        with budget.action({}):
            job, _ = scheduler.submit(token, "future", 7)
            state = wait_state(scheduler, token, job["id"], ("queued",))
            # Wait until the worker has actually tried the shared original gate.
            deadline = time.monotonic()+1
            while state.get("wait_reason") != "other_mode" and time.monotonic() < deadline:
                time.sleep(.005)
                state = scheduler.get(token, job["id"])
            assert state["wait_reason"] == "other_mode" and state["started"] is None
            assert len(budget._admitted) == 1
        wait_state(scheduler, token, job["id"])
        assert len(budget._admitted) == 2


def test_legacy_consumption_exhausts_guided_shared_window_and_recovers():
    with scheduler_fixture() as (scheduler, budget, clock):
        for _ in range(12):
            with budget.action({}):
                pass
        token = scheduler.new_session()
        job, _ = scheduler.submit(token, "groups", 42)
        state = wait_state(scheduler, token, job["id"], ("waiting_budget",))
        assert state["started"] is None and len(budget._admitted) == 12
        clock[0] += 60
        with scheduler.cv:
            scheduler.cv.notify_all()
        wait_state(scheduler, token, job["id"])
        assert len(budget._admitted) == 1


def test_guided_consumption_exhausts_legacy_shared_window():
    with scheduler_fixture() as (scheduler, budget, _):
        for i in range(12):
            token = scheduler.new_session()
            job, _ = scheduler.submit(token, "future", i)
            wait_state(scheduler, token, job["id"])
        with pytest.raises(limits.PublicLimitError, match="compartido"):
            with budget.action({}):
                pytest.fail("Legacy mode bypassed Guided's budget")


def test_three_second_session_interval_is_shared_both_directions():
    with scheduler_fixture() as (scheduler, budget, clock):
        ui_session = {}
        shared = fifo.attach_session_budget(ui_session)
        with budget.action(ui_session):
            pass
        assert shared[limits.SESSION_BUDGET_KEY] == 103
        client = fifo.InProcessClient(scheduler, shared)
        token = json.loads(client.call("POST", "/sessions"))["token"]
        job, _ = scheduler.submit(token, "future", 7)
        state = wait_state(scheduler, token, job["id"], ("waiting_budget",))
        assert state["wait_reason"] == "session_interval"
        clock[0] += 3
        with scheduler.cv:
            scheduler.cv.notify_all()
        wait_state(scheduler, token, job["id"])
        with pytest.raises(limits.PublicLimitError, match="3 segundos"):
            with budget.action(ui_session):
                pytest.fail("Changing mode bypassed per-session interval")


def test_enabled_real_guided_result_is_validated_per_sent_config(monkeypatch):
    monkeypatch.setenv("DCS_GUIDED_FIFO", "1")
    with scheduler_fixture(run_experiment) as (scheduler, _, _):
        session = fifo.Session(fifo.InProcessClient(scheduler, {}))
        session.submit("future", 7)
        wait_state(scheduler, session.token, session.job["id"])
        session.poll()
        assert session.result.seed == 7 and session.result.case_id == "future"
        assert session.result.to_json() == session.raw
        other = fifo.Session(fifo.InProcessClient(scheduler, {}))
        with pytest.raises(fifo.ServiceError) as error:
            other.client.call("GET", "/jobs/"+session.job["id"], json.loads(other.client.call("POST", "/sessions"))["token"])
        assert error.value.status == 404
