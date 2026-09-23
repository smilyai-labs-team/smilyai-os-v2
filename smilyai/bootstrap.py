from __future__ import annotations

from pathlib import Path

from .audit import AuditLog
from .config import ConfigStore
from .hardware.base import HardwareBackend
from .permissions import PermissionEngine, Risk
from .tools.files import FileTools, PathSandbox
from .tools.integration import NetworkTools, WindowTools
from .tools.registry import ToolRegistry, ToolSpec
from .tools.system import AppTools, PackageTools, SystemTools


def build_registry(config: ConfigStore, audit: AuditLog, permissions: PermissionEngine, hardware: HardwareBackend) -> ToolRegistry:
    settings = config.get()
    files = FileTools(PathSandbox(settings["security"].get("allowed_roots", ["~"])))
    system = SystemTools()
    apps = AppTools()
    # System desktop entries only; user-created launchers are not AI capabilities.
    packages = PackageTools()
    network = NetworkTools()
    windows = WindowTools()
    registry = ToolRegistry(permissions, audit)

    def add(name, description, properties, required, risk, handler, summary, enabled=lambda: True):
        registry.register(ToolSpec(name, description, {"properties": properties, "required": required, "additionalProperties": False}, risk, handler, summary, enabled))

    path = {"type": "string", "maxLength": 1024}
    limit = {"type": "integer", "minimum": 1, "maximum": 200, "default": 80}
    add("list_files", "List files and folders in an allowed location.", {"path": {**path, "default": "~"}, "limit": limit}, [], Risk.LOW, files.list_files, "List files in {path}")
    add("read_file", "Read a small text file; its contents may be sent to the configured AI provider.", {"path": path, "max_bytes": {"type": "integer", "minimum": 1, "maximum": 1048576, "default": 262144}}, ["path"], Risk.CONFIRM, files.read_file, "Read {path} and share its contents with the selected AI provider")
    add("create_folder", "Create a folder in an allowed user location.", {"path": path}, ["path"], Risk.LOW, files.create_folder, "Create folder {path}")
    add("move_file", "Move a file without overwriting.", {"source": path, "destination": path}, ["source", "destination"], Risk.CONFIRM, files.move_file, "Move {source} to {destination}")
    add("copy_file", "Copy one regular file without overwriting (up to 64 MiB).", {"source": path, "destination": path}, ["source", "destination"], Risk.LOW, files.copy_file, "Copy {source} to {destination}")
    add("rename_file", "Rename a file without overwriting.", {"source": path, "destination": path}, ["source", "destination"], Risk.CONFIRM, files.rename_file, "Rename {source} to {destination}")
    add("delete_file", "Move an item to Trash by default.", {"path": path, "permanent": {"type": "boolean", "default": False}}, ["path"], Risk.CONFIRM, files.delete_file, "Move {path} to Trash")
    add("search_files", "Search file names under an allowed location.", {"query": {"type": "string", "maxLength": 200}, "path": {**path, "default": "~"}, "limit": {**limit, "default": 50}}, ["query"], Risk.LOW, files.search_files, "Search for {query}")

    add("get_memory_usage", "Read memory usage and top processes.", {"include_processes": {"type": "boolean", "default": True}, "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 6}}, [], Risk.LOW, system.get_memory_usage, "Inspect memory usage")
    add("get_cpu_usage", "Read CPU load and temperature.", {}, [], Risk.LOW, system.get_cpu_usage, "Inspect CPU usage")
    add("get_disk_usage", "Read disk usage.", {"path": {**path, "default": "~"}}, [], Risk.LOW, system.get_disk_usage, "Inspect disk usage")
    add("get_system_info", "Read basic operating system information.", {}, [], Risk.LOW, system.get_system_info, "Inspect system information")
    add("get_battery_status", "Read battery charge state.", {}, [], Risk.LOW, system.get_battery_status, "Inspect battery status")
    add("set_volume", "Set default output volume.", {"level": {"type": "integer", "minimum": 0, "maximum": 100}}, ["level"], Risk.LOW, system.set_volume, "Set volume to {level}%")
    add("set_brightness", "Set display brightness.", {"level": {"type": "integer", "minimum": 1, "maximum": 100}}, ["level"], Risk.LOW, system.set_brightness, "Set brightness to {level}%")
    add("take_screenshot", "Capture the current desktop.", {}, [], Risk.CONFIRM, system.take_screenshot, "Capture visible screen contents")
    add("restart", "Restart the computer.", {}, [], Risk.ADMIN, system.restart, "Restart the computer")
    add("shutdown", "Shut down the computer.", {}, [], Risk.ADMIN, system.shutdown, "Shut down the computer")

    add("open_app", "Launch an installed desktop application by its desktop entry.", {"app": {"type": "string", "maxLength": 120}}, ["app"], Risk.LOW, apps.open_app, "Open {app}")
    add("list_applications", "List installed system applications.", {}, [], Risk.LOW, apps.list_applications, "List applications")
    add("list_running_apps", "List the current user's running processes.", {}, [], Risk.LOW, apps.list_running_apps, "List running applications")
    add("open_url", "Open an HTTP or HTTPS URL.", {"url": {"type": "string", "maxLength": 2048}}, ["url"], Risk.LOW, apps.open_url, "Open {url}")
    add("search_package", "Search Debian package metadata.", {"name": {"type": "string", "maxLength": 100}}, ["name"], Risk.LOW, packages.search_package, "Search packages for {name}")
    add("install_package", "Install one validated Debian package using a graphical privilege prompt.", {"name": {"type": "string", "maxLength": 100}}, ["name"], Risk.CONFIRM, packages.install_package, "Install package {name}")
    # Package removal is deliberately not exposed until dependency previews exist.

    add("get_network_status", "Read network connection state.", {}, [], Risk.LOW, network.get_network_status, "Inspect network status")
    add("list_wifi_networks", "Scan visible Wi-Fi networks.", {}, [], Risk.LOW, network.list_wifi_networks, "Scan Wi-Fi networks", network.available)
    add("open_network_settings", "Open the native network chooser; enter Wi-Fi credentials there, never in AI chat.", {}, [], Risk.LOW, network.open_settings, "Open network settings", network.available)

    add("list_windows", "List application windows using Sway or X11 tooling.", {}, [], Risk.LOW, windows.list_windows, "List windows", windows.available)
    add("focus_window", "Focus a named window.", {"title": {"type": "string", "maxLength": 200}}, ["title"], Risk.LOW, windows.focus_window, "Focus {title}", windows.available)
    add("close_window", "Close a named window.", {"title": {"type": "string", "maxLength": 200}}, ["title"], Risk.CONFIRM, windows.close_window, "Close {title}", windows.available)
    add("tile_window", "Tile a named Sway window left or right.", {"title": {"type": "string", "maxLength": 200}, "side": {"type": "string", "enum": ["left", "right"]}}, ["title", "side"], Risk.LOW, windows.tile_window, "Tile {title} to the {side}", windows.available)

    caps = hardware.capabilities()
    add("gpio_read", "Read a Raspberry Pi BCM GPIO pin.", {"pin": {"type": "integer", "minimum": 0, "maximum": 27}}, ["pin"], Risk.LOW, hardware.gpio_read, "Read GPIO {pin}", lambda: caps.gpio)
    add("gpio_write", "Write a Raspberry Pi BCM GPIO pin.", {"pin": {"type": "integer", "minimum": 0, "maximum": 27}, "value": {"type": "integer", "enum": [0, 1]}}, ["pin", "value"], Risk.CONFIRM, hardware.gpio_write, "Set GPIO {pin} to {value}", lambda: caps.gpio)
    add("camera_capture", "Capture an image with a Raspberry Pi camera.", {"path": {**path, "default": "~/Pictures/SmilyAI-camera.jpg"}}, [], Risk.CONFIRM, hardware.camera_capture, "Capture an image to {path}", lambda: caps.camera)
    return registry
