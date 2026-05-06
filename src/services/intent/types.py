"""Shared data types for the intent layer.

`ToolSpec` is the LLM-facing description of one Action — used to build
the function-calling tools list the LLM picks from.

`ParsedIntent` is what the LLM returns: which tool was picked (or None
if the model didn't pick any) plus the parsed arguments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    """Function-calling description of one Action.

    `name` and `description` are read by the LLM. `params_schema` is a
    JSON-schema dict (object type with properties) — same shape as
    OpenAI's function-calling and Gemini's FunctionDeclaration.parameters.
    """

    name: str
    description: str
    params_schema: dict[str, Any]


@dataclass(frozen=True)
class ParsedIntent:
    """Result of `LLMProvider.parse_intent`.

    `tool_name=None` means the model didn't pick any tool — the user's
    text doesn't match any bot function. The caller shows a "не понял"
    response in that case.
    """

    tool_name: str | None
    args: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    rationale: str | None = None  # for debugging/logging
