from __future__ import annotations

import json
import shutil
import subprocess
import os
import re
from typing import Any


def _run(args: list[str], timeout: int = 25) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)


class NetworkTools:
    def open_settings(self):
        subprocess.Popen(["nm-connection-editor"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"opened": True}
    def available(self) -> bool:
        return bool(shutil.which("nmcli"))

    def get_network_status(self) -> dict[str, Any]:
        if not self.available():
            return {"available": False, "connected": False, "surface": "network"}
        result = _run(["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "device", "status"])
        devices = []
        for line in result.stdout.splitlines():
            parts = line.split(":", 2)
            if len(parts) == 3:
                devices.append({"type": parts[0], "state": parts[1], "connection": parts[2]})
        return {"available": True, "connected": any(d["state"] == "connected" for d in devices), "devices": devices, "surface": "network"}

    def list_wifi_networks(self) -> dict[str, Any]:
        if not self.available():
            raise RuntimeError("NetworkManager is not available")
        result = _run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE", "device", "wifi", "list", "--rescan", "auto"])
        networks = []
        for line in result.stdout.splitlines():
            parts = re.split(r"(?<!\\):", line, maxsplit=3)
            if len(parts) == 4 and parts[0]:
                networks.append({"ssid": parts[0], "signal": int(parts[1] or 0), "security": parts[2], "connected": parts[3] == "*"})
        return {"networks": networks[:40], "surface": "wifi"}

    def connect_wifi(self, ssid: str, password: str = "") -> dict[str, Any]:
        if not self.available():
            raise RuntimeError("NetworkManager is not available")
        args = ["nmcli", "device", "wifi", "connect", ssid]
        if password:
            args.extend(["password", password])
        result = _run(args, timeout=60)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "Wi-Fi connection failed")
        return {"ssid": ssid, "connected": True}


class WindowTools:
    def available(self) -> bool:
        return bool((os.environ.get("SWAYSOCK") and shutil.which("swaymsg")) or (os.environ.get("DISPLAY") and shutil.which("wmctrl")))

    def list_windows(self) -> dict[str, Any]:
        if os.environ.get("SWAYSOCK") and shutil.which("swaymsg"):
            result = _run(["swaymsg", "-t", "get_tree", "-r"])
            tree = json.loads(result.stdout or "{}")
            windows = []
            _walk_sway(tree, windows)
            return {"backend": "sway", "windows": windows, "surface": "windows"}
        if shutil.which("wmctrl"):
            result = _run(["wmctrl", "-lx"])
            windows = [{"id": line.split(None, 1)[0], "title": line.split(None, 4)[-1]} for line in result.stdout.splitlines() if line.strip()]
            return {"backend": "x11", "windows": windows, "surface": "windows"}
        raise RuntimeError("No supported window-control backend was found")

    def focus_window(self, title: str) -> dict[str, Any]:
        return self._act(title, "focus")

    def close_window(self, title: str) -> dict[str, Any]:
        return self._act(title, "kill")

    def tile_window(self, title: str, side: str) -> dict[str, Any]:
        if os.environ.get("SWAYSOCK") and shutil.which("swaymsg"):
            direction = "left" if side == "left" else "right"
            result = _run(["swaymsg", f"[title=\"{_sway_escape(title)}\"]", "focus", ",", "move", direction])
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or "Window tiling failed")
            return {"title": title, "side": side}
        raise RuntimeError("Precise tiling currently requires Sway")

    def _act(self, title: str, action: str) -> dict[str, Any]:
        if os.environ.get("SWAYSOCK") and shutil.which("swaymsg"):
            result = _run(["swaymsg", f"[title=\"{_sway_escape(title)}\"]", action])
        elif shutil.which("wmctrl"):
            flag = "-a" if action == "focus" else "-c"
            result = _run(["wmctrl", flag, title])
        else:
            raise RuntimeError("No supported window-control backend was found")
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "Window action failed")
        return {"title": title, "action": action}


def _walk_sway(node: dict[str, Any], output: list[dict[str, Any]]) -> None:
    if node.get("app_id") or node.get("window_properties"):
        output.append({"id": node.get("id"), "app_id": node.get("app_id"), "title": node.get("name")})
    for child in node.get("nodes", []) + node.get("floating_nodes", []):
        _walk_sway(child, output)


def _sway_escape(value: str) -> str:
    # Literal anchored title, not a model-controlled regular expression.
    return ("^" + re.escape(value[:200]) + "$").replace("\\", "\\\\").replace('"', '\\"')
