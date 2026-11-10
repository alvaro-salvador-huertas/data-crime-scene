"""In-process adapter of the preserved, tested FIFO and per-session controller.

No HTTP listener is created. The queue and the legacy UI share one PublicBudget.
"""
import atexit
import json

import streamlit as st

from data_crime_scene import experiments
from prototypes.fifo.service import Scheduler, Refusal
from prototypes.fifo.pilot.client import Session, ServiceError
from ui.public_limits import (get_public_budget, SESSION_BUDGET_KEY,
                              SHARED_SESSION_BUDGET_KEY)


def attach_session_budget(session):
    """Plain session-owned state usable by both UI threads and the FIFO worker."""
    if SHARED_SESSION_BUDGET_KEY not in session:
        session[SHARED_SESSION_BUDGET_KEY] = {
            SESSION_BUDGET_KEY: session.get(SESSION_BUDGET_KEY, 0)}
    return session[SHARED_SESSION_BUDGET_KEY]


class SharedScheduler(Scheduler):
    def __init__(self, budget, *, engine=experiments.run_experiment, **kwargs):
        # The base starts an idle worker. No job can be submitted until this
        # constructor returns, so replace its unused budget under the same lock.
        super().__init__(engine=engine, clock=budget._clock, **kwargs)
        with self.cv:
            self.budget = budget

    def _view(self, job):
        view = super()._view(job)
        if view["state"] == "waiting_budget":
            with self.budget._lock:
                if self.budget._active:
                    # A legacy mode owns the global executor. Keep the original
                    # controller's pending states, but distinguish this from quota.
                    view.update(state="queued", wait_reason="other_mode")
                elif self.clock() < self.sessions[job["owner"]]["execution"].get(SESSION_BUDGET_KEY, 0):
                    view["wait_reason"] = "session_interval"
        return view


@st.cache_resource(show_spinner=False)
def get_guided_scheduler():
    """One queue/worker per process, never per browser or Streamlit session."""
    scheduler = SharedScheduler(get_public_budget())
    atexit.register(scheduler.close)
    return scheduler


class InProcessClient:
    """The pilot controller's transport contract, implemented as direct calls."""
    def __init__(self, scheduler, session_budget):
        self.scheduler, self.session_budget = scheduler, session_budget

    def call(self, method, path, token=None, body=None):
        try:
            if method == "POST" and path == "/sessions":
                token = self.scheduler.new_session()
                with self.scheduler.cv:
                    self.scheduler.sessions[token]["execution"] = self.session_budget
                return json.dumps({"token": token})
            if method == "POST" and path == "/jobs":
                job, duplicate = self.scheduler.submit(token, body["case"], body["seed"])
                return json.dumps(job | {"duplicate": duplicate})
            parts = path.split("/")
            if method == "GET" and len(parts) in (3, 4) and parts[1] == "jobs":
                value = self.scheduler.get(token, parts[2], result=len(parts) == 4)
                return value if isinstance(value, str) else json.dumps(value)
            raise ServiceError(404, "expired")
        except Refusal as error:
            reason = {401: "session_lost", 404: "expired", 409: "not_ready"}.get(error.status, error.reason)
            raise ServiceError(error.status, reason) from None


def get_guided_session():
    """Token/state stay on the server; the inherited RLock serializes fast reruns."""
    if "guided_fifo_session" not in st.session_state:
        st.session_state.guided_fifo_session = Session(InProcessClient(
            get_guided_scheduler(), attach_session_budget(st.session_state)))
    return st.session_state.guided_fifo_session
