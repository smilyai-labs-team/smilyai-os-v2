"""Launcher contract tests; no real Chromium/compositor is claimed as verified."""
import contextlib
import io
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import URLError
from smilyai import shell_launcher as launcher

ROOT = Path(__file__).resolve().parents[1]


class Response(io.BytesIO):
    status = 200


class Clock:
    def __init__(self): self.now = 0
    def monotonic(self): return self.now
    def sleep(self, duration): self.now += duration


class LauncherTests(unittest.TestCase):
    def unix_socket(self):
        try:
            return socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        except PermissionError:
            self.skipTest("Host policy prohibits Unix stream sockets; run on the Linux release host")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.output = io.StringIO()
        logs = contextlib.redirect_stderr(self.output)
        logs.__enter__()
        self.addCleanup(logs.__exit__, None, None, None)

    def test_concrete_flag_and_sandbox_preserved(self):
        command = launcher.browser_command("/usr/bin/chromium", "wayland", self.path)
        for flag in ("--ozone-platform=wayland", "--enable-logging=stderr"):
            self.assertIn(flag, command)
        for flag in ("--ozone-platform=auto", "--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"):
            self.assertNotIn(flag, command)

    def test_explicit_software_recovery_does_not_disable_sandbox(self):
        command = launcher.browser_command("chromium", "x11", self.path, True)
        self.assertIn("--ozone-platform=x11", command)
        self.assertIn("--disable-gpu", command)
        self.assertFalse(any("sandbox" in item for item in command))

    def test_prefers_wayland_session_over_available_x11(self):
        backend, path = launcher.display_socket("session", {
            "XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-1",
            "XDG_RUNTIME_DIR": "/run/user/1000", "DISPLAY": ":0"})
        self.assertEqual((backend, path), ("wayland", Path("/run/user/1000/wayland-1")))

    def test_x11_session_does_not_use_stale_wayland_variable(self):
        backend, path = launcher.display_socket("session", {
            "XDG_SESSION_TYPE": "x11", "WAYLAND_DISPLAY": "wayland-1", "DISPLAY": ":1.0"})
        self.assertEqual((backend, path), ("x11", Path("/tmp/.X11-unix/X1")))

    def test_explicit_x11_recovery(self):
        self.assertEqual(launcher.display_socket("x11", {"DISPLAY": ":0"})[0], "x11")

    def test_missing_or_invalid_display_is_diagnosed(self):
        for backend, env in [("session", {}), ("wayland", {"WAYLAND_DISPLAY": "wayland-0"}),
                             ("x11", {"DISPLAY": "untrusted.example:0"}), ("auto", {})]:
            with self.subTest(backend=backend, env=env):
                with self.assertRaises(launcher.StartupError) as error:
                    launcher.display_socket(backend, env)
                self.assertEqual((error.exception.category, error.exception.code), ("display", 78))

    def test_absolute_wayland_socket_supported(self):
        self.assertEqual(launcher.display_socket("wayland", {"WAYLAND_DISPLAY": "/tmp/display"})[1], Path("/tmp/display"))

    def test_real_wayland_style_socket_connects(self):
        path = self.path / "wayland-test"
        with self.unix_socket() as listener:
            listener.bind(str(path)); listener.listen()
            self.assertEqual(launcher.wait_for_display("wayland", {"WAYLAND_DISPLAY": str(path)}, .2), "wayland")
        self.assertIn("accepts connections", self.output.getvalue())

    def test_delayed_display_socket(self):
        path = self.path / "delayed-display"
        listener = self.unix_socket()
        self.addCleanup(listener.close)
        def start():
            listener.bind(str(path)); listener.listen()
        timer = threading.Timer(.04, start)
        timer.start()
        try:
            self.assertEqual(launcher.wait_for_display("wayland", {"WAYLAND_DISPLAY": str(path)}, 1), "wayland")
        finally:
            timer.join()

    def test_display_timeout_bounded(self):
        with self.assertRaises(launcher.StartupError) as error:
            launcher.wait_for_display("wayland", {"WAYLAND_DISPLAY": str(self.path / "missing")}, .01)
        self.assertEqual((error.exception.code, error.exception.category), (75, "display"))

    def test_regular_file_cannot_impersonate_display(self):
        path = self.path / "not-a-socket"; path.touch()
        with self.assertRaises(launcher.StartupError) as error:
            launcher.wait_for_display("wayland", {"WAYLAND_DISPLAY": str(path)}, .01)
        self.assertEqual(error.exception.code, 78)

    def test_foreign_wayland_socket_rejected(self):
        path = self.path / "foreign"
        info = SimpleNamespace(st_mode=stat.S_IFSOCK, st_uid=os.getuid() + 1)
        with patch.object(Path, "stat", return_value=info):
            with self.assertRaises(launcher.StartupError) as error:
                launcher.wait_for_display("wayland", {"WAYLAND_DISPLAY": str(path)}, .01)
            self.assertEqual(error.exception.code, 77)

    def test_mocked_display_connection_checks_socket(self):
        info = SimpleNamespace(st_mode=stat.S_IFSOCK, st_uid=os.getuid())
        connection = MagicMock()
        with patch.object(Path, "stat", return_value=info), patch.object(launcher.socket, "socket", return_value=connection):
            self.assertEqual(launcher.wait_for_display("wayland", {"WAYLAND_DISPLAY": "/tmp/test-wayland"}, 1), "wayland")
        connection.__enter__.return_value.connect.assert_called_once_with("/tmp/test-wayland")

    def test_profile_private_and_chromium_lock_not_deleted(self):
        profile = launcher.prepare_profile({"XDG_STATE_HOME": str(self.path)})
        self.assertEqual(profile.stat().st_mode & 0o777, 0o700)
        lock = profile / "SingletonLock"; lock.symlink_to("same-host-123")
        launcher.prepare_profile({"XDG_STATE_HOME": str(self.path)})
        self.assertEqual(os.readlink(lock), "same-host-123")
        self.assertEqual(list(profile.glob(".smilyai-write-check-*")), [])

    def test_profile_symlink_refused(self):
        (self.path / "smilyai-os").mkdir()
        target = self.path / "other"; target.mkdir()
        (self.path / "smilyai-os/chromium").symlink_to(target, target_is_directory=True)
        with self.assertRaises(launcher.StartupError) as error:
            launcher.prepare_profile({"XDG_STATE_HOME": str(self.path)})
        self.assertEqual((error.exception.category, error.exception.code), ("profile", 77))

    def test_profile_foreign_owner_refused(self):
        with patch.object(launcher.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaises(launcher.StartupError) as error:
                launcher.prepare_profile({"XDG_STATE_HOME": str(self.path)})
            self.assertEqual(error.exception.code, 77)

    def test_relative_profile_refused(self):
        with self.assertRaises(launcher.StartupError):
            launcher.prepare_profile({"XDG_STATE_HOME": "relative"})

    def test_missing_chromium_is_distinct(self):
        with patch.object(launcher.shutil, "which", return_value=None):
            with self.assertRaises(launcher.StartupError) as error: launcher.find_browser()
        self.assertEqual((error.exception.category, error.exception.code), ("browser", 69))

    def test_chromium_browser_package_variant(self):
        with patch.object(launcher.shutil, "which", side_effect=[None, "/usr/bin/chromium-browser"]):
            self.assertEqual(launcher.find_browser(), "/usr/bin/chromium-browser")

    def test_readiness_wait_tolerates_45_second_vm_start(self):
        clock = Clock(); opener = MagicMock()
        def request(*args, **kwargs):
            self.assertLessEqual(kwargs["timeout"], 2)
            if clock.now < 45: raise URLError("not listening yet")
            return Response(b'{"service":"smilyai-ui","ready":true}')
        opener.open.side_effect = request
        with patch.object(launcher, "build_opener", return_value=opener), \
             patch.object(launcher.time, "monotonic", clock.monotonic), \
             patch.object(launcher.time, "sleep", clock.sleep):
            launcher.wait_for_ui(90)
        self.assertEqual(clock.now, 45)

    def test_unavailable_ui_deadline_is_exact(self):
        clock = Clock(); opener = MagicMock()
        opener.open.side_effect = URLError("refused")
        with patch.object(launcher, "build_opener", return_value=opener), \
             patch.object(launcher.time, "monotonic", clock.monotonic), \
             patch.object(launcher.time, "sleep", clock.sleep):
            with self.assertRaises(launcher.StartupError) as error: launcher.wait_for_ui(2)
        self.assertEqual(clock.now, 2)
        self.assertEqual((error.exception.category, error.exception.code), ("ui", 75))

    def test_malformed_or_wrong_server_never_becomes_ready(self):
        for payload in [b"<html/>", b'{"service":"other","ready":true}', b'{"service":"smilyai-ui","ready":false}', b"[]", b"x" * 4097]:
            with self.subTest(payload=payload[:30]):
                clock = Clock(); opener = MagicMock()
                opener.open.side_effect = lambda *a, **k: Response(payload)
                with patch.object(launcher, "build_opener", return_value=opener), \
                     patch.object(launcher.time, "monotonic", clock.monotonic), \
                     patch.object(launcher.time, "sleep", clock.sleep):
                    with self.assertRaises(launcher.StartupError): launcher.wait_for_ui(.25)

    def test_readiness_redirect_is_not_followed(self):
        with self.assertRaises(launcher.StartupError):
            launcher.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example")

    def test_browser_exit_failure_retained_and_logged(self):
        self.assertEqual(launcher.run_browser([sys.executable, "-c", "raise SystemExit(42)"]), 42)
        self.assertIn("exit 42", self.output.getvalue())

    def test_browser_normal_exit_is_not_error(self):
        self.assertEqual(launcher.run_browser([sys.executable, "-c", "pass"]), 0)
        self.assertIn("no restart requested", self.output.getvalue())

    def test_browser_signal_failure_normalized(self):
        child = MagicMock(); child.wait.return_value = -signal.SIGSEGV
        with patch.object(launcher.subprocess, "Popen", return_value=child):
            self.assertEqual(launcher.run_browser(["chromium"]), 139)

    def test_browser_exec_failure_categorized(self):
        with patch.object(launcher.subprocess, "Popen", side_effect=FileNotFoundError):
            with self.assertRaises(launcher.StartupError) as error: launcher.run_browser(["chromium"])
        self.assertEqual(error.exception.category, "launch")

    def test_root_is_refused_without_launch(self):
        with patch.object(launcher.os, "geteuid", return_value=0), patch.object(launcher, "run_browser") as launch:
            self.assertEqual(launcher.main([]), 77); launch.assert_not_called()
        self.assertIn("[sandbox]", self.output.getvalue())

    def test_manual_entry_and_service_use_identical_launch_logic(self):
        with patch.object(launcher.os, "geteuid", return_value=1000), \
             patch.object(launcher, "find_browser", return_value="/usr/bin/chromium"), \
             patch.object(launcher.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "Chromium test", "")), \
             patch.object(launcher, "prepare_profile", return_value=self.path), \
             patch.object(launcher, "wait_for_display", return_value="wayland") as display, \
             patch.object(launcher, "wait_for_ui") as ready, \
             patch.object(launcher, "run_browser", return_value=0) as launch:
            self.assertEqual(launcher.main([]), 0)
            display.assert_called_once(); ready.assert_called_once()
            self.assertIn("--ozone-platform=wayland", launch.call_args.args[0])

    def test_diagnose_checks_without_browser_launch(self):
        with patch.object(launcher.os, "geteuid", return_value=1000), \
             patch.object(launcher, "find_browser", return_value="chromium"), \
             patch.object(launcher.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "test", "")), \
             patch.object(launcher, "prepare_profile", return_value=self.path), \
             patch.object(launcher, "wait_for_display", return_value="wayland"), \
             patch.object(launcher, "wait_for_ui"), patch.object(launcher, "run_browser") as launch:
            self.assertEqual(launcher.main(["--diagnose"]), 0); launch.assert_not_called()
        self.assertIn("does not verify", self.output.getvalue())

    def test_developer_entry_forwards_arguments(self):
        result = subprocess.run(["bash", str(ROOT / "scripts/launch-shell.sh"), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr); self.assertIn("--diagnose", result.stdout)

    def test_restart_policy_and_native_recovery_contract(self):
        units = ROOT / "packaging/rootfs/etc/systemd/user"
        shell = (units / "smilyai-shell.service").read_text(); ui = (units / "smilyai-ui.service").read_text()
        for unit in (shell, ui):
            self.assertIn("StartLimitIntervalSec=30min", unit); self.assertIn("StartLimitBurst=3", unit)
            self.assertNotIn("StartLimitIntervalSec=0", unit)
        self.assertIn("RestartSec=10", shell); self.assertIn("RestartPreventExitStatus=64 69 77 78", shell)
        self.assertIn("After=smilyai-ui.service", shell); self.assertIn("Type=notify", ui)
        self.assertIn("NotifyAccess=main", ui)
        recovery = (ROOT / "packaging/rootfs/usr/local/bin/smilyai-recover").read_text()
        self.assertLess(recovery.index("reset-failed"), recovery.index("--user restart"))
        for name in ("rc.xml", "menu.xml"):
            self.assertIn("smilyai-recover", (ROOT / "packaging/rootfs/etc/xdg/smilyai/labwc" / name).read_text())
        for name in ("packaging/image/debian/config/package-lists/smilyai.list.chroot",
                     "packaging/image/raspberrypi/stage-smily/00-install/00-packages"):
            self.assertIn("chromium-sandbox", (ROOT / name).read_text().splitlines())

    def test_environment_import_includes_xauthority_and_checks_failure(self):
        script = (ROOT / "packaging/rootfs/usr/local/bin/smilyai-session-environment").read_text()
        self.assertIn("import-environment WAYLAND_DISPLAY DISPLAY XAUTHORITY XDG_RUNTIME_DIR", script)
        self.assertIn("if ! systemctl", script)


if __name__ == "__main__": unittest.main()
