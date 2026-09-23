"""Checked Chromium session launch. No shell commands or sandbox bypasses.

Both installed and developer entry points call this module. Exit codes:
69 missing program, 75 readiness failure, 77 unsafe user/profile, 78 bad config.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

URL = "http://127.0.0.1:47810/"
UI_TIMEOUT = 90.0
DISPLAY_TIMEOUT = 30.0


class StartupError(Exception):
    def __init__(self, category: str, message: str, code: int = 75):
        super().__init__(message)
        self.category, self.code = category, code


def log(category: str, message: str):
    print(f"smilyai-shell [{category}] {message}", file=sys.stderr, flush=True)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise StartupError("ui", "Readiness endpoint redirected; refusing an unexpected server")


def wait_for_ui(timeout: float = UI_TIMEOUT):
    """Bounded monotonic wait for static assets, never AI/provider readiness."""
    opener = build_opener(ProxyHandler({}), NoRedirect())
    deadline = time.monotonic() + timeout
    reason = "not responding"
    log("ui", f"Waiting up to {timeout:g}s for {URL}readyz (no AI/network dependency)")
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise StartupError("ui", f"UI server unavailable after {timeout:g}s: {reason}")
        try:
            with opener.open(Request(URL + "readyz"), timeout=min(2.0, remaining)) as response:
                payload = response.read(4097)
                if len(payload) > 4096:
                    raise ValueError("oversized readiness response")
                data = json.loads(payload)
                if response.status == 200 and isinstance(data, dict) and data.get("service") == "smilyai-ui" and data.get("ready") is True:
                    log("ui", "Static shell server is ready")
                    return
                reason = "unexpected readiness response"
        except (URLError, OSError, ValueError) as error:
            reason = type(error).__name__
        time.sleep(min(0.25, max(0, deadline - time.monotonic())))


def find_browser():
    for name in ("chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    raise StartupError("browser", "Chromium missing: install the distribution chromium package", 69)


def display_socket(platform: str, env) -> tuple[str, Path]:
    """Only concrete Ozone backends are valid: auto is NOT a backend."""
    if platform == "session":
        if env.get("XDG_SESSION_TYPE") == "x11":
            platform = "x11"
        elif env.get("WAYLAND_DISPLAY") or env.get("XDG_SESSION_TYPE") == "wayland":
            platform = "wayland"
        elif env.get("DISPLAY"):
            platform = "x11"
        else:
            raise StartupError("display", "No compositor environment. Run from a labwc terminal, not a root/SSH shell.", 78)
    if platform == "wayland":
        display = env.get("WAYLAND_DISPLAY", "")
        runtime = env.get("XDG_RUNTIME_DIR", "")
        if not display or (not display.startswith("/") and not runtime.startswith("/")):
            raise StartupError("display", "WAYLAND_DISPLAY or absolute XDG_RUNTIME_DIR missing; session environment was not imported", 78)
        path = Path(display) if display.startswith("/") else Path(runtime) / display
        return platform, path
    if platform != "x11":
        raise StartupError("display", "Ozone platform must be wayland or x11", 78)
    display = env.get("DISPLAY", "")
    match = re.fullmatch(r"(?:unix/)?:(\d+)(?:\.\d+)?", display)
    if not match:
        raise StartupError("display", "X11 recovery requires a local DISPLAY such as :0; start XWayland first", 78)
    return "x11", Path("/tmp/.X11-unix") / ("X" + match[1])


def wait_for_display(platform: str, env, timeout: float = DISPLAY_TIMEOUT):
    platform, path = display_socket(platform, env)
    deadline = time.monotonic() + timeout
    reason = "socket absent"
    log("display", f"Selected {platform}; checking compositor socket {path}")
    while True:
        try:
            info = path.stat()
            if not stat.S_ISSOCK(info.st_mode):
                raise StartupError("display", f"Display path is not a socket: {path}", 78)
            if platform == "wayland" and info.st_uid != os.getuid():
                raise StartupError("display", "Wayland socket belongs to another user", 77)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(min(1.0, max(.01, deadline - time.monotonic())))
                connection.connect(str(path))
            log("display", "Compositor socket accepts connections")
            return platform
        except OSError as error:
            reason = type(error).__name__
        if time.monotonic() >= deadline:
            raise StartupError("display", f"{platform} unavailable after {timeout:g}s ({reason}); inspect imported display variables")
        time.sleep(min(.25, max(0, deadline - time.monotonic())))


def prepare_profile(env):
    state = env.get("XDG_STATE_HOME") or str(Path(env.get("HOME", "")) / ".local/state")
    if not Path(state).is_absolute():
        raise StartupError("profile", "HOME/XDG_STATE_HOME must identify an absolute user directory", 78)
    profile = Path(state) / "smilyai-os/chromium"
    try:
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(profile, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if os.fstat(fd).st_uid != os.getuid():
                raise StartupError("profile", "Profile belongs to another user; do not launch the shell with sudo", 77)
            os.fchmod(fd, 0o700)
            name = f".smilyai-write-check-{os.getpid()}"
            probe = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            os.close(probe)
            os.unlink(name, dir_fd=fd)
        finally:
            os.close(fd)
    except OSError as error:
        raise StartupError("profile", f"Profile cannot be used ({type(error).__name__}): {profile}. Nothing was deleted.", 77) from error
    log("profile", f"Owner-only writable profile: {profile}")
    return profile


def browser_command(browser, platform, profile, software_rendering=False):
    command = [browser, f"--app={URL}", "--class=smilyai-shell", "--start-maximized",
               "--no-first-run", "--disable-session-crashed-bubble", "--disable-features=Translate",
               f"--ozone-platform={platform}", f"--user-data-dir={profile}",
               "--enable-logging=stderr", "--log-level=1"]
    if software_rendering:
        # Explicit troubleshooting only. CSS fallback remains usable without WebGL.
        command.append("--disable-gpu")
    return command


def run_browser(command):
    started = time.monotonic()
    try:
        child = subprocess.Popen(command)
    except OSError as error:
        raise StartupError("launch", f"Chromium could not execute ({type(error).__name__}); check runtime libraries and package integrity", 69) from error
    stopping = False

    def forward(signum, frame):
        nonlocal stopping
        stopping = True
        if child.poll() is None:
            child.send_signal(signum)

    previous = {number: signal.signal(number, forward) for number in (signal.SIGTERM, signal.SIGINT)}
    try:
        code = child.wait()
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
    elapsed = time.monotonic() - started
    if stopping:
        log("launch", "Chromium stopped by user/session")
        return 0
    if code == 0:
        log("launch", f"Chromium exited normally after {elapsed:.1f}s (or handed off to an existing profile); no restart requested")
        return 0
    log("launch", f"Chromium failed after {elapsed:.1f}s: {'signal ' + str(-code) if code < 0 else 'exit ' + str(code)}. Chromium stderr above contains the cause.")
    log("recovery", "Sandbox remains enabled. Try --diagnose; use --platform=x11 or --software-rendering only for a targeted display/GPU test.")
    return min(255, 128 - code if code < 0 else code)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("session", "wayland", "x11"), default="session")
    parser.add_argument("--software-rendering", action="store_true", help="Explicit GPU troubleshooting; never disables sandboxing")
    parser.add_argument("--diagnose", action="store_true", help="Check executable, profile, display and UI without launching Chromium")
    args = parser.parse_args(argv)
    try:
        if os.geteuid() == 0:
            raise StartupError("sandbox", "Refusing a root browser. Run as the logged-in desktop user without sudo; no sandbox bypass is offered.", 77)
        browser = find_browser()
        log("browser", f"Found {browser}; Chromium sandbox stays enabled")
        try:
            version = subprocess.run([browser, "--version"], text=True, capture_output=True, timeout=5)
            log("browser", version.stdout.strip()[:200] or f"Version probe exited {version.returncode}; launch diagnostics will follow")
        except (OSError, subprocess.TimeoutExpired):
            log("browser", "Version probe unavailable; continuing with checked launch")
        profile = prepare_profile(os.environ)
        platform = wait_for_display(args.platform, os.environ)
        wait_for_ui()
        if args.diagnose:
            log("ready", "Preflight passed. No browser was launched; this does not verify that a window is visible.")
            return 0
        command = browser_command(browser, platform, profile, args.software_rendering)
        log("launch", f"Launching Chromium: platform={platform}, software_rendering={args.software_rendering}. Errors are sent to this terminal/journal.")
        return run_browser(command)
    except StartupError as error:
        log(error.category, str(error))
        log("recovery", "Native desktop remains available: Super+Return terminal, Super+E files, Super+R retry. Journal: journalctl --user -b -u smilyai-shell -u smilyai-ui")
        return error.code


if __name__ == "__main__":
    raise SystemExit(main())
