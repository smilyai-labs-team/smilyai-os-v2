import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from smilyai.config import ConfigStore, SecretStore, validate_config
from smilyai.audit import AuditLog
from smilyai.permissions import PermissionEngine, Risk
from smilyai.tools.files import FileTools, PathSandbox
from smilyai.tools.registry import ToolRegistry, ToolSpec
from smilyai.providers.base import ProviderResponse, ToolCall
from smilyai.agent import AgentRuntime

class ConfigSecurityTests(unittest.TestCase):
    def test_first_and_subsequent_boot(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"config.json"
            self.assertFalse(ConfigStore(p).get()["setup_complete"])
            ConfigStore(p).update({"setup_complete":True,"provider":{"kind":"smilyai","model":"user-model"}})
            self.assertTrue(ConfigStore(p).get()["setup_complete"])
            self.assertEqual(ConfigStore(p).get()["provider"]["kind"],"smilyai")
    def test_malformed_config_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"config.json";p.write_text("{bad")
            self.assertFalse(ConfigStore(p).get()["setup_complete"])
    def test_reject_secret_and_bad_types(self):
        for config in [{"provider":{"api_key":"secret"}},{"privacy":{"microphone":"false"}},{"setup_complete":1},{"unknown":{}},{"voice":{"wake_word":True}}]:
            with self.subTest(config=config),self.assertRaises(ValueError):validate_config(config)
    def test_stt_must_be_local(self):
        with self.assertRaises(ValueError):validate_config({"voice":{"stt_url":"https://cloud.example/inference"}})
        validate_config({"voice":{"stt_url":"http://127.0.0.1:8080/inference"}})
    def test_save_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            c=ConfigStore(Path(d)/"config.json")
            with patch.object(c,"save",side_effect=OSError),self.assertRaises(OSError):c.update({"setup_complete":True})
            self.assertFalse(c.get()["setup_complete"])
    def test_no_keyring_memory_only(self):
        with patch("smilyai.config.shutil.which",return_value=None):
            s=SecretStore();s.set("scope","test-key")
            self.assertEqual(s.get("scope"),"test-key");self.assertFalse(s.persistent)
            s.delete("scope");self.assertIsNone(s.get("scope"))
    def test_audit_redaction(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"audit"
            AuditLog(p).write("test",api_key="KEY",text="PRIVATE",result={"content":"CONTENT"})
            payload=p.read_text()
            for secret in ["KEY","PRIVATE","CONTENT"]:self.assertNotIn(secret,payload)
    def test_permission_arguments_are_immutable(self):
        engine=PermissionEngine();args={"path":"safe"}
        request=engine.evaluate("move_file",args,Risk.CONFIRM,"Move")
        args["path"]="changed"
        accepted=engine.consume(request["confirmation"]["token"],True)
        self.assertEqual(accepted.arguments["path"],"safe")
    def test_permission_expires(self):
        engine=PermissionEngine(ttl_seconds=-1)
        req=engine.evaluate("x",{},Risk.CONFIRM,"x")
        self.assertIsNone(engine.consume(req["confirmation"]["token"],True))

class FilesSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.tools=FileTools(PathSandbox([str(self.root)]))
    def test_hidden_and_parent_paths_blocked(self):
        for p in [self.root/".ssh/key",self.root/"folder/../target"]:
            with self.subTest(path=p),self.assertRaises(PermissionError):self.tools.sandbox.resolve(str(p))
    def test_copy_no_overwrite(self):
        a=self.root/"a";b=self.root/"b";a.write_text("a");b.write_text("b")
        with self.assertRaises(FileExistsError):self.tools.copy_file(str(a),str(b))
        self.assertEqual(b.read_text(),"b")
    def test_move_no_overwrite(self):
        a=self.root/"a";b=self.root/"b";a.write_text("a");b.write_text("b")
        with self.assertRaises(FileExistsError):self.tools.move_file(str(a),str(b))
        self.assertEqual(a.read_text(),"a")
    def test_recursive_copy_disabled(self):
        p=self.root/"folder";p.mkdir()
        with self.assertRaises((ValueError,PermissionError,OSError)):self.tools.copy_file(str(p),str(self.root/"copy"))
    def test_cannot_delete_root_or_permanently(self):
        with self.assertRaises(PermissionError):self.tools.delete_file(str(self.root))
        p=self.root/"a";p.write_text("a")
        with self.assertRaises(PermissionError):self.tools.delete_file(str(p),True)
    def test_trash_metadata(self):
        p=self.root/"a";p.write_text("a")
        with patch.dict(os.environ,{"XDG_DATA_HOME":str(self.root/"data")}):
            self.tools.delete_file(str(p))
        self.assertFalse(p.exists())
        self.assertEqual(len(list((self.root/"data/Trash/info").glob("*.trashinfo"))),1)

class LoopTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.audit=AuditLog(Path(self.temp.name)/"audit")
        self.registry=ToolRegistry(PermissionEngine(),self.audit);self.executed=[]
        self.registry.register(ToolSpec("read","read",{"properties":{}},Risk.LOW,lambda:self.executed.append("read") or {"ok":True},"Read"))
        self.registry.register(ToolSpec("change","change",{"properties":{}},Risk.CONFIRM,lambda:self.executed.append("change") or {},"Change"))
    def runloop(self,responses,approve=lambda _:{"approved":False},cancel=lambda:False):
        class Provider:
            async def chat(inner,messages,tools):
                inner.messages=messages
                return responses.pop(0)
        p=Provider();events=[]
        result=asyncio.run(AgentRuntime(p,self.registry,self.audit).loop("request",lambda *a,**kw:events.append((a,kw)),cancel,approve))
        return result,p,events
    def test_observation_returns_to_model(self):
        r,p,_=self.runloop([ProviderResponse(tool_calls=[ToolCall("read",{},"a")]),ProviderResponse(text="complete")])
        self.assertEqual(r["message"],"complete")
        self.assertEqual(p.messages[-1]["role"],"tool")
        self.assertEqual(self.executed,["read"])
    def test_entire_batch_validated_before_execution(self):
        with self.assertRaises(ValueError):
            self.runloop([ProviderResponse(tool_calls=[ToolCall("read",{},"a"),ToolCall("shell",{},"b")])])
        self.assertEqual(self.executed,[])
    def test_permission_denied_stops(self):
        r,_,_=self.runloop([ProviderResponse(tool_calls=[ToolCall("change",{},"a")])])
        self.assertEqual(r["status"],"cancelled");self.assertFalse(self.executed)
    def test_permission_approved_resumes(self):
        r,_,_=self.runloop([ProviderResponse(tool_calls=[ToolCall("change",{},"a")]),ProviderResponse(text="done")],lambda _:{"approved":True})
        self.assertEqual(r["status"],"success");self.assertEqual(self.executed,["change"])
    def test_cancel_before_tool(self):
        r,_,_=self.runloop([],cancel=lambda:True)
        self.assertEqual(r["status"],"cancelled");self.assertFalse(self.executed)
    def test_step_bound(self):
        r,_,_=self.runloop([ProviderResponse(tool_calls=[ToolCall("read",{},str(i))]) for i in range(12)])
        self.assertEqual(r["status"],"error");self.assertEqual(len(self.executed),12)
