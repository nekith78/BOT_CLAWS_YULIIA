"""Unit tests for OpenAIWhisperSTT — AsyncOpenAI is monkeypatched away."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest


class _FakeTranscriptions:
    captured_calls: ClassVar[list[dict[str, Any]]] = []
    next_result: Any = "Запиши Иру."

    async def create(self, **kwargs: Any) -> Any:
        type(self).captured_calls.append(kwargs)
        return type(self).next_result


class _FakeAudio:
    def __init__(self) -> None:
        self.transcriptions = _FakeTranscriptions()


class _FakeClient:
    captured_init: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, *, api_key: str) -> None:
        type(self).captured_init.append({"api_key": api_key})
        self.audio = _FakeAudio()


@pytest.fixture
def fake_openai(monkeypatch: pytest.MonkeyPatch) -> type[_FakeTranscriptions]:
    _FakeClient.captured_init = []
    _FakeTranscriptions.captured_calls = []
    _FakeTranscriptions.next_result = "Запиши Иру."
    monkeypatch.setattr("openai.AsyncOpenAI", _FakeClient)
    return _FakeTranscriptions


def test_init_passes_api_key_to_async_client(
    fake_openai: type[_FakeTranscriptions],
) -> None:
    from src.services.voice.openai_whisper_stt import OpenAIWhisperSTT

    OpenAIWhisperSTT(api_key="sk-test")
    assert _FakeClient.captured_init == [{"api_key": "sk-test"}]


async def test_transcribe_uses_russian_language_and_text_format(
    fake_openai: type[_FakeTranscriptions],
) -> None:
    from src.services.voice.openai_whisper_stt import OpenAIWhisperSTT

    stt = OpenAIWhisperSTT(api_key="sk-test")
    await stt.transcribe(b"\x00\x00", mime="audio/ogg")

    assert len(fake_openai.captured_calls) == 1
    call = fake_openai.captured_calls[0]
    assert call["language"] == "ru"
    assert call["response_format"] == "text"
    assert call["model"] == "whisper-1"


async def test_transcribe_attaches_file_with_extension_from_mime(
    fake_openai: type[_FakeTranscriptions],
) -> None:
    from src.services.voice.openai_whisper_stt import OpenAIWhisperSTT

    stt = OpenAIWhisperSTT(api_key="sk-test")
    await stt.transcribe(b"\x00", mime="audio/ogg")

    file_obj = fake_openai.captured_calls[0]["file"]
    assert file_obj.name == "voice.ogg"


async def test_transcribe_returns_stripped_text_when_sdk_returns_string(
    fake_openai: type[_FakeTranscriptions],
) -> None:
    from src.services.voice.openai_whisper_stt import OpenAIWhisperSTT

    fake_openai.next_result = "  Привет. \n"

    stt = OpenAIWhisperSTT(api_key="sk-test")
    text = await stt.transcribe(b"\x00", mime="audio/ogg")

    assert text == "Привет."


async def test_transcribe_handles_legacy_transcription_object(
    fake_openai: type[_FakeTranscriptions],
) -> None:
    """Older OpenAI SDKs wrap text in a Transcription dataclass."""
    from src.services.voice.openai_whisper_stt import OpenAIWhisperSTT

    class _LegacyTranscription:
        text = "Запиши Иру."

    fake_openai.next_result = _LegacyTranscription()

    stt = OpenAIWhisperSTT(api_key="sk-test")
    text = await stt.transcribe(b"\x00", mime="audio/ogg")

    assert text == "Запиши Иру."
