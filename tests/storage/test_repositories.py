"""Repository-layer tests (using in-memory SQLite from conftest)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.repositories.clients import ClientRepository


@pytest.mark.asyncio
async def test_create_and_get_by_id(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    client = await repo.create(name="Олег", instagram="oleg_insta", notes="любит чай")

    fetched = await repo.get(client.id)
    assert fetched is not None
    assert fetched.name == "Олег"
    assert fetched.instagram == "oleg_insta"


@pytest.mark.asyncio
async def test_search_by_name_case_insensitive(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    await repo.create(name="Анна Петрова")
    await repo.create(name="Олег Иванов")
    await repo.create(name="анна сидорова")

    results = await repo.search_by_name("анн")
    names = [c.name for c in results]
    assert "Анна Петрова" in names
    assert "анна сидорова" in names
    assert "Олег Иванов" not in names


@pytest.mark.asyncio
async def test_list_recent(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    for n in ["a", "b", "c", "d", "e"]:
        await repo.create(name=n)

    recent = await repo.list_recent(limit=3)
    assert len(recent) == 3


@pytest.mark.asyncio
async def test_update_partial(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    client = await repo.create(name="Олег")
    updated = await repo.update(client.id, instagram="oleg2", notes="VIP")

    assert updated is not None
    assert updated.instagram == "oleg2"
    assert updated.notes == "VIP"
    assert updated.name == "Олег"  # не изменилось


@pytest.mark.asyncio
async def test_delete(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    client = await repo.create(name="Tmp")
    deleted = await repo.delete(client.id)
    assert deleted is True

    fetched = await repo.get(client.id)
    assert fetched is None
