"""Voice / STT services.

Public entry point: `get_stt(settings)` from `stt.py`. Concrete provider
modules (`faster_whisper_stt`, `openai_whisper_stt`) are imported lazily
inside the dispatcher to avoid loading heavy deps in tests that don't
need them.
"""

from src.services.voice.stt import STTProvider, get_stt

__all__ = ["STTProvider", "get_stt"]
