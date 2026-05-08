"""End-to-end smart-fallback flow tests.

These exercise the FULL pipeline of `intake._dispatch`:
  LLM #1 (stubbed) → second-brain text normalizer → LLM #2 (stubbed) →
  action.plan → confirm-card render.

The LLM is replaced with a `FakeLLM` that returns canned responses
keyed by the input text — letting us script "LLM #1 returns no tool"
vs "LLM #2 picks create_appointment" without any network calls.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.handlers.intake import _dispatch
from src.bot.states import IntakePending
from src.config import Settings
from src.services.intent.types import ParsedIntent
from src.storage.repositories.clients import ClientRepository


@pytest_asyncio.fixture
async def state() -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=100, user_id=100)
    return FSMContext(storage=storage, key=key)


@pytest.fixture
def bot() -> MagicMock:
    b = MagicMock()
    b.send_message = AsyncMock(return_value=MagicMock(message_id=555))
    b.edit_message_text = AsyncMock()
    b.delete_message = AsyncMock()
    return b


@pytest_asyncio.fixture
async def session_factory(engine):  # type: ignore[no-untyped-def]
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture
def settings_obj() -> Settings:
    """A minimal Settings — only the fields read by intake/_dispatch matter."""
    return Settings(
        bot_token="x:y",
        owner_chat_id=100,
        owner_tz="Asia/Almaty",
        openai_api_key="sk-test",
        stt_provider="faster_whisper",
        whisper_model="small",
        llm_provider="openrouter",
        llm_api_key="sk-test",
    )


def _make_message(chat_id: int = 100) -> MagicMock:
    m = MagicMock(spec=Message)
    m.chat = MagicMock(id=chat_id)
    return m


class FakeLLM:
    """LLM stub. `responses` maps the FIRST user-text substring it
    matches against parsed input → ParsedIntent. Calls are recorded so
    tests can assert on call count + ordering."""

    def __init__(self, responses: dict[str, ParsedIntent]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    async def parse_intent(
        self, *, text: str, tools: Any, system: str, now_local: Any
    ) -> ParsedIntent:
        self.calls.append(text)
        for key, parsed in self.responses.items():
            if key in text:
                return parsed
        return ParsedIntent(tool_name=None, args={})


# --- tests ----------------------------------------------------------------


async def test_llm_first_misses_then_canonical_is_built_and_llm2_picks_tool(
    state: FSMContext,
    bot: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
    settings_obj: Settings,
    session: AsyncSession,
) -> None:
    """Happy path through smart-brain: «запиши Иру на 2026-05-08 в 14:30»
    — LLM #1 returns None, normalizer produces canonical, LLM #2 picks
    create_appointment."""
    await ClientRepository(session).create(name="Ира")
    # Detach from the test session so a fresh session opens via factory.
    await session.commit()

    fake_llm = FakeLLM(
        responses={
            # LLM #2 sees the canonical text — "запиши Ира на YYYY-MM-DD в HH:MM".
            "Ира на ": ParsedIntent(
                tool_name="create_appointment",
                args={
                    "client_name": "Ира",
                    "date": "2026-05-08",
                    "time": "14:30",
                },
            ),
        }
    )
    msg = _make_message()
    data = {
        "session_factory": session_factory,
        "settings": settings_obj,
        "llm": fake_llm,
        "scheduler": None,
        "notify_runner": None,
    }

    await _dispatch(
        message=msg,
        state=state,
        bot=bot,
        transcript="запиши Иру на завтра в 14:30",
        data=data,
        status_msg_id=999,
    )

    # Two LLM calls — first on raw transcript, second on canonical.
    assert len(fake_llm.calls) == 2
    assert "Иру" in fake_llm.calls[0]
    assert "Ира" in fake_llm.calls[1]
    # Canonical must use ISO date — the normalizer's whole point.
    assert "запиши Ира на " in fake_llm.calls[1]
    # The bot rendered SOMETHING via edit_message_text.
    assert bot.edit_message_text.await_count >= 1


async def test_llm_first_misses_normalizer_no_verb_shows_help(
    state: FSMContext,
    bot: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
    settings_obj: Settings,
) -> None:
    """«привет, как дела» — no verb keyword → no_verb_detected → «не понял»."""
    fake_llm = FakeLLM(responses={})
    msg = _make_message()
    data = {
        "session_factory": session_factory,
        "settings": settings_obj,
        "llm": fake_llm,
        "scheduler": None,
        "notify_runner": None,
    }
    await _dispatch(
        message=msg, state=state, bot=bot,
        transcript="привет, как дела",
        data=data, status_msg_id=999,
    )
    # Only LLM #1 called — normalizer detected no verb so no LLM #2.
    assert len(fake_llm.calls) == 1
    assert bot.edit_message_text.await_count == 1
    text_arg = bot.edit_message_text.await_args.kwargs.get("text") or ""
    assert "не понял" in text_arg.lower() or "не понял" in text_arg.lower()


async def test_loop_guard_llm2_also_misses_shows_help(
    state: FSMContext,
    bot: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
    settings_obj: Settings,
    session: AsyncSession,
) -> None:
    """Even if normalizer produces canonical, if LLM #2 also returns
    no tool we MUST stop — never enter the normalizer a third time."""
    await ClientRepository(session).create(name="Ира")
    await session.commit()

    fake_llm = FakeLLM(responses={})  # always returns tool_name=None
    msg = _make_message()
    data = {
        "session_factory": session_factory,
        "settings": settings_obj,
        "llm": fake_llm,
        "scheduler": None,
        "notify_runner": None,
    }

    await _dispatch(
        message=msg, state=state, bot=bot,
        transcript="запиши Иру на завтра в 14:30",
        data=data, status_msg_id=999,
    )

    # Exactly TWO LLM calls — no third retry.
    assert len(fake_llm.calls) == 2
    text_arg = bot.edit_message_text.await_args.kwargs.get("text") or ""
    assert "не понял" in text_arg.lower()


async def test_llm_first_misses_normalizer_asks_for_note_text(
    state: FSMContext,
    bot: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
    settings_obj: Settings,
    session: AsyncSession,
) -> None:
    """edit_note with appointment but no note text → text-input question.
    State must end up at smart_brain_text waiting for the user."""
    from datetime import date as _date
    from datetime import datetime as _datetime
    from datetime import time as _time
    from datetime import timezone as _tz
    from zoneinfo import ZoneInfo

    from src.storage.repositories.appointments import AppointmentRepository

    tz = ZoneInfo("Asia/Almaty")
    irene = await ClientRepository(session).create(name="Ира")
    # Far-future date so `list_upcoming` (filtered by real wall-clock now())
    # always sees this appointment as upcoming, regardless of when the test
    # is run. The test is checking «single match → asks for note text», not
    # date logic — any always-future date works.
    local = _datetime.combine(_date(2099, 1, 1), _time(14, 0), tzinfo=tz)
    utc = local.astimezone(_tz.utc).replace(tzinfo=None)
    await AppointmentRepository(session).create(
        client_id=irene.id, starts_at=utc
    )
    await session.commit()

    fake_llm = FakeLLM(responses={})  # LLM #1 misses → normalizer kicks in.
    msg = _make_message()
    data = {
        "session_factory": session_factory,
        "settings": settings_obj,
        "llm": fake_llm,
        "scheduler": None,
        "notify_runner": None,
    }

    # «припиши Ире» triggers verb=edit_note; we pass a date so the
    # appointment_ref resolves to a single record (no second clarify step).
    await _dispatch(
        message=msg, state=state, bot=bot,
        transcript="припиши Ире",
        data=data, status_msg_id=999,
    )

    # Only LLM #1 was called — normalizer is asking for the note text.
    assert len(fake_llm.calls) == 1
    cur = await state.get_state()
    assert cur == IntakePending.smart_brain_text.state
    fsm_data = await state.get_data()
    assert fsm_data["sb_field_being_asked"] == "note_text"
    assert fsm_data["sb_verb"] == "edit_note"
