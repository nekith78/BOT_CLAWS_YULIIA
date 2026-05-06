"""Shared fixtures for action tests.

`build_ctx` constructs an `ActionContext` with the test DB session and
None scheduler/bot — actions don't depend on those at unit-test level.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.intent.types import ActionContext

TZ_ALMATY = ZoneInfo("Asia/Almaty")


def build_ctx(
    session: AsyncSession,
    *,
    now_local: datetime | None = None,
    tz: ZoneInfo = TZ_ALMATY,
) -> ActionContext:
    """Build an ActionContext for tests. `now_local` is interpreted in `tz`
    if naive; UTC if tz-aware."""
    if now_local is None:
        now_local = datetime(2026, 5, 7, 12, 0)  # Thursday noon Almaty
    if now_local.tzinfo is None:
        now_local = now_local.replace(tzinfo=tz)
    now_utc_naive = now_local.astimezone(timezone.utc).replace(tzinfo=None)

    # `bot` and `state` are not used by action.plan/execute in the cases we
    # test here — passing None and ignoring type strictness.
    return ActionContext(
        session=session,
        bot=None,  # type: ignore[arg-type]
        chat_id=12345,
        state=None,  # type: ignore[arg-type]
        scheduler=None,
        notify_runner=None,
        tz=tz,
        now_utc=now_utc_naive,
    )


@pytest.fixture
def ctx_factory(session: AsyncSession) -> Any:
    """Returns a callable that builds an ActionContext bound to the test session."""

    def _make(now_local: datetime | None = None) -> ActionContext:
        return build_ctx(session, now_local=now_local)

    return _make
