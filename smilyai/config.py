from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "setup_complete": False,
    "user": {"display_name": "", "device_name": "smilyai"},
    "locale": {"language": "en-AU", "region": "AU", "keyboard": "us"},
    "provider": {
        "kind": "mock",
        "model": "smily-simulator",
        "endpoint": "",
        "streaming": True,
    },
    "appearance": {"reduced_effects": False, "high_contrast": False},
    "privacy": {"microphone": False, "camera": False, "analytics": False},
    "voice": {"auto_speak": False, "voice": "", "rate": 1.0, "stt_url": "", "wake_word": False},
    "security": {
        "allowed_roots": ["~"],
        "developer_mode": False,
        "confirm_installs": True,
    },
}


class ConfigStore:
    """Thread-safe JSON configuration persisted with owner-only permissions."""

    def __init__(self, path: Path | None = None):
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self.path = path or base / "smilyai-os" / "config.json"
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        data = deepcopy(DEFAULT_CONFIG)
        if not self.path.exists():
            return data
        try:
            incoming = json.loads(self.path.read_text(encoding="utf-8"))
            # Drop the legacy capability claim, but reject malformed/corrupt config.
            if isinstance(incoming, dict) and isinstance(incoming.get("provider"), dict):
                incoming["provider"].pop("capabilities", None)
            validate_config(incoming)
            return _deep_merge(data, incoming)
        except (OSError, ValueError, TypeError):
            return data

    def get(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._data)

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        validate_config(patch)
        with self._lock:
            previous = self._data
            self._data = _deep_merge(self._data, patch)
            try:
                self.save()
            except Exception:
                self._data = previous
                raise
            return deepcopy(self._data)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = json.dumps(self._data, indent=2, sort_keys=True) + "\n"
        fd, tmp_name = tempfile.mkstemp(prefix=".config-", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        finally:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass


class SecretStore:
    """Stores provider credentials in Secret Service; never in config or browser storage.

    If libsecret is unavailable, credentials remain in memory for the current session.
    This fail-closed fallback avoids silently writing API keys to disk.
    """

    def __init__(self):
        self._memory: dict[str, str] = {}
        self._secret_tool = shutil.which("secret-tool")
        self._persistent = False
        self._lock = threading.RLock()

    @property
    def persistent(self) -> bool:
        return self._persistent

    def set(self, provider: str, value: str) -> None:
        value = value.strip()
        if not value:
            self.delete(provider)
            return
        if self._secret_tool:
            try:
                subprocess.run(
                [self._secret_tool, "store", "--label=SmilyAI OS provider key", "application", "smilyai-os", "provider", provider],
                input=value,
                text=True,
                check=True,
                timeout=3,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                )
                self._persistent = True
            except (OSError, subprocess.SubprocessError):
                self._persistent = False
                raise RuntimeError("Unlock the system keyring and retry; the saved key was not replaced") from None
        self._memory[provider] = value

    def get(self, provider: str) -> str | None:
        if provider in self._memory:
            return self._memory[provider] or None
        if self._secret_tool:
            try:
                result = subprocess.run(
                [self._secret_tool, "lookup", "application", "smilyai-os", "provider", provider],
                text=True,
                capture_output=True,
                timeout=3,
                check=False,
                )
                if result.returncode == 0:
                    self._persistent = True
                    self._memory[provider] = result.stdout.strip()
                    return self._memory[provider] or None
            except (OSError, subprocess.SubprocessError):
                pass
        return self._memory.get(provider)

    def delete(self, provider: str) -> None:
        if self._secret_tool:
            try:
                result = subprocess.run(
                [self._secret_tool, "clear", "application", "smilyai-os", "provider", provider],
                check=False,
                timeout=3,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                )
                if result.returncode != 0:
                    raise RuntimeError("Unlock your keyring to delete the stored key")
            except (OSError, subprocess.SubprocessError):
                raise RuntimeError("Keyring unavailable; saved credential deletion could not be verified") from None
        self._memory[provider] = ""


def credential_scope(provider):
    from .providers.openai_compatible import normalize_endpoint
    from .providers.factory import DEFAULT_ENDPOINTS
    endpoint = provider.get("endpoint") or DEFAULT_ENDPOINTS.get(provider["kind"], "")
    normalized = normalize_endpoint(endpoint) if endpoint else ""
    return hashlib.sha256((provider["kind"] + "\n" + normalized).encode()).hexdigest()


def validate_config(patch):
    if not isinstance(patch, dict) or set(patch) - set(DEFAULT_CONFIG):
        raise ValueError("Unknown settings section")
    for section, values in patch.items():
        template = DEFAULT_CONFIG[section]
        if not isinstance(template, dict):
            if type(values) is not type(template):
                raise ValueError("Invalid setting type")
            continue
        if not isinstance(values, dict) or set(values) - set(template):
            raise ValueError("Unknown setting")
        for key, value in values.items():
            expected = template[key]
            if key == "rate":
                if type(value) not in (int, float) or not .5 <= value <= 2:
                    raise ValueError("Speech rate must be between 0.5 and 2")
            elif type(value) is not type(expected):
                raise ValueError("Invalid setting type")
            if isinstance(value, str) and (len(value) > 2048 or any(ord(c) < 32 for c in value)):
                raise ValueError("Invalid setting text")
            if key == "allowed_roots" and (not value or not all(isinstance(x, str) and x for x in value)):
                raise ValueError("Invalid file roots")
    p = patch.get("provider", {})
    if p.get("kind", "mock") not in {"mock", "smilyai", "custom", "openai", "openrouter", "ollama", "llama.cpp", "anthropic", "gemini"}:
        raise ValueError("Unknown provider")
    if p.get("endpoint"):
        from .providers.openai_compatible import normalize_endpoint
        normalize_endpoint(p["endpoint"])
    stt = patch.get("voice", {}).get("stt_url")
    if stt:
        from urllib.parse import urlsplit
        u = urlsplit(stt)
        if u.scheme != "http" or u.hostname not in {"localhost", "127.0.0.1", "::1"} or u.username or u.password or u.query or u.fragment:
            raise ValueError("Speech service must be local HTTP, without credentials")
    if patch.get("voice", {}).get("wake_word"):
        raise ValueError("Wake-word engine not installed; push-to-talk remains available")


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out
