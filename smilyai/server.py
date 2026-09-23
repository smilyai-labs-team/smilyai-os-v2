from __future__ import annotations
import argparse
import asyncio
import json
import mimetypes
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .agent import AgentRuntime
from .audit import AuditLog
from .bootstrap import build_registry
from .config import ConfigStore, SecretStore, credential_scope, validate_config, _deep_merge
from .hardware import detect_hardware
from .permissions import PermissionEngine
from .providers import create_provider
from .providers.mock import MockProvider
from .providers.openai_compatible import ProviderError
from .jobs import Jobs

CSP = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"

class Runtime:
    def __init__(self, config_path=None):
        self.config = ConfigStore(config_path)
        self.secrets = SecretStore()
        self.audit = AuditLog()
        self.permissions = PermissionEngine()
        self.csrf_token = secrets.token_urlsafe(32)
        self.hardware = detect_hardware()
        self.registry = build_registry(self.config, self.audit, self.permissions, self.hardware)
        self.agent = AgentRuntime(MockProvider(), self.registry, self.audit)
        self.settings_lock = threading.Lock()
        self.jobs = Jobs(self.agent)
        self.reload_provider()

    def reload_provider(self):
        try:
            self.agent.provider = create_provider(self.config.get(), self.secrets)
        except (ValueError, RuntimeError):
            self.agent.provider = MockProvider()

    def candidate(self, body):
        patch = body.get("config", {})
        if not isinstance(patch, dict):
            raise ValueError("Settings must be an object")
        if "security" in patch and set(patch["security"]) - {"developer_mode"}:
            raise ValueError("File scope and permission policy cannot be changed through the shell API")
        validate_config(patch)
        config = _deep_merge(self.config.get(), patch)
        key = body.get("api_key", "")
        if not isinstance(key, str) or len(key) > 4096 or any(ord(c) < 32 for c in key):
            raise ValueError("Invalid credential")
        return config, key

    def temporary_provider(self, body):
        config, key = self.candidate(body)
        class CandidateSecrets:
            def get(inner, scope):
                return key or self.secrets.get(scope)
        return create_provider(config, CandidateSecrets())

class SmilyHandler(BaseHTTPRequestHandler):
    server_version = "SmilyAI/0.3.1"
    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, *args):
        pass

    def trusted(self):
        port = self.server.server_address[1]
        host = self.headers.get("Host")
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        origin = self.headers.get("Origin")
        return host in allowed and (origin is None or origin in {"http://" + x for x in allowed}) and self.headers.get("Sec-Fetch-Site") not in {"cross-site"}

    def do_GET(self):
        if not self.trusted():
            return self._json({"error": "Untrusted request origin"}, 403)
        try:
            u = urlparse(self.path)
            route = u.path
            if route == "/api/health":
                return self._json({"ok": True, "version": "0.3.1"})
            if route == "/api/bootstrap":
                c = self.runtime.config.get()
                return self._json({"config": c, "session_token": self.runtime.csrf_token,
                    "hardware": self.runtime.hardware.capabilities().to_dict(),
                    "tools": self.runtime.registry.describe(), "secret_persistence": self.runtime.secrets.persistent,
                    "credential_saved": bool(self.runtime.agent.provider.__dict__.get("api_key")),
                    "active_job": next((j.id for j in self.runtime.jobs.items.copy().values() if j.result is None), None)})
            if route.startswith("/api/"):
                self.require_session()
            if route == "/api/activity":
                return self._json({"items": self.runtime.audit.recent()})
            if route == "/api/job":
                q = parse_qs(u.query)
                return self._json(self.runtime.jobs.get(q.get("id", [""])[0]).snapshot(int(q.get("after", ["0"])[0])))
            self._static(route)
        except (ValueError, PermissionError):
            self._json({"error": "Invalid request or shell session"}, 400)

    def require_session(self):
        if not secrets.compare_digest(self.headers.get("X-SmilyAI-Session", ""), self.runtime.csrf_token):
            raise PermissionError("Invalid shell session")

    def do_POST(self):
        if not self.trusted():
            return self._json({"error": "Untrusted request origin"}, 403)
        try:
            self.require_session()
            body = self._body()
            route = urlparse(self.path).path
            if route in {"/api/intent", "/api/jobs", "/api/tool"}:
                text = body.get("text", "")
                if not isinstance(text, str) or len(text) > 16000 or (not text.strip() and route != "/api/tool"):
                    raise ValueError("Enter a request of up to 16000 characters")
                direct = None
                if route == "/api/tool":
                    direct = {"name": body.get("name"), "arguments": body.get("arguments", {})}
                # /intent remains a synchronous compatibility API; UI uses cancellable jobs.
                with self.runtime.settings_lock:
                    job = self.runtime.jobs.start(text.strip(), direct)
                if route == "/api/intent":
                    import time
                    deadline = time.monotonic() + 16
                    while job.result is None and time.monotonic() < deadline:
                        pending = job.pending
                        if pending:
                            return self._json({"job_id": job.id, "message": "Waiting for permission.", "action": {"status": "confirmation_required", "confirmation": pending}})
                        time.sleep(.02)
                    return self._json(job.result or {"job_id": job.id, "status": "running"})
                return self._json({"job_id": job.id}, 202)
            if route in {"/api/confirm", "/api/cancel"}:
                job = self.runtime.jobs.get(body.get("job_id", ""))
                if route.endswith("cancel"):
                    job.stop()
                else:
                    if type(body.get("approved")) is not bool:
                        raise ValueError("Approval must be a boolean")
                    job.decide(body.get("token"), body["approved"], body.get("phrase"))
                return self._json({"ok": True})
            if route in {"/api/provider/test", "/api/provider/models"}:
                provider = self.runtime.temporary_provider(body)
                return self._json(asyncio.run(provider.test_connection()))
            if route == "/api/settings":
                with self.runtime.settings_lock:
                    if any(j.result is None for j in self.runtime.jobs.items.copy().values()):
                        raise ValueError("Stop the current task before changing settings")
                    config, key = self.runtime.candidate(body)
                    # Validate provider before persisting either settings or credentials.
                    create_provider(config, type("NoSecrets", (), {"get": lambda s, _: None})())
                    scope = credential_scope(config["provider"])
                    if body.get("delete_key") is True:
                        self.runtime.secrets.delete(scope)
                    elif key:
                        self.runtime.secrets.set(scope, key)
                    updated = self.runtime.config.update(body.get("config", {}))
                    self.runtime.reload_provider()
                    self.runtime.audit.write("settings_updated", sections=list(body.get("config", {})))
                    return self._json({"config": updated, "secret_persistence": self.runtime.secrets.persistent,
                        "credential_saved": bool(self.runtime.agent.provider.__dict__.get("api_key"))})
            if route == "/api/voice/transcribe":
                from .voice.local import transcribe
                return self._json({"text": transcribe(body, self.runtime.config.get())})
            return self._json({"error": "Not found"}, 404)
        except PermissionError:
            self._json({"error": "Invalid shell session"}, 403)
        except ProviderError as e:
            self._json({"error": str(e)}, 502)
        except ValueError as e:
            self._json({"error": str(e)}, 400)
        except Exception:
            self.runtime.audit.write("api_error", category="internal")
            self._json({"error": "Request failed safely. Check settings and retry."}, 500)

    def _body(self):
        if self.headers.get("Transfer-Encoding") or self.headers.get_content_type() != "application/json":
            raise ValueError("Expected JSON with Content-Length")
        length = int(self.headers.get("Content-Length", "-1"))
        if not 0 <= length <= 3_000_000:
            raise ValueError("Request size is invalid")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
        return data

    def _json(self, value, status=200):
        self._send(json.dumps(value).encode(), "application/json; charset=utf-8", status)

    def _send(self, payload, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(self)")
        self.end_headers()
        try:
            if self.command != "HEAD":
                self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _static(self, route):
        relative = "index.html" if route in {"", "/"} else route.lstrip("/")
        root = self.shell_root.resolve()
        candidate = (root / relative).resolve()
        if root not in candidate.parents or not candidate.is_file():
            return self._json({"error": "Not found"}, 404)
        self._send(candidate.read_bytes(), mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")

def serve(host="127.0.0.1", port=47811, config_path=None):
    if host != "127.0.0.1":
        raise ValueError("The harness may bind only to 127.0.0.1")
    root = Path(os.environ.get("SMILYAI_SHELL_ROOT", Path(__file__).resolve().parent.parent / "shell"))
    handler = type("Handler", (SmilyHandler,), {"runtime": Runtime(config_path), "shell_root": root})
    return ThreadingHTTPServer((host, port), handler)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=47811)
    p.add_argument("--config", type=Path)
    a = p.parse_args()
    server = serve(a.host, a.port, a.config)
    try:
        server.serve_forever()
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
