from __future__ import annotations
import json
import os
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

REDACT_KEYS = {"api_key", "authorization", "password", "secret", "token", "content", "text", "result", "error"}

def redact(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if k.lower() in REDACT_KEYS else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value

class AuditLog:
    def __init__(self, path=None):
        self.path = path or Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "smilyai-os/activity.jsonl"
        self._lock = threading.Lock()

    def write(self, event, **fields):
        record = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **redact(fields)}
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._lock:
            if self.path.exists() and self.path.stat().st_size > 2_000_000:
                os.replace(self.path, self.path.with_suffix(".previous"))
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")

    def recent(self, limit=50):
        try:
            with self._lock, self.path.open(encoding="utf-8") as f:
                lines = deque(f, maxlen=max(1, min(limit, 200)))
        except FileNotFoundError:
            return []
        result = []
        for line in lines:
            try:
                result.append(json.loads(line))
            except ValueError:
                pass
        return result

