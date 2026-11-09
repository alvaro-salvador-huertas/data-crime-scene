"""Test-only controls; never imported by the pilot or the normal FIFO service.

    gate -> controlled wait before invoking the real engine
    full_budget -> insert 12 recent admissions without running 12 experiments
    advance -> add a monotonic clock offset (expiry and budget recovery)
    fail_next -> injected exception, not an observed real-engine failure
No test-control HTTP routes or browser-facing switches are added.
"""
from collections import deque
import threading
import time

from data_crime_scene.experiments import run_experiment
from prototypes.fifo.service import Scheduler, make_server


class Fixture:
    def __init__(self, trace):
        self.offset = 0
        self.gate = threading.Event()
        self.gate.set()
        self.fail_next = False
        self.real_calls = []
        self.scheduler = Scheduler(engine=self.engine, clock=lambda: time.monotonic()+self.offset, trace=trace)
        self.server = make_server(self.scheduler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def engine(self, case, seed):
        if not self.gate.wait(120):
            raise RuntimeError("Test gate exceeded its deadline")
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("Injected failure for browser QA")
        self.real_calls.append((case, seed))
        return run_experiment(case, seed)

    def advance(self, seconds):
        with self.scheduler.cv:
            self.offset += seconds
            self.scheduler.cv.notify_all()

    def full_budget(self):
        with self.scheduler.cv:
            assert self.scheduler.active is None
            now = self.scheduler.clock()
            self.scheduler.starts = deque([now]*12)
            self.scheduler.budget._admitted = deque([now]*12)

    def close(self):
        self.gate.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.scheduler.close()
