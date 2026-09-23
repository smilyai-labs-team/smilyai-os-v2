from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time
import urllib.parse
import re
from pathlib import Path
from typing import Any


def _run(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)


class SystemTools:
    def get_memory_usage(self, include_processes: bool = True, limit: int = 6) -> dict[str, Any]:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", 0)
        used = total - available
        processes = []
        if include_processes:
            result = _run(["ps", "-eo", "pid=,comm=,rss=", "--sort=-rss"])
            for line in result.stdout.splitlines()[:limit]:
                parts = line.split(None, 2)
                if len(parts) == 3:
                    processes.append({"pid": int(parts[0]), "name": parts[1], "bytes": int(parts[2]) * 1024})
        return {"total": total, "used": used, "available": available, "percent": round(used / total * 100, 1) if total else 0, "processes": processes, "surface": "memory"}

    def get_cpu_usage(self) -> dict[str, Any]:
        load1, load5, load15 = os.getloadavg()
        cores = os.cpu_count() or 1
        temp = None
        thermal = Path("/sys/class/thermal/thermal_zone0/temp")
        if thermal.exists():
            try:
                temp = round(int(thermal.read_text().strip()) / 1000, 1)
            except ValueError:
                pass
        return {"cores": cores, "load": [round(load1, 2), round(load5, 2), round(load15, 2)], "estimated_percent": min(round(load1 / cores * 100, 1), 100), "temperature_c": temp, "surface": "cpu"}

    def get_disk_usage(self, path: str = "~") -> dict[str, Any]:
        target = Path(os.path.expanduser(path)).resolve()
        usage = shutil.disk_usage(target)
        return {"path": str(target), "total": usage.total, "used": usage.used, "free": usage.free, "percent": round(usage.used / usage.total * 100, 1), "surface": "disk"}

    def get_system_info(self) -> dict[str, Any]:
        os_release = {}
        release = Path("/etc/os-release")
        if release.exists():
            for line in release.read_text(errors="replace").splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    os_release[key] = value.strip('"')
        return {"os": os_release.get("PRETTY_NAME", platform.system()), "kernel": platform.release(), "architecture": platform.machine(), "hostname": platform.node(), "python": platform.python_version(), "surface": "system"}

    def get_battery_status(self) -> dict[str, Any]:
        batteries = list(Path("/sys/class/power_supply").glob("BAT*"))
        if not batteries:
            return {"present": False, "surface": "battery"}
        battery = batteries[0]
        return {"present": True, "percent": _read_int(battery / "capacity"), "status": _read_text(battery / "status"), "surface": "battery"}

    def set_volume(self, level: int) -> dict[str, Any]:
        if shutil.which("wpctl"):
            result = _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level}%"])
        elif shutil.which("pactl"):
            result = _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"])
        else:
            raise RuntimeError("No supported audio control service was found")
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "Volume change failed")
        return {"level": level}

    def set_brightness(self, level: int) -> dict[str, Any]:
        command = shutil.which("brightnessctl")
        if not command:
            raise RuntimeError("brightnessctl is not installed")
        result = _run([command, "set", f"{level}%"])
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "Brightness change failed")
        return {"level": level}

    def take_screenshot(self) -> dict[str, Any]:
        output = Path.home() / "Pictures" / f"Screenshot-{time.strftime('%Y%m%d-%H%M%S')}.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        if shutil.which("grim"):
            args = ["grim", str(output)]
        elif shutil.which("gnome-screenshot"):
            args = ["gnome-screenshot", "-f", str(output)]
        else:
            raise RuntimeError("Install grim or gnome-screenshot for screenshots")
        result = _run(args)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "Screenshot failed")
        return {"path": str(output), "surface": "success"}

    def restart(self) -> dict[str, Any]:
        return self._power("reboot")

    def shutdown(self) -> dict[str, Any]:
        return self._power("poweroff")

    @staticmethod
    def _power(action: str) -> dict[str, Any]:
        result = _run(["systemctl", action])
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or f"Could not {action}")
        return {"requested": action}


class AppTools:
    def __init__(self):
        self._apps: dict[str, str] = {}
        self.refresh()

    def refresh(self) -> None:
        paths = [Path("/usr/local/share/applications"), Path("/usr/share/applications")]
        apps: dict[str, str] = {}
        for root in paths:
            if not root.exists():
                continue
            for file in root.glob("*.desktop"):
                name = file.stem
                try:
                    for line in file.read_text(errors="replace").splitlines():
                        if line.startswith("Name="):
                            name = line[5:]
                            break
                except OSError:
                    continue
                apps.setdefault(name.casefold(), str(file))
                apps.setdefault(file.stem.casefold(), str(file))
        self._apps = apps

    def open_app(self, app: str) -> dict[str, Any]:
        self.refresh()
        key = app.casefold().removesuffix(" app")
        key = {"terminal": "foot", "files": "thunar", "network": "advanced network configuration"}.get(key, key)
        if not key.strip():
            raise ValueError("Choose an application")
        desktop_id = self._apps.get(key)
        if not desktop_id:
            candidates = [(name, value) for name, value in self._apps.items() if key in name]
            if candidates:
                desktop_id = sorted(candidates, key=lambda item: len(item[0]))[0][1]
        if not desktop_id:
            return {"launched": False, "installed": False, "app": app, "surface": "app_missing"}
        launcher = shutil.which("gio")
        if not launcher:
            raise RuntimeError("gio is unavailable")
        result = _run([launcher, "launch", desktop_id], timeout=5)
        if result.returncode:
            raise RuntimeError("Application launch failed; use the native launcher")
        return {"launched": True, "installed": True, "app": app, "desktop_id": desktop_id}

    def list_applications(self):
        self.refresh()
        seen = set()
        items = []
        for name, path in self._apps.items():
            if path not in seen:
                seen.add(path)
                items.append({"name": name, "desktop": Path(path).name})
        return {"surface": "apps", "items": items[:150]}

    def list_running_apps(self) -> dict[str, Any]:
        result = _run(["ps", "-u", str(os.getuid()), "-o", "pid=,comm="])
        processes = []
        for line in result.stdout.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                processes.append({"pid": int(parts[0]), "name": parts[1]})
        return {"processes": processes[:100]}

    def open_url(self, url: str) -> dict[str, Any]:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Only http and https URLs are allowed")
        result = _run(["xdg-open", url], timeout=5)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "Could not open URL")
        return {"opened": url}


class PackageTools:
    def search_package(self, name: str) -> dict[str, Any]:
        if not shutil.which("apt-cache"):
            raise RuntimeError("APT is unavailable")
        result = _run(["apt-cache", "search", "--names-only", "--", _safe_package(name)])
        packages = []
        for line in result.stdout.splitlines()[:30]:
            package, _, description = line.partition(" - ")
            packages.append({"name": package, "description": description})
        return {"query": name, "packages": packages, "surface": "packages"}

    def install_package(self, name: str) -> dict[str, Any]:
        package = _safe_package(name)
        # PackageKit talks to the system daemon; no setuid child or root shell.
        command = ["pkcon", "--noninteractive", "install", package]
        result = _run(command, timeout=1800)
        if result.returncode:
            raise RuntimeError(result.stderr.strip()[-1000:] or "Package installation failed")
        return {"package": package, "installed": True}

    def remove_package(self, name: str) -> dict[str, Any]:
        raise PermissionError("Remove packages with the native package manager; AI removal is disabled")


def _safe_package(name: str) -> str:
    value = name.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]{1,99}", value):
        raise ValueError("Invalid package name")
    return value


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None
