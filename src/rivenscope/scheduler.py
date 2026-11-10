"""Shared low-rate scheduler. No threads, busy loops or hidden contract routes."""
from collections import deque
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
import random
import time
from PySide6.QtCore import QObject, QTimer, Signal
from .network import request_path


def retry_seconds(value, now):
    if not value:
        return 0
    try:
        seconds = float(value)
        return max(0, seconds) if seconds < float("inf") else 86400
    except ValueError:
        try:
            return max(0, parsedate_to_datetime(value).timestamp() - now)
        except (ValueError, TypeError, OverflowError):
            return 0


@dataclass
class Job:
    key: str
    priority: int
    created: float
    due: float
    attempts: int = 0
    consumers: set[str] = field(default_factory=set)


class Budget:
    def __init__(self, spacing=6.1):
        self.spacing = max(6.1, spacing)
        self.starts = deque()
        self.next_start = 0
        self.cooldown = 0
        self.failures = 0

    def prune(self, now):
        while self.starts and self.starts[0] <= now - 60:
            self.starts.popleft()

    def ready_at(self, now):
        self.prune(now)
        return max(self.next_start, self.cooldown, self.starts[0] + 60.01 if len(self.starts) >= 10 else 0)

    def start(self, now):
        if now < self.ready_at(now):
            raise ValueError("Request budget exhausted")
        self.starts.append(now)
        self.next_start = now + self.spacing * min(4, 1 + self.failures * .5)

    def failure(self, now, status, retry_after="", rng=random.random):
        self.failures = min(10, self.failures + 1)
        delay = min(900, 6 * 2 ** (self.failures - 1)) + rng() * 3
        delay = max(delay, retry_seconds(retry_after, now))
        if status in (401, 403, 509):
            delay = max(delay, 900)
        self.cooldown = max(self.cooldown, now + delay)
        return self.cooldown

    def success(self):
        self.failures = max(0, self.failures - 1)

    def snapshot(self):
        return {"starts": list(self.starts), "next_start": self.next_start, "cooldown": self.cooldown, "failures": self.failures}

    def restore(self, value, now):
        if not isinstance(value, dict):
            return
        self.starts = deque(sorted(x for x in value.get("starts", []) if isinstance(x, (int, float)) and now - 60 < x <= now))
        # A backwards wall-clock change remains conservative: wait for saved deadline.
        self.next_start = float(value.get("next_start", 0))
        self.cooldown = float(value.get("cooldown", 0))
        self.failures = max(0, min(10, int(value.get("failures", 0))))


class FairQueue:
    def __init__(self):
        self.jobs = {}
        self.virtual = {}

    def add(self, key, priority, now, consumer="global"):
        priority = max(1, min(10, priority))
        if key in self.jobs:
            job = self.jobs[key]
            job.priority = max(job.priority, priority)
            job.consumers.add(consumer)
        else:
            self.jobs[key] = Job(key, priority, now, now, consumers={consumer})
        return self.jobs[key]

    def pop(self, now):
        ready = [j for j in self.jobs.values() if j.due <= now]
        if not ready:
            return None
        aged = [j for j in ready if now - j.created >= 60]
        if aged:
            job = min(aged, key=lambda j: j.created)
        else:
            job = min(ready, key=lambda j: (self.virtual.get(j.key, 0) + 1 / j.priority, j.created))
        self.virtual[job.key] = self.virtual.get(job.key, 0) + 1 / job.priority
        del self.jobs[job.key]
        return job


class Scheduler(QObject):
    outcome = Signal(object)
    changed = Signal(object)
    persist = Signal(object)

    def __init__(self, transport, parent=None, clock=time.time):
        super().__init__(parent)
        self.transport, self.clock = transport, clock
        self.queue, self.budget = FairQueue(), Budget()
        self.running = False
        self.active = None
        self.last_status = "Stopped"
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.tick)
        self.transport.finished.connect(self._finished)
        self.last_report = 0

    def start(self):
        if self.running:
            return
        self.running = True
        self.last_status = "Monitoring enabled; legacy searches require explicit opt-in"
        self.timer.start()
        self.report()

    def stop(self):
        self.running = False
        self.timer.stop()
        self.queue.jobs.clear()
        self.active = None
        self.transport.abort()
        self.last_status = "Stopped"
        self.persist.emit(self.budget.snapshot())
        self.report()

    def enqueue(self, key, priority=3, consumer="global"):
        request_path(key)
        if not self.running:
            return
        if self.active and self.active.key == key:
            self.active.consumers.add(consumer)
            return
        self.queue.add(key, priority, self.clock(), consumer)
        self.tick()

    def tick(self):
        now = self.clock()
        if self.running and self.active is None and now >= self.budget.ready_at(now):
            job = self.queue.pop(now)
            if job:
                self.active = job
                self.budget.start(now)
                self.persist.emit(self.budget.snapshot())
                self.last_status = f"Fetching {job.key}"
                self.transport.get(job.key)
        if now - self.last_report >= 1:
            self.report()

    def _finished(self, outcome):
        job, self.active = self.active, None
        if outcome.cancelled or job is None or not self.running:
            return
        now = self.clock()
        if outcome.status == 200:
            self.budget.success()
            self.last_status = f"{outcome.key} received"
        else:
            due = self.budget.failure(now, outcome.status, outcome.retry_after)
            self.last_status = f"HTTP {outcome.status or 'network error'}; cooling down"
            retryable = outcome.status in (0, 408, 429, 509) or outcome.status >= 500
            if retryable and job.attempts < 4:
                job.attempts += 1
                job.due = due
                self.queue.jobs[job.key] = job
            elif outcome.status in (401, 403):
                self.queue.jobs.clear()
                self.last_status = "Access restricted; requests paused for at least 15 minutes"
        self.outcome.emit(outcome)
        self.persist.emit(self.budget.snapshot())
        self.report()

    def report(self):
        now = self.clock(); self.budget.prune(now); self.last_report = now
        self.changed.emit({"running": self.running, "status": self.last_status,
                           "queued": len(self.queue.jobs), "active": self.active.key if self.active else None,
                           "requests_minute": len(self.budget.starts), "remaining": max(0, 10-len(self.budget.starts)),
                           "wait": max(0, self.budget.ready_at(now)-now), "failures": self.budget.failures})
