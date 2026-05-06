"""Unit tests for GeminiLLM — google-genai SDK is monkeypatched away."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

import pytest

from src.services.intent.types import ToolSpec

# --- Fakes for the genai SDK ---------------------------------------------


class _FakeFunctionCall:
    def __init__(self, name: str, args: dict[str, Any]) -> None:
        self.name = name
        self.args = args


class _FakePart:
    def __init__(self, function_call: _FakeFunctionCall | None = None) -> None:
        self.function_call = function_call


class _FakeContent:
    def __init__(self, parts: list[_FakePart]) -> None:
        self.parts = parts


class _FakeCandidate:
    def __init__(self, content: _FakeContent) -> None:
        self.content = content


class _FakeResponse:
    def __init__(
        self,
        function_calls: list[_FakeFunctionCall] | None = None,
        candidates: list[_FakeCandidate] | None = None,
    ) -> None:
        self.function_calls = function_calls or []
        self.candidates = candidates or []


class _FakeAsyncModels:
    captured_kwargs: ClassVar[list[dict[str, Any]]] = []
    next_response: ClassVar[_FakeResponse] = _FakeResponse()

    async def generate_content(self, **kwargs: Any) -> _FakeResponse:
        type(self).captured_kwargs.append(kwargs)
        return type(self).next_response


class _FakeAio:
    def __init__(self) -> None:
        self.models = _FakeAsyncModels()


class _FakeClient:
    captured_init: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, *, api_key: str) -> None:
        type(self).captured_init.append({"api_key": api_key})
        self.aio = _FakeAio()


# --- Fakes for genai.types module ----------------------------------------


class _FakeFunctionDeclaration:
    def __init__(self, *, name: str, description: str, parameters: dict[str, Any]) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters


class _FakeTool:
    def __init__(self, *, function_declarations: list[_FakeFunctionDeclaration]) -> None:
        self.function_declarations = function_declarations


class _FakeGenerateContentConfig:
    def __init__(
        self,
        *,
        system_instruction: str,
        tools: list[_FakeTool],
        temperature: float,
    ) -> None:
        self.system_instruction = system_instruction
        self.tools = tools
        self.temperature = temperature


class _FakeTypesModule:
    FunctionDeclaration = _FakeFunctionDeclaration
    Tool = _FakeTool
    GenerateContentConfig = _FakeGenerateContentConfig


# --- Fixtures ------------------------------------------------------------


@pytest.fixture
def fake_genai(monkeypatch: pytest.MonkeyPatch) -> type[_FakeAsyncModels]:
    _FakeClient.captured_init = []
    _FakeAsyncModels.captured_kwargs = []
    _FakeAsyncModels.next_response = _FakeResponse()
    monkeypatch.setattr("google.genai.Client", _FakeClient)
    monkeypatch.setattr("google.genai.types", _FakeTypesModule)
    return _FakeAsyncModels


# --- Tests ---------------------------------------------------------------


def test_init_passes_api_key_to_client(
    fake_genai: type[_FakeAsyncModels],
) -> None:
    from src.services.intent.llm_gemini import GeminiLLM

    GeminiLLM(api_key="fake-key", model="gemini-2.5-flash")
    assert _FakeClient.captured_init == [{"api_key": "fake-key"}]


async def test_parse_intent_returns_tool_when_function_called(
    fake_genai: type[_FakeAsyncModels],
) -> None:
    from src.services.intent.llm_gemini import GeminiLLM

    fake_genai.next_response = _FakeResponse(
        function_calls=[
            _FakeFunctionCall("create_appointment", {"client_name": "Ира", "date": "2026-05-08"})
        ]
    )

    llm = GeminiLLM(api_key="fake-key")
    result = await llm.parse_intent(
        text="запиши Иру на 8 мая",
        tools=[
            ToolSpec(
                name="create_appointment",
                description="Create a new appointment",
                params_schema={"type": "object", "properties": {}},
            )
        ],
        system="system prompt",
        now_local=datetime(2026, 5, 6, 10, 0),
    )

    assert result.tool_name == "create_appointment"
    assert result.args == {"client_name": "Ира", "date": "2026-05-08"}
    assert result.raw_text == "запиши Иру на 8 мая"


async def test_parse_intent_returns_none_when_no_function_called(
    fake_genai: type[_FakeAsyncModels],
) -> None:
    from src.services.intent.llm_gemini import GeminiLLM

    # Empty response — model decided not to call any tool ("привет" case).
    fake_genai.next_response = _FakeResponse(function_calls=[], candidates=[])

    llm = GeminiLLM(api_key="fake-key")
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


async def test_parse_intent_extracts_function_call_from_candidate_parts(
    fake_genai: type[_FakeAsyncModels],
) -> None:
    """SDK sometimes exposes function call only via candidates[].content.parts."""
    from src.services.intent.llm_gemini import GeminiLLM

    fc = _FakeFunctionCall("list_appointments", {"period": "today"})
    fake_genai.next_response = _FakeResponse(
        function_calls=[],
        candidates=[_FakeCandidate(_FakeContent([_FakePart(function_call=fc)]))],
    )

    llm = GeminiLLM(api_key="fake-key")
    result = await llm.parse_intent(
        text="покажи записи на сегодня",
        tools=[
            ToolSpec(
                name="list_appointments",
                description="d",
                params_schema={"type": "object"},
            )
        ],
        system="s",
        now_local=datetime(2026, 5, 6, 10, 0),
    )

    assert result.tool_name == "list_appointments"
    assert result.args == {"period": "today"}


async def test_parse_intent_uses_zero_temperature_for_determinism(
    fake_genai: type[_FakeAsyncModels],
) -> None:
    from src.services.intent.llm_gemini import GeminiLLM

    llm = GeminiLLM(api_key="fake-key")
    await llm.parse_intent(
        text="x",
        tools=[ToolSpec(name="t", description="d", params_schema={"type": "object"})],
        system="s",
        now_local=datetime(2026, 5, 6, 10, 0),
    )

    assert len(fake_genai.captured_kwargs) == 1
    cfg = fake_genai.captured_kwargs[0]["config"]
    assert cfg.temperature == 0.0


async def test_parse_intent_passes_function_declarations_to_sdk(
    fake_genai: type[_FakeAsyncModels],
) -> None:
    from src.services.intent.llm_gemini import GeminiLLM

    llm = GeminiLLM(api_key="fake-key")
    await llm.parse_intent(
        text="x",
        tools=[
            ToolSpec(
                name="create_appointment",
                description="Create a new appointment",
                params_schema={"type": "object", "properties": {"name": {"type": "string"}}},
            ),
            ToolSpec(
                name="list_appointments",
                description="List appointments",
                params_schema={"type": "object"},
            ),
        ],
        system="system prompt",
        now_local=datetime(2026, 5, 6, 10, 0),
    )

    cfg = fake_genai.captured_kwargs[0]["config"]
    assert cfg.system_instruction == "system prompt"
    assert len(cfg.tools) == 1
    decls = cfg.tools[0].function_declarations
    names = [d.name for d in decls]
    assert names == ["create_appointment", "list_appointments"]
