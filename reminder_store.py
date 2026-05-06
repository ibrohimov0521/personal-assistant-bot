from __future__ import annotations

import os
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from db import connect_db, parse_utc, utc_text


LOCAL_TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tashkent"))
VALID_REPEAT_RULES = {"daily", "weekly", "monthly"}


async def add_reminder(user_id: int, chat_id: int, due_at: datetime, text: str, repeat_rule: str = "") -> int:
    if repeat_rule not in VALID_REPEAT_RULES:
        repeat_rule = ""
    async with connect_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO reminders (user_id, chat_id, created_at, due_at, message, status, repeat_rule)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (user_id, chat_id, utc_text(), utc_text(due_at), text, repeat_rule),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def list_reminders(user_id: int) -> list[tuple[int, datetime, str]]:
    async with connect_db() as db:
        rows = await db.execute_fetchall(
            """
            SELECT id, due_at, message
            FROM reminders
            WHERE user_id = ? AND status = 'pending'
            ORDER BY due_at ASC
            LIMIT 30
            """,
            (user_id,),
        )
    return [(int(row[0]), parse_utc(row[1]), str(row[2])) for row in rows]


async def list_pending_reminder_records(user_id: int, limit: int = 30) -> list[dict]:
    async with connect_db() as db:
        rows = await db.execute_fetchall(
            """
            SELECT id, created_at, due_at, message, status, sent_at, repeat_rule
            FROM reminders
            WHERE user_id = ? AND status = 'pending'
            ORDER BY due_at ASC
            LIMIT ?
            """,
            (user_id, limit),
        )
    return [
        {
            "id": int(row[0]),
            "created_at": parse_utc(row[1]),
            "due_at": parse_utc(row[2]),
            "text": str(row[3]),
            "status": str(row[4]),
            "sent_at": parse_utc(row[5]) if row[5] else None,
            "repeat_rule": str(row[6] or ""),
        }
        for row in rows
    ]


async def list_completed_reminder_records(user_id: int, limit: int = 30) -> list[dict]:
    async with connect_db() as db:
        rows = await db.execute_fetchall(
            """
            SELECT id, created_at, due_at, message, status, sent_at, repeat_rule
            FROM reminders
            WHERE user_id = ? AND status IN ('sent', 'cancelled')
            ORDER BY COALESCE(sent_at, due_at) DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
    return [
        {
            "id": int(row[0]),
            "created_at": parse_utc(row[1]),
            "due_at": parse_utc(row[2]),
            "text": str(row[3]),
            "status": str(row[4]),
            "sent_at": parse_utc(row[5]) if row[5] else None,
            "repeat_rule": str(row[6] or ""),
        }
        for row in rows
    ]


async def delete_reminder(user_id: int, reminder_id: int) -> bool:
    async with connect_db() as db:
        cursor = await db.execute(
            "UPDATE reminders SET status = 'cancelled' WHERE user_id = ? AND id = ? AND status = 'pending'",
            (user_id, reminder_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def due_reminders() -> list[tuple[int, int, str]]:
    async with connect_db() as db:
        rows = await db.execute_fetchall(
            """
            SELECT id, chat_id, message
            FROM reminders
            WHERE status = 'pending' AND due_at <= ?
            ORDER BY due_at ASC
            LIMIT 50
            """,
            (utc_text(),),
        )
    return [(int(row[0]), int(row[1]), str(row[2])) for row in rows]


def add_months(dt: datetime, months: int = 1) -> datetime:
    local = dt.astimezone(LOCAL_TZ)
    month_index = local.month - 1 + months
    year = local.year + month_index // 12
    month = month_index % 12 + 1
    day = min(local.day, monthrange(year, month)[1])
    return local.replace(year=year, month=month, day=day).astimezone(timezone.utc)


def next_repeat_due(due_at: datetime, repeat_rule: str) -> datetime | None:
    if repeat_rule not in VALID_REPEAT_RULES:
        return None
    now = datetime.now(timezone.utc)
    next_due = due_at
    while next_due <= now:
        if repeat_rule == "daily":
            next_due += timedelta(days=1)
        elif repeat_rule == "weekly":
            next_due += timedelta(weeks=1)
        elif repeat_rule == "monthly":
            next_due = add_months(next_due, 1)
    return next_due


async def mark_reminder_sent(reminder_id: int) -> None:
    async with connect_db() as db:
        rows = await db.execute_fetchall(
            """
            SELECT user_id, chat_id, due_at, message, repeat_rule
            FROM reminders
            WHERE id = ?
            LIMIT 1
            """,
            (reminder_id,),
        )
        await db.execute(
            "UPDATE reminders SET status = 'sent', sent_at = ? WHERE id = ?",
            (utc_text(), reminder_id),
        )
        if rows:
            user_id, chat_id, due_at_text, message, repeat_rule = rows[0]
            next_due = next_repeat_due(parse_utc(due_at_text), str(repeat_rule or ""))
            if next_due:
                await db.execute(
                    """
                    INSERT INTO reminders (user_id, chat_id, created_at, due_at, message, status, repeat_rule)
                    VALUES (?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (int(user_id), int(chat_id), utc_text(), utc_text(next_due), str(message), str(repeat_rule)),
                )
        await db.commit()
