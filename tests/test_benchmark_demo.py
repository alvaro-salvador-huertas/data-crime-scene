"""Checks for benchmark safety and interpretation, without running the engine."""
from copy import deepcopy
import asyncio
import json
import signal
import time
from types import SimpleNamespace

import pytest

from scripts.benchmark_demo import descendants, local_url, summarize, verify_download
from scripts import benchmark_demo as benchmark


@pytest.mark.parametrize("url", ["https://example.com", "http://localhost:8501",
    "http://127.0.0.1:80", "http://127.0.0.1:8501/path", "http://127.0.0.1:8501?x=1",
    "http://user@127.0.0.1:8501", "https://127.0.0.1:8501"])
def test_rejects_nonowned_target_shapes(url):
    with pytest.raises(ValueError):
        local_url(url)


def test_accepts_explicit_loopback_port():
    assert local_url("http://127.0.0.1:8765/") == ("http://127.0.0.1:8765", 8765)


def report():
    return {"case_id": "future", "seed": 42, "variants": {"incorrect": {
        "y_true": [0, 0, 1, 1], "y_pred": [0, 1, 1, 1],
        "metrics": {"accuracy": .75, "balanced_accuracy": .75, "f1": .8},
        "confusion_matrix": [[1, 1], [0, 2]]}}}


def test_download_must_match_configuration_and_predictions():
    value = report()
    verify_download(value, "future", 42)
    for case, seed in [("groups", 42), ("future", 7)]:
        with pytest.raises(ValueError, match="different"):
            verify_download(value, case, seed)
    corrupted = deepcopy(value)
    corrupted["variants"]["incorrect"]["y_pred"][0] = 1
    with pytest.raises(ValueError, match="metrics"):
        verify_download(corrupted, "future", 42)


def test_limits_and_cache_responses_do_not_count_as_training_capacity():
    rows = [{"status": "success", "latency_seconds": n, "clicked": True} for n in [1, 3]]
    rows += [{"status": "limit", "latency_seconds": .1, "clicked": True},
             {"status": "timeout", "latency_seconds": 45, "clicked": True},
             {"status": "prepare_error", "clicked": False}]
    events = [{"event": "admitted"}, {"event": "engine_start"}, {"event": "admitted"},
              {"event": "denied", "reason": "busy"}]
    result = summarize(rows, events)
    assert result["attempts"] == 5 and result["clicked"] == 4
    assert result["successes"] == 2 and result["limited"] == 1 and result["timeouts"] == 1
    assert result["failures_excluding_limits"] == 2
    assert result["success_median_seconds"] == 2 and result["success_max_seconds"] == 3
    assert result["response_max_seconds"] == 45
    assert result["admitted"] == 2 and result["engine_calls"] == 1 and result["cache_hits_inferred"] == 1


def test_no_success_has_no_latency_estimate():
    result = summarize([{"status": "limit", "latency_seconds": .1}], [])
    assert result["success_median_seconds"] is None
    assert result["success_max_seconds"] is None


def test_unlaunched_sessions_are_incomplete_not_application_failures():
    result = summarize([{"status": "incomplete", "clicked": False}], [])
    assert result["attempts"] == 1 and result["clicked"] == 0
    assert result["incomplete"] == 1 and result["failures_excluding_limits"] == 0
    assert result["response_max_seconds"] is None


def test_server_tree_excludes_browser_sibling():
    rows = {1: (0, 0, 0), 2: (1, 0, 0), 3: (1, 0, 0), 4: (2, 0, 0), 5: (3, 0, 0)}
    assert descendants(rows, 2) == {2, 4}
    assert descendants(rows, 1) - descendants(rows, 2) - {1} == {3, 5}


@pytest.mark.parametrize("scenario", ["wave", "unconfirmed", "warm"])
def test_cancelled_trial_preserves_observations_and_cleans_up(monkeypatch, tmp_path, scenario):
    """Cancel real execute/gather after one result and another confirmed click.

    Browser and server I/O are controlled doubles; cancellation and trial cleanup
    run normally. No network, subprocess, or training is started by this test.
    """
    cleanup = []
    contexts = []
    process = SimpleNamespace(pid=123456789, returncode=None)

    def wait(timeout):
        assert process.returncode == -signal.SIGKILL
        cleanup.append("wait")
        return process.returncode

    process.poll = lambda: process.returncode
    process.wait = wait

    def popen(*args, **kwargs):
        process.log = kwargs["stdout"]
        return process

    def killpg(pid, sig):
        assert (pid, sig) == (process.pid, signal.SIGKILL)
        process.returncode = -sig
        cleanup.append("kill")

    class Monitor:
        def __init__(self, output, pid):
            assert pid == process.pid
            self.pressure, self.samples = None, []
            self.thread = SimpleNamespace(start=lambda: None)

        def close(self):
            cleanup.append("monitor_closed")

    class Socket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def setsockopt(self, *args):
            pass

        def bind(self, address):
            assert address == ("127.0.0.1", 8765)

    class Health:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(benchmark.subprocess, "Popen", popen)
    monkeypatch.setattr(benchmark.os, "killpg", killpg)
    monkeypatch.setattr(benchmark, "Monitor", Monitor)
    monkeypatch.setattr(benchmark, "socket", SimpleNamespace(socket=Socket,
                        SOL_SOCKET=benchmark.socket.SOL_SOCKET, SO_REUSEADDR=benchmark.socket.SO_REUSEADDR))
    monkeypatch.setattr(benchmark.urllib.request, "urlopen", lambda *a, **kw: Health())

    async def process_io(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(benchmark.asyncio, "to_thread", process_io)

    async def check():
        first_finished, second_waiting, unconfirmed = (asyncio.Event() for _ in range(3))
        blocked = asyncio.Event()

        class Value:
            async def json_value(self):
                return "success"

        class Locator:
            def __init__(self, index):
                self.index = index
                self.first = self

            async def click(self):
                if self.index == 2:
                    # Dispatch has begun, but the controller cannot confirm the click.
                    unconfirmed.set()
                    await blocked.wait()

            async def wait_for(self):
                pass

            async def inner_text(self):
                first_finished.set()
                return "75.0%"

        class Page:
            def __init__(self, index):
                self.index = index

            def get_by_role(self, *args, **kwargs):
                return Locator(self.index)

            def get_by_test_id(self, *args):
                return Locator(self.index)

            def get_by_text(self, *args, **kwargs):
                return Locator(self.index)

            async def evaluate(self, expression):
                return time.time()*1000

            async def wait_for_function(self, expression):
                if "stException" in expression and self.index != 0:
                    second_waiting.set()
                    await blocked.wait()
                return Value()

            def is_closed(self):
                return False

        class Context:
            def __init__(self, index):
                self.index = index
                self.closed = False

            async def close(self):
                assert process.returncode == -signal.SIGKILL
                self.closed = True
                cleanup.append(f"context_{self.index}_closed")

        async def prepare(browser, url, case, seed, index, timeout, errors):
            context = Context(index)
            contexts.append(context)
            return {"context": context, "page": Page(index), "case": case,
                    "seed": seed, "user": index, "prepare_seconds": .01, "errors": errors}

        monkeypatch.setattr(benchmark, "prepare", prepare)
        count = {"wave": 2, "unconfirmed": 3, "warm": 1}[scenario]
        args = SimpleNamespace(url="http://127.0.0.1:8765", case="future", seed=42,
                               seed_policy="distinct", timeout=30, download_sample=0)
        output = tmp_path/"trial"
        campaign = []
        task = asyncio.create_task(benchmark.trial(object(), args, output, count, 1, results=campaign))
        try:
            async with asyncio.timeout(3):
                await first_finished.wait()
                await second_waiting.wait()
                if scenario == "unconfirmed":
                    await unconfirmed.wait()
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        info = json.loads((output/"result.json").read_text())
        assert campaign == [info]
        rows = benchmark.read_jsonl(output/"executions.jsonl")
        assert rows == info["rows"]
        assert len(rows) == count
        assert rows[0]["status"] == "success"
        assert rows[0]["clicked"] is True
        assert rows[0]["visible_accuracy"] == "75.0%"
        assert rows[0]["latency_seconds"] >= 0
        assert rows[0]["observation"] == "outcome_obtained"
        pending = info["warm_probe"]["row"] if scenario == "warm" else rows[1]
        assert pending["status"] == "incomplete"
        assert pending["clicked"] is True
        assert pending["click_wall_seconds"] > 0
        assert pending["observation"] == "click_confirmed"
        assert pending["cancelled"] is True
        assert "usable_wall_seconds" not in pending
        if scenario == "unconfirmed":
            assert rows[2]["status"] == "incomplete"
            assert rows[2]["clicked"] is None
            assert rows[2]["observation"] == "action_unconfirmed"
        assert info["summary"]["successes"] == 1
        assert info["summary"]["clicked"] == (1 if scenario == "warm" else 2)
        assert info["summary"]["click_unconfirmed"] == (1 if scenario == "unconfirmed" else 0)
        assert info["server_exit"] == -signal.SIGKILL
        assert all(context.closed for context in contexts)
        assert process.log.closed
        assert "monitor_closed" in cleanup
        assert cleanup[0:2] == ["kill", "wait"]

    asyncio.run(check())


def test_cancel_before_dispatch_leaves_click_unknown():
    async def check():
        user = {"case": "future", "seed": 42, "user": 0, "prepare_seconds": .01,
                "page": object(), "errors": []}
        row = benchmark.execution_row("future", 42, 0, 1)
        task = asyncio.create_task(benchmark.execute(user, asyncio.Event(), 30, 1, row))
        await asyncio.sleep(0)  # The session is waiting for the release barrier.
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert row["clicked"] is None
        assert row["observation"] == "action_unconfirmed"
        assert row["status"] == "incomplete"
        assert "action_start_mono" not in row
        summary = summarize([row], [])
        assert summary["clicked"] == 0 and summary["click_unconfirmed"] == 1

    asyncio.run(check())
