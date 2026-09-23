from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..audit import AuditLog
from ..permissions import PermissionEngine, Risk
from .schema import validate


ToolHandler = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    schema: dict[str, Any]
    risk: Risk
    handler: ToolHandler
    summary: str
    enabled: Callable[[], bool] = lambda: True

    def provider_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": {"type": "object", **self.schema}},
        }


class ToolRegistry:
    def __init__(self, permissions: PermissionEngine, audit: AuditLog):
        self.permissions = permissions
        self.audit = audit
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Duplicate tool: {spec.name}")
        self._tools[spec.name] = spec

    def schemas(self) -> list[dict[str, Any]]:
        return [spec.provider_schema() for spec in self._tools.values() if spec.enabled()]

    def describe(self) -> list[dict[str, Any]]:
        return [{"name": spec.name, "risk": spec.risk.value, "enabled": spec.enabled()} for spec in self._tools.values()]

    def prepare(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        spec = self._tools.get(name)
        if not spec:
            raise ValueError("The model requested an unregistered tool")
        if not spec.enabled():
            raise RuntimeError(f"{name} is not available on this hardware")
        clean = validate(arguments, spec.schema)
        if name == "delete_file" and clean.get("permanent"):
            raise PermissionError("Permanent deletion is not exposed to the AI")
        risk = Risk.ADMIN if name in {"install_package", "remove_package", "delete_file"} else spec.risk
        decision = self.permissions.evaluate(name, clean, risk, spec.summary.format(**clean))
        if decision["allowed"]:
            return self.execute(name, clean)
        self.audit.write("permission_requested", tool=name, arguments=clean, risk=spec.risk.value)
        return {"status": "confirmation_required", **decision}

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        spec = self._tools[name]
        arguments = validate(arguments, spec.schema)
        if not spec.enabled():
            return {"status": "error", "tool": name, "error": "Capability is no longer available"}
        self.audit.write("tool_started", tool=name, arguments=arguments)
        try:
            data = spec.handler(**arguments)
            result = {"status": "success", "tool": name, "data": data}
            self.audit.write("tool_finished", tool=name, success=True, result=data)
            return result
        except Exception as exc:
            self.audit.write("tool_finished", tool=name, success=False, error=str(exc))
            return {"status": "error", "tool": name, "error": str(exc)}

    def confirm(self, token: str, approved: bool, phrase: str | None = None) -> dict[str, Any]:
        request = self.permissions.consume(token, approved, phrase)
        if not request:
            self.audit.write("permission_decided", token=token, approved=False)
            return {"status": "cancelled", "message": "Action cancelled or confirmation expired."}
        self.audit.write("permission_decided", tool=request.tool, approved=True)
        return self.execute(request.tool, request.arguments)
