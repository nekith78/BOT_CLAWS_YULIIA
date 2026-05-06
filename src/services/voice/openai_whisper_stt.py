"""Cloud STT via OpenAI Whisper API.

Used when `STT_PROVIDER=openai_whisper`. The SDK is wrapped here so the
rest of the codebase only knows about the `STTProvider` Protocol.
"""

from __future__ import annotations

import io
import logging

log = logging.getLogger(__name__)


class OpenAIWhisperSTT:
    def __init__(self, *, api_key: str, model: str = "whisper-1") -> None:
        # Imported here so unit tests can monkeypatch AsyncOpenAI before construction.
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def transcribe(self, audio: bytes, *, mime: str) -> str:
        # OpenAI SDK expects a file-like object with a `.name` attribute carrying
        # an extension — without it the API rejects with "Unsupported format".
        ext = mime.split("/")[-1] if "/" in mime else "ogg"
        buf = io.BytesIO(audio)
        buf.name = f"voice.{ext}"

        result = await self._client.audio.transcriptions.create(
            model=self._model,
            file=buf,
            language="ru",
            response_format="text",
        )
        # response_format="text" returns a bare string in modern SDKs; older
        # versions wrap into a Transcription object with `.text`. Handle both.
        if isinstance(result, str):
            return result.strip()
        text = getattr(result, "text", str(result))
        return text.strip()
