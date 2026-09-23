import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from smilyai.server import serve
from smilyai.ui_server import UIHandler
from http.server import ThreadingHTTPServer

class APIRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.env=patch.dict(os.environ,{"HOME":self.temp.name,"XDG_STATE_HOME":self.temp.name});self.env.start();self.addCleanup(self.env.stop)
        self.s=serve(port=0,config_path=Path(self.temp.name)/"config.json")
        self.thread=threading.Thread(target=self.s.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close)
        self.port=self.s.server_address[1]
        self.token=self.request("GET","/api/bootstrap")[1]["session_token"]
    def close(self):
        self.s.shutdown();self.s.server_close();self.thread.join(2)
    def request(self,method,path,body=None,headers=None):
        h={"Content-Type":"application/json","X-SmilyAI-Session":getattr(self,"token","")};h.update(headers or {})
        c=http.client.HTTPConnection("127.0.0.1",self.port,timeout=5)
        c.request(method,path,json.dumps(body) if body is not None else None,h)
        r=c.getresponse();data=r.read();status=r.status;c.close()
        return status,json.loads(data)
    def test_dns_rebinding_blocked(self):
        self.assertEqual(self.request("GET","/api/bootstrap",headers={"Host":"attacker.example"})[0],403)
    def test_cross_origin_blocked(self):
        self.assertEqual(self.request("POST","/api/jobs",{"text":"memory"},headers={"Origin":"https://attacker.example"})[0],403)
    def test_session_required(self):
        self.assertEqual(self.request("POST","/api/jobs",{"text":"memory"},headers={"X-SmilyAI-Session":""})[0],403)
    def test_settings_do_not_expand_file_scope(self):
        self.assertEqual(self.request("POST","/api/settings",{"config":{"security":{"allowed_roots":["/"]}}})[0],400)
    def test_key_never_in_bootstrap(self):
        runtime=self.s.RequestHandlerClass.runtime
        runtime.secrets._secret_tool=None
        status,_=self.request("POST","/api/settings",{"config":{"provider":{"kind":"smilyai","model":"test"}},"api_key":"test-only-secret"})
        self.assertEqual(status,200)
        status,data=self.request("GET","/api/bootstrap")
        self.assertTrue(data["credential_saved"]);self.assertNotIn("test-only-secret",json.dumps(data))
        self.assertNotIn("test-only-secret",(Path(self.temp.name)/"config.json").read_text())
    def test_job_local_tool_roundtrip(self):
        status,job=self.request("POST","/api/tool",{"name":"get_memory_usage","arguments":{}})
        self.assertEqual(status,202)
        for _ in range(50):
            _,data=self.request("GET","/api/job?id="+job["job_id"])
            if data["result"]:break
            time.sleep(.01)
        self.assertEqual(data["result"]["status"],"success")
        self.assertTrue(any(e["state"]=="observation" for e in data["events"]))
    def test_malformed_tool_no_execution(self):
        _,job=self.request("POST","/api/tool",{"name":"shell","arguments":{"command":"true"}})
        for _ in range(50):
            _,data=self.request("GET","/api/job?id="+job["job_id"])
            if data["result"]:break
            time.sleep(.01)
        self.assertEqual(data["result"]["status"],"error")
    def test_boolean_approval_required(self):
        _,job=self.request("POST","/api/tool",{"name":"shutdown","arguments":{}})
        status,_=self.request("POST","/api/confirm",{"job_id":job["job_id"],"approved":"false"})
        self.assertEqual(status,400)
        self.request("POST","/api/cancel",{"job_id":job["job_id"]})
    def test_static_shell_survives_backend_unavailable(self):
        proxy=ThreadingHTTPServer(("127.0.0.1",0),UIHandler)
        thread=threading.Thread(target=proxy.serve_forever,daemon=True);thread.start()
        try:
            c=http.client.HTTPConnection("127.0.0.1",proxy.server_address[1])
            c.request("GET","/");res=c.getresponse();html=res.read()
            self.assertEqual(res.status,200);self.assertIn(b"orbButton",html);c.close()
            c=http.client.HTTPConnection("127.0.0.1",proxy.server_address[1])
            send=c.request
            with patch("smilyai.ui_server.http.client.HTTPConnection.request",side_effect=ConnectionRefusedError):
                send("GET","/api/bootstrap")
                res=c.getresponse();error=json.loads(res.read())
                self.assertEqual(res.status,503)
                self.assertIn("reconnecting",error["error"])
            c.close()
        finally:
            proxy.shutdown();proxy.server_close();thread.join(2)
