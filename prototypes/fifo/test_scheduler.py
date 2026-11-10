"""Concurrency and ownership contracts; fake engines only for deterministic control."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time

import pytest

from prototypes.fifo.service import Refusal, Scheduler


class Result:
    def __init__(self, case, seed):
        self.case, self.seed = case, seed

    def to_json(self):
        return json.dumps({"case_id": self.case, "seed": self.seed})


def await_state(scheduler, token, jid, desired="succeeded"):
    end = time.monotonic()+3
    while time.monotonic() < end:
        value = scheduler.get(token, jid)
        if value["state"] == desired:
            return value
        time.sleep(.005)
    raise AssertionError(value)


def refused(status, reason, fn, *args):
    with pytest.raises(Refusal) as error:
        fn(*args)
    assert (error.value.status, error.value.reason) == (status, reason)


@pytest.mark.parametrize("policy", ["fifo", "reject"])
def test_atomic_duplicates_during_and_after_execution(policy):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def engine(case, seed):
        calls.append((case, seed))
        entered.set()
        assert release.wait(3)
        return Result(case, seed)
    scheduler = Scheduler(policy, engine=engine)
    token = scheduler.new_session()
    try:
        with ThreadPoolExecutor(max_workers=20) as pool:
            jobs = list(pool.map(lambda _: scheduler.submit(token, "future", 42), range(20)))
        assert len({j[0]["id"] for j in jobs}) == 1
        assert sum(not j[1] for j in jobs) == 1
        assert entered.wait(1)
        jid = jobs[0][0]["id"]
        refused(409, "result_not_ready", scheduler.get, token, jid, True)
        release.set()
        await_state(scheduler, token, jid)
        assert scheduler.submit(token, "future", 42)[1]
        assert json.loads(scheduler.get(token, jid, True))["seed"] == 42
        assert calls == [("future", 42)]
    finally:
        release.set()
        scheduler.close()


def test_fifo_capacity_order_and_ownership_with_distinct_results():
    entered, release = threading.Event(), threading.Event()
    calls = []
    def engine(case, seed):
        calls.append(seed)
        if seed == 1:
            entered.set()
            assert release.wait(3)
        return Result(case, seed)
    scheduler = Scheduler(queue_size=2, engine=engine)
    tokens = [scheduler.new_session() for _ in range(4)]
    try:
        jobs = [scheduler.submit(tokens[0], "future", 1)[0]]
        assert entered.wait(1)
        jobs.extend(scheduler.submit(tokens[i], "future", i+1)[0] for i in (1, 2))
        assert [job["position"] for job in jobs[1:]] == [1, 2]
        refused(429, "queue_full", scheduler.submit, tokens[3], "future", 4)
        # Duplicate is successful even when all waiting slots are occupied.
        assert scheduler.submit(tokens[1], "future", 2)[1]
        for suffix in (False, True):
            refused(404, "job_not_found", scheduler.get, tokens[3], jobs[0]["id"], suffix)
        release.set()
        for i, job in enumerate(jobs):
            await_state(scheduler, tokens[i], job["id"])
            assert json.loads(scheduler.get(tokens[i], job["id"], True))["seed"] == i+1
        assert calls == [1, 2, 3]
        job, _ = scheduler.submit(tokens[3], "groups", 4)
        await_state(scheduler, tokens[3], job["id"])
    finally:
        release.set()
        scheduler.close()


def test_original_rejection_has_no_waiting_job():
    entered, release = threading.Event(), threading.Event()
    def engine(case, seed):
        entered.set()
        assert release.wait(3)
        return Result(case, seed)
    scheduler = Scheduler("reject", engine=engine)
    try:
        a, b = scheduler.new_session(), scheduler.new_session()
        scheduler.submit(a, "future", 1)
        assert entered.wait(1)
        refused(429, "busy", scheduler.submit, b, "future", 2)
        assert len(scheduler.jobs) == 1 and not scheduler.pending
    finally:
        release.set()
        scheduler.close()


@pytest.mark.parametrize("policy", ["fifo", "reject"])
def test_failure_is_terminal_idempotent_and_releases_executor(policy):
    calls = []
    def engine(case, seed):
        calls.append(seed)
        if seed == 1:
            raise ValueError("deliberate test failure")
        return Result(case, seed)
    scheduler = Scheduler(policy, engine=engine)
    try:
        a, b = scheduler.new_session(), scheduler.new_session()
        job, _ = scheduler.submit(a, "future", 1)
        await_state(scheduler, a, job["id"], "failed")
        assert scheduler.submit(a, "future", 1)[1]
        refused(409, "job_failed", scheduler.get, a, job["id"], True)
        other, _ = scheduler.submit(b, "groups", 2)
        await_state(scheduler, b, other["id"])
        assert calls == [1, 2]
    finally:
        scheduler.close()


@pytest.mark.parametrize("policy", ["fifo", "reject"])
def test_original_rolling_budget_is_preserved_and_boundary_recovers(policy):
    clock = [100.0]
    scheduler = Scheduler(policy, clock=lambda: clock[0], engine=Result)
    try:
        for i in range(12):
            token = scheduler.new_session()
            job, _ = scheduler.submit(token, "future", i)
            await_state(scheduler, token, job["id"])
        token = scheduler.new_session()
        if policy == "reject":
            refused(429, "rate_limit", scheduler.submit, token, "future", 12)
        else:
            job, _ = scheduler.submit(token, "future", 12)
            await_state(scheduler, token, job["id"], "waiting_budget")
        assert len(scheduler.budget._admitted) == 12
        clock[0] = 159.999
        with scheduler.cv:
            scheduler.cv.notify_all()
        if policy == "reject":
            refused(429, "rate_limit", scheduler.submit, token, "future", 12)
        clock[0] = 160.0
        with scheduler.cv:
            scheduler.cv.notify_all()
        if policy == "reject":
            job, _ = scheduler.submit(token, "future", 12)
        await_state(scheduler, token, job["id"])
        assert len(scheduler.budget._admitted) == 1
    finally:
        scheduler.close()


def test_session_interval_and_expiry_are_explicit_and_bounded():
    clock = [100.0]
    scheduler = Scheduler(engine=Result, clock=lambda: clock[0], retention=10)
    try:
        token = scheduler.new_session()
        job, _ = scheduler.submit(token, "future", 1)
        await_state(scheduler, token, job["id"])
        refused(429, "session_interval", scheduler.submit, token, "future", 2)
        refused(401, "invalid_session", scheduler.get, "invalid", job["id"])
        assert scheduler.submit(token, "future", 1)[1]
        clock[0] = 103
        other, _ = scheduler.submit(token, "groups", 2)
        await_state(scheduler, token, other["id"])
        clock[0] = 110
        refused(404, "job_not_found", scheduler.get, token, job["id"])
        assert scheduler.get(token, other["id"])["state"] == "succeeded"
        clock[0] = 1011
        refused(401, "invalid_session", scheduler.get, token, other["id"])
        assert not scheduler.jobs and not scheduler.keys and not scheduler.sessions
    finally:
        scheduler.close()


def test_cache_shares_calculation_while_results_are_owned():
    calls = []
    def engine(case, seed):
        calls.append(seed)
        return Result(case, seed)
    scheduler = Scheduler(engine=engine)
    try:
        a, b = scheduler.new_session(), scheduler.new_session()
        first, _ = scheduler.submit(a, "future", 42)
        second, _ = scheduler.submit(b, "future", 42)
        await_state(scheduler, a, first["id"])
        state = await_state(scheduler, b, second["id"])
        assert state["cache_hit"] and calls == [42]
        assert scheduler.get(a, first["id"], True) == scheduler.get(b, second["id"], True)
        refused(404, "job_not_found", scheduler.get, a, second["id"], True)
    finally:
        scheduler.close()


@pytest.mark.parametrize("queue_size", [0, 19])
def test_exact_capacity_includes_reserved_executor_and_full_queue_duplicates(queue_size):
    entered, release = threading.Event(), threading.Event()
    def engine(case, seed):
        entered.set()
        assert release.wait(3)
        return Result(case, seed)
    scheduler = Scheduler(queue_size=queue_size, engine=engine)
    try:
        tokens = [scheduler.new_session() for _ in range(queue_size+2)]
        first, _ = scheduler.submit(tokens[0], "future", 0)
        assert entered.wait(1)
        for i in range(1, queue_size+1):
            scheduler.submit(tokens[i], "future", i)
        assert len(scheduler.pending) == queue_size
        assert scheduler.submit(tokens[0], "future", 0)[0]["id"] == first["id"]
        refused(429, "queue_full", scheduler.submit, tokens[-1], "future", 100)
    finally:
        release.set()
        scheduler.close()


def test_session_capacity_and_retained_job_cap_are_reclaimed():
    clock = [100.0]
    scheduler = Scheduler(engine=Result, clock=lambda: clock[0])
    try:
        tokens = [scheduler.new_session() for _ in range(64)]
        refused(429, "session_capacity", scheduler.new_session)
        for i in range(4):
            job, _ = scheduler.submit(tokens[0], "future", i)
            await_state(scheduler, tokens[0], job["id"])
            clock[0] += 3
        refused(429, "retained_job_capacity", scheduler.submit, tokens[0], "future", 4)
        clock[0] = 500
        job, _ = scheduler.submit(tokens[0], "future", 4)
        await_state(scheduler, tokens[0], job["id"])
        clock[0] = 1500
        assert scheduler.new_session() not in tokens
        assert len(scheduler.sessions) == 1 and not scheduler.jobs
    finally:
        scheduler.close()


def test_waiting_jobs_do_not_expire_and_same_session_starts_respect_interval():
    clock = [100.0]
    entered, release = threading.Event(), threading.Event()
    def engine(case, seed):
        if seed == 1:
            entered.set()
            assert release.wait(3)
        return Result(case, seed)
    scheduler = Scheduler(engine=engine, clock=lambda: clock[0], retention=10)
    try:
        token = scheduler.new_session()
        first, _ = scheduler.submit(token, "future", 1)
        assert entered.wait(1)
        clock[0] = 103
        second, _ = scheduler.submit(token, "future", 2)
        clock[0] = 1100
        assert scheduler.get(token, second["id"])["state"] == "queued"
        release.set()
        await_state(scheduler, token, second["id"])
        third, _ = scheduler.submit(token, "future", 3)
        await_state(scheduler, token, third["id"], "waiting_budget")
        clock[0] += 3
        with scheduler.cv:
            scheduler.cv.notify_all()
        await_state(scheduler, token, third["id"])
    finally:
        release.set()
        scheduler.close()
