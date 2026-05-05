import asyncio
import csv
import hashlib
import hmac
import io
import json
import logging
import math
import os
import re
import time
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

import aiosqlite
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    MenuButtonWebApp,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from aiogram.utils.markdown import hbold, hcode
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DB_PATH = BASE_DIR / "assistant.db"
MINIAPP_DIR = BASE_DIR / "miniapp"
LOCAL_TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tashkent"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "assistant.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

router = Router()

MAIN_REMINDERS = "Eslatma"
MAIN_FINANCE = "Moliya"
MAIN_PRAYER = "Namoz"
MAIN_MINI_APP = "Mini App"
MAIN_HELP = "Yordam"
BACK = "Orqaga"
CANCEL = "Bekor qilish"
MAIN_MENU = "Asosiy menyu"

REMINDER_ADD = "Eslatma qo'shish"
REMINDER_LIST = "Eslatmalarim"
REMINDER_DELETE = "Eslatma o'chirish"

FINANCE_BANK = "Bank xabarini qo'shish"
FINANCE_INCOME = "Kirim qo'shish"
FINANCE_EXPENSE = "Xarajat qo'shish"
FINANCE_TODAY = "Bugungi hisobot"
FINANCE_WEEK = "Haftalik hisobot"
FINANCE_MONTH = "Oylik hisobot"
FINANCE_LAST = "Oxirgi yozuvlar"
FINANCE_BALANCES = "Kartalar balansi"

PRAYER_TODAY = "Bugungi namoz vaqtlari"
PRAYER_ENABLE = "Eslatmani yoqish"
PRAYER_DISABLE = "Eslatmani o'chirish"
PRAYER_CITY = "Shahar tanlash"
PRAYER_SETTINGS = "Namoz sozlamalari"

PRAYER_NAMES = {
    "fajr": "Bomdod",
    "sunrise": "Quyosh",
    "dhuhr": "Peshin",
    "asr": "Asr",
    "maghrib": "Shom",
    "isha": "Xufton",
}
DEFAULT_PRAYER_KEYS = ["fajr", "dhuhr", "asr", "maghrib", "isha"]
DEFAULT_PRAYER_CITY = os.getenv("PRAYER_DEFAULT_CITY", "Toshkent")
REPEAT_LABELS = {
    "daily": "Har kuni",
    "weekly": "Har hafta",
    "monthly": "Har oy",
}
PRAYER_CITIES = {
    "Toshkent": (41.2995, 69.2401),
    "Samarqand": (39.6542, 66.9597),
    "Buxoro": (39.7747, 64.4286),
    "Andijon": (40.7821, 72.3442),
    "Farg'ona": (40.3894, 71.7847),
    "Namangan": (41.0011, 71.6683),
    "Qarshi": (38.8606, 65.7890),
    "Nukus": (42.4619, 59.6166),
    "Urganch": (41.5500, 60.6333),
    "Navoiy": (40.0844, 65.3792),
    "Jizzax": (40.1250, 67.8808),
    "Guliston": (40.4897, 68.7842),
    "Termiz": (37.2242, 67.2783),
}


class ReminderWizard(StatesGroup):
    waiting_datetime = State()
    waiting_text = State()
    waiting_delete_id = State()


class FinanceWizard(StatesGroup):
    waiting_bank_message = State()
    waiting_income = State()
    waiting_expense = State()


class PrayerWizard(StatesGroup):
    waiting_city = State()


@dataclass
class ParsedTransaction:
    type: str
    amount: int
    currency: str
    occurred_at_utc: datetime
    source: str
    card_last4: str
    description: str
    category: str
    balance_after: int | None
    raw_text: str


@dataclass
class ParsedBalance:
    source: str
    card_last4: str
    amount: int
    currency: str
    bank: str
    owner: str
    raw_text: str


def mini_app_url() -> str:
    configured = os.getenv("MINI_APP_URL", "").strip()
    if configured:
        return configured
    port = int(os.getenv("MINIAPP_PORT", "8080"))
    return f"http://127.0.0.1:{port}/"


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MAIN_HELP)],
        ],
        resize_keyboard=True,
    )


def miniapp_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Mini Appni ochish", web_app=WebAppInfo(url=mini_app_url()))]
        ]
    )


def reminders_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=REMINDER_ADD)],
            [KeyboardButton(text=REMINDER_LIST), KeyboardButton(text=REMINDER_DELETE)],
            [KeyboardButton(text=MAIN_MENU)],
        ],
        resize_keyboard=True,
    )


def finance_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=FINANCE_WEEK), KeyboardButton(text=FINANCE_MONTH)],
            [KeyboardButton(text=FINANCE_BALANCES)],
            [KeyboardButton(text=MAIN_MENU)],
        ],
        resize_keyboard=True,
    )


def prayer_keyboard(enabled: bool = False) -> ReplyKeyboardMarkup:
    toggle = PRAYER_DISABLE if enabled else PRAYER_ENABLE
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=PRAYER_TODAY)],
            [KeyboardButton(text=toggle), KeyboardButton(text=PRAYER_CITY)],
            [KeyboardButton(text=PRAYER_SETTINGS)],
            [KeyboardButton(text=MAIN_MENU)],
        ],
        resize_keyboard=True,
    )


def city_keyboard() -> ReplyKeyboardMarkup:
    names = list(PRAYER_CITIES.keys())
    rows: list[list[KeyboardButton]] = []
    for index in range(0, len(names), 2):
        rows.append([KeyboardButton(text=name) for name in names[index : index + 2]])
    rows.append([KeyboardButton(text=BACK), KeyboardButton(text=CANCEL)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def back_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BACK), KeyboardButton(text=CANCEL)]],
        resize_keyboard=True,
    )


def escape_html(text: object) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def allowed_user_ids() -> set[int]:
    raw = os.getenv("ALLOWED_USER_IDS", "").strip()
    if not raw:
        return set()
    result: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if item.isdigit():
            result.add(int(item))
    return result


@router.message(
    lambda message: bool(allowed_user_ids())
    and message.from_user is not None
    and message.from_user.id not in allowed_user_ids()
)
async def reject_not_allowed(message: Message) -> None:
    user_id = user_id_from(message)
    await message.answer(
        "Bu botdan foydalanish uchun sizga ruxsat berilmagan.\n\n"
        f"Adminga yuboriladigan Telegram ID: {hcode(str(user_id))}"
    )


def user_id_from(message: Message) -> int:
    if not message.from_user:
        raise RuntimeError("Telegram user aniqlanmadi.")
    return message.from_user.id


def now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


def utc_text(dt: datetime | None = None) -> str:
    value = dt or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def parse_utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(timezone.utc)


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                due_at TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                sent_at TEXT,
                repeat_rule TEXT NOT NULL DEFAULT ''
            )
            """
        )
        try:
            await db.execute("ALTER TABLE reminders ADD COLUMN repeat_rule TEXT NOT NULL DEFAULT ''")
        except aiosqlite.OperationalError:
            pass
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_reminders_due
            ON reminders(status, due_at)
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'UZS',
                source TEXT,
                card_last4 TEXT,
                description TEXT,
                category TEXT,
                balance_after INTEGER,
                raw_text TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_transactions_user_date
            ON transactions(user_id, occurred_at)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_transactions_dedupe
            ON transactions(user_id, occurred_at, type, amount, card_last4)
            """
        )
        await db.execute("UPDATE transactions SET raw_text = '' WHERE raw_text <> ''")
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS card_balances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                card_last4 TEXT NOT NULL,
                bank TEXT,
                owner TEXT,
                amount INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'UZS',
                raw_text TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, card_last4)
            )
            """
        )
        await db.execute(
            """
            DELETE FROM card_balances
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM card_balances
                GROUP BY user_id, card_last4
            )
            """
        )
        await db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_card_balances_user_last4
            ON card_balances(user_id, card_last4)
            """
        )
        await db.execute("UPDATE card_balances SET raw_text = '' WHERE raw_text <> ''")
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS prayer_settings (
                user_id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                city TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                prayers TEXT NOT NULL,
                minutes_before INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS prayer_sent (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                prayer_key TEXT NOT NULL,
                prayer_date TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                UNIQUE(user_id, prayer_key, prayer_date)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, key)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_report_sent (
                user_id INTEGER NOT NULL,
                report_date TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY (user_id, report_date)
            )
            """
        )
        await db.commit()


async def add_reminder(user_id: int, chat_id: int, due_at: datetime, text: str, repeat_rule: str = "") -> int:
    if repeat_rule not in REPEAT_LABELS:
        repeat_rule = ""
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE reminders SET status = 'cancelled' WHERE user_id = ? AND id = ? AND status = 'pending'",
            (user_id, reminder_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def due_reminders() -> list[tuple[int, int, str]]:
    async with aiosqlite.connect(DB_PATH) as db:
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
    if repeat_rule not in REPEAT_LABELS:
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
        else:
            return None
    return next_due


async def mark_reminder_sent(reminder_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
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


async def save_transaction(user_id: int, tx: ParsedTransaction) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        duplicate_rows = await db.execute_fetchall(
            """
            SELECT id
            FROM transactions
            WHERE user_id = ?
              AND occurred_at = ?
              AND type = ?
              AND amount = ?
              AND COALESCE(card_last4, '') = ?
              AND COALESCE(description, '') = ?
              AND COALESCE(category, '') = ?
            LIMIT 1
            """,
            (
                user_id,
                utc_text(tx.occurred_at_utc),
                tx.type,
                tx.amount,
                tx.card_last4 or "",
                tx.description or "",
                tx.category or "",
            ),
        )
        if duplicate_rows:
            return int(duplicate_rows[0][0])
        cursor = await db.execute(
            """
            INSERT INTO transactions (
                user_id, created_at, occurred_at, type, amount, currency, source,
                card_last4, description, category, balance_after, raw_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                utc_text(),
                utc_text(tx.occurred_at_utc),
                tx.type,
                tx.amount,
                tx.currency,
                tx.source,
                tx.card_last4,
                tx.description,
                tx.category,
                tx.balance_after,
                "",
            ),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def save_balances(user_id: int, balances: list[ParsedBalance]) -> int:
    if not balances:
        return 0
    async with aiosqlite.connect(DB_PATH) as db:
        for item in balances:
            existing = await db.execute_fetchall(
                """
                SELECT id, source, bank, owner
                FROM card_balances
                WHERE user_id = ? AND card_last4 = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (user_id, item.card_last4),
            )
            if existing:
                row_id, old_source, old_bank, old_owner = existing[0]
                source = item.source if item.source and item.source != "CARD" else old_source
                bank = item.bank or old_bank or ""
                owner = item.owner or old_owner or ""
                await db.execute(
                    """
                    UPDATE card_balances
                    SET source = ?, bank = ?, owner = ?, amount = ?, currency = ?, raw_text = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (source, bank, owner, item.amount, item.currency, "", utc_text(), row_id),
                )
                await db.execute(
                    "DELETE FROM card_balances WHERE user_id = ? AND card_last4 = ? AND id <> ?",
                    (user_id, item.card_last4, row_id),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO card_balances (
                        user_id, source, card_last4, bank, owner, amount, currency, raw_text, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        item.source,
                        item.card_last4,
                        item.bank,
                        item.owner,
                        item.amount,
                        item.currency,
                        "",
                        utc_text(),
                    ),
                )
        await db.commit()
    return len(balances)


async def get_card_balances(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall(
            """
            SELECT source, card_last4, bank, owner, amount, currency, updated_at
            FROM card_balances
            WHERE user_id = ?
            ORDER BY source ASC, card_last4 ASC
            """,
            (user_id,),
        )
    return [
        {
            "source": row[0],
            "card_last4": row[1],
            "bank": row[2] or "",
            "owner": row[3] or "",
            "amount": int(row[4]),
            "currency": row[5],
            "updated_at": parse_utc(row[6]),
        }
        for row in rows
    ]


async def get_card_balance(user_id: int, card_last4: str) -> dict | None:
    if not card_last4:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall(
            """
            SELECT source, card_last4, bank, owner, amount, currency, updated_at
            FROM card_balances
            WHERE user_id = ? AND card_last4 = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (user_id, card_last4),
        )
    if not rows:
        return None
    row = rows[0]
    return {
        "source": row[0],
        "card_last4": row[1],
        "bank": row[2] or "",
        "owner": row[3] or "",
        "amount": int(row[4]),
        "currency": row[5],
        "updated_at": parse_utc(row[6]),
    }


async def get_transactions(
    user_id: int,
    start_utc: datetime | None = None,
    end_utc: datetime | None = None,
    tx_type: str | None = None,
    limit: int = 200,
) -> list[dict]:
    query = """
        SELECT id, occurred_at, type, amount, currency, source, card_last4, description, category, balance_after
        FROM transactions
        WHERE user_id = ?
    """
    params: list[object] = [user_id]
    if start_utc is not None:
        query += " AND occurred_at >= ?"
        params.append(utc_text(start_utc))
    if end_utc is not None:
        query += " AND occurred_at < ?"
        params.append(utc_text(end_utc))
    if tx_type in {"income", "expense"}:
        query += " AND type = ?"
        params.append(tx_type)
    query += " ORDER BY occurred_at DESC LIMIT ?"
    params.append(limit)
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall(query, params)
    return [
        {
            "id": row[0],
            "occurred_at": parse_utc(row[1]),
            "type": row[2],
            "amount": row[3],
            "currency": row[4],
            "source": row[5] or "",
            "card_last4": row[6] or "",
            "description": row[7] or "",
            "category": row[8] or "Boshqa",
            "balance_after": row[9],
        }
        for row in rows
    ]


async def delete_transaction(user_id: int, transaction_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM transactions WHERE user_id = ? AND id = ?",
            (user_id, transaction_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_transaction(
    user_id: int,
    transaction_id: int,
    tx_type: str,
    amount: int,
    category: str,
    description: str,
    occurred_at: datetime | None = None,
) -> bool:
    if tx_type not in {"income", "expense"} or amount <= 0:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        fields = ["type = ?", "amount = ?", "category = ?", "description = ?"]
        params: list[object] = [
            tx_type,
            amount,
            category.strip()[:60] or "Boshqa",
            description.strip()[:120] or ("Kirim" if tx_type == "income" else "Xarajat"),
        ]
        if occurred_at is not None:
            fields.append("occurred_at = ?")
            params.append(utc_text(occurred_at))
        params.extend([user_id, transaction_id])
        cursor = await db.execute(
            f"""
            UPDATE transactions
            SET {", ".join(fields)}
            WHERE user_id = ? AND id = ?
            """,
            params,
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_user_setting(user_id: int, key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall(
            "SELECT value FROM user_settings WHERE user_id = ? AND key = ? LIMIT 1",
            (user_id, key),
        )
    return str(rows[0][0]) if rows else default


async def set_user_setting(user_id: int, key: str, value: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO user_settings (user_id, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (user_id, key, value, utc_text()),
        )
        await db.commit()


async def clear_user_data(user_id: int, scope: str) -> None:
    if scope not in {"finance", "reminders", "all"}:
        raise ValueError("Unknown clear scope")
    async with aiosqlite.connect(DB_PATH) as db:
        if scope in {"finance", "all"}:
            await db.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
            await db.execute("DELETE FROM card_balances WHERE user_id = ?", (user_id,))
        if scope in {"reminders", "all"}:
            await db.execute("DELETE FROM reminders WHERE user_id = ?", (user_id,))
        if scope == "all":
            await db.execute("DELETE FROM prayer_settings WHERE user_id = ?", (user_id,))
            await db.execute("DELETE FROM prayer_sent WHERE user_id = ?", (user_id,))
            await db.execute("DELETE FROM daily_report_sent WHERE user_id = ?", (user_id,))
            await db.execute("DELETE FROM user_settings WHERE user_id = ?", (user_id,))
        await db.commit()


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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO prayer_sent (user_id, prayer_key, prayer_date, sent_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, prayer_key, prayer_date.isoformat(), utc_text()),
        )
        await db.commit()


def parse_reminder_datetime(text: str) -> datetime | None:
    raw = text.strip().lower()
    now = now_local()
    time_match = re.search(r"(?:soat\s*)?(\d{1,2})[:.](\d{2})", raw)
    hour_only_match = None if time_match else re.search(r"\bsoat\s*(\d{1,2})(?:\s*(?:da|ga))?\b", raw)

    def time_or_default(base: datetime, default_hour: int = 9) -> datetime:
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if hour_only_match:
            hour = int(hour_only_match.group(1))
            if 0 <= hour <= 23:
                return base.replace(hour=hour, minute=0, second=0, microsecond=0)
        return base.replace(hour=default_hour, minute=0, second=0, microsecond=0)

    if re.search(r"\byarim\s*soat", raw):
        return (now + timedelta(minutes=30)).astimezone(timezone.utc)

    relative = re.search(r"(\d+(?:[.,]\d+)?)\s*(daqiq\w*|minut\w*|min\b|minute\w*)", raw)
    if relative:
        minutes = float(relative.group(1).replace(",", "."))
        return (now + timedelta(minutes=max(round(minutes), 1))).astimezone(timezone.utc)

    relative = re.search(r"(\d+(?:[.,]\d+)?)\s*(soat\w*|hour\w*)", raw)
    if relative:
        hours = float(relative.group(1).replace(",", "."))
        return (now + timedelta(minutes=max(round(hours * 60), 1))).astimezone(timezone.utc)

    relative = re.search(r"(\d+)\s*(kun\w*|day\w*)", raw)
    if relative:
        base = now + timedelta(days=int(relative.group(1)))
        return time_or_default(base).astimezone(timezone.utc)

    relative = re.search(r"(\d+)\s*(hafta\w*|week\w*)", raw)
    if relative:
        base = now + timedelta(weeks=int(relative.group(1)))
        return time_or_default(base).astimezone(timezone.utc)

    relative = re.search(r"(\d+)\s*(oy\w*|month\w*)", raw)
    if relative:
        base = now + timedelta(days=30 * int(relative.group(1)))
        return time_or_default(base).astimezone(timezone.utc)

    if any(word in raw for word in ["indinga", "after tomorrow"]):
        return time_or_default(now + timedelta(days=2)).astimezone(timezone.utc)

    if any(word in raw for word in ["ertaga", "tomorrow"]):
        return time_or_default(now + timedelta(days=1)).astimezone(timezone.utc)

    if any(word in raw for word in ["bugun", "today"]):
        due = time_or_default(now, default_hour=now.hour)
        if due <= now:
            due += timedelta(days=1)
        return due.astimezone(timezone.utc)

    weekdays = {
        "dushanba": 0,
        "seshanba": 1,
        "chorshanba": 2,
        "payshanba": 3,
        "juma": 4,
        "shanba": 5,
        "yakshanba": 6,
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    for word, weekday in weekdays.items():
        if re.search(rf"\b{word}\b", raw):
            days_ahead = (weekday - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return time_or_default(now + timedelta(days=days_ahead)).astimezone(timezone.utc)

    patterns = [
        (r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\s+(\d{1,2})[:.](\d{2})", "ymd"),
        (r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\s+(\d{1,2})[:.](\d{2})", "dmy"),
        (r"(\d{1,2})[-/.](\d{1,2})\s+(\d{1,2})[:.](\d{2})", "dm"),
    ]
    for pattern, mode in patterns:
        match = re.search(pattern, raw)
        if not match:
            continue
        try:
            if mode == "ymd":
                year, month, day, hour, minute = map(int, match.groups())
            elif mode == "dmy":
                day, month, year, hour, minute = map(int, match.groups())
            else:
                day, month, hour, minute = map(int, match.groups())
                year = now.year
            due = datetime(year, month, day, hour, minute, tzinfo=LOCAL_TZ)
            if mode == "dm" and due <= now:
                due = due.replace(year=year + 1)
            return due.astimezone(timezone.utc)
        except ValueError:
            return None

    if time_match or hour_only_match:
        due = time_or_default(now, default_hour=now.hour)
        if due <= now:
            due += timedelta(days=1)
        return due.astimezone(timezone.utc)

    return None


def looks_like_reminder_request(text: str) -> bool:
    raw = text.strip().lower()
    if not raw:
        return False
    if any(word in raw for word in ["eslat", "eslatma", "esimga", "yodimga", "remind", "napom"]):
        return True
    if re.search(r"\d+(?:[.,]\d+)?\s*(daqiq\w*|minut\w*|min\b|minute\w*|soat\w*|hour\w*|kun\w*|day\w*|hafta\w*|week\w*|oy\w*|month\w*)", raw):
        return True
    if re.search(r"\byarim\s*soat", raw):
        return True
    if re.search(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\s+\d{1,2}[:.]\d{2}", raw):
        return True
    if re.search(r"\d{1,2}[-/.]\d{1,2}(?:[-/.]\d{2,4})?\s+\d{1,2}[:.]\d{2}", raw):
        return True
    if re.search(r"\bsoat\s*\d{1,2}(?:[:.]\d{2})?(?:\s*(?:da|ga))?\b", raw):
        return True
    day_words = [
        "bugun",
        "ertaga",
        "indinga",
        "dushanba",
        "seshanba",
        "chorshanba",
        "payshanba",
        "juma",
        "shanba",
        "yakshanba",
        "today",
        "tomorrow",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]
    if any(word in raw for word in day_words):
        return True
    return False


def detect_repeat_rule(text: str) -> str:
    raw = text.strip().lower()
    if re.search(r"\b(har\s*kuni|har\s*kun|every\s*day|daily)\b", raw):
        return "daily"
    if re.search(r"\b(har\s*hafta|every\s*week|weekly)\b", raw):
        return "weekly"
    if re.search(r"\b(har\s*oy|every\s*month|monthly)\b", raw):
        return "monthly"
    return ""


def extract_reminder_text(text: str) -> str:
    cleaned = text.strip()
    for pattern in [
        r"\b(?:har\s*kuni|har\s*kun|har\s*hafta|har\s*oy|every\s*day|daily|every\s*week|weekly|every\s*month|monthly)\b",
        r"\b\d+(?:[.,]\d+)?\s*(?:daqiq\w*|minut\w*|min|minute\w*)\s*(?:keyin|song|so'ng|dan keyin)?\b",
        r"\byarim\s*soat(?:dan)?\s*(?:keyin|song|so'ng)?\b",
        r"\b\d+(?:[.,]\d+)?\s*(?:soat\w*|hour\w*)\s*(?:keyin|song|so'ng|dan keyin)?\b",
        r"\b\d+\s*(?:kun\w*|day\w*)\s*(?:keyin|song|so'ng|dan keyin)?\b",
        r"\b\d+\s*(?:hafta\w*|week\w*)\s*(?:keyin|song|so'ng|dan keyin)?\b",
        r"\b\d+\s*(?:oy\w*|month\w*)\s*(?:keyin|song|so'ng|dan keyin)?\b",
        r"\b(?:ertaga|bugun|indinga|tomorrow|today|after tomorrow)\b",
        r"\b(?:dushanba|seshanba|chorshanba|payshanba|juma|shanba|yakshanba)\b",
        r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\s+\d{1,2}[:.]\d{2}\b",
        r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\s+\d{1,2}[:.]\d{2}\b",
        r"\b\d{1,2}[-/.]\d{1,2}\s+\d{1,2}[:.]\d{2}\b",
        r"\b(?:soat\s*)?\d{1,2}[:.]\d{2}\b",
        r"\bsoat\s*\d{1,2}(?:\s*(?:da|ga))?\b",
    ]:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.I)
    cleaned = re.sub(
        r"\b(?:menga|meni|esimga|yodimga|sol|tushir|eslatib|eslat|eslatma|qil|qilib|qoy|qo'y|remind|me|please|iltimos)\b",
        " ",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-:;")
    if cleaned.lower() in {"shu xabarni", "shu xabar", "xabarni", "xabar"}:
        return ""
    return cleaned


def parse_inline_reminder(text: str) -> tuple[datetime, str] | None:
    if not looks_like_reminder_request(text):
        return None
    due_at = parse_reminder_datetime(text)
    if not due_at:
        return None
    return due_at, extract_reminder_text(text)


def parse_transaction_datetime(text: str) -> datetime:
    raw = text.lower()
    match = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\s+(\d{1,2})[:.](\d{2})", raw)
    if match:
        day, month, year, hour, minute = map(int, match.groups())
        if year < 100:
            year += 2000
        try:
            return datetime(year, month, day, hour, minute, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
        except ValueError:
            pass
    match = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\s+(\d{1,2})[:.](\d{2})", raw)
    if match:
        year, month, day, hour, minute = map(int, match.groups())
        try:
            return datetime(year, month, day, hour, minute, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
        except ValueError:
            pass
    match = re.search(r"(\d{1,2})[:.](\d{2})\s+(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", raw)
    if match:
        hour, minute, day, month, year = map(int, match.groups())
        if year < 100:
            year += 2000
        try:
            return datetime(year, month, day, hour, minute, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def clean_amount(raw: str) -> int:
    value = raw.replace(" ", "").replace("'", "").replace("\u00a0", "")
    if "," in value and "." in value:
        if value.rfind(",") < value.rfind("."):
            value = value.replace(",", "")
        else:
            value = value.replace(".", "").replace(",", ".")
    elif "," in value:
        parts = value.split(",")
        if len(parts[-1]) == 3 and all(part.isdigit() for part in parts):
            value = "".join(parts)
        else:
            value = value.replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", value)
    if not match:
        return 0
    return int(round(float(match.group(0))))


def normalize_sign(sign: str | None) -> str | None:
    if sign in {"➕", "＋"}:
        return "+"
    if sign in {"➖", "−", "–", "—"}:
        return "-"
    return sign or None


def find_amount(text: str) -> tuple[str | None, int]:
    signed = re.search(r"([+\-➕➖＋−–—])\s*([0-9][0-9\s'.,\u00a0]*)\s*(uzs|sum|so'?m|som)", text, re.I)
    if signed:
        return normalize_sign(signed.group(1)), clean_amount(signed.group(2))

    labelled = re.search(
        r"(summa|miqdor|amount|kirim|chiqim|xarajat|oplata|platezh|payment|to'?ldirish|toldirish)[^\d+\-➕➖＋−–—]*([+\-➕➖＋−–—]?)\s*([0-9][0-9\s'.,\u00a0]*)",
        text,
        re.I,
    )
    if labelled:
        return normalize_sign(labelled.group(2)), clean_amount(labelled.group(3))

    manual = re.search(r"([0-9][0-9\s'.,\u00a0]*)", text)
    if manual:
        return None, clean_amount(manual.group(1))
    return None, 0


def detect_tx_type(text: str, sign: str | None, fallback: str | None = None) -> str | None:
    lowered = text.lower()
    if sign == "+":
        return "income"
    if sign == "-":
        return "expense"
    income_words = [
        "kirim",
        "tushdi",
        "kelib tushdi",
        "to'ldirish",
        "toldirish",
        "topup",
        "top up",
        "popolnenie",
        "income",
        "plus",
    ]
    expense_words = [
        "chiqim",
        "xarajat",
        "to'lov",
        "tolov",
        "oplata",
        "platezh",
        "payment",
        "spisanie",
        "minus",
    ]
    if any(word in lowered for word in income_words):
        return "income"
    if any(word in lowered for word in expense_words):
        return "expense"
    return fallback


def detect_source(text: str) -> str:
    lowered = text.lower()
    if "humo" in lowered:
        return "HUMO"
    if "uzcard" in lowered or "cardxabar" in lowered:
        return "UZCARD"
    return "BANK"


def detect_card_last4(text: str) -> str:
    patterns = [
        r"(?:karta|card|карта)[^\d*]{0,20}(?:[*xX.\s]{2,})?(\d{4})",
        r"(?:[*xX.]{2,}\s*)(\d{4})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1)
    return ""


def detect_balance(text: str) -> int | None:
    match = re.search(
        r"(balans|balance|qoldiq|остаток|доступно)[^\d]{0,20}([0-9][0-9\s'.,\u00a0]*)",
        text,
        re.I,
    )
    if not match:
        return None
    amount = clean_amount(match.group(2))
    return amount or None


def detect_category(text: str) -> str:
    lowered = text.lower()
    categories = [
        ("Ovqat", ["ovqat", "food", "kafe", "cafe", "restoran", "restaurant", "fast food"]),
        ("Transport", ["taxi", "yandex", "transport", "yo'l", "yol", "metro", "avtobus"]),
        ("Market", ["market", "supermarket", "magazin", "do'kon", "dokon", "korzinka", "makro"]),
        ("Aloqa", ["paynet", "internet", "telefon", "beeline", "uzmobile", "ucell", "mobiuz"]),
        ("Kiyim", ["kiyim", "clothes", "fashion", "обув", "odej", "dress"]),
        ("Dorixona", ["apteka", "dorixona", "pharmacy"]),
        ("Uy", ["kommunal", "gaz", "svet", "elektr", "ijara", "arenda"]),
        ("Ish haqi", ["ish haqi", "oylik", "salary", "maosh"]),
    ]
    for category, keywords in categories:
        if any(keyword in lowered for keyword in keywords):
            return category
    return "Boshqa"


def looks_like_bank_message(text: str) -> bool:
    lowered = text.lower()
    keywords = [
        "uzcard",
        "humo",
        "cardxabar",
        "karta",
        "card",
        "balans",
        "balance",
        "ostatok",
        "остаток",
        "uzs",
        "сум",
        "so'm",
        "sum",
    ]
    return any(keyword in lowered for keyword in keywords) and bool(re.search(r"\d", text))


def parse_bank_message(text: str, fallback_type: str | None = None) -> ParsedTransaction | None:
    sign, amount = find_amount(text)
    tx_type = detect_tx_type(text, sign, fallback_type)
    if not tx_type or amount <= 0:
        return None
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    description = first_line[:120] if first_line else ("Kirim" if tx_type == "income" else "Xarajat")
    return ParsedTransaction(
        type=tx_type,
        amount=amount,
        currency="UZS",
        occurred_at_utc=parse_transaction_datetime(text),
        source=detect_source(text),
        card_last4=detect_card_last4(text),
        description=description,
        category=detect_category(text),
        balance_after=detect_balance(text),
        raw_text=text,
    )


def parse_balance_message(text: str) -> list[ParsedBalance]:
    balances = parse_uzcard_balances(text)
    if not balances:
        balances = parse_humo_balances(text)
    unique: dict[str, ParsedBalance] = {}
    for item in balances:
        if item.card_last4:
            unique[item.card_last4] = item
    return list(unique.values())


def parse_uzcard_balances(text: str) -> list[ParsedBalance]:
    lowered = text.lower()
    if "umumiy balans" not in lowered and "karta:" not in lowered:
        return []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result: list[ParsedBalance] = []
    current: dict[str, str] | None = None

    for line in lines:
        card_match = re.search(r"karta:\s*([0-9* xX.]+)", line, re.I)
        if card_match:
            if current:
                balance = balance_from_block(current, text, "UZCARD")
                if balance:
                    result.append(balance)
            current = {"card": card_match.group(1), "bank": "", "owner": "", "amount": ""}
            continue
        if current is None:
            continue
        bank_match = re.search(r"bank:\s*(.+)", line, re.I)
        if bank_match:
            current["bank"] = bank_match.group(1).strip()
            continue
        amount_match = re.search(r"([0-9][0-9\s'.,\u00a0]*)\s*(so'?m|сум|uzs|sum)", line, re.I)
        if amount_match:
            current["amount"] = amount_match.group(1)
            continue
        if not current["owner"] and not any(token in line.lower() for token in ["umumiy", "balans", "karta:", "bank:"]):
            current["owner"] = cleanup_bank_label(line)

    if current:
        balance = balance_from_block(current, text, "UZCARD")
        if balance:
            result.append(balance)
    return result


def balance_from_block(block: dict[str, str], raw_text: str, source: str) -> ParsedBalance | None:
    card_last4 = last4_from_card(block.get("card", ""))
    amount_text = block.get("amount", "")
    if not card_last4 or not amount_text:
        return None
    return ParsedBalance(
        source=source,
        card_last4=card_last4,
        amount=clean_amount(amount_text),
        currency="UZS",
        bank=block.get("bank", ""),
        owner=block.get("owner", ""),
        raw_text=raw_text,
    )


def parse_humo_balances(text: str) -> list[ParsedBalance]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result: list[ParsedBalance] = []
    pending: dict[str, str] | None = None

    for line in lines:
        card_match = re.search(r"(.+?)\s*\*(\d{4})\s*$", line)
        if card_match:
            label = cleanup_bank_label(card_match.group(1))
            pending = {
                "label": label,
                "card_last4": card_match.group(2),
                "source": detect_balance_source(label),
                "bank": detect_balance_bank(label),
            }
            continue
        amount_match = re.search(r"([0-9][0-9\s'.,\u00a0]*)\s*(uzs|so'?m|сум|sum)", line, re.I)
        if pending and amount_match:
            result.append(
                ParsedBalance(
                    source=pending["source"],
                    card_last4=pending["card_last4"],
                    amount=clean_amount(amount_match.group(1)),
                    currency="UZS",
                    bank=pending["bank"],
                    owner="",
                    raw_text=text,
                )
            )
            pending = None
    return result


def cleanup_bank_label(text: str) -> str:
    return re.sub(r"^[^\w\d]+", "", text, flags=re.U).strip()


def detect_balance_source(label: str) -> str:
    lowered = label.lower()
    if "humo" in lowered:
        return "HUMO"
    if "visa" in lowered:
        return "VISA"
    if "uzcard" in lowered:
        return "UZCARD"
    return "CARD"


def detect_balance_bank(label: str) -> str:
    cleaned = label.strip()
    cleaned = re.sub(r"\b(humocard|humo|visa|uzcard)\b", "", cleaned, flags=re.I).strip()
    return cleaned or label.strip()


def last4_from_card(text: str) -> str:
    digits = re.findall(r"\d", text)
    if len(digits) >= 4:
        return "".join(digits[-4:])
    return ""


def fix_angle(value: float) -> float:
    return value - 360.0 * math.floor(value / 360.0)


def fix_hour(value: float) -> float:
    return value - 24.0 * math.floor(value / 24.0)


def deg_sin(value: float) -> float:
    return math.sin(math.radians(value))


def deg_cos(value: float) -> float:
    return math.cos(math.radians(value))


def deg_tan(value: float) -> float:
    return math.tan(math.radians(value))


def deg_asin(value: float) -> float:
    return math.degrees(math.asin(value))


def deg_acos(value: float) -> float:
    return math.degrees(math.acos(max(-1.0, min(1.0, value))))


def julian_day(day: date) -> float:
    year = day.year
    month = day.month
    current_day = day.day
    if month <= 2:
        year -= 1
        month += 12
    century = math.floor(year / 100)
    correction = 2 - century + math.floor(century / 4)
    return (
        math.floor(365.25 * (year + 4716))
        + math.floor(30.6001 * (month + 1))
        + current_day
        + correction
        - 1524.5
    )


def sun_position(day: date) -> tuple[float, float]:
    days_from_epoch = julian_day(day) - 2451545.0
    mean_anomaly = fix_angle(357.529 + 0.98560028 * days_from_epoch)
    mean_longitude = fix_angle(280.459 + 0.98564736 * days_from_epoch)
    ecliptic_longitude = fix_angle(
        mean_longitude
        + 1.915 * deg_sin(mean_anomaly)
        + 0.020 * deg_sin(2 * mean_anomaly)
    )
    obliquity = 23.439 - 0.00000036 * days_from_epoch
    right_ascension = math.degrees(
        math.atan2(deg_cos(obliquity) * deg_sin(ecliptic_longitude), deg_cos(ecliptic_longitude))
    ) / 15.0
    right_ascension = fix_hour(right_ascension)
    declination = deg_asin(deg_sin(obliquity) * deg_sin(ecliptic_longitude))
    equation_of_time = mean_longitude / 15.0 - right_ascension
    return declination, equation_of_time


def timezone_hours(day: date) -> float:
    midday = datetime(day.year, day.month, day.day, 12, 0, tzinfo=LOCAL_TZ)
    offset = midday.utcoffset() or timedelta(hours=5)
    return offset.total_seconds() / 3600.0


def sun_hour_angle(angle: float, latitude: float, declination: float) -> float:
    numerator = -deg_sin(angle) - deg_sin(latitude) * deg_sin(declination)
    denominator = deg_cos(latitude) * deg_cos(declination)
    return deg_acos(numerator / denominator) / 15.0


def local_datetime_from_hour(day: date, hour_value: float) -> datetime:
    hour_value = fix_hour(hour_value)
    hour = int(hour_value)
    minute_float = (hour_value - hour) * 60
    minute = int(round(minute_float))
    if minute >= 60:
        hour += 1
        minute -= 60
    if hour >= 24:
        hour -= 24
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=LOCAL_TZ)


def calculate_prayer_times(city: str, day: date | None = None) -> dict[str, datetime]:
    target_day = day or now_local().date()
    latitude, longitude = PRAYER_CITIES.get(city, PRAYER_CITIES["Toshkent"])
    declination, equation = sun_position(target_day)
    noon = 12 + timezone_hours(target_day) - longitude / 15.0 - equation
    asr_shadow_factor = 2  # Uzbekistanda odatda Hanafi ishlatiladi.
    asr_angle = math.degrees(math.atan(1 / (asr_shadow_factor + deg_tan(abs(latitude - declination)))))

    times = {
        "fajr": noon - sun_hour_angle(18.0, latitude, declination),
        "sunrise": noon - sun_hour_angle(0.833, latitude, declination),
        "dhuhr": noon,
        "asr": noon + sun_hour_angle(-asr_angle, latitude, declination),
        "maghrib": noon + sun_hour_angle(0.833, latitude, declination),
        "isha": noon + sun_hour_angle(17.0, latitude, declination),
    }
    return {key: local_datetime_from_hour(target_day, value) for key, value in times.items()}


def normalize_prayer_city(text: str) -> str | None:
    raw = text.strip().lower().replace("'", "").replace("`", "")
    aliases = {
        "tashkent": "Toshkent",
        "toshkent": "Toshkent",
        "samarkand": "Samarqand",
        "samarqand": "Samarqand",
        "bukhara": "Buxoro",
        "buxoro": "Buxoro",
        "andijon": "Andijon",
        "andijan": "Andijon",
        "fargona": "Farg'ona",
        "fargana": "Farg'ona",
        "fergana": "Farg'ona",
        "namangan": "Namangan",
        "qarshi": "Qarshi",
        "karshi": "Qarshi",
        "nukus": "Nukus",
        "urganch": "Urganch",
        "urgench": "Urganch",
        "navoiy": "Navoiy",
        "navoi": "Navoiy",
        "jizzax": "Jizzax",
        "jizzakh": "Jizzax",
        "guliston": "Guliston",
        "termiz": "Termiz",
        "termez": "Termiz",
    }
    if raw in aliases:
        return aliases[raw]
    for city in PRAYER_CITIES:
        if city.lower().replace("'", "") == raw:
            return city
    return None


def format_time_only(dt: datetime) -> str:
    return dt.astimezone(LOCAL_TZ).strftime("%H:%M")


def format_prayer_times(city: str, day: date | None = None) -> str:
    target_day = day or now_local().date()
    times = calculate_prayer_times(city, target_day)
    lines = [
        hbold(f"Namoz vaqtlari - {city}"),
        target_day.strftime("%d.%m.%Y"),
        "",
    ]
    for key in ["fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"]:
        lines.append(f"{PRAYER_NAMES[key]}: {hcode(format_time_only(times[key]))}")
    return "\n".join(lines)


def format_money(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " so'm"


def format_local(dt: datetime) -> str:
    return dt.astimezone(LOCAL_TZ).strftime("%d.%m.%Y %H:%M")


def period_range(period: str) -> tuple[datetime, datetime, str]:
    now = now_local()
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        title = "Bugungi hisobot"
    elif period == "week":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        title = "Haftalik hisobot"
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        title = "Oylik hisobot"
    end = now + timedelta(seconds=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc), title


def format_transaction_saved(tx_id: int, tx: ParsedTransaction) -> str:
    tx_name = "Kirim" if tx.type == "income" else "Xarajat"
    balance = f"\nBalans: {hcode(format_money(tx.balance_after))}" if tx.balance_after is not None else ""
    card = f"\nKarta: {hcode(tx.card_last4)}" if tx.card_last4 else ""
    return (
        f"{hbold(tx_name + ' saqlandi')}: ID {hcode(str(tx_id))}\n"
        f"Summa: {hcode(format_money(tx.amount))}\n"
        f"Kategoriya: {escape_html(tx.category)}\n"
        f"Manba: {escape_html(tx.source)}"
        f"{card}{balance}"
    )


def format_balances_saved(count: int, balances: list[ParsedBalance]) -> str:
    total = sum(item.amount for item in balances)
    lines = [
        hbold("Karta balanslari yangilandi"),
        "",
        f"Yangilangan kartalar: {hcode(str(count))}",
        f"Jami balans: {hcode(format_money(total))}",
        "",
    ]
    for item in balances:
        label = " ".join(part for part in [item.source, item.bank, "*" + item.card_last4] if part)
        lines.append(f"- {escape_html(label)}: {hcode(format_money(item.amount))}")
    return "\n".join(lines)


async def format_report(user_id: int, period: str) -> str:
    start, end, title = period_range(period)
    rows = await get_transactions(user_id, start, end)
    income = sum(row["amount"] for row in rows if row["type"] == "income")
    expense = sum(row["amount"] for row in rows if row["type"] == "expense")
    net = income - expense

    category_expenses: dict[str, int] = {}
    for row in rows:
        if row["type"] == "expense":
            category_expenses[row["category"]] = category_expenses.get(row["category"], 0) + row["amount"]

    lines = [
        hbold(title),
        "",
        f"Kirim: {hcode(format_money(income))}",
        f"Xarajat: {hcode(format_money(expense))}",
        f"Farq: {hcode(format_money(net))}",
        f"Yozuvlar: {hcode(str(len(rows)))}",
    ]
    if category_expenses:
        lines.extend(["", hbold("Xarajat kategoriyalari")])
        for category, amount in sorted(category_expenses.items(), key=lambda item: item[1], reverse=True)[:8]:
            lines.append(f"- {escape_html(category)}: {hcode(format_money(amount))}")

    balances = await get_card_balances(user_id)
    if balances:
        lines.extend(["", hbold("Oxirgi balanslar")])
        for row in balances:
            label = balance_label(row)
            lines.append(f"- {escape_html(label)}: {hcode(format_money(row['amount']))}")
    return "\n".join(lines)


async def daily_report_users() -> list[tuple[int, int]]:
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall(
            """
            SELECT DISTINCT user_id, chat_id
            FROM prayer_settings
            WHERE chat_id > 0
            """
        )
    result: list[tuple[int, int]] = []
    for user_id, chat_id in rows:
        if (await get_user_setting(int(user_id), "daily_report_enabled", "1")) != "0":
            result.append((int(user_id), int(chat_id)))
    return result


async def was_daily_report_sent(user_id: int, report_date: date) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall(
            """
            SELECT 1
            FROM daily_report_sent
            WHERE user_id = ? AND report_date = ?
            LIMIT 1
            """,
            (user_id, report_date.isoformat()),
        )
    return bool(rows)


async def mark_daily_report_sent(user_id: int, report_date: date) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO daily_report_sent (user_id, report_date, sent_at)
            VALUES (?, ?, ?)
            """,
            (user_id, report_date.isoformat(), utc_text()),
        )
        await db.commit()


def balance_label(row: dict) -> str:
    parts = [row.get("source", "CARD")]
    if row.get("bank"):
        parts.append(row["bank"])
    if row.get("card_last4"):
        parts.append("*" + row["card_last4"])
    return " ".join(parts)


async def format_card_balances(user_id: int) -> str:
    rows = await get_card_balances(user_id)
    if not rows:
        return "Hali karta balanslari saqlanmagan. UZCARD/HUMO balans xabarini forward yoki copy-paste qiling."
    total = sum(row["amount"] for row in rows)
    lines = [hbold("Kartalar balansi"), "", f"Jami: {hcode(format_money(total))}", ""]
    for row in rows:
        lines.append(f"{escape_html(balance_label(row))}: {hcode(format_money(row['amount']))}")
        if row.get("owner"):
            lines.append(f"Egasi: {escape_html(row['owner'])}")
        lines.append(f"Yangilangan: {hcode(format_local(row['updated_at']))}")
        lines.append("")
    return "\n".join(lines).strip()


async def estimated_balance_from_transaction(user_id: int, tx: ParsedTransaction) -> ParsedBalance | None:
    if not tx.card_last4:
        return None
    current = await get_card_balance(user_id, tx.card_last4)
    if not current:
        if tx.type != "income":
            return None
        return ParsedBalance(
            source=tx.source,
            card_last4=tx.card_last4,
            amount=tx.amount,
            currency=tx.currency,
            bank="",
            owner="",
            raw_text=tx.raw_text,
        )
    amount = current["amount"] + tx.amount if tx.type == "income" else current["amount"] - tx.amount
    if amount < 0:
        amount = 0
    return ParsedBalance(
        source=tx.source if tx.source and tx.source != "BANK" else current["source"],
        card_last4=tx.card_last4,
        amount=amount,
        currency=tx.currency,
        bank=current["bank"],
        owner=current["owner"],
        raw_text=tx.raw_text,
    )


async def save_finance_text(user_id: int, text: str) -> tuple[ParsedTransaction | None, int | None, list[ParsedBalance], int, bool]:
    tx = parse_bank_message(text)
    bank_balances = parse_balance_message(text)
    balances = list(bank_balances)
    used_estimated_balance = False
    tx_id: int | None = None
    balance_count = 0
    if tx:
        tx_id = await save_transaction(user_id, tx)
        if tx.card_last4 and not any(item.card_last4 == tx.card_last4 for item in bank_balances):
            estimated = await estimated_balance_from_transaction(user_id, tx)
            if estimated:
                balances.append(estimated)
                used_estimated_balance = True
    if balances:
        balance_count = await save_balances(user_id, balances)
    return tx, tx_id, balances, balance_count, used_estimated_balance


def format_finance_saved(
    tx: ParsedTransaction | None,
    tx_id: int | None,
    balances: list[ParsedBalance],
    balance_count: int,
    used_estimated_balance: bool = False,
) -> str:
    parts: list[str] = []
    if tx and tx_id is not None:
        parts.append(format_transaction_saved(tx_id, tx))
    if balances:
        text = format_balances_saved(balance_count, balances)
        if used_estimated_balance:
            text += "\n" + hcode("Balans kirim/chiqim bo'yicha hisoblandi. Bank aniq balans yuborsa, o'sha qiymatga almashtiriladi.")
        parts.append(text)
    return "\n\n".join(parts)


async def format_last_transactions(user_id: int) -> str:
    rows = await get_transactions(user_id, limit=10)
    if not rows:
        return "Hali moliya yozuvlari yo'q."
    lines = [hbold("Oxirgi 10 yozuv"), ""]
    for row in rows:
        sign = "+" if row["type"] == "income" else "-"
        lines.append(
            f"ID {hcode(str(row['id']))}: {sign}{hcode(format_money(row['amount']))} | "
            f"{escape_html(row['category'])} | {format_local(row['occurred_at'])}"
        )
    return "\n".join(lines)


def json_dt(dt: datetime) -> str:
    return dt.astimezone(LOCAL_TZ).isoformat()


def json_money(amount: int) -> str:
    return format_money(amount)


def transaction_json(row: dict) -> dict:
    return {
        "id": row["id"],
        "type": row["type"],
        "amount": row["amount"],
        "amount_text": json_money(row["amount"]),
        "category": row["category"],
        "source": row["source"],
        "card_last4": row["card_last4"],
        "description": row["description"],
        "occurred_at": json_dt(row["occurred_at"]),
    }


def reminder_json(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": json_dt(row["created_at"]),
        "due_at": json_dt(row["due_at"]),
        "text": row["text"],
        "status": row["status"],
        "sent_at": json_dt(row["sent_at"]) if row["sent_at"] else None,
        "repeat_rule": row.get("repeat_rule", ""),
        "repeat_label": REPEAT_LABELS.get(row.get("repeat_rule", ""), ""),
    }


async def dashboard_payload(user_id: int, chat_id: int | None = None) -> dict:
    balances = await get_card_balances(user_id)
    today_start, today_end, _ = period_range("today")
    week_start, week_end, _ = period_range("week")
    month_start, month_end, _ = period_range("month")
    today_rows = await get_transactions(user_id, today_start, today_end)
    week_rows = await get_transactions(user_id, week_start, week_end)
    month_rows = await get_transactions(user_id, month_start, month_end)
    recent_rows = await get_transactions(user_id, limit=8)
    transaction_rows = await get_transactions(user_id, limit=80)
    active_reminders = await list_pending_reminder_records(user_id, limit=30)
    completed_reminders = await list_completed_reminder_records(user_id, limit=30)
    prayer_setting = await get_prayer_setting(user_id, chat_id)
    prayer_times = calculate_prayer_times(prayer_setting["city"], now_local().date())
    enabled_prayers = {key for key in prayer_setting["prayers"].split(",") if key in DEFAULT_PRAYER_KEYS}
    daily_limit = int((await get_user_setting(user_id, "daily_expense_limit", "0")) or 0)
    daily_report_enabled = (await get_user_setting(user_id, "daily_report_enabled", "1")) != "0"
    now = now_local()
    next_prayer = None
    for key in ["fajr", "dhuhr", "asr", "maghrib", "isha"]:
        if prayer_times[key] >= now:
            next_prayer = {
                "key": key,
                "name": PRAYER_NAMES[key],
                "time": format_time_only(prayer_times[key]),
                "iso": json_dt(prayer_times[key]),
            }
            break

    def totals(rows: list[dict]) -> dict:
        income = sum(row["amount"] for row in rows if row["type"] == "income")
        expense = sum(row["amount"] for row in rows if row["type"] == "expense")
        return {
            "income": income,
            "expense": expense,
            "net": income - expense,
            "count": len(rows),
            "income_text": json_money(income),
            "expense_text": json_money(expense),
            "net_text": json_money(income - expense),
        }

    category_totals: dict[str, int] = {}
    for row in month_rows:
        if row["type"] == "expense":
            category = row["category"] or "Boshqa"
            category_totals[category] = category_totals.get(category, 0) + row["amount"]

    return {
        "generated_at": json_dt(now),
        "balances": [
            {
                "label": balance_label(row),
                "source": row["source"],
                "card_last4": row["card_last4"],
                "bank": row["bank"],
                "owner": row["owner"],
                "amount": row["amount"],
                "amount_text": json_money(row["amount"]),
                "updated_at": json_dt(row["updated_at"]),
            }
            for row in balances
        ],
        "balance_total": sum(row["amount"] for row in balances),
        "balance_total_text": json_money(sum(row["amount"] for row in balances)),
        "today": totals(today_rows),
        "week": totals(week_rows),
        "month": totals(month_rows),
        "categories": [
            {"name": name, "amount": amount, "amount_text": json_money(amount)}
            for name, amount in sorted(category_totals.items(), key=lambda item: item[1], reverse=True)[:6]
        ],
        "recent_transactions": [transaction_json(row) for row in recent_rows],
        "transactions": [transaction_json(row) for row in transaction_rows],
        "reminders": [reminder_json(row) for row in active_reminders[:6]],
        "active_reminders": [reminder_json(row) for row in active_reminders],
        "completed_reminders": [reminder_json(row) for row in completed_reminders],
        "prayer": {
            "city": prayer_setting["city"],
            "enabled": prayer_setting["enabled"],
            "enabled_keys": sorted(enabled_prayers),
            "minutes_before": prayer_setting["minutes_before"],
            "source": "Hozircha offline hisoblash. Rasmiy API topilsa ulanadi.",
            "next": next_prayer,
            "times": [
                {
                    "key": key,
                    "name": PRAYER_NAMES[key],
                    "time": format_time_only(prayer_times[key]),
                    "iso": json_dt(prayer_times[key]),
                    "enabled": key in enabled_prayers if key in DEFAULT_PRAYER_KEYS else False,
                    "can_notify": key in DEFAULT_PRAYER_KEYS,
                }
                for key in ["fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"]
            ],
        },
        "settings": {
            "daily_expense_limit": daily_limit,
            "daily_expense_limit_text": json_money(daily_limit) if daily_limit > 0 else "Belgilanmagan",
            "daily_report_enabled": daily_report_enabled,
        },
        "cities": list(PRAYER_CITIES.keys()),
    }


def validate_telegram_init_data(init_data: str, bot_token: str) -> int | None:
    if not init_data or not bot_token:
        return None
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None
    data_check_string = "\n".join(f"{key}={parsed[key]}" for key in sorted(parsed))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        return None
    try:
        auth_date = int(parsed.get("auth_date", "0"))
    except ValueError:
        return None
    max_age = int(os.getenv("MINIAPP_AUTH_MAX_AGE_SECONDS", "86400"))
    if not auth_date or (max_age > 0 and time.time() - auth_date > max_age):
        return None
    try:
        user = json.loads(parsed.get("user", "{}"))
        return int(user["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def local_dev_user_id(request: web.Request) -> int | None:
    preview_enabled = os.getenv("MINIAPP_ALLOW_LOCAL_PREVIEW", "").strip().lower()
    if preview_enabled not in {"1", "true", "yes", "on"}:
        return None
    if request.remote not in {"127.0.0.1", "::1", "localhost"}:
        return None
    host = request.headers.get("Host", "").split(":", 1)[0].strip("[]").lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return None
    if request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For"):
        return None
    raw = os.getenv("MINIAPP_DEV_USER_ID", "").strip()
    if raw.isdigit():
        return int(raw)
    allowed = allowed_user_ids()
    if len(allowed) == 1:
        return next(iter(allowed))
    return None


async def miniapp_user_id(request: web.Request) -> int:
    token = os.getenv("BOT_TOKEN", "").strip()
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user_id = validate_telegram_init_data(init_data, token) or local_dev_user_id(request)
    if not user_id:
        raise web.HTTPUnauthorized(text="Mini App auth failed")
    allowed = allowed_user_ids()
    if allowed and user_id not in allowed:
        raise web.HTTPForbidden(text="User is not allowed")
    return user_id


def no_store_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store, max-age=0"}


async def request_json(request: web.Request) -> dict:
    try:
        body = await request.json()
    except (TypeError, ValueError, json.JSONDecodeError):
        raise web.HTTPBadRequest(text="JSON body required")
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="JSON object required")
    return body


async def miniapp_index(_: web.Request) -> web.FileResponse:
    return web.FileResponse(MINIAPP_DIR / "index.html", headers=no_store_headers())


async def miniapp_asset(request: web.Request) -> web.FileResponse:
    filename = request.match_info["filename"]
    safe_path = (MINIAPP_DIR / filename).resolve()
    if MINIAPP_DIR.resolve() not in safe_path.parents:
        raise web.HTTPForbidden()
    if not safe_path.exists() or not safe_path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(safe_path, headers=no_store_headers())


async def miniapp_dashboard(request: web.Request) -> web.Response:
    user_id = await miniapp_user_id(request)
    payload = await dashboard_payload(user_id)
    return web.json_response(payload, headers=no_store_headers())


async def miniapp_reminder_delete(request: web.Request) -> web.Response:
    user_id = await miniapp_user_id(request)
    body = await request_json(request)
    try:
        reminder_id = int(body.get("id"))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="Reminder id required")
    ok = await delete_reminder(user_id, reminder_id)
    return web.json_response({"ok": ok}, headers=no_store_headers())


async def miniapp_transaction_delete(request: web.Request) -> web.Response:
    user_id = await miniapp_user_id(request)
    body = await request_json(request)
    try:
        transaction_id = int(body.get("id"))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="Transaction id required")
    ok = await delete_transaction(user_id, transaction_id)
    return web.json_response({"ok": ok}, headers=no_store_headers())


async def miniapp_transaction_update(request: web.Request) -> web.Response:
    user_id = await miniapp_user_id(request)
    body = await request_json(request)
    try:
        transaction_id = int(body.get("id"))
        amount = int(clean_amount(str(body.get("amount", ""))))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="Transaction id and amount required")
    tx_type = str(body.get("type", "")).strip()
    category = str(body.get("category", "Boshqa")).strip()[:60] or "Boshqa"
    description = str(body.get("description", "")).strip()[:120]
    occurred_at = None
    occurred_raw = str(body.get("occurred_at", "")).strip()
    if occurred_raw:
        try:
            occurred_at = parse_utc(occurred_raw)
        except ValueError:
            occurred_at = None
    ok = await update_transaction(user_id, transaction_id, tx_type, amount, category, description, occurred_at)
    return web.json_response({"ok": ok}, headers=no_store_headers())


async def miniapp_daily_limit(request: web.Request) -> web.Response:
    user_id = await miniapp_user_id(request)
    body = await request_json(request)
    amount = clean_amount(str(body.get("amount", "")))
    await set_user_setting(user_id, "daily_expense_limit", str(max(amount, 0)))
    return web.json_response({"ok": True, "amount": amount}, headers=no_store_headers())


async def miniapp_daily_report_setting(request: web.Request) -> web.Response:
    user_id = await miniapp_user_id(request)
    body = await request_json(request)
    enabled = bool(body.get("enabled"))
    await set_user_setting(user_id, "daily_report_enabled", "1" if enabled else "0")
    return web.json_response({"ok": True, "enabled": enabled}, headers=no_store_headers())


async def miniapp_export_transactions(request: web.Request) -> web.Response:
    user_id = await miniapp_user_id(request)
    rows = await get_transactions(user_id, limit=10000)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "date", "type", "amount", "currency", "source", "card_last4", "category", "description"])
    for row in rows:
        writer.writerow(
            [
                row["id"],
                json_dt(row["occurred_at"]),
                row["type"],
                row["amount"],
                row["currency"],
                row["source"],
                row["card_last4"],
                row["category"],
                row["description"],
            ]
        )
    headers = no_store_headers()
    headers["Content-Disposition"] = 'attachment; filename="assistant-transactions.csv"'
    return web.Response(text=output.getvalue(), content_type="text/csv", charset="utf-8", headers=headers)


async def miniapp_clear_data(request: web.Request) -> web.Response:
    user_id = await miniapp_user_id(request)
    body = await request_json(request)
    scope = str(body.get("scope", "")).strip()
    try:
        await clear_user_data(user_id, scope)
    except ValueError:
        raise web.HTTPBadRequest(text="Unknown clear scope")
    return web.json_response({"ok": True, "scope": scope}, headers=no_store_headers())


async def miniapp_prayer_toggle(request: web.Request) -> web.Response:
    user_id = await miniapp_user_id(request)
    body = await request_json(request)
    enabled = bool(body.get("enabled"))
    prayers = ",".join(DEFAULT_PRAYER_KEYS) if enabled else ""
    setting = await save_prayer_setting(user_id, 0, enabled=enabled, prayers=prayers)
    return web.json_response({"ok": True, "enabled": setting["enabled"]}, headers=no_store_headers())


async def miniapp_prayer_key(request: web.Request) -> web.Response:
    user_id = await miniapp_user_id(request)
    body = await request_json(request)
    key = str(body.get("key", "")).strip()
    if key not in DEFAULT_PRAYER_KEYS:
        raise web.HTTPBadRequest(text="Unknown prayer key")
    setting = await get_prayer_setting(user_id)
    enabled_keys = {item for item in setting["prayers"].split(",") if item in DEFAULT_PRAYER_KEYS}
    if bool(body.get("enabled")):
        enabled_keys.add(key)
    else:
        enabled_keys.discard(key)
    ordered = [item for item in DEFAULT_PRAYER_KEYS if item in enabled_keys]
    updated = await save_prayer_setting(
        user_id,
        0,
        prayers=",".join(ordered),
        enabled=bool(ordered),
    )
    return web.json_response({"ok": True, "enabled": updated["enabled"], "enabled_keys": ordered}, headers=no_store_headers())


async def miniapp_prayer_city(request: web.Request) -> web.Response:
    user_id = await miniapp_user_id(request)
    body = await request_json(request)
    city = normalize_prayer_city(str(body.get("city", "")))
    if not city:
        raise web.HTTPBadRequest(text="Unknown city")
    setting = await save_prayer_setting(user_id, 0, city=city)
    return web.json_response({"ok": True, "city": setting["city"]}, headers=no_store_headers())


async def miniapp_prayer_lead_time(request: web.Request) -> web.Response:
    user_id = await miniapp_user_id(request)
    body = await request_json(request)
    try:
        minutes = int(body.get("minutes", 0))
    except (TypeError, ValueError):
        minutes = 0
    if minutes not in {0, 5, 10, 15}:
        raise web.HTTPBadRequest(text="Allowed values: 0, 5, 10, 15")
    setting = await save_prayer_setting(user_id, 0, minutes_before=minutes)
    return web.json_response({"ok": True, "minutes_before": setting["minutes_before"]}, headers=no_store_headers())


async def start_miniapp_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", miniapp_index)
    app.router.add_get("/api/dashboard", miniapp_dashboard)
    app.router.add_post("/api/reminders/delete", miniapp_reminder_delete)
    app.router.add_post("/api/transactions/delete", miniapp_transaction_delete)
    app.router.add_post("/api/transactions/update", miniapp_transaction_update)
    app.router.add_post("/api/settings/daily-limit", miniapp_daily_limit)
    app.router.add_post("/api/settings/daily-report", miniapp_daily_report_setting)
    app.router.add_get("/api/export/transactions.csv", miniapp_export_transactions)
    app.router.add_post("/api/data/clear", miniapp_clear_data)
    app.router.add_post("/api/prayer/toggle", miniapp_prayer_toggle)
    app.router.add_post("/api/prayer/key", miniapp_prayer_key)
    app.router.add_post("/api/prayer/city", miniapp_prayer_city)
    app.router.add_post("/api/prayer/lead-time", miniapp_prayer_lead_time)
    app.router.add_get("/{filename:.*\\.(?:css|js|png|jpg|jpeg|webp|svg|ico)}", miniapp_asset)
    runner = web.AppRunner(app)
    await runner.setup()
    host = os.getenv("MINIAPP_HOST", "127.0.0.1")
    port = int(os.getenv("MINIAPP_PORT", "8080"))
    site = web.TCPSite(runner, host, port)
    await site.start()
    logging.info("Mini App server started at http://%s:%s", host, port)
    return runner


async def configure_miniapp_menu_button(bot: Bot, chat_id: int | None = None) -> None:
    url = mini_app_url()
    if not url.startswith("https://"):
        logging.warning("Mini App menu button o'rnatilmadi: HTTPS URL kerak, hozirgi URL=%s", url)
        return
    try:
        await bot.set_chat_menu_button(
            chat_id=chat_id,
            menu_button=MenuButtonWebApp(text=MAIN_MINI_APP, web_app=WebAppInfo(url=url)),
        )
        target = f"chat_id={chat_id}" if chat_id else "default"
        logging.info("Telegram Mini App menu button o'rnatildi (%s): %s", target, url)
    except Exception as exc:
        logging.exception("Mini App menu button o'rnatilmadi: %s", exc)


async def configure_known_user_menu_buttons(bot: Bot) -> None:
    chat_ids = set(allowed_user_ids())
    dev_user_id = os.getenv("MINIAPP_DEV_USER_ID", "").strip()
    if dev_user_id.isdigit():
        chat_ids.add(int(dev_user_id))
    for chat_id in chat_ids:
        await configure_miniapp_menu_button(bot, chat_id)


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    await save_prayer_setting(user_id_from(message), message.chat.id)
    await configure_miniapp_menu_button(bot, message.chat.id)
    await message.answer(
        "Assalomu alaykum. Men shaxsiy yordamchi botman.\n\n"
        "Eslatmalarni saqlayman, UZCARD/HUMO xabarlaridan kirim-xarajat hisobotini chiqaraman.\n"
        "Namoz vaqtlarini ko'rsatib, yoqsangiz eslatib turaman.\n"
        "Har bir foydalanuvchining ma'lumoti alohida saqlanadi.",
        reply_markup=main_keyboard(),
    )


@router.message(Command("app"))
async def app_link(message: Message, bot: Bot) -> None:
    await configure_miniapp_menu_button(bot, message.chat.id)
    await message.answer(
        "Mini App tugmasi yangilandi. Ochish uchun:",
        reply_markup=miniapp_inline_keyboard(),
    )


@router.message(Command("cancel"))
@router.message(F.text == CANCEL)
@router.message(F.text == MAIN_MENU)
async def cancel_or_main(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Asosiy menyu.", reply_markup=main_keyboard())


@router.message(F.text == BACK)
async def go_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Asosiy menyu.", reply_markup=main_keyboard())


@router.message(Command("id"))
async def show_my_id(message: Message) -> None:
    await message.answer(f"Sizning Telegram ID: {hcode(str(user_id_from(message)))}", reply_markup=main_keyboard())


@router.message(Command("connect"))
async def connect_guide(message: Message) -> None:
    assistant_username = os.getenv("ASSISTANT_BOT_USERNAME", "").strip() or "assistant bot username"
    source_bots = os.getenv("SOURCE_BOT_USERNAMES", "@CardXabarBot,@HUMOcardbot").strip()
    settings_title = "Kerak bo'ladigan sozlamalar"
    await message.answer(
        f"{hbold('Avtomatik moliya ulash')}\n\n"
        "Telegram login kodi va 2FA parolni botga yuborish xavfsiz emas. "
        "Shuning uchun avtomatik ulash har bir userning o'z kompyuterida ishlaydigan forwarder orqali qilinadi.\n\n"
        f"{hbold(settings_title)}\n"
        f"ASSISTANT_BOT_USERNAME={hcode(assistant_username)}\n"
        f"SOURCE_BOT_USERNAMES={hcode(source_bots)}\n\n"
        f"{hbold('Qanday ishlaydi')}\n"
        "1. User forwarder papkasini o'z kompyuterida ishga tushiradi.\n"
        "2. Telefon raqami va Telegram kodi faqat o'sha kompyuterda kiritiladi.\n"
        "3. UZCARD/HUMO xabarlari assistant botga o'sha user nomidan yuboriladi.\n"
        "4. Bot ma'lumotlarni o'sha user Telegram ID siga alohida saqlaydi.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == MAIN_HELP)
@router.message(Command("help"))
async def help_message(message: Message) -> None:
    await message.answer(
        f"{hbold('Yordam')}\n\n"
        f"{hbold('Eslatma')}\n"
        "Asosiy menyuda ham eslatma yozishingiz mumkin.\n"
        "Masalan: 1 daqiqadan keyin suv ichishni eslat.\n"
        "Misollar: ertaga soat 5 da, yarim soatdan keyin, juma soat 10, 03.05 09:00.\n\n"
        f"{hbold('Moliya')}\n"
        "UZCARD/HUMO xabarini asosiy menyuda turib ham forward qiling yoki copy-paste qiling.\n"
        "Balans ro'yxati yuborsangiz, kartalar balansini yangilaydi.\n"
        "Qo'lda yozish ham mumkin: plus 500000 oylik, minus 45000 ovqat.\n\n"
        f"{hbold('Namoz')}\n"
        "Shahar tanlang, bugungi namoz vaqtlarini ko'ring va eslatmani yoqing.\n\n"
        f"{hbold('ID')}\n"
        f"O'z Telegram ID ingizni ko'rish: /id\n"
        f"Avtomatik bank xabarlarini ulash yo'riqnomasi: /connect\n\n"
        "Bot boshqa foydalanuvchilarning ma'lumotlarini sizga ko'rsatmaydi.",
        reply_markup=miniapp_inline_keyboard(),
    )


@router.message(F.text == MAIN_PRAYER)
@router.message(Command("prayer"))
@router.message(Command("namoz"))
async def prayer_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    setting = await get_prayer_setting(user_id_from(message), message.chat.id)
    status = "yoqilgan" if setting["enabled"] else "o'chirilgan"
    title = "Namoz bo'limi"
    enabled_prayers = ", ".join(
        PRAYER_NAMES[key] for key in setting["prayers"].split(",") if key in PRAYER_NAMES
    )
    await message.answer(
        f"{hbold(title)}\n\n"
        f"Shahar: {hcode(setting['city'])}\n"
        f"Eslatma: {hcode(status)}\n"
        f"Eslatiladigan namozlar: {hcode(enabled_prayers)}",
        reply_markup=prayer_keyboard(setting["enabled"]),
    )


@router.message(F.text == PRAYER_TODAY)
async def prayer_today(message: Message) -> None:
    setting = await get_prayer_setting(user_id_from(message), message.chat.id)
    await message.answer(format_prayer_times(setting["city"]), reply_markup=prayer_keyboard(setting["enabled"]))


@router.message(F.text == PRAYER_ENABLE)
async def prayer_enable(message: Message) -> None:
    setting = await save_prayer_setting(user_id_from(message), message.chat.id, enabled=True)
    await message.answer(
        "Namoz eslatmalari yoqildi.\n\n" + format_prayer_times(setting["city"]),
        reply_markup=prayer_keyboard(True),
    )


@router.message(F.text == PRAYER_DISABLE)
async def prayer_disable(message: Message) -> None:
    setting = await save_prayer_setting(user_id_from(message), message.chat.id, enabled=False)
    await message.answer("Namoz eslatmalari o'chirildi.", reply_markup=prayer_keyboard(setting["enabled"]))


@router.message(F.text == PRAYER_CITY)
async def prayer_city_start(message: Message, state: FSMContext) -> None:
    await state.set_state(PrayerWizard.waiting_city)
    await message.answer("Shaharni tanlang yoki nomini yozing.", reply_markup=city_keyboard())


@router.message(PrayerWizard.waiting_city)
async def prayer_city_finish(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Shahar nomini matn qilib yozing.")
        return
    city = normalize_prayer_city(message.text)
    if not city:
        await message.answer(
            "Bu shahar ro'yxatda yo'q. Tugmalardan birini tanlang yoki masalan Toshkent deb yozing.",
            reply_markup=city_keyboard(),
        )
        return
    setting = await save_prayer_setting(user_id_from(message), message.chat.id, city=city)
    await state.clear()
    await message.answer(
        f"Shahar saqlandi: {hcode(city)}\n\n" + format_prayer_times(city),
        reply_markup=prayer_keyboard(setting["enabled"]),
    )


@router.message(F.text == PRAYER_SETTINGS)
async def prayer_settings(message: Message) -> None:
    setting = await get_prayer_setting(user_id_from(message), message.chat.id)
    status = "yoqilgan" if setting["enabled"] else "o'chirilgan"
    prayer_names = ", ".join(PRAYER_NAMES[key] for key in setting["prayers"].split(",") if key in PRAYER_NAMES)
    await message.answer(
        f"{hbold('Namoz sozlamalari')}\n\n"
        f"Shahar: {hcode(setting['city'])}\n"
        f"Eslatma: {hcode(status)}\n"
        f"Namozlar: {hcode(prayer_names)}\n"
        f"Oldindan eslatish: {hcode(str(setting['minutes_before']))} daqiqa\n\n"
        "Oldindan eslatish vaqtini Mini App ichidagi Qo'shimcha bo'limidan 0/5/10/15 daqiqaga o'zgartirish mumkin.",
        reply_markup=prayer_keyboard(setting["enabled"]),
    )


@router.message(F.text == MAIN_REMINDERS)
@router.message(Command("reminders"))
async def reminders_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Eslatma bo'limi.", reply_markup=reminders_keyboard())


@router.message(F.text == REMINDER_ADD)
async def reminder_add_start(message: Message, state: FSMContext) -> None:
    await state.set_state(ReminderWizard.waiting_datetime)
    await message.answer(
        "Qachon eslatay?\n\n"
        "Misollar:\n"
        "- 2026-05-03 14:30\n"
        "- 03.05 09:00\n"
        "- ertaga soat 10\n"
        "- indinga 09:30\n"
        "- juma soat 10\n"
        "- yarim soatdan keyin\n"
        "- 30 daqiqadan keyin",
        reply_markup=back_keyboard(),
    )


@router.message(ReminderWizard.waiting_datetime)
async def reminder_datetime(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Sana va vaqtni matn qilib yozing.")
        return
    due_at = parse_reminder_datetime(message.text)
    if not due_at or due_at <= datetime.now(timezone.utc):
        await message.answer("Vaqtni tushunmadim yoki o'tib ketgan vaqt. Masalan: ertaga 10:00")
        return
    await state.update_data(due_at=utc_text(due_at), repeat_rule=detect_repeat_rule(message.text))
    await state.set_state(ReminderWizard.waiting_text)
    await message.answer("Nimani eslatay? Xabar matnini yozing.", reply_markup=back_keyboard())


@router.message(ReminderWizard.waiting_text)
async def reminder_text(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Eslatma matnini yozing.")
        return
    data = await state.get_data()
    due_at = parse_utc(data["due_at"])
    data_repeat = str(data.get("repeat_rule", ""))
    reminder_id = await add_reminder(user_id_from(message), message.chat.id, due_at, message.text.strip(), data_repeat)
    await state.clear()
    repeat_text = f"\nTakrorlash: {hcode(REPEAT_LABELS[data_repeat])}" if data_repeat in REPEAT_LABELS else ""
    await message.answer(
        f"Eslatma saqlandi: ID {hcode(str(reminder_id))}\n"
        f"Vaqt: {hcode(format_local(due_at))}\n"
        f"Xabar: {escape_html(message.text.strip())}{repeat_text}",
        reply_markup=reminders_keyboard(),
    )


@router.message(F.text == REMINDER_LIST)
async def reminder_list(message: Message) -> None:
    rows = await list_reminders(user_id_from(message))
    if not rows:
        await message.answer("Sizda faol eslatmalar yo'q.", reply_markup=reminders_keyboard())
        return
    lines = [hbold("Faol eslatmalar"), ""]
    for reminder_id, due_at, text in rows:
        lines.append(f"ID {hcode(str(reminder_id))}: {hcode(format_local(due_at))}")
        lines.append(escape_html(text[:120]))
        lines.append("")
    await message.answer("\n".join(lines).strip(), reply_markup=reminders_keyboard())


@router.message(F.text == REMINDER_DELETE)
async def reminder_delete_start(message: Message, state: FSMContext) -> None:
    await state.set_state(ReminderWizard.waiting_delete_id)
    await message.answer("O'chiriladigan eslatma ID raqamini yozing.", reply_markup=back_keyboard())


@router.message(ReminderWizard.waiting_delete_id)
async def reminder_delete_finish(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip().isdigit():
        await message.answer("Faqat ID raqamini yozing.")
        return
    ok = await delete_reminder(user_id_from(message), int(message.text.strip()))
    await state.clear()
    await message.answer(
        "Eslatma o'chirildi." if ok else "Bu ID bo'yicha faol eslatma topilmadi.",
        reply_markup=reminders_keyboard(),
    )


@router.message(F.text == MAIN_FINANCE)
@router.message(Command("finance"))
async def finance_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Moliya bo'limi.\n\n"
        "Bu yerda haftalik/oylik hisobot va karta balanslarini ko'rasiz.\n"
        "UZCARD/HUMO xabarini qo'shish uchun alohida bo'limga kirish shart emas: "
        "asosiy menyuda turib forward yoki copy-paste qilsangiz, bot o'zi moliyaga saqlaydi.",
        reply_markup=finance_keyboard(),
    )


@router.message(F.text == FINANCE_BANK)
async def finance_bank_start(message: Message, state: FSMContext) -> None:
    await state.set_state(FinanceWizard.waiting_bank_message)
    await message.answer(
        "UZCARD/HUMO xabarini shu yerga forward qiling yoki matnini tashlang.",
        reply_markup=back_keyboard(),
    )


@router.message(F.text == FINANCE_INCOME)
async def finance_income_start(message: Message, state: FSMContext) -> None:
    await state.set_state(FinanceWizard.waiting_income)
    await message.answer("Kirimni yozing. Masalan: 500000 oylik", reply_markup=back_keyboard())


@router.message(F.text == FINANCE_EXPENSE)
async def finance_expense_start(message: Message, state: FSMContext) -> None:
    await state.set_state(FinanceWizard.waiting_expense)
    await message.answer("Xarajatni yozing. Masalan: 45000 ovqat", reply_markup=back_keyboard())


@router.message(FinanceWizard.waiting_bank_message)
async def finance_bank_finish(message: Message, state: FSMContext) -> None:
    text = message.text or message.caption or ""
    tx, tx_id, balances, balance_count, used_estimated_balance = await save_finance_text(user_id_from(message), text)
    if not tx and not balances:
        await message.answer(
            "Bu xabardan summa va kirim/xarajatni aniqlay olmadim. "
            "UZCARD/HUMO xabarini to'liq yuboring yoki qo'lda plus/minus qilib kiriting."
        )
        return
    await state.clear()
    await message.answer(
        format_finance_saved(tx, tx_id, balances, balance_count, used_estimated_balance),
        reply_markup=finance_keyboard(),
    )


@router.message(FinanceWizard.waiting_income)
async def finance_income_finish(message: Message, state: FSMContext) -> None:
    await save_manual_transaction(message, state, "income")


@router.message(FinanceWizard.waiting_expense)
async def finance_expense_finish(message: Message, state: FSMContext) -> None:
    await save_manual_transaction(message, state, "expense")


async def save_manual_transaction(message: Message, state: FSMContext, tx_type: str) -> None:
    text = message.text or ""
    tx = parse_bank_message(text, fallback_type=tx_type)
    if not tx:
        await message.answer("Summa topilmadi. Masalan: 45000 ovqat")
        return
    tx.type = tx_type
    tx.source = "MANUAL"
    tx.category = detect_category(text)
    tx.description = text.strip()[:120] or ("Kirim" if tx_type == "income" else "Xarajat")
    tx_id = await save_transaction(user_id_from(message), tx)
    await state.clear()
    await message.answer(format_transaction_saved(tx_id, tx), reply_markup=finance_keyboard())


@router.message(F.text == FINANCE_TODAY)
async def finance_today(message: Message) -> None:
    await message.answer(await format_report(user_id_from(message), "today"), reply_markup=finance_keyboard())


@router.message(F.text == FINANCE_WEEK)
async def finance_week(message: Message) -> None:
    await message.answer(await format_report(user_id_from(message), "week"), reply_markup=finance_keyboard())


@router.message(F.text == FINANCE_MONTH)
async def finance_month(message: Message) -> None:
    await message.answer(await format_report(user_id_from(message), "month"), reply_markup=finance_keyboard())


@router.message(F.text == FINANCE_LAST)
async def finance_last(message: Message) -> None:
    await message.answer(await format_last_transactions(user_id_from(message)), reply_markup=finance_keyboard())


@router.message(F.text == FINANCE_BALANCES)
async def finance_balances(message: Message) -> None:
    await message.answer(await format_card_balances(user_id_from(message)), reply_markup=finance_keyboard())


@router.message(F.text)
async def catch_bank_reminder_or_unknown(message: Message, state: FSMContext) -> None:
    text = message.text or ""
    if looks_like_bank_message(text):
        tx, tx_id, balances, balance_count, used_estimated_balance = await save_finance_text(user_id_from(message), text)
        if tx or balances:
            await message.answer(
                format_finance_saved(tx, tx_id, balances, balance_count, used_estimated_balance),
                reply_markup=main_keyboard(),
            )
            return

    reminder = parse_inline_reminder(text)
    if reminder:
        due_at, reminder_body = reminder
        if due_at <= datetime.now(timezone.utc):
            await message.answer("Eslatma vaqti o'tib ketgan. Masalan: ertaga 10:00 dori ichish", reply_markup=main_keyboard())
            return
        if reminder_body:
            repeat_rule = detect_repeat_rule(text)
            reminder_id = await add_reminder(user_id_from(message), message.chat.id, due_at, reminder_body, repeat_rule)
            repeat_text = f"\nTakrorlash: {hcode(REPEAT_LABELS[repeat_rule])}" if repeat_rule in REPEAT_LABELS else ""
            await message.answer(
                f"Eslatma avtomatik saqlandi: ID {hcode(str(reminder_id))}\n"
                f"Vaqt: {hcode(format_local(due_at))}\n"
                f"Xabar: {escape_html(reminder_body)}{repeat_text}",
                reply_markup=main_keyboard(),
            )
            return
        await state.update_data(due_at=utc_text(due_at), repeat_rule=detect_repeat_rule(text))
        await state.set_state(ReminderWizard.waiting_text)
        await message.answer(
            f"Vaqtni tushundim: {hcode(format_local(due_at))}\n"
            "Endi nimani eslatay? Xabar matnini yozing.",
            reply_markup=back_keyboard(),
        )
        return

    if looks_like_reminder_request(text):
        await state.set_state(ReminderWizard.waiting_datetime)
        await message.answer(
            "Eslatma qo'shamiz. Vaqtni aniqroq yozing.\n"
            "Masalan: ertaga 10:00 yoki 30 daqiqadan keyin.",
            reply_markup=back_keyboard(),
        )
        return

    await message.answer(
        "Bank xabari yoki eslatma yozsangiz, o'zim ajratib saqlashga harakat qilaman.\n\n"
        "Masalan: ertaga 10:00 qo'ng'iroq qilish yoki minus 45000 ovqat.",
        reply_markup=main_keyboard(),
    )


async def reminder_loop(bot: Bot) -> None:
    interval = int(os.getenv("REMINDER_CHECK_SECONDS", "10"))
    while True:
        try:
            for reminder_id, chat_id, text in await due_reminders():
                await bot.send_message(chat_id, f"{hbold('Eslatma')}\n\n{escape_html(text)}")
                await mark_reminder_sent(reminder_id)
        except Exception as exc:
            logging.exception("Reminder loop failed: %s", exc)
        await asyncio.sleep(max(interval, 3))


async def prayer_loop(bot: Bot) -> None:
    interval = int(os.getenv("PRAYER_CHECK_SECONDS", "30"))
    while True:
        try:
            now = now_local()
            for setting in await active_prayer_settings():
                city = setting["city"]
                times = calculate_prayer_times(city, now.date())
                prayer_keys = [key for key in setting["prayers"].split(",") if key in DEFAULT_PRAYER_KEYS]
                minutes_before = max(int(setting["minutes_before"]), 0)
                for key in prayer_keys:
                    prayer_time = times[key]
                    notify_at = prayer_time - timedelta(minutes=minutes_before)
                    delta = (now - notify_at).total_seconds()
                    if delta < 0 or delta > max(interval + 90, 120):
                        continue
                    if await was_prayer_sent(setting["user_id"], key, prayer_time.date()):
                        continue
                    title = PRAYER_NAMES[key]
                    prefix = f"{minutes_before} daqiqa keyin " if minutes_before else ""
                    await bot.send_message(
                        setting["chat_id"],
                        f"{hbold('Namoz eslatmasi')}\n\n"
                        f"{prefix}{escape_html(title)} vaqti: {hcode(format_time_only(prayer_time))}\n"
                        f"Shahar: {escape_html(city)}",
                    )
                    await mark_prayer_sent(setting["user_id"], key, prayer_time.date())
        except Exception as exc:
            logging.exception("Prayer loop failed: %s", exc)
        await asyncio.sleep(max(interval, 10))


async def daily_report_loop(bot: Bot) -> None:
    interval = int(os.getenv("DAILY_REPORT_CHECK_SECONDS", "300"))
    report_hour = int(os.getenv("DAILY_REPORT_HOUR", "21"))
    while True:
        try:
            now = now_local()
            if now.hour >= report_hour:
                report_date = now.date()
                for user_id, chat_id in await daily_report_users():
                    if await was_daily_report_sent(user_id, report_date):
                        continue
                    await bot.send_message(chat_id, await format_report(user_id, "today"))
                    await mark_daily_report_sent(user_id, report_date)
        except Exception as exc:
            logging.exception("Daily report loop failed: %s", exc)
        await asyncio.sleep(max(interval, 60))


async def main() -> None:
    await init_db()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(".env faylda BOT_TOKEN yozilmagan.")

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    miniapp_runner = await start_miniapp_server()
    await configure_miniapp_menu_button(bot)
    await configure_known_user_menu_buttons(bot)
    reminders_task = asyncio.create_task(reminder_loop(bot))
    prayer_task = asyncio.create_task(prayer_loop(bot))
    daily_report_task = asyncio.create_task(daily_report_loop(bot))
    try:
        await dp.start_polling(bot)
    finally:
        reminders_task.cancel()
        prayer_task.cancel()
        daily_report_task.cancel()
        await asyncio.gather(reminders_task, prayer_task, daily_report_task, return_exceptions=True)
        await miniapp_runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
