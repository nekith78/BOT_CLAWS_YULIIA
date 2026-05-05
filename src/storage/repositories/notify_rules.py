"""Notify-rule repository — CRUD plus a bulk replace for preset switching."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import NotifyRule


class NotifyRuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, *, kind: str, value: str, enabled: bool = True
    ) -> NotifyRule:
        rule = NotifyRule(kind=kind, value=value, enabled=enabled)
        self._session.add(rule)
        await self._session.flush()
        return rule

    async def get(self, rule_id: int) -> NotifyRule | None:
        return await self._session.get(NotifyRule, rule_id)

    async def list_all(self) -> list[NotifyRule]:
        result = await self._session.execute(select(NotifyRule).order_by(NotifyRule.id))
        return list(result.scalars())

    async def list_enabled(self) -> list[NotifyRule]:
        result = await self._session.execute(
            select(NotifyRule).where(NotifyRule.enabled.is_(True)).order_by(NotifyRule.id)
        )
        return list(result.scalars())

    async def set_enabled(self, rule_id: int, enabled: bool) -> NotifyRule | None:
        rule = await self.get(rule_id)
        if rule is None:
            return None
        rule.enabled = enabled
        await self._session.flush()
        return rule

    async def update_value(self, rule_id: int, value: str) -> NotifyRule | None:
        rule = await self.get(rule_id)
        if rule is None:
            return None
        rule.value = value
        await self._session.flush()
        return rule

    async def delete(self, rule_id: int) -> bool:
        rule = await self.get(rule_id)
        if rule is None:
            return False
        await self._session.delete(rule)
        await self._session.flush()
        return True

    async def replace_all(self, rules: list[tuple[str, str, bool]]) -> None:
        """Wipe table and insert new tuples (kind, value, enabled)."""
        await self._session.execute(delete(NotifyRule))
        for kind, value, enabled in rules:
            self._session.add(NotifyRule(kind=kind, value=value, enabled=enabled))
        await self._session.flush()
