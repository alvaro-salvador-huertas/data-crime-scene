"""Admission controls for the public UI, independent of experiment semantics.

These are process-local budgets, not authentication or network/DDoS protection.
No visitor identifiers, IP addresses or experiment results are stored here.
"""

from collections import deque
from contextlib import contextmanager
from threading import Lock
from time import monotonic

import streamlit as st


MAX_NOTES_CHARS = 2000
SESSION_INTERVAL_SECONDS = 3
WINDOW_SECONDS = 60
MAX_ACTIONS_PER_WINDOW = 12
SESSION_BUDGET_KEY = "public_next_action_at"
SHARED_SESSION_BUDGET_KEY = "public_shared_session_budget"


class PublicLimitError(Exception):
    """An action was refused before it could change investigation state."""


class PublicBudget:
    """One worker and a bounded rolling budget shared across public sessions."""

    def __init__(self, *, clock=monotonic):
        self._clock = clock
        self._lock = Lock()
        self._active = False
        self._admitted = deque()

    @contextmanager
    def action(self, session):
        # Opt-in Guided workers cannot use Streamlit's thread-local proxy.
        # All modes use this same plain dict once attached to their UI session.
        session = session.get(SHARED_SESSION_BUDGET_KEY, session)
        with self._lock:
            now = self._clock()
            while self._admitted and self._admitted[0] <= now - WINDOW_SECONDS:
                self._admitted.popleft()
            if self._active:
                raise PublicLimitError("Hay un cálculo en curso. Espera a que termine e inténtalo de nuevo.")
            if now < session.get(SESSION_BUDGET_KEY, 0):
                raise PublicLimitError("Espera 3 segundos entre solicitudes de cálculo. Tu progreso se conserva.")
            if len(self._admitted) >= MAX_ACTIONS_PER_WINDOW:
                raise PublicLimitError("La demo ha alcanzado su presupuesto compartido. Espera un minuto e inténtalo de nuevo.")
            # Failed work also consumes its admission. No waiting queue or retry.
            session[SESSION_BUDGET_KEY] = now + SESSION_INTERVAL_SECONDS
            self._admitted.append(now)
            self._active = True
        try:
            yield
        finally:
            with self._lock:
                self._active = False


@st.cache_resource(show_spinner=False)
def get_public_budget():
    """Streamlit shares this thread-safe resource across sessions and reruns."""
    return PublicBudget()


@contextmanager
def public_action(public_demo):
    if public_demo:
        with get_public_budget().action(st.session_state):
            yield
    else:
        yield


def validate_public_notes(notes, public_demo):
    """Server-side guard before saving a draft or confirming a public answer."""
    if public_demo and (not isinstance(notes, str) or len(notes) > MAX_NOTES_CHARS):
        raise PublicLimitError(f"Las notas admiten como máximo {MAX_NOTES_CHARS} caracteres. Acórtalas antes de confirmar.")
