import asyncio
import io
import json
import unittest
import urllib.error
from unittest.mock import Mock
from smilyai.providers.openai_compatible import OpenAICompatibleProvider, ProviderError, parse_sse, parse_message, normalize_endpoint, NoRedirect
from smilyai.providers.factory import create_provider
from smilyai.config import credential_scope

def stream(*chunks, done=True):
    text = "".join("data: " + json.dumps({"choices": [c]}) + "\n\n" for c in chunks)
    return io.BytesIO((text + ("data: [DONE]\n\n" if done else "")).encode())
def delta(content="", finish=None, tools=None):
    d = {"content": content}
    if tools is not None:
        d["tool_calls"] = tools
    return {"index": 0, "delta": d, "finish_reason": finish}

class ProviderTests(unittest.TestCase):
    def test_text_stream(self):
        parts=[]
        r=parse_sse(stream(delta("Hello "), delta("computer"), delta(finish="stop")),parts.append)
        self.assertEqual(r.text,"Hello computer")
        self.assertEqual(parts,["Hello ","computer"])
    def test_fragmented_tool(self):
        chunks=[delta(tools=[{"index":0,"id":"call1","type":"function","function":{"name":"read_file","arguments":'{"pa'}}]),
                delta(tools=[{"index":0,"function":{"arguments":'th":"test"}'}}]),delta(finish="tool_calls")]
        r=parse_sse(stream(*chunks))
        self.assertEqual(r.tool_calls[0].arguments,{"path":"test"})
    def test_interrupted_never_returns_tools(self):
        with self.assertRaises(ProviderError):
            parse_sse(stream(delta(tools=[{"index":0,"id":"x","function":{"name":"shutdown","arguments":"{}"}}]),done=False))
    def test_missing_done_rejected(self):
        with self.assertRaises(ProviderError): parse_sse(stream(delta("hello",finish="stop"),done=False))
    def test_truncated_finish_rejected(self):
        with self.assertRaises(ProviderError): parse_sse(stream(delta("hello",finish="length")))
    def test_malformed_arguments(self):
        with self.assertRaises(ProviderError):
            parse_sse(stream(delta(tools=[{"index":0,"id":"x","function":{"name":"shutdown","arguments":'{"a":'}}]),delta(finish="tool_calls")))
    def test_malformed_json(self):
        with self.assertRaises(ProviderError): parse_sse(io.BytesIO(b"data: broken\n\n"))
    def test_cancel(self):
        with self.assertRaises(ProviderError): parse_sse(stream(delta("x")),cancelled=lambda:True)
    def test_comment_and_multiline_event(self):
        lines=io.BytesIO(b': keepalive\n\ndata: {"choices":\ndata: [{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        self.assertEqual(parse_sse(lines).text,"ok")
    def test_size_bound(self):
        with self.assertRaises(ProviderError): parse_sse([b"x"*2_000_001])
    def test_duplicate_call_ids(self):
        call={"id":"same","type":"function","function":{"name":"x","arguments":"{}"}}
        with self.assertRaises(ProviderError):
            parse_message({"choices":[{"finish_reason":"tool_calls","message":{"tool_calls":[call,call]}}]})
    def test_nonobject_arguments(self):
        with self.assertRaises(ProviderError):
            parse_message({"choices":[{"finish_reason":"tool_calls","message":{"tool_calls":[{"id":"x","type":"function","function":{"name":"x","arguments":"[]"}}]}}]})
    def test_endpoint_validation(self):
        for value in ["http://remote.example/v1","https://user:password@example.com","https://example.com/v1?key=x","file:///etc/passwd","https://example.com/#x"]:
            with self.subTest(value=value),self.assertRaises(ValueError): normalize_endpoint(value)
        self.assertEqual(normalize_endpoint("https://EXAMPLE.com/v1/"),"https://example.com/v1")
        self.assertEqual(normalize_endpoint("http://127.0.0.1:8080/v1"),"http://127.0.0.1:8080/v1")
    def test_endpoint_scoped_key(self):
        a={"kind":"smilyai","endpoint":"","model":"a"}
        self.assertNotEqual(credential_scope(a),credential_scope({**a,"endpoint":"https://example.com/v1"}))
        self.assertEqual(credential_scope(a),credential_scope({**a,"model":"b"}))
    def test_smilyai_default(self):
        secret=Mock();secret.get.return_value="test-only"
        provider=create_provider({"provider":{"kind":"smilyai","model":"example"}},secret)
        self.assertEqual(provider.endpoint,"https://apismilyai.pythonanywhere.com/v1")
        self.assertEqual(provider.api_key,"test-only")
    def test_model_listing(self):
        p=OpenAICompatibleProvider("https://example.com/v1","model","test-only")
        p.opener=Mock();p.opener.open.return_value=io.BytesIO(b'{"data":[{"id":"alpha"},{"id":"beta"},{}]}')
        self.assertEqual(asyncio.run(p.models()),["alpha","beta"])
        request=p.opener.open.call_args.args[0]
        self.assertEqual(request.full_url,"https://example.com/v1/models")
        self.assertEqual(request.get_header("Authorization"),"Bearer test-only")
    def test_invalid_key_and_rate_limit_are_redacted(self):
        for status in [401,403,404,429,500]:
            p=OpenAICompatibleProvider("https://example.com/v1","model","test-only")
            p.opener=Mock();p.opener.open.side_effect=urllib.error.HTTPError("https://example.com",status,"secret body",{},io.BytesIO(b"private-key"))
            with self.subTest(status=status),self.assertRaises(ProviderError) as err: asyncio.run(p.models())
            self.assertNotIn("private-key",str(err.exception))
            self.assertNotIn("secret body",str(err.exception))
    def test_redirect_is_refused(self):
        with self.assertRaises(ProviderError): NoRedirect().redirect_request(None,None,302,"",{},"https://other.example")
    def test_nonstreaming(self):
        p=OpenAICompatibleProvider("https://example.com/v1","model",None,streaming=False)
        p.opener=Mock();p.opener.open.return_value=io.BytesIO(b'{"choices":[{"finish_reason":"stop","message":{"content":"done"}}]}')
        self.assertEqual(asyncio.run(p.chat([],[])).text,"done")
    def test_bad_model_list(self):
        p=OpenAICompatibleProvider("https://example.com/v1","model",None)
        p.opener=Mock();p.opener.open.return_value=io.BytesIO(b'{"error":"private details"}')
        with self.assertRaises(ProviderError): asyncio.run(p.models())
