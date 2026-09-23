from __future__ import annotations

from abc import ABC, abstractmethod


class SpeechToText(ABC):
    @abstractmethod
    async def transcribe(self, audio: bytes, mime_type: str) -> str:
        raise NotImplementedError


class TextToSpeech(ABC):
    @abstractmethod
    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        raise NotImplementedError


class VoiceUnavailable(SpeechToText, TextToSpeech):
    async def transcribe(self, audio: bytes, mime_type: str) -> str:
        raise RuntimeError("No speech-to-text engine is configured")

    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        raise RuntimeError("No text-to-speech engine is configured")

