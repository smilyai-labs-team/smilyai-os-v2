"""Opt-in local STT bridge to whisper.cpp's /inference multipart contract.
No microphone data is sent to the chat provider or a vendor recognition service.
"""
import base64
import json
import secrets
import urllib.request
from ..providers.openai_compatible import NoRedirect

def transcribe(body, config):
    if not config["privacy"]["microphone"]:
        raise ValueError("Enable push-to-talk in Voice settings first")
    endpoint = config["voice"]["stt_url"]
    if not endpoint:
        raise ValueError("Configure a local speech server in Voice settings")
    try:
        audio = base64.b64decode(body.get("audio", ""), validate=True)
    except (ValueError, TypeError):
        raise ValueError("Invalid recording") from None
    if not 44 <= len(audio) <= 2_000_000 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise ValueError("Expected a short PCM WAV recording")
    boundary = "smily-" + secrets.token_hex(16)
    payload = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"voice.wav\"\r\nContent-Type: audio/wav\r\n\r\n".encode()
               + audio + f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"response_format\"\r\n\r\njson\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(endpoint, data=payload, headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=15) as res:
            raw = json.loads(res.read(100000))
        text = raw["text"]
        if not isinstance(text, str) or len(text) > 16000:
            raise ValueError()
        return text.strip()
    except Exception:
        raise ValueError("Speech service unavailable. Typing still works.") from None
