import asyncio
import tempfile
import unittest
from pathlib import Path

from smilyai.audit import AuditLog
from smilyai.agent import AgentRuntime
from smilyai.providers.base import AIProvider, ModelCapabilities
from smilyai.permissions import PermissionEngine, Risk
from smilyai.providers.mock import MockProvider
from smilyai.tools.registry import ToolRegistry, ToolSpec


class ProviderAgentTests(unittest.TestCase):
    def test_mock_emits_structured_tool_call(self):
        response = asyncio.run(MockProvider().chat([{"role": "user", "content": "What's using my memory?"}], []))
        self.assertEqual(response.tool_calls[0].name, "get_memory_usage")
        self.assertIsInstance(response.tool_calls[0].arguments, dict)

    def test_registry_executes_only_registered_schema(self):
        with tempfile.TemporaryDirectory() as root:
            registry = ToolRegistry(PermissionEngine(), AuditLog(Path(root, "audit.jsonl")))
            registry.register(ToolSpec("echo", "safe", {"properties": {"text": {"type": "string"}}, "required": ["text"]}, Risk.LOW, lambda text: {"text": text}, "Echo {text}"))
            self.assertEqual(registry.prepare("echo", {"text": "ok"})["data"]["text"], "ok")
            with self.assertRaises(ValueError):
                registry.prepare("shell", {"command": "id"})

    def test_failed_provider_does_not_infer_an_action(self):
        class FailingProvider(AIProvider):
            async def chat(self, messages, tools):
                raise RuntimeError("offline")
            async def models(self):
                return []
            def capabilities(self):
                return ModelCapabilities()

        with tempfile.TemporaryDirectory() as root:
            audit = AuditLog(Path(root, "audit.jsonl"))
            registry = ToolRegistry(PermissionEngine(), audit)
            registry.register(ToolSpec("get_memory_usage", "memory", {"properties": {"include_processes": {"type": "boolean", "default": True}, "limit": {"type": "integer", "default": 6}}, "required": []}, Risk.LOW, lambda **_: {"total": 1}, "memory"))
            result = asyncio.run(AgentRuntime(FailingProvider(), registry, audit).process("What's using my memory?"))
            self.assertEqual(result["status"], "provider_unavailable")
            self.assertNotIn("action", result)


if __name__ == "__main__":
    unittest.main()
