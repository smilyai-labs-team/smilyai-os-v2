from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from .base import AIProvider, ModelCapabilities, ProviderResponse, ToolCall


class MockProvider(AIProvider):
    """Deterministic offline intent simulator used until a provider is configured."""

    name = "mock"

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ProviderResponse:
        text = str(messages[-1].get("content", "")).strip()
        lower = text.lower()
        call: ToolCall | None = None

        folder = re.search(r"(?:folder|directory)(?: called| named)?\s+[\"']?([^\"']+?)[\"']?\s+(?:in|inside)\s+(?:my\s+)?(home|downloads|desktop)", text, re.I)
        if not folder:
            folder = re.search(r"create (?:a )?(?:folder|directory)(?: called| named)?\s+[\"']?([^\"']+?)[\"']?(?:\s+in my home(?: directory)?)?$", text, re.I)
        if folder:
            name = _clean_name(folder.group(1))
            location = folder.group(2).lower() if folder.lastindex and folder.lastindex >= 2 and folder.group(2) else "home"
            base = {"home": "~", "downloads": "~/Downloads", "desktop": "~/Desktop"}[location]
            call = _call("create_folder", {"path": str(Path(base) / name)})
        elif "memory" in lower or "ram" in lower:
            call = _call("get_memory_usage", {"include_processes": True, "limit": 6})
        elif lower in {"show my files", "show files", "files"}:
            call = _call("list_files", {"path": "~", "limit": 80})
        elif lower in {"restart", "restart the computer", "shutdown", "shut down"}:
            call = _call("restart" if lower.startswith("restart") else "shutdown", {})
        elif "network" in lower or "wi-fi" in lower or "wifi" in lower:
            call = _call("open_network_settings", {})
        elif lower.startswith("open "):
            target = text[5:].strip().rstrip(".")
            if target.startswith(("http://", "https://")):
                call = _call("open_url", {"url": target})
            elif target.lower() in {"files", "my files", "file manager"}:
                call = _call("list_files", {"path": "~", "limit": 80})
            elif target.lower() in {"settings", "ai settings"}:
                return ProviderResponse(text="Opening settings.", raw_metadata={"surface": "settings"})
            else:
                call = _call("open_app", {"app": target})
        elif "cpu" in lower:
            call = _call("get_cpu_usage", {})
        elif "disk" in lower or "storage" in lower:
            call = _call("get_disk_usage", {"path": "~"})
        elif "battery" in lower:
            call = _call("get_battery_status", {})
        elif "system info" in lower or "about this computer" in lower:
            call = _call("get_system_info", {})
        elif "volume" in lower:
            amount = re.search(r"(\d{1,3})\s*%?", lower)
            call = _call("set_volume", {"level": min(int(amount.group(1)) if amount else 40, 100)})
        elif "screenshot" in lower:
            call = _call("take_screenshot", {})
        elif lower.startswith("install "):
            call = _call("install_package", {"name": text[8:].strip()})
        elif "gpio" in lower:
            pin = re.search(r"gpio\s*(\d+)", lower)
            value = 1 if re.search(r"\b(on|high)\b|(?:to|=)\s*1\b", lower) else 0
            call = _call("gpio_write", {"pin": int(pin.group(1)) if pin else 17, "value": value})

        if call:
            return ProviderResponse(tool_calls=[call], raw_metadata={"simulated_provider": True})
        return ProviderResponse(
            text="I can open apps, manage files, inspect this computer, adjust sound, and use supported Raspberry Pi hardware. Try “What’s using my memory?”",
            raw_metadata={"simulated_provider": True},
        )

    async def models(self) -> list[str]:
        return ["smily-simulator"]

    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(streaming=True, tool_calling=True, context_tokens=8192)


def _call(name: str, arguments: dict[str, Any]) -> ToolCall:
    return ToolCall(name=name, arguments=arguments, call_id=str(uuid.uuid4()))


def _clean_name(value: str) -> str:
    return value.strip().strip(". ").replace("/", "-")[:120] or "New Folder"
