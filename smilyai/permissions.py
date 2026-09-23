from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from copy import deepcopy
from .audit import redact


class Risk(StrEnum):
    LOW = "low"
    CONFIRM = "confirm"
    ADMIN = "admin"


@dataclass(frozen=True)
class PermissionRequest:
    token: str
    tool: str
    arguments: dict[str, Any]
    risk: Risk
    title: str
    description: str
    created_at: float
    strong_phrase: str | None = None


class PermissionEngine:
    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self._pending: dict[str, PermissionRequest] = {}
        self._lock = threading.Lock()

    def evaluate(self, tool: str, arguments: dict[str, Any], risk: Risk, summary: str) -> dict[str, Any]:
        if risk == Risk.LOW:
            return {"allowed": True, "risk": risk.value}
        token = secrets.token_urlsafe(24)
        phrase = "CONFIRM ADMIN ACTION" if risk == Risk.ADMIN else None
        request = PermissionRequest(
            token=token,
            tool=tool,
            arguments=deepcopy(arguments),
            risk=risk,
            title=_title(tool, arguments),
            description=summary,
            created_at=time.monotonic(),
            strong_phrase=phrase,
        )
        with self._lock:
            self._purge_locked()
            self._pending[token] = request
        return {"allowed": False, "confirmation": self.public(request)}

    def consume(self, token: str, approved: bool, phrase: str | None = None) -> PermissionRequest | None:
        with self._lock:
            self._purge_locked()
            request = self._pending.pop(token, None)
        if not request or approved is not True:
            return None
        if request.strong_phrase and phrase != request.strong_phrase:
            return None
        return request

    @staticmethod
    def public(request: PermissionRequest) -> dict[str, Any]:
        return {
            "token": request.token,
            "tool": request.tool,
            "arguments": redact(request.arguments),
            "risk": request.risk.value,
            "title": request.title,
            "description": request.description,
            "strong_phrase": request.strong_phrase,
        }

    def _purge_locked(self) -> None:
        cutoff = time.monotonic() - self.ttl_seconds
        expired = [token for token, item in self._pending.items() if item.created_at < cutoff]
        for token in expired:
            self._pending.pop(token, None)


def _title(tool: str, arguments: dict[str, Any]) -> str:
    names = {
        "delete_file": "Move this item to Trash?",
        "install_package": "Install this application?",
        "remove_package": "Remove this application?",
        "connect_wifi": "Change the Wi-Fi connection?",
        "restart": "Restart this computer?",
        "shutdown": "Shut down this computer?",
        "gpio_write": "Change a GPIO output?",
    }
    return names.get(tool, f"Allow {tool.replace('_', ' ')}?")
