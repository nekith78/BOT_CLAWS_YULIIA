"""Cloud STT via OpenAI Whisper API.

Stub — full implementation lands in Plan #4 Task 3.
"""

from __future__ import annotations


class OpenAIWhisperSTT:
    def __init__(self, *, api_key: str, model: str = "whisper-1") -> None:
        self._api_key = api_key
        self._model = model

    async def transcribe(self, audio: bytes, *, mime: str) -> str:
        raise NotImplementedError("OpenAIWhisperSTT lands in Plan #4 Task 3")
