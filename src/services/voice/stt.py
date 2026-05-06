"""Speech-to-text abstraction.

`STTProvider` is the surface every concrete provider implements. The
dispatcher `get_stt(settings)` returns the configured provider instance —
called once at bot startup so the model is loaded eagerly (faster-whisper
takes ~3 sec to load `small`).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.config import Settings


@runtime_checkable
class STTProvider(Protocol):
    """Convert audio bytes to plain transcript text (Russian)."""

    async def transcribe(self, audio: bytes, *, mime: str) -> str: ...


def get_stt(settings: Settings) -> STTProvider:
    """Construct the STT provider configured in `settings`. Call once at
    startup; the returned instance owns its model/clients."""
    if settings.stt_provider == "faster_whisper":
        from src.services.voice.faster_whisper_stt import FasterWhisperSTT

        return FasterWhisperSTT(model_size=settings.whisper_model_size)
    if settings.stt_provider == "openai_whisper":
        from src.services.voice.openai_whisper_stt import OpenAIWhisperSTT

        if settings.openai_api_key is None:
            raise RuntimeError("OPENAI_API_KEY required for openai_whisper")
        return OpenAIWhisperSTT(api_key=settings.openai_api_key.get_secret_value())
    raise AssertionError(f"unknown stt_provider: {settings.stt_provider}")
