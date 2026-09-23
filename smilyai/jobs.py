from __future__ import annotations
import asyncio
import secrets
import threading
import time
from collections import deque
from copy import deepcopy


class Job:
    def __init__(self, runner, text, direct=None):
        self.id = secrets.token_urlsafe(18)
        self.cancelled = threading.Event()
        self.condition = threading.Condition()
        self.events = deque(maxlen=100)
        self.sequence = 0
        self.result = None
        self.pending = None
        self.decision = None
        self.started = time.monotonic()
        self.runner, self.text, self.direct = runner, text, direct

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()

    def emit(self, state, message, **extra):
        with self.condition:
            self.sequence += 1
            self.events.append({"seq": self.sequence, "state": state, "message": message, **extra})

    def approve(self, info):
        with self.condition:
            self.pending = info
            self.condition.wait_for(lambda: self.cancelled.is_set() or self.decision is not None, timeout=295)
            decision = self.decision or {"approved": False}
            self.pending = self.decision = None
            return decision

    def decide(self, token, approved, phrase):
        with self.condition:
            # The event can reach the UI just before the worker enters approve().
            info = self.pending
            if info is None:
                info = next((e.get("confirmation") for e in reversed(self.events) if e.get("confirmation")), None)
            if not info or token != info["token"] or self.decision is not None or self.cancelled.is_set() or self.result is not None:
                raise ValueError("Permission expired or belongs to another task")
            self.decision = {"approved": approved, "phrase": phrase}
            self.condition.notify_all()

    def stop(self):
        with self.condition:
            self.cancelled.set()
            self.condition.notify_all()
        self.emit("stopping", "Stopping after the current atomic action…")

    def run(self):
        try:
            result = asyncio.run(self.runner.loop(self.text, self.emit, self.cancelled.is_set, self.approve, self.direct))
        except Exception:
            result = {"status": "error", "message": "The task could not be completed safely. No further steps will run."}
        with self.condition:
            self.result = result
            self.text = ""

    def snapshot(self, after=0):
        with self.condition:
            return deepcopy({"id": self.id, "events": [e for e in self.events if e["seq"] > after],
                             "result": self.result, "active": self.result is None})


class Jobs:
    def __init__(self, runner):
        self.runner, self.items, self.lock = runner, {}, threading.Lock()

    def start(self, text, direct=None):
        with self.lock:
            if any(j.result is None for j in self.items.values()):
                raise ValueError("A task is still running. Stop it or wait before starting another.")
            while len(self.items) >= 20:
                self.items.pop(next(iter(self.items)))
            job = Job(self.runner, text, direct)
            self.items[job.id] = job
            job.start()
            return job

    def get(self, identity):
        with self.lock:
            if identity not in self.items:
                raise ValueError("Task no longer exists")
            return self.items[identity]
