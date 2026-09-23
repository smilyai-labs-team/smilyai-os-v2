"""Independent static shell + same-origin API proxy; survives harness failure."""
import http.client
import logging
from http.server import ThreadingHTTPServer
from pathlib import Path
from .server import SmilyHandler
from .service_notify import notify

LOG = logging.getLogger("smilyai-ui")


def validate_assets(root):
    for name in ("index.html", "app.js", "boot.js", "styles.css", "orb.js", "voice.js", "pcm-worklet.js", "assets/smilyai-logo.png"):
        path = root / name
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Required shell asset missing or empty: {path}")

class UIHandler(SmilyHandler):
    shell_root = Path(__file__).resolve().parent.parent / "shell"
    def proxy(self):
        if not self.trusted():
            return self._json({"error": "Untrusted origin"}, 403)
        conn = http.client.HTTPConnection("127.0.0.1", 47811, timeout=18)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 3_000_000 or self.headers.get("Transfer-Encoding"):
                return self._json({"error": "Invalid request size"}, 400)
            payload = self.rfile.read(length) if length else None
            headers = {"Host": "127.0.0.1:47811", "Content-Type": "application/json",
                       "X-SmilyAI-Session": self.headers.get("X-SmilyAI-Session", "")}
            conn.request(self.command, self.path, body=payload, headers=headers)
            response = conn.getresponse()
            self._send(response.read(4_000_000), "application/json", response.status)
        except Exception:
            self._json({"error": "System harness is reconnecting. Native shortcuts still work."}, 503)
        finally:
            conn.close()
    def do_GET(self):
        if self.path.startswith("/api/"):
            return self.proxy()
        if not self.trusted():
            return self._json({"error": "Untrusted origin"}, 403)
        from urllib.parse import urlparse
        route = urlparse(self.path).path
        if route == "/readyz":
            try:
                validate_assets(self.shell_root)
            except (OSError, RuntimeError):
                return self._json({"service": "smilyai-ui", "ready": False}, 503)
            return self._json({"service": "smilyai-ui", "ready": True})
        return self._static(route)
    def do_HEAD(self):
        # Match static GET headers without writing a body. curl -I now works.
        if self.path.startswith("/api/"):
            return self._json({"error": "Use GET for the API"}, 405)
        return self.do_GET()
    def do_POST(self):
        return self.proxy()

def serve_ui(host="127.0.0.1", port=47810, handler=UIHandler):
    if host != "127.0.0.1":
        raise ValueError("The UI server may bind only to 127.0.0.1")
    validate_assets(handler.shell_root)
    return ThreadingHTTPServer((host, port), handler)


def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s [%(levelname)s] %(message)s")
    try:
        # Construction binds/listens; validate assets BEFORE publishing readiness.
        server = serve_ui()
    except (OSError, RuntimeError) as error:
        LOG.error("startup failed: %s", error)
        raise SystemExit(1) from error
    try:
        notify("READY=1\nSTATUS=Static shell assets validated; listening on 127.0.0.1:47810")
        LOG.info("ready at http://127.0.0.1:47810/; backend availability is independent")
        server.serve_forever()
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
