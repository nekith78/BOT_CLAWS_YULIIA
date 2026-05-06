"""Local STT via faster-whisper (CTranslate2 backend).

Loads the model once on instance creation; subsequent `transcribe` calls
reuse the loaded weights. faster-whisper's internal ffmpeg call decodes
whatever format Telegram sent (.ogg/opus for voice, .mp3 for audio) so
the caller doesn't have to convert manually.
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

log = logging.getLogger(__name__)


class FasterWhisperSTT:
    def __init__(self, *, model_size: str = "small", language: str = "ru") -> None:
        # Imported here so unit tests can monkeypatch WhisperModel before construction.
        from faster_whisper import WhisperModel

        log.info("loading faster-whisper model: %s", model_size)
        # int8 keeps RAM low (~0.5 GB for `small`) and runs ok on CPU.
        self._model: Any = WhisperModel(
            model_size, device="cpu", compute_type="int8"
        )
        self._language = language
        log.info("faster-whisper model loaded")

    async def transcribe(self, audio: bytes, *, mime: str) -> str:
        # WhisperModel.transcribe is sync + CPU-bound; offload to a thread so
        # the asyncio loop stays responsive while the model runs (1–3 sec for
        # short clips with `small` on a modern CPU).
        return await asyncio.to_thread(self._transcribe_sync, audio)

    def _transcribe_sync(self, audio: bytes) -> str:
        segments, _info = self._model.transcribe(
            io.BytesIO(audio),
            language=self._language,
            beam_size=5,
            vad_filter=True,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
