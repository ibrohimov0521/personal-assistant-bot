from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram.types import Message

from access_control import admin_user_ids, allowed_user_ids, blocked_user_ids
from db import connect_db, parse_utc, utc_text


LOCAL_TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tashkent"))


def _json_dt(dt: datetime) -> str:
    return dt.astimezone(LOCAL_TZ).isoformat()


def _json_money(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " so'm"


async def save_user_profile(
    user_id: int,
    chat_id: int | None = None,
    first_name: str = "",
    last_name: str = "",
    username: str = "",
    language_code: str = "",
    is_bot: bool = False,
) -> None:
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO user_profiles (
                user_id, chat_id, first_name, last_name, username, language_code, is_bot, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                chat_id = COALESCE(excluded.chat_id, user_profiles.chat_id),
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                username = excluded.username,
                language_code = excluded.language_code,
                is_bot = excluded.is_bot,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                chat_id,
                first_name[:120],
                last_name[:120],
                username[:120],
                language_code[:20],
                1 if is_bot else 0,
                utc_text(),
                utc_text(),
            ),
        )
        await db.commit()


async def save_user_profile_from_message(message: Message) -> None:
    if not message.from_user:
        return
    user = message.from_user
    await save_user_profile(
        user_id=user.id,
        chat_id=message.chat.id,
        first_name=user.first_name or "",
        last_name=user.last_name or "",
        username=user.username or "",
        language_code=user.language_code or "",
        is_bot=user.is_bot,
    )


async def save_user_profile_from_webapp_user(user: dict, chat_id: int | None = None) -> None:
    try:
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError):
        return
    await save_user_profile(
        user_id=user_id,
        chat_id=chat_id,
        first_name=str(user.get("first_name") or ""),
        last_name=str(user.get("last_name") or ""),
        username=str(user.get("username") or ""),
        language_code=str(user.get("language_code") or ""),
        is_bot=bool(user.get("is_bot")),
    )


async def get_user_profile(user_id: int) -> dict | None:
    async with connect_db() as db:
        rows = await db.execute_fetchall(
            """
            SELECT user_id, chat_id, first_name, last_name, username, language_code, is_bot, created_at, updated_at
            FROM user_profiles
            WHERE user_id = ?
            LIMIT 1
            """,
            (user_id,),
        )
    if not rows:
        return None
    row = rows[0]
    return {
        "user_id": int(row[0]),
        "chat_id": int(row[1]) if row[1] is not None else None,
        "first_name": row[2] or "",
        "last_name": row[3] or "",
        "username": row[4] or "",
        "language_code": row[5] or "",
        "is_bot": bool(row[6]),
        "created_at": parse_utc(row[7]),
        "updated_at": parse_utc(row[8]),
    }


async def admin_user_rows() -> list[dict]:
    ids = sorted(allowed_user_ids() | blocked_user_ids() | admin_user_ids())
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    async with connect_db() as db:
        profile_rows = await db.execute_fetchall(
            f"""
            SELECT user_id, chat_id, first_name, last_name, username, language_code, is_bot, created_at, updated_at
            FROM user_profiles
            WHERE user_id IN ({placeholders})
            """,
            tuple(ids),
        )
        tx_rows = await db.execute_fetchall(
            f"""
            SELECT user_id, COUNT(*), COALESCE(SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END), 0),
                   COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0)
            FROM transactions
            WHERE user_id IN ({placeholders})
            GROUP BY user_id
            """,
            tuple(ids),
        )
        card_rows = await db.execute_fetchall(
            f"""
            SELECT user_id, COUNT(*), COALESCE(SUM(amount), 0)
            FROM card_balances
            WHERE user_id IN ({placeholders})
            GROUP BY user_id
            """,
            tuple(ids),
        )
    profiles = {
        int(row[0]): {
            "user_id": int(row[0]),
            "chat_id": int(row[1]) if row[1] is not None else None,
            "first_name": row[2] or "",
            "last_name": row[3] or "",
            "username": row[4] or "",
            "language_code": row[5] or "",
            "is_bot": bool(row[6]),
            "created_at": parse_utc(row[7]),
            "updated_at": parse_utc(row[8]),
        }
        for row in profile_rows
    }
    tx_stats = {int(row[0]): {"transactions": int(row[1]), "income": int(row[2]), "expense": int(row[3])} for row in tx_rows}
    card_stats = {int(row[0]): {"cards": int(row[1]), "balance": int(row[2])} for row in card_rows}
    blocked = blocked_user_ids()
    admins = admin_user_ids()
    allowed = allowed_user_ids()
    result: list[dict] = []
    for user_id in ids:
        profile = profiles.get(
            user_id,
            {
                "user_id": user_id,
                "chat_id": None,
                "first_name": "",
                "last_name": "",
                "username": "",
                "language_code": "",
                "is_bot": False,
                "created_at": None,
                "updated_at": None,
            },
        )
        stats = tx_stats.get(user_id, {"transactions": 0, "income": 0, "expense": 0})
        cards = card_stats.get(user_id, {"cards": 0, "balance": 0})
        full_name = " ".join(part for part in [profile["first_name"], profile["last_name"]] if part).strip()
        result.append(
            {
                "user_id": user_id,
                "chat_id": profile.get("chat_id"),
                "first_name": profile["first_name"],
                "last_name": profile["last_name"],
                "username": profile["username"],
                "language_code": profile["language_code"],
                "is_bot": profile["is_bot"],
                "name": full_name or f"User {user_id}",
                "username_text": f"@{profile['username']}" if profile["username"] else "Ko'rsatilmagan",
                "allowed": user_id in allowed,
                "blocked": user_id in blocked,
                "admin": user_id in admins,
                "transactions": stats["transactions"],
                "income": stats["income"],
                "income_text": _json_money(stats["income"]),
                "expense": stats["expense"],
                "expense_text": _json_money(stats["expense"]),
                "cards": cards["cards"],
                "balance": cards["balance"],
                "balance_text": _json_money(cards["balance"]),
                "created_at_text": _json_dt(profile["created_at"]) if profile.get("created_at") else "",
                "updated_at_text": _json_dt(profile["updated_at"]) if profile.get("updated_at") else "",
            }
        )
    return result


async def add_audit_log(
    actor_user_id: int,
    action: str,
    target_user_id: int | None = None,
    details: str = "",
) -> None:
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO audit_logs (actor_user_id, action, target_user_id, details, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (actor_user_id, action.strip()[:80], target_user_id, details.strip()[:500], utc_text()),
        )
        await db.commit()


async def list_audit_logs(limit: int = 30) -> list[dict]:
    async with connect_db() as db:
        rows = await db.execute_fetchall(
            """
            SELECT id, actor_user_id, action, target_user_id, details, created_at
            FROM audit_logs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
    return [
        {
            "id": int(row[0]),
            "actor_user_id": int(row[1]),
            "action": row[2],
            "target_user_id": int(row[3]) if row[3] is not None else None,
            "details": row[4] or "",
            "created_at": _json_dt(parse_utc(row[5])),
            "created_at_text": _json_dt(parse_utc(row[5])),
        }
        for row in rows
    ]
