"""Real loopback readiness tests; no Chromium, systemd manager, or AI required."""
import http.client
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from smilyai import service_notify, ui_server


ASSETS = (
    "index.html", "app.js", "boot.js", "styles.css", "orb.js",
    "voice.js", "pcm-worklet.js", "assets/smilyai-logo.png",
)


class UIReadinessTests(unittest.TestCase):
    def start_server(self, root=None):
        handler = ui_server.UIHandler
        if root is not None:
            handler = type("FixtureUIHandler", (handler,), {"shell_root": root})
        server = ui_server.serve_ui(port=0, handler=handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def close():
            server.shutdown()
            server.server_close()
            thread.join(2)
        self.addCleanup(close)
        return server

    @staticmethod
    def request(server, method="GET", path="/", headers=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_address[1], timeout=3)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def fixture_assets(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name in ASSETS:
            asset = root / name
            asset.parent.mkdir(parents=True, exist_ok=True)
            asset.write_bytes(b"nonempty fixture asset")
        return root

    def test_readyz_is_backend_independent(self):
        server = self.start_server()
        with patch.object(ui_server.UIHandler, "proxy",
                          side_effect=AssertionError("Readiness contacted backend")):
            status, headers, payload = self.request(server, path="/readyz")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload), {"service": "smilyai-ui", "ready": True})
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_root_and_head_work_without_backend(self):
        server = self.start_server()
        with patch.object(ui_server.UIHandler, "proxy",
                          side_effect=AssertionError("Static content contacted backend")):
            status, get_headers, payload = self.request(server)
            head_status, head_headers, head_body = self.request(server, method="HEAD")
        self.assertEqual(status, 200)
        self.assertIn(b"orbButton", payload)
        self.assertEqual(head_status, 200)
        self.assertEqual(head_body, b"")
        self.assertEqual(head_headers["Content-Length"], str(len(payload)))
        self.assertEqual(head_headers["Content-Type"], get_headers["Content-Type"])
        self.assertEqual(head_headers["Content-Security-Policy"], get_headers["Content-Security-Policy"])

    def test_readyz_head_has_get_length_without_body(self):
        server = self.start_server()
        _, _, payload = self.request(server, path="/readyz")
        status, headers, body = self.request(server, method="HEAD", path="/readyz")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Length"], str(len(payload)))
        self.assertEqual(body, b"")

    def test_backend_outage_does_not_remove_readiness(self):
        server = self.start_server()
        # Construct the caller before replacing only new proxy connections.
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        try:
            with patch("smilyai.ui_server.http.client.HTTPConnection") as backend:
                backend.return_value.request.side_effect = ConnectionRefusedError("fixture outage")
                connection.request("GET", "/api/bootstrap")
                response = connection.getresponse()
                payload = response.read()
                self.assertEqual(response.status, 503)
                self.assertIn("reconnecting", json.loads(payload)["error"])
                backend.return_value.close.assert_called_once()
        finally:
            connection.close()
        self.assertEqual(self.request(server, path="/readyz")[0], 200)
        self.assertEqual(self.request(server)[0], 200)

    def test_head_api_does_not_proxy(self):
        server = self.start_server()
        with patch.object(ui_server.UIHandler, "proxy",
                          side_effect=AssertionError("HEAD must not proxy")):
            status, _, body = self.request(server, method="HEAD", path="/api/bootstrap")
        self.assertEqual(status, 405)
        self.assertEqual(body, b"")

    def test_readyz_retains_host_and_origin_guards(self):
        server = self.start_server()
        for headers in ({"Host": "attacker.example"}, {"Origin": "https://attacker.example"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request(server, path="/readyz", headers=headers)[0], 403)

    def test_missing_asset_prevents_bind_and_readiness(self):
        root = self.fixture_assets()
        (root / "orb.js").unlink()
        handler = type("MissingAssetHandler", (ui_server.UIHandler,), {"shell_root": root})
        with patch("smilyai.ui_server.ThreadingHTTPServer") as bind:
            with self.assertRaisesRegex(RuntimeError, "orb.js"):
                ui_server.serve_ui(port=0, handler=handler)
        bind.assert_not_called()

    def test_empty_asset_is_rejected(self):
        root = self.fixture_assets()
        (root / "app.js").write_bytes(b"")
        with self.assertRaisesRegex(RuntimeError, "app.js"):
            ui_server.validate_assets(root)

    def test_asset_removed_after_start_changes_readyz_to_503(self):
        root = self.fixture_assets()
        server = self.start_server(root)
        self.assertEqual(self.request(server, path="/readyz")[0], 200)
        (root / "styles.css").unlink()
        status, _, payload = self.request(server, path="/readyz")
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(payload), {"service": "smilyai-ui", "ready": False})

    def test_main_never_notifies_on_asset_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(ui_server.UIHandler, "shell_root", Path(directory)):
                with patch("smilyai.ui_server.notify") as notify:
                    with self.assertLogs("smilyai-ui", level="ERROR"):
                        with self.assertRaises(SystemExit) as exited:
                            ui_server.main()
                    self.assertEqual(exited.exception.code, 1)
                    notify.assert_not_called()

    def test_main_never_notifies_when_actual_bind_fails(self):
        real_serve_ui = ui_server.serve_ui
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen(1)
            port = occupied.getsockname()[1]
            with patch("smilyai.ui_server.serve_ui", side_effect=lambda: real_serve_ui(port=port)):
                with patch("smilyai.ui_server.notify") as notify:
                    with self.assertLogs("smilyai-ui", level="ERROR"):
                        with self.assertRaises(SystemExit) as exited:
                            ui_server.main()
                    self.assertEqual(exited.exception.code, 1)
                    notify.assert_not_called()

    def test_main_notifies_only_with_bound_validated_server(self):
        server = ui_server.serve_ui(port=0)
        self.addCleanup(server.server_close)
        events = []

        def notified(message):
            self.assertEqual(server.socket.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN), 1)
            ui_server.validate_assets(server.RequestHandlerClass.shell_root)
            self.assertIn("READY=1", message.splitlines())
            events.append("notified")

        with patch("smilyai.ui_server.serve_ui", return_value=server):
            with patch("smilyai.ui_server.notify", side_effect=notified):
                with patch.object(server, "serve_forever", side_effect=lambda: events.append("serving")):
                    ui_server.main()
        self.assertEqual(events, ["notified", "serving"])
        self.assertEqual(server.socket.fileno(), -1)

    def test_non_loopback_bind_is_refused(self):
        with self.assertRaises(ValueError):
            ui_server.serve_ui(host="0.0.0.0", port=0)


class ServiceNotifyTests(unittest.TestCase):
    def unix_receiver(self):
        try:
            return socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        except PermissionError as error:
            self.skipTest(f"Host prohibits AF_UNIX datagram sockets: {error}")

    def test_manual_launch_without_notify_socket_is_supported(self):
        with patch.dict(os.environ):
            os.environ.pop("NOTIFY_SOCKET", None)
            self.assertFalse(service_notify.notify("READY=1"))

    def test_real_filesystem_datagram(self):
        with tempfile.TemporaryDirectory() as directory:
            address = str(Path(directory) / "notify.sock")
            with self.unix_receiver() as receiver:
                receiver.bind(address)
                receiver.settimeout(2)
                message = "READY=1\nSTATUS=Static shell ready"
                with patch.dict(os.environ, {"NOTIFY_SOCKET": address}):
                    self.assertTrue(service_notify.notify(message))
                self.assertEqual(receiver.recv(1024), message.encode())

    @unittest.skipUnless(sys.platform.startswith("linux"), "Abstract Unix sockets are Linux-specific")
    def test_real_abstract_datagram(self):
        name = "smilyai-notify-test-" + uuid.uuid4().hex
        with self.unix_receiver() as receiver:
            receiver.bind("\0" + name)
            receiver.settimeout(2)
            with patch.dict(os.environ, {"NOTIFY_SOCKET": "@" + name}):
                self.assertTrue(service_notify.notify("READY=1"))
            self.assertEqual(receiver.recv(1024), b"READY=1")

    def test_datagram_address_and_payload_encoding(self):
        for address, expected in (("/run/user/123/notify.sock", "/run/user/123/notify.sock"),
                                  ("@smilyai-notify", "\0smilyai-notify")):
            with self.subTest(address=address):
                with patch("smilyai.service_notify.socket.socket") as factory:
                    client = factory.return_value.__enter__.return_value
                    with patch.dict(os.environ, {"NOTIFY_SOCKET": address}):
                        self.assertTrue(service_notify.notify("READY=1\nSTATUS=ready"))
                    factory.assert_called_once_with(socket.AF_UNIX, socket.SOCK_DGRAM)
                    client.settimeout.assert_called_once_with(1)
                    client.connect.assert_called_once_with(expected)
                    client.sendall.assert_called_once_with(b"READY=1\nSTATUS=ready")

    def test_missing_notify_socket_does_not_claim_success(self):
        with patch("smilyai.service_notify.socket.socket") as factory:
            client = factory.return_value.__enter__.return_value
            client.connect.side_effect = FileNotFoundError("fixture: missing socket")
            with patch.dict(os.environ, {"NOTIFY_SOCKET": "/missing/notify.sock"}):
                with self.assertRaises(FileNotFoundError):
                    service_notify.notify("READY=1")
            client.sendall.assert_not_called()


if __name__ == "__main__":
    unittest.main()
