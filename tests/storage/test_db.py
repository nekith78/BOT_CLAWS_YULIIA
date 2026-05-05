"""Verify async engine + session factory build correctly."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage import db


@pytest.mark.asyncio
async def test_create_engine_and_run_query() -> None:
    engine = db.create_engine("sqlite+aiosqlite:///:memory:")
    factory = db.create_session_factory(engine)
    async with factory() as session:
        assert isinstance(session, AsyncSession)
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_session_scope_commits_on_exit() -> None:
    engine = db.create_engine("sqlite+aiosqlite:///:memory:")
    factory = db.create_session_factory(engine)
    async with db.session_scope(factory) as session:
        await session.execute(text("CREATE TABLE t (id INTEGER)"))
        await session.execute(text("INSERT INTO t VALUES (42)"))

    async with factory() as verify:
        result = await verify.execute(text("SELECT id FROM t"))
        assert result.scalar() == 42
    await engine.dispose()
