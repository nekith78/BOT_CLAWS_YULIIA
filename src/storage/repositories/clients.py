"""Client repository — CRUD and case-insensitive name search."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import Client


class ClientRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        name: str,
        instagram: str | None = None,
        notes: str | None = None,
    ) -> Client:
        client = Client(name=name, instagram=instagram, notes=notes)
        self._session.add(client)
        await self._session.flush()
        return client

    async def get(self, client_id: int) -> Client | None:
        return await self._session.get(Client, client_id)

    async def search_by_name(self, query: str, *, limit: int = 20) -> list[Client]:
        # SQLite LIKE with COLLATE NOCASE doesn't properly support Cyrillic.
        # Fetch all and filter in Python, then sort and limit.
        stmt = select(Client).order_by(Client.name)
        result = await self._session.execute(stmt)
        all_clients = list(result.scalars())

        query_lower = query.lower()
        matching = [c for c in all_clients if query_lower in c.name.lower()]
        return matching[:limit]

    async def list_recent(self, *, limit: int = 10) -> list[Client]:
        stmt = select(Client).order_by(desc(Client.created_at)).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars())

    async def update(
        self,
        client_id: int,
        *,
        name: str | None = None,
        instagram: str | None = None,
        notes: str | None = None,
    ) -> Client | None:
        client = await self.get(client_id)
        if client is None:
            return None
        if name is not None:
            client.name = name
        if instagram is not None:
            client.instagram = instagram
        if notes is not None:
            client.notes = notes
        await self._session.flush()
        return client

    async def delete(self, client_id: int) -> bool:
        client = await self.get(client_id)
        if client is None:
            return False
        await self._session.delete(client)
        await self._session.flush()
        return True
