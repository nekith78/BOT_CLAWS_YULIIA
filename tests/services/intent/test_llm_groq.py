"""Unit tests for GroqLLM — AsyncOpenAI is monkeypatched away.

Groq's API is OpenAI-compatible so the test scaffolding mirrors
test_llm_openai.py; the only thing that differs is the base_url passed
to AsyncOpenAI on construction.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, ClassVar

import pytest

from src.services.intent.types import ToolSpec


class _FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, name: str, arguments: str) -> None:
        self.function = _FakeFunction(name, arguments)


class _FakeMessage:
    def __init__(self, tool_calls: list[_FakeToolCall] | None = None) -> None:
        self.tool_calls = tool_calls or []
        self.content: str | None = None


class _FakeChoice:
    def __init__(self, message: _FakeMessage) -> None:
        self.message = message


class _FakeCompletionResponse:
    def __init__(self, choices: list[_FakeChoice]) -> None:
        self.choices = choices


class _FakeCompletions:
    captured_kwargs: ClassVar[list[dict[str, Any]]] = []
    next_response: ClassVar[_FakeCompletionResponse] = _FakeCompletionResponse(
        [_FakeChoice(_FakeMessage(tool_calls=None))]
    )

    async def create(self, **kwargs: Any) -> _FakeCompletionResponse:
        type(self).captured_kwargs.append(kwargs)
        return type(self).next_response


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()


class _FakeClient:
    captured_init: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, *, api_key: str, base_url: str) -> None:
        type(self).captured_init.append({"api_key": api_key, "base_url": base_url})
        self.chat = _FakeChat()


@pytest.fixture
def fake_openai(monkeypatch: pytest.MonkeyPatch) -> type[_FakeCompletions]:
    _FakeClient.captured_init = []
    _FakeCompletions.captured_kwargs = []
    _FakeCompletions.next_response = _FakeCompletionResponse(
        [_FakeChoice(_FakeMessage(tool_calls=None))]
    )
    monkeypatch.setattr("openai.AsyncOpenAI", _FakeClient)
    return _FakeCompletions


def test_init_points_async_openai_at_groq_base_url(
    fake_openai: type[_FakeCompletions],
) -> None:
    from src.services.intent.llm_groq import GroqLLM

    GroqLLM(api_key="gsk-test")
    assert _FakeClient.captured_init == [
        {"api_key": "gsk-test", "base_url": "https://api.groq.com/openai/v1"}
    ]


async def test_parse_intent_returns_tool_when_function_called(
    fake_openai: type[_FakeCompletions],
) -> None:
    from src.services.intent.llm_groq import GroqLLM

    fake_openai.next_response = _FakeCompletionResponse(
        [
            _FakeChoice(
                _FakeMessage(
                    tool_calls=[
                        _FakeToolCall(
                            "create_appointment",
                            json.dumps({"client_name": "Ира"}),
                        )
                    ]
                )
            )
        ]
    )

    llm = GroqLLM(api_key="gsk-test")
    result = await llm.parse_intent(
        text="запиши Иру",
        tools=[
            ToolSpec(
                name="create_appointment",
                description="d",
                params_schema={"type": "object"},
            )
        ],
        system="s",
        now_local=datetime(2026, 5, 7, 12, 0),
    )
    assert result.tool_name == "create_appointment"
    assert result.args == {"client_name": "Ира"}


async def test_parse_intent_returns_none_when_no_tool_called(
    fake_openai: type[_FakeCompletions],
) -> None:
    from src.services.intent.llm_groq import GroqLLM

    fake_openai.next_response = _FakeCompletionResponse(
        [_FakeChoice(_FakeMessage(tool_calls=None))]
    )

    llm = GroqLLM(api_key="gsk-test")
    result = await llm.parse_intent(
        text="привет",
        tools=[
            ToolSpec(
                name="create_appointment",
                description="d",
                params_schema={"type": "object"},
            )
        ],
        system="s",
        now_local=datetime(2026, 5, 7, 12, 0),
    )
    assert result.tool_name is None


async def test_parse_intent_uses_default_llama_model(
    fake_openai: type[_FakeCompletions],
) -> None:
    from src.services.intent.llm_groq import GroqLLM

    llm = GroqLLM(api_key="gsk-test")
    await llm.parse_intent(
        text="x",
        tools=[ToolSpec(name="t", description="d", params_schema={"type": "object"})],
        system="s",
        now_local=datetime(2026, 5, 7, 12, 0),
    )
    assert fake_openai.captured_kwargs[0]["model"] == "llama-3.3-70b-versatile"
    assert fake_openai.captured_kwargs[0]["temperature"] == 0.0
    assert fake_openai.captured_kwargs[0]["tool_choice"] == "auto"
