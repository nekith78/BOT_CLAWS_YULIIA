"""Unit tests for OpenAIMiniLLM — AsyncOpenAI is monkeypatched away."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, ClassVar

import pytest

from src.services.intent.types import ToolSpec

# --- Fakes for the OpenAI SDK --------------------------------------------


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

    def __init__(self, *, api_key: str) -> None:
        type(self).captured_init.append({"api_key": api_key})
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


# --- Tests ---------------------------------------------------------------


def test_init_passes_api_key_to_async_client(
    fake_openai: type[_FakeCompletions],
) -> None:
    from src.services.intent.llm_openai import OpenAIMiniLLM

    OpenAIMiniLLM(api_key="sk-test")
    assert _FakeClient.captured_init == [{"api_key": "sk-test"}]


async def test_parse_intent_returns_tool_when_function_called(
    fake_openai: type[_FakeCompletions],
) -> None:
    from src.services.intent.llm_openai import OpenAIMiniLLM

    fake_openai.next_response = _FakeCompletionResponse(
        [
            _FakeChoice(
                _FakeMessage(
                    tool_calls=[
                        _FakeToolCall(
                            "create_appointment",
                            json.dumps({"client_name": "Ира", "date": "2026-05-08"}),
                        )
                    ]
                )
            )
        ]
    )

    llm = OpenAIMiniLLM(api_key="sk-test")
    result = await llm.parse_intent(
        text="запиши Иру на 8 мая",
        tools=[
            ToolSpec(
                name="create_appointment",
                description="Create a new appointment",
                params_schema={"type": "object"},
            )
        ],
        system="system",
        now_local=datetime(2026, 5, 6, 10, 0),
    )

    assert result.tool_name == "create_appointment"
    assert result.args == {"client_name": "Ира", "date": "2026-05-08"}


async def test_parse_intent_returns_none_when_no_tool_called(
    fake_openai: type[_FakeCompletions],
) -> None:
    from src.services.intent.llm_openai import OpenAIMiniLLM

    # tool_calls=None — model decided not to pick any tool ("привет").
    fake_openai.next_response = _FakeCompletionResponse(
        [_FakeChoice(_FakeMessage(tool_calls=None))]
    )

    llm = OpenAIMiniLLM(api_key="sk-test")
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
        now_local=datetime(2026, 5, 6, 10, 0),
    )

    assert result.tool_name is None
    assert result.args == {}


async def test_parse_intent_passes_tools_with_correct_shape(
    fake_openai: type[_FakeCompletions],
) -> None:
    from src.services.intent.llm_openai import OpenAIMiniLLM

    llm = OpenAIMiniLLM(api_key="sk-test")
    await llm.parse_intent(
        text="x",
        tools=[
            ToolSpec(
                name="create_appointment",
                description="Create an appointment",
                params_schema={"type": "object", "properties": {}},
            )
        ],
        system="sys",
        now_local=datetime(2026, 5, 6, 10, 0),
    )

    call = fake_openai.captured_kwargs[0]
    assert call["temperature"] == 0.0
    assert call["tool_choice"] == "auto"
    assert call["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "create_appointment",
                "description": "Create an appointment",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    # System prompt is the first message; user text is second.
    assert call["messages"][0] == {"role": "system", "content": "sys"}
    assert call["messages"][1] == {"role": "user", "content": "x"}


async def test_parse_intent_recovers_from_invalid_json_args(
    fake_openai: type[_FakeCompletions],
) -> None:
    """If the model emits malformed JSON in tool arguments, fall back to
    empty args rather than crashing the handler."""
    from src.services.intent.llm_openai import OpenAIMiniLLM

    fake_openai.next_response = _FakeCompletionResponse(
        [
            _FakeChoice(
                _FakeMessage(
                    tool_calls=[_FakeToolCall("create_appointment", "{not-json")]
                )
            )
        ]
    )

    llm = OpenAIMiniLLM(api_key="sk-test")
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
        now_local=datetime(2026, 5, 6, 10, 0),
    )

    assert result.tool_name == "create_appointment"
    assert result.args == {}
