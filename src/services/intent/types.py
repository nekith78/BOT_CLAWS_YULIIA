"""Shared data types for the intent layer.

Two groups of types live here:

1. **Parser-facing**: `ToolSpec` (LLM tool description), `ParsedIntent`
   (LLM result).

2. **Action-facing**: `ActionContext` (per-call deps), `ActionResponse` +
   `ActionResult` enum (what an Action returns), `Action` Protocol (the
   interface every concrete action implements).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.fsm.context import FSMContext
    from aiogram.types import InlineKeyboardMarkup
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from sqlalchemy.ext.asyncio import AsyncSession


# --- Parser-facing types -------------------------------------------------


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
    rationale: str | None = None


# --- Action-facing types -------------------------------------------------


class ActionResult(str, Enum):
    """How the intake handler should react to an Action's response.

    `str` mixin (instead of 3.11+ StrEnum) keeps us 3.10-compatible while
    still supporting `value == "executed"` comparisons everywhere.
    """

    EXECUTED = "executed"     # done — send the result message, no follow-up
    CONFIRM = "confirm"       # show confirm-card, wait for ✅/✏️/❌
    CLARIFY = "clarify"       # ask user to disambiguate via inline buttons
    FAIL = "fail"             # parse-or-execute error — show text, abort


@dataclass(frozen=True)
class ClarifyOption:
    """One disambiguation choice for an Action's CLARIFY response.

    The handler renders these as inline buttons; when the user picks one,
    its `payload` is merged into the original args and `Action.plan` is
    called again. This way the action stays oblivious to FSM tags.
    """

    label: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class EditableField:
    """Declares one field of a CONFIRM-state action that the user can
    edit in place via «✏️ Изменить <label>» on the confirm-card.

    The handler uses `editor` to pick the right UI sub-flow: inline
    calendar, time picker, client picker, or text input. After the user
    finishes editing, the new value gets merged into the action's pending
    payload and `Action.plan` is called again — no fresh LLM call.

    `prompt_text` is mandatory only when `editor="text_input"`; the
    handler shows it as the question above the input. Ignored otherwise.
    """

    key: str
    label: str
    editor: Literal["calendar", "time_picker", "client_picker", "text_input"]
    prompt_text: str | None = None


@dataclass(frozen=True)
class ActionResponse:
    """Return value of `Action.plan` and `Action.execute`.

    - `EXECUTED`: `text` (+ optional `keyboard` for list/result cards).
    - `CONFIRM`:  `text` describes what's about to happen; `pending_payload`
                  is stashed in FSM and passed back to `execute`.
    - `CLARIFY`:  `text` is the question; `clarify_options` are the user's
                  choices. Handler builds the keyboard with proper `tag`s.
    - `FAIL`:     `text` is the error message; nothing else is honoured.
    """

    result: ActionResult
    text: str
    keyboard: InlineKeyboardMarkup | None = None
    clarify_options: list[ClarifyOption] | None = None
    pending_payload: dict[str, Any] | None = None
    # `context_snapshot` is a small dict the action can leave behind after
    # an EXECUTED read-only result (list of appointments / history). The
    # intake handler stashes it in a short-lived per-chat memory so the
    # next LLM call sees what the bot just showed — enables follow-ups
    # like «удали эту запись» referring back to a list.
    context_snapshot: dict[str, Any] | None = None
    # `editable_fields` (CONFIRM-only) declares which payload keys the
    # user may edit in place from the confirm-card via «✏️ Изменить ...»
    # buttons. The intake handler renders them dynamically; on edit the
    # action's `plan()` is re-called with the merged payload (no LLM hit).
    editable_fields: list[EditableField] | None = None


@dataclass(frozen=True)
class ActionContext:
    """Per-call dependencies. Built once per intake handler call and
    threaded into both `plan` and `execute`."""

    session: AsyncSession
    bot: Bot
    chat_id: int
    state: FSMContext
    scheduler: AsyncIOScheduler | None
    notify_runner: Any  # dotted path string; see notifications.scheduler.NOTIFY_RUNNER_PATH
    tz: ZoneInfo
    now_utc: datetime  # naive UTC, matches the rest of the codebase


@runtime_checkable
class Action(Protocol):
    """One bot function exposed to the LLM via tool-calling.

    Each concrete action declares its `name`, `description` and JSON-schema
    `params_schema` (used to build the `ToolSpec`). `confirm_required`
    decides whether the handler routes through a confirm-card before
    `execute` runs (destructive actions: True; read-only listings: False).
    """

    # All four are class-level constants on each concrete Action.
    name: ClassVar[str]
    description: ClassVar[str]
    confirm_required: ClassVar[bool]
    params_schema: ClassVar[dict[str, Any]]

    async def plan(self, ctx: ActionContext, args: dict[str, Any]) -> ActionResponse: ...
    async def execute(self, ctx: ActionContext, payload: dict[str, Any]) -> ActionResponse: ...
