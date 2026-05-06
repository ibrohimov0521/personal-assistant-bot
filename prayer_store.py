from __future__ import annotations

from datetime import date

from db import connect_db, utc_text
from prayer_times import DEFAULT_PRAYER_CITY, DEFAULT_PRAYER_KEYS, PRAYER_CITIES


def default_prayer_setting(user_id: int, chat_id: int | None = None) -> dict:
    return {
        "user_id": user_id,
        "chat_id": chat_id or 0,
        "city": DEFAULT_PRAYER_CITY if DEFAULT_PRAYER_CITY in PRAYER_CITIES else "Toshkent",
        "enabled": False,
        "prayers": ",".join(DEFAULT_PRAYER_KEYS),
        "minutes_before": 0,
    }


async def get_prayer_setting(user_id: int, chat_id: int | None = None) -> dict:
    async with connect_db() as db:
        rows = await db.execute_fetchall(
            """
            SELECT user_id, chat_id, city, enabled, prayers, minutes_before
            FROM prayer_settings
            WHERE user_id = ?
            """,
            (user_id,),
        )
    if not rows:
        return default_prayer_setting(user_id, chat_id)
    row = rows[0]
    return {
        "user_id": int(row[0]),
        "chat_id": int(row[1]),
        "city": row[2] if row[2] in PRAYER_CITIES else "Toshkent",
        "enabled": bool(row[3]),
        "prayers": row[4] if row[4] is not None else ",".join(DEFAULT_PRAYER_KEYS),
        "minutes_before": int(row[5] or 0),
    }


async def save_prayer_setting(
    user_id: int,
    chat_id: int,
    city: str | None = None,
    enabled: bool | None = None,
    prayers: str | None = None,
    minutes_before: int | None = None,
) -> dict:
    current = await get_prayer_setting(user_id, chat_id)
    chat_id_value = chat_id or current["chat_id"]
    city_value = city or current["city"]
    enabled_value = current["enabled"] if enabled is None else enabled
    prayers_value = current["prayers"] if prayers is None else prayers
    minutes_value = current["minutes_before"] if minutes_before is None else minutes_before
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO prayer_settings (
                user_id, chat_id, city, enabled, prayers, minutes_before, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                chat_id = excluded.chat_id,
                city = excluded.city,
                enabled = excluded.enabled,
                prayers = excluded.prayers,
                minutes_before = excluded.minutes_before,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                chat_id_value,
                city_value,
                1 if enabled_value else 0,
                prayers_value,
                minutes_value,
                utc_text(),
            ),
        )
        await db.commit()
    return await get_prayer_setting(user_id, chat_id_value)


async def active_prayer_settings() -> list[dict]:
    async with connect_db() as db:
        rows = await db.execute_fetchall(
            """
            SELECT user_id, chat_id, city, prayers, minutes_before
            FROM prayer_settings
            WHERE enabled = 1
            """
        )
    return [
        {
            "user_id": int(row[0]),
            "chat_id": int(row[1]),
            "city": row[2] if row[2] in PRAYER_CITIES else "Toshkent",
            "prayers": row[3] or ",".join(DEFAULT_PRAYER_KEYS),
            "minutes_before": int(row[4] or 0),
        }
        for row in rows
    ]


async def was_prayer_sent(user_id: int, prayer_key: str, prayer_date: date) -> bool:
    async with connect_db() as db:
        rows = await db.execute_fetchall(
            """
            SELECT 1
            FROM prayer_sent
            WHERE user_id = ? AND prayer_key = ? AND prayer_date = ?
            LIMIT 1
            """,
            (user_id, prayer_key, prayer_date.isoformat()),
        )
    return bool(rows)


async def mark_prayer_sent(user_id: int, prayer_key: str, prayer_date: date) -> None:
    async with connect_db() as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO prayer_sent (user_id, prayer_key, prayer_date, sent_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, prayer_key, prayer_date.isoformat(), utc_text()),
        )
        await db.commit()
