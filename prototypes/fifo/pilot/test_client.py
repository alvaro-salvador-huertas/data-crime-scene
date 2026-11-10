"""State transitions, uncertain sends, expiry, identity and private transport."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import io
import json
import threading
import urllib.error

import pytest

from data_crime_scene.experiments import run_experiment
from prototypes.fifo.pilot.client import Client, ServiceError, Session, decode_result


def job(state="queued", case="future", seed=42, jid="job-1", **extra):
    return dict(id=jid, case=case, seed=seed, state=state, position=0, **extra)


class Scripted:
    def __init__(self, *replies):
        self.replies, self.calls = deque(replies), []

    def call(self, method, path, token=None, body=None):
        self.calls.append((method, path, body))
        reply = self.replies.popleft()
        if isinstance(reply, Exception):
            raise reply
        return json.dumps(reply) if isinstance(reply, dict) else reply


@pytest.fixture(scope="module")
def result():
    return run_experiment("future", 42).to_json()


def test_send_duplicate_and_pending_change_keep_the_submitted_config():
    client = Scripted({"token": "private"}, job(), job(duplicate=True))
    session = Session(client)
    session.submit("future", 42)
    assert session.pending
    session.submit("groups", 7)
    assert session.notice == "pending_configuration" and session.job["seed"] == 42
    assert len(client.calls) == 2
    session.submit("future", 42)
    assert session.notice == "duplicate" and session.job["id"] == "job-1"
    assert not client.replies


def test_overlapping_reruns_create_only_one_backend_session():
    entered, release, second_started = threading.Event(), threading.Event(), threading.Event()
    extra_session = threading.Event()
    class ConcurrentClient:
        def __init__(self):
            self.sessions = 0
            self.tokens_used = []

        def call(self, method, path, token=None, body=None):
            if path == "/sessions":
                self.sessions += 1
                if self.sessions > 1:
                    extra_session.set()
                entered.set()
                assert release.wait(3)
                return json.dumps({"token": "private-"+str(self.sessions)})
            self.tokens_used.append(token)
            return json.dumps(job(duplicate=len(self.tokens_used) > 1))
    client = ConcurrentClient()
    session = Session(client)
    def second():
        second_started.set()
        session.submit("future", 42)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(session.submit, "future", 42)
        try:
            assert entered.wait(1)
            other = pool.submit(second)
            assert second_started.wait(1)
            assert not extra_session.wait(.1), "overlapping reruns created a second backend session"
        finally:
            release.set()
        first.result()
        other.result()
    assert client.sessions == 1
    assert client.tokens_used == ["private-1", "private-1"]
    assert session.job["id"] == "job-1" and session.notice == "duplicate"


def test_pending_configuration_notice_clears_on_completion(result):
    client = Scripted({"token": "private"}, job(), job("succeeded"), result)
    session = Session(client)
    session.submit("future", 42)
    session.submit("future", 43)
    assert session.notice == "pending_configuration"
    session.poll()
    assert session.notice is None and session.result.seed == 42


def test_uncertain_post_is_reconciled_with_same_config_without_new_session():
    client = Scripted({"token": "private"}, ServiceError(0, "unavailable"), job(duplicate=True))
    session = Session(client)
    session.submit("future", 42)
    assert session.unconfirmed == {"case": "future", "seed": 42} and session.pending
    session.submit("future", 43)
    assert session.notice == "pending_configuration" and len(client.calls) == 2
    session.submit("future", 42)
    assert session.job["id"] == "job-1" and session.unconfirmed is None
    assert sum(path == "/sessions" for _, path, _ in client.calls) == 1


def test_explicit_full_queue_is_not_treated_as_an_accepted_job():
    session = Session(Scripted({"token": "private"}, ServiceError(429, "queue_full")))
    session.submit("future", 42)
    assert session.notice == "queue_full" and session.job is None
    assert not session.pending


def test_poll_and_download_validate_identity_and_cache_only_the_owned_result(result):
    client = Scripted({"token": "private"}, job(), job("running"), job("succeeded"), result,
                      job("succeeded"), ServiceError(404, "expired"))
    session = Session(client)
    session.submit("future", 42)
    session.poll()
    assert session.pending and session.raw is None
    session.poll()
    assert not session.pending and session.result.seed == 42
    assert session.raw == result and session.result.to_json() == result
    session.poll()
    assert len([p for _, p, _ in client.calls if p.endswith("/result")]) == 1
    session.poll()
    assert session.job["state"] == "expired" and session.raw is session.result is None
    session.poll()
    assert not client.replies
    assert sum(method == "POST" for method, _, _ in client.calls) == 2


@pytest.mark.parametrize("response", [job("succeeded", seed=43), job("succeeded", jid="foreign")])
def test_job_identity_mismatch_is_not_displayed(response):
    session = Session(Scripted({"token": "private"}, job(), response))
    session.submit("future", 42)
    session.poll()
    assert session.notice == "invalid_result" and session.result is None


def test_result_identity_and_metrics_are_checked(result):
    with pytest.raises(ValueError):
        decode_result(result, "groups", 42)
    with pytest.raises(ValueError):
        decode_result(result, "future", 43)
    tampered = json.loads(result)
    tampered["variants"]["incorrect"]["metrics"]["accuracy"] = 0
    with pytest.raises(ValueError):
        decode_result(json.dumps(tampered), "future", 42)


def test_session_loss_clears_result_and_never_reenqueues():
    client = Scripted({"token": "private"}, job(), ServiceError(401, "session_lost"))
    session = Session(client)
    session.submit("future", 42)
    session.poll()
    assert session.token is None and session.job["state"] == "session_lost"
    assert not session.pending
    session.poll()
    assert not client.replies and len(client.calls) == 3


def test_failed_work_remains_idempotent():
    client = Scripted({"token": "private"}, job(), job("failed"), job("failed", duplicate=True))
    session = Session(client)
    session.submit("future", 42)
    session.poll()
    session.submit("future", 42)
    assert session.job["state"] == "failed" and session.notice == "duplicate"
    assert session.raw is session.result is None


@pytest.mark.parametrize("url", ["https://127.0.0.1:8877", "http://example.com:8877", "http://127.0.0.1:8877/?token=x"])
def test_client_only_accepts_clean_loopback_urls(url):
    with pytest.raises(ValueError):
        Client(url)


def test_authorization_is_header_only_and_error_does_not_reflect_token(monkeypatch):
    observed = []
    class Opener:
        def open(self, request, timeout):
            observed.append(request)
            raise urllib.error.HTTPError(request.full_url, 429, "full", {},
                                         io.BytesIO(b'{"error":"private-token-reflected"}'))
    monkeypatch.setattr("urllib.request.build_opener", lambda *_: Opener())
    with pytest.raises(ServiceError) as error:
        Client("http://127.0.0.1:8877").call("GET", "/jobs/job-1", "private-token-reflected")
    assert observed[0].get_header("Authorization") == "Bearer private-token-reflected"
    assert "private-token-reflected" not in observed[0].full_url
    assert str(error.value) == "capacity"
