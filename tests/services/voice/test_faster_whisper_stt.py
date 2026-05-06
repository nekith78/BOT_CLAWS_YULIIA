"""Unit tests for FasterWhisperSTT — model is monkeypatched away so the
real Whisper weights never get loaded during tests."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest


class _FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeModel:
    """Stand-in for `faster_whisper.WhisperModel`. Captures init args and
    returns a configurable list of segments from `transcribe`."""

    init_calls: ClassVar[list[dict[str, Any]]] = []
    transcribe_calls: ClassVar[list[dict[str, Any]]] = []
    next_segments: ClassVar[list[_FakeSegment]] = []

    def __init__(self, model_size: str, *, device: str, compute_type: str) -> None:
        type(self).init_calls.append(
            {"model_size": model_size, "device": device, "compute_type": compute_type}
        )

    def transcribe(self, audio: Any, **kwargs: Any) -> tuple[Any, Any]:
        type(self).transcribe_calls.append({"audio": audio, **kwargs})
        return iter(type(self).next_segments), object()


@pytest.fixture
def fake_whisper(monkeypatch: pytest.MonkeyPatch) -> type[_FakeModel]:
    _FakeModel.init_calls = []
    _FakeModel.transcribe_calls = []
    _FakeModel.next_segments = []
    monkeypatch.setattr("faster_whisper.WhisperModel", _FakeModel)
    return _FakeModel


def test_init_loads_model_with_int8_cpu(fake_whisper: type[_FakeModel]) -> None:
    from src.services.voice.faster_whisper_stt import FasterWhisperSTT

    FasterWhisperSTT(model_size="tiny")
    assert fake_whisper.init_calls == [
        {"model_size": "tiny", "device": "cpu", "compute_type": "int8"}
    ]


async def test_transcribe_concatenates_segments(fake_whisper: type[_FakeModel]) -> None:
    from src.services.voice.faster_whisper_stt import FasterWhisperSTT

    fake_whisper.next_segments = [
        _FakeSegment(" Запиши "),
        _FakeSegment("Иру на завтра."),
    ]

    stt = FasterWhisperSTT(model_size="tiny")
    text = await stt.transcribe(b"\x00\x00", mime="audio/ogg")

    assert text == "Запиши Иру на завтра."


async def test_transcribe_passes_russian_lang_and_vad(
    fake_whisper: type[_FakeModel],
) -> None:
    from src.services.voice.faster_whisper_stt import FasterWhisperSTT

    stt = FasterWhisperSTT(model_size="tiny")
    await stt.transcribe(b"\x00", mime="audio/ogg")

    assert len(fake_whisper.transcribe_calls) == 1
    call = fake_whisper.transcribe_calls[0]
    assert call["language"] == "ru"
    assert call["vad_filter"] is True


async def test_transcribe_returns_empty_string_when_no_segments(
    fake_whisper: type[_FakeModel],
) -> None:
    from src.services.voice.faster_whisper_stt import FasterWhisperSTT

    fake_whisper.next_segments = []

    stt = FasterWhisperSTT(model_size="tiny")
    text = await stt.transcribe(b"", mime="audio/ogg")

    assert text == ""
