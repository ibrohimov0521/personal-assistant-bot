from __future__ import annotations

import asyncio
import json
from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey

from db import connect_db, utc_text


class SQLiteFSMStorage(BaseStorage):
    def __init__(self) -> None:
        self._schema_ready = False
        self._schema_lock = asyncio.Lock()

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        async with self._schema_lock:
            if self._schema_ready:
                return
            async with connect_db() as db:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS fsm_states (
                        storage_key TEXT PRIMARY KEY,
                        state TEXT,
                        data TEXT NOT NULL DEFAULT '{}',
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                await db.commit()
            self._schema_ready = True

    @staticmethod
    def _key(key: StorageKey) -> str:
        parts = [
            key.bot_id,
            key.chat_id,
            key.user_id,
            key.thread_id or "",
            key.business_connection_id or "",
            key.destiny,
        ]
        return ":".join(str(part) for part in parts)

    @staticmethod
    def _state_text(state: StateType = None) -> str | None:
        if state is None:
            return None
        if isinstance(state, State):
            return state.state
        return str(state)

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        await self._ensure_schema()
        async with connect_db() as db:
            await db.execute(
                """
                INSERT INTO fsm_states (storage_key, state, data, updated_at)
                VALUES (?, ?, '{}', ?)
                ON CONFLICT(storage_key) DO UPDATE SET
                    state = excluded.state,
                    updated_at = excluded.updated_at
                """,
                (self._key(key), self._state_text(state), utc_text()),
            )
            await db.commit()

    async def get_state(self, key: StorageKey) -> str | None:
        await self._ensure_schema()
        async with connect_db() as db:
            rows = await db.execute_fetchall(
                "SELECT state FROM fsm_states WHERE storage_key = ? LIMIT 1",
                (self._key(key),),
            )
        if not rows:
            return None
        return rows[0][0]

    async def set_data(self, key: StorageKey, data: dict[str, Any]) -> None:
        await self._ensure_schema()
        payload = json.dumps(data or {}, ensure_ascii=False)
        async with connect_db() as db:
            await db.execute(
                """
                INSERT INTO fsm_states (storage_key, state, data, updated_at)
                VALUES (?, NULL, ?, ?)
                ON CONFLICT(storage_key) DO UPDATE SET
                    data = excluded.data,
                    updated_at = excluded.updated_at
                """,
                (self._key(key), payload, utc_text()),
            )
            await db.commit()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        await self._ensure_schema()
        async with connect_db() as db:
            rows = await db.execute_fetchall(
                "SELECT data FROM fsm_states WHERE storage_key = ? LIMIT 1",
                (self._key(key),),
            )
        if not rows or not rows[0][0]:
            return {}
        try:
            value = json.loads(rows[0][0])
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    async def close(self) -> None:
        self._schema_ready = False
