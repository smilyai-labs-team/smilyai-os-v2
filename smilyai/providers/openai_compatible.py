from __future__ import annotations
import asyncio
import ipaddress
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from .base import AIProvider, ModelCapabilities, ProviderResponse, ToolCall

MAX_RESPONSE = 2_000_000

class ProviderError(RuntimeError):
    """Safe public error; never include a provider response body or credential."""

def normalize_endpoint(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("Invalid provider endpoint")
    u = urllib.parse.urlsplit(value.strip().rstrip("/"))
    local = u.hostname in {"localhost", "127.0.0.1", "::1"}
    if u.scheme != "https" and not (u.scheme == "http" and local):
        raise ValueError("Use HTTPS, or HTTP on localhost for local inference")
    if not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError("Endpoint must not contain credentials, query or fragment")
    _ = u.port
    return urllib.parse.urlunsplit((u.scheme, u.netloc.lower(), u.path.rstrip("/"), "", ""))

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError("Provider redirects are refused. Set its final HTTPS endpoint.")

def parse_message(raw):
    try:
        choices = raw["choices"]
        if len(choices) != 1:
            raise ValueError()
        choice = choices[0]
        if choice.get("finish_reason") not in {"stop", "tool_calls"}:
            raise ValueError()
        msg = choice["message"]
        text = msg.get("content") or ""
        if not isinstance(text, str):
            raise ValueError()
        calls = []
        items = msg.get("tool_calls") or []
        if not isinstance(items, list) or len(items) > 8:
            raise ValueError()
        if items and choice["finish_reason"] != "tool_calls":
            raise ValueError()
        ids = set()
        for item in items:
            if item.get("type") != "function":
                raise ValueError()
            fn = item["function"]
            args = json.loads(fn["arguments"])
            name, call_id = fn["name"], item["id"]
            if not isinstance(args, dict) or not isinstance(name, str) or not name or not isinstance(call_id, str) or not call_id or call_id in ids:
                raise ValueError()
            ids.add(call_id)
            calls.append(ToolCall(name, args, call_id))
        return ProviderResponse(text=text, tool_calls=calls)
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        raise ProviderError("Provider returned an incomplete or malformed response; no tools were run.") from None

def parse_sse(lines, emit=lambda text: None, cancelled=lambda: False):
    """Never yield an executable call until a complete, terminated stream is validated."""
    text, calls, finished, done, size = "", {}, None, False, 0
    data = []
    deadline = time.monotonic() + 120
    for line in lines:
        if cancelled():
            raise ProviderError("Request cancelled")
        if time.monotonic() > deadline:
            raise ProviderError("Provider stream exceeded its time limit")
        size += len(line)
        if size > MAX_RESPONSE:
            raise ProviderError("Provider response exceeded its size limit")
        try:
            line = line.decode("utf-8") if isinstance(line, bytes) else line
        except UnicodeError:
            raise ProviderError("Invalid stream encoding") from None
        line = line.rstrip("\r\n")
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
            continue
        if line or not data:
            continue
        payload = "\n".join(data)
        data = []
        if payload == "[DONE]":
            done = True
            break
        try:
            event = json.loads(payload)
            if "error" in event:
                raise ValueError()
            choices = event.get("choices", [])
            if not choices:
                continue
            if len(choices) != 1 or choices[0].get("index", 0) != 0 or finished:
                raise ValueError()
            c = choices[0]
            delta = c.get("delta", {})
            part = delta.get("content") or ""
            if not isinstance(part, str):
                raise ValueError()
            text += part
            if part:
                emit(part)
            for tc in delta.get("tool_calls") or []:
                index = tc["index"]
                if type(index) is not int or not 0 <= index < 8:
                    raise ValueError()
                item = calls.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                if "id" in tc:
                    item["id"] += tc["id"]
                if tc.get("type", "function") != "function":
                    raise ValueError()
                for key in ("name", "arguments"):
                    item["function"][key] += tc.get("function", {}).get(key, "")
            if c.get("finish_reason"):
                finished = c["finish_reason"]
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ProviderError("Malformed provider stream; no tools were run.") from None
    if not done or finished not in {"stop", "tool_calls"}:
        raise ProviderError("Provider stream was interrupted; no tools were run.")
    return parse_message({"choices": [{"finish_reason": finished, "message": {
        "content": text, "tool_calls": [calls[i] for i in sorted(calls)]
    }}]})

class OpenAICompatibleProvider(AIProvider):
    name = "openai-compatible"

    def __init__(self, endpoint, model, api_key, label="OpenAI-compatible", streaming=True):
        self.endpoint = normalize_endpoint(endpoint)
        self.model, self.api_key, self.label, self.streaming = model, api_key, label, streaming
        self.opener = urllib.request.build_opener(NoRedirect())

    async def chat(self, messages, tools):
        return await self.complete(messages, tools)

    async def complete(self, messages, tools, emit=lambda text: None, cancelled=lambda: False):
        if not self.model:
            raise ProviderError("Choose a model in AI settings")
        def request():
            payload = {"model": self.model, "messages": messages, "stream": self.streaming}
            if tools:
                payload.update(tools=tools, tool_choice="auto")
            with self._open("/chat/completions", payload) as response:
                if self.streaming:
                    result = parse_sse(iter(lambda: response.readline(262145), b""), emit, cancelled)
                else:
                    result = parse_message(self._json(response))
                result.raw_metadata = {"provider": self.label}
                return result
        try:
            return await asyncio.to_thread(request)
        except ProviderError:
            raise
        except Exception:
            raise ProviderError("Provider unavailable or timed out. Check AI settings and retry.") from None

    async def stream(self, messages, tools):
        # Public text-only stream; executable tool calls are returned only by complete().
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        def emit(part):
            loop.call_soon_threadsafe(queue.put_nowait, part)
        task = asyncio.create_task(self.complete(messages, tools, emit))
        while not task.done() or not queue.empty():
            try:
                yield await asyncio.wait_for(queue.get(), .1)
            except asyncio.TimeoutError:
                pass
        await task

    async def models(self):
        def fetch():
            with self._open("/models") as response:
                raw = self._json(response)
            if not isinstance(raw.get("data"), list):
                raise ProviderError("Model listing is unavailable; enter a model ID manually")
            return [x["id"] for x in raw["data"][:500] if isinstance(x, dict) and isinstance(x.get("id"), str)]
        try:
            return await asyncio.to_thread(fetch)
        except ProviderError:
            raise
        except Exception:
            raise ProviderError("Cannot list models. Enter a model ID manually.") from None

    def capabilities(self):
        return ModelCapabilities(streaming=self.streaming, tool_calling=True)

    def _open(self, path, payload=None):
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream" if payload and payload.get("stream") else "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        req = urllib.request.Request(self.endpoint + path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        try:
            return self.opener.open(req, timeout=15)
        except urllib.error.HTTPError as e:
            e.close()
            raise ProviderError({401: "API key rejected", 403: "Provider access denied", 404: "Endpoint or model not found", 429: "Provider rate limit reached; try later"}.get(e.code, "Provider request failed") + f" (HTTP {e.code})") from None
        except urllib.error.URLError:
            raise ProviderError("Provider connection failed; check endpoint and network") from None

    @staticmethod
    def _json(response):
        payload = response.read(MAX_RESPONSE + 1)
        if len(payload) > MAX_RESPONSE:
            raise ProviderError("Provider response is too large")
        try:
            raw = json.loads(payload)
            if not isinstance(raw, dict):
                raise ValueError()
            return raw
        except ValueError:
            raise ProviderError("Provider returned invalid JSON") from None
