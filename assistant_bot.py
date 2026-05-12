import asyncio
import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

import aiohttp
from aiohttp import web
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    MenuButtonWebApp,
    Message,
    ReplyKeyboardMarkup,
    TelegramObject,
    WebAppInfo,
)
from aiogram.utils.markdown import hbold, hcode
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

from access_control import (
    admin_user_ids,
    allowed_user_ids,
    blocked_user_ids,
    is_admin_user,
    permitted_user_ids,
)
from ai_assistant import ask_openai, friendly_ai_error, openai_configured, openai_model, ping_openai
from db import DB_PATH, connect_db, parse_utc, utc_text
from db_schema import init_db
from finance import (
    ParsedBalance,
    ParsedTransaction,
    clean_amount,
    detect_category,
    looks_like_bank_message,
    parse_bank_message,
)
from finance_store import (
    delete_transaction,
    export_transactions_csv_file,
    get_card_balances,
    get_category_limits,
    get_transaction_by_id,
    get_transactions,
    get_user_setting,
    save_finance_text,
    save_transaction,
    set_category_limit,
    update_transaction,
)
from fsm_sqlite_storage import SQLiteFSMStorage
from handlers.admin import AdminHandlerDeps, register_admin_handlers
from miniapp_api import MiniAppApi, MiniAppContext, miniapp_error_middleware
from prayer_times import (
    DEFAULT_PRAYER_KEYS,
    PRAYER_CITIES,
    PRAYER_NAMES,
    calculate_prayer_times,
    format_time_only,
    normalize_prayer_city,
)
from prayer_store import (
    active_prayer_settings,
    get_prayer_setting,
    mark_prayer_sent,
    save_prayer_setting,
    was_prayer_sent,
)
from reminders import (
    detect_repeat_rule,
    looks_like_reminder_request,
    parse_inline_reminder,
    parse_reminder_datetime,
)
from reminder_store import (
    add_reminder,
    delete_reminder,
    due_reminders,
    list_completed_reminder_records,
    list_pending_reminder_records,
    list_reminders,
    mark_reminder_sent,
)
from user_store import (
    add_audit_log,
    admin_user_rows,
    get_user_profile,
    list_audit_logs,
    save_user_profile_from_message,
    save_user_profile_from_webapp_user,
)


MINIAPP_DIR = BASE_DIR / "miniapp"
BACKUP_DIR = BASE_DIR / "backups"
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

REPEAT_LABELS = {
    "daily": "Har kuni",
    "weekly": "Har hafta",
    "monthly": "Har oy",
}

AI_COOLDOWNS: dict[int, datetime] = {}


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


def miniapp_inline_keyboard() -> InlineKeyboardMarkup | None:
    url = mini_app_url()
    if not url.startswith("https://"):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Mini Appni ochish", web_app=WebAppInfo(url=url))]
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


@router.message(
    lambda message: message.from_user is not None
    and message.from_user.id in blocked_user_ids()
    and not is_admin_user(message.from_user.id)
)
async def reject_blocked(message: Message) -> None:
    await message.answer("Bu botdan foydalanishingiz bloklangan.")


@router.message(
    lambda message: bool(permitted_user_ids())
    and message.from_user is not None
    and message.from_user.id not in permitted_user_ids()
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



class UserProfileMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            try:
                await save_user_profile_from_message(event)
            except Exception as exc:
                logging.warning("User profile saqlanmadi: %s", exc)
        return await handler(event, data)


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


def finance_warning_text(category_expenses: dict[str, int], category_limits: dict[str, int]) -> list[str]:
    warnings: list[str] = []
    lower_totals = {category.lower(): (category, amount) for category, amount in category_expenses.items()}
    for limit_category, limit in category_limits.items():
        row = lower_totals.get(limit_category.lower())
        if not row:
            continue
        category, amount = row
        if amount >= limit:
            warnings.append(f"{category}: limit oshdi ({format_money(amount)} / {format_money(limit)})")
        elif amount >= limit * 0.8:
            warnings.append(f"{category}: limitga yaqin ({format_money(amount)} / {format_money(limit)})")
    return warnings


async def build_finance_warnings(user_id: int, category_expenses: dict[str, int]) -> list[dict[str, str]]:
    category_limits = await get_category_limits(user_id)
    warnings: list[dict[str, str]] = []
    for text in finance_warning_text(category_expenses, category_limits):
        icon = "triangle-alert" if "oshdi" in text else "bell-ring"
        title = "Kategoriya limiti"
        warnings.append({"icon": icon, "title": title, "text": text})
    return warnings


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
        warnings = finance_warning_text(category_expenses, await get_category_limits(user_id))
        if warnings:
            lines.extend(["", hbold("Limit signallari")])
            for warning in warnings:
                lines.append(f"- {escape_html(warning)}")

    balances = await get_card_balances(user_id)
    if balances:
        lines.extend(["", hbold("Oxirgi balanslar")])
        for row in balances:
            label = balance_label(row)
            lines.append(f"- {escape_html(label)}: {hcode(format_money(row['amount']))}")
    return "\n".join(lines)


async def daily_report_users() -> list[tuple[int, int]]:
    async with connect_db() as db:
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
    async with connect_db() as db:
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
    async with connect_db() as db:
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


async def delete_last_transaction(user_id: int) -> dict | None:
    rows = await get_transactions(user_id, limit=1)
    if not rows:
        return None
    row = rows[0]
    ok = await delete_transaction(user_id, int(row["id"]))
    return row if ok else None


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
    user_profile = await get_user_profile(user_id)
    is_admin = is_admin_user(user_id)
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
    category_limits = await get_category_limits(user_id)
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
    finance_warnings = await build_finance_warnings(user_id, category_totals)

    return {
        "generated_at": json_dt(now),
        "is_admin": is_admin,
        "current_user": {
            "user_id": user_id,
            "name": (user_profile or {}).get("first_name", "") if user_profile else "",
            "last_name": (user_profile or {}).get("last_name", "") if user_profile else "",
            "username": (user_profile or {}).get("username", "") if user_profile else "",
            "chat_id": (user_profile or {}).get("chat_id") if user_profile else None,
            "language_code": (user_profile or {}).get("language_code", "") if user_profile else "",
        },
        "admin": {
            "users": await admin_user_rows() if is_admin else [],
            "audit_logs": await list_audit_logs(20) if is_admin else [],
            "allowed_count": len(allowed_user_ids()),
            "blocked_count": len(blocked_user_ids()),
        },
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
        "finance_warnings": finance_warnings,
        "category_limits": [
            {"category": category, "amount": amount, "amount_text": json_money(amount)}
            for category, amount in sorted(category_limits.items())
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


async def start_miniapp_server() -> web.AppRunner:
    app = web.Application(middlewares=[miniapp_error_middleware])
    api = MiniAppApi(
        MiniAppContext(
            miniapp_dir=MINIAPP_DIR,
            dashboard_payload=dashboard_payload,
            save_user_profile_from_webapp_user=save_user_profile_from_webapp_user,
            admin_user_rows=admin_user_rows,
            list_audit_logs=list_audit_logs,
            add_audit_log=add_audit_log,
            delete_reminder=delete_reminder,
            get_prayer_setting=get_prayer_setting,
            save_prayer_setting=save_prayer_setting,
        )
    )
    api.register_routes(app)
    runner = web.AppRunner(app)
    await runner.setup()
    host = os.getenv("MINIAPP_HOST", "127.0.0.1")
    port = int(os.getenv("MINIAPP_PORT", "8080"))
    site = web.TCPSite(runner, host, port)
    await site.start()
    logging.info("Mini App server started at http://%s:%s", host, port)
    return runner

async def create_db_backup(reason: str = "manual") -> Path:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"DB topilmadi: {DB_PATH}")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    safe_reason = re.sub(r"[^a-zA-Z0-9_-]+", "-", reason).strip("-") or "backup"
    backup_path = BACKUP_DIR / f"assistant-{now_local().strftime('%Y%m%d-%H%M%S')}-{safe_reason}.db"
    async with connect_db() as source:
        async with connect_db(backup_path) as target:
            await source.backup(target)
    keep_last = int(os.getenv("BACKUP_KEEP_LAST", "14"))
    backups = sorted(BACKUP_DIR.glob("assistant-*.db"), key=lambda item: item.stat().st_mtime, reverse=True)
    for old_backup in backups[keep_last:]:
        try:
            old_backup.unlink()
        except OSError as exc:
            logging.warning("Eski backup o'chmadi (%s): %s", old_backup, exc)
    return backup_path


async def count_db_rows(query: str, params: tuple = ()) -> int:
    async with connect_db() as db:
        rows = await db.execute_fetchall(query, params)
    return int(rows[0][0]) if rows else 0


async def bot_stats_text() -> str:
    user_count = await count_db_rows(
        """
        SELECT COUNT(DISTINCT user_id)
        FROM (
            SELECT user_id FROM transactions
            UNION SELECT user_id FROM card_balances
            UNION SELECT user_id FROM prayer_settings
            UNION SELECT user_id FROM reminders
        )
        """
    )
    tx_count = await count_db_rows("SELECT COUNT(*) FROM transactions")
    card_count = await count_db_rows("SELECT COUNT(*) FROM card_balances")
    prayer_enabled = await count_db_rows("SELECT COUNT(*) FROM prayer_settings WHERE enabled = 1")
    backup_count = len(list(BACKUP_DIR.glob("assistant-*.db"))) if BACKUP_DIR.exists() else 0
    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    return (
        f"Foydalanuvchilar: {hcode(str(user_count))}\n"
        f"Operatsiyalar: {hcode(str(tx_count))}\n"
        f"Kartalar: {hcode(str(card_count))}\n"
        f"Namoz eslatmasi yoqilgan: {hcode(str(prayer_enabled))}\n"
        f"Backup soni: {hcode(str(backup_count))}\n"
        f"DB hajmi: {hcode(str(round(db_size / 1024, 1)) + ' KB')}"
    )


async def service_status(name: str) -> str:
    if os.name == "nt":
        return "local"
    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "is-active",
            name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
        return stdout.decode("utf-8", errors="ignore").strip() or "unknown"
    except (FileNotFoundError, asyncio.TimeoutError, OSError):
        return "unknown"


async def collect_health() -> dict[str, str]:
    status: dict[str, str] = {}
    for service in ["assistant-bot", "assistant-forwarder", "cloudflared"]:
        status[service] = await service_status(service)
    try:
        async with connect_db() as db:
            rows = await db.execute_fetchall("PRAGMA quick_check")
        status["database"] = "ok" if rows and rows[0][0] == "ok" else "warning"
    except Exception:
        status["database"] = "error"
    port = int(os.getenv("MINIAPP_PORT", "8080"))
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(f"http://127.0.0.1:{port}/") as response:
                status["miniapp"] = "ok" if response.status < 500 else f"http_{response.status}"
    except Exception:
        status["miniapp"] = "error"
    return status


def health_text(status: dict[str, str]) -> str:
    def label(value: str) -> str:
        return "OK" if value in {"active", "ok", "local"} else "XATO"

    lines = [hbold("Bot holati"), ""]
    for key, value in status.items():
        lines.append(f"{key}: {hcode(label(value))} ({escape_html(value)})")
    return "\n".join(lines)


async def notify_admins(bot: Bot, text: str) -> None:
    for chat_id in admin_user_ids():
        try:
            await bot.send_message(chat_id, text)
        except Exception as exc:
            logging.warning("Adminga xabar yuborilmadi (%s): %s", chat_id, exc)


async def backup_loop(bot: Bot) -> None:
    interval = int(os.getenv("BACKUP_CHECK_SECONDS", "900"))
    backup_hour = int(os.getenv("BACKUP_HOUR", "3"))
    marker = BACKUP_DIR / ".last_backup_date"
    while True:
        try:
            now = now_local()
            last_date = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
            if now.hour >= backup_hour and last_date != now.date().isoformat():
                backup_path = await create_db_backup("auto")
                marker.write_text(now.date().isoformat(), encoding="utf-8")
                await notify_admins(bot, f"{hbold('Backup tayyor')}\n\n{hcode(backup_path.name)}")
        except Exception as exc:
            logging.exception("Backup loop failed: %s", exc)
            await notify_admins(bot, f"{hbold('Backup xatosi')}\n\n{escape_html(exc)}")
        await asyncio.sleep(max(interval, 300))


async def health_monitor_loop(bot: Bot) -> None:
    interval = int(os.getenv("HEALTH_CHECK_SECONDS", "300"))
    last_issue_text = ""
    while True:
        try:
            status = await collect_health()
            issues = {key: value for key, value in status.items() if value not in {"active", "ok", "local"}}
            issue_text = json.dumps(issues, sort_keys=True)
            if issues and issue_text != last_issue_text:
                await notify_admins(bot, health_text(status))
            last_issue_text = issue_text
        except Exception as exc:
            logging.exception("Health monitor failed: %s", exc)
        await asyncio.sleep(max(interval, 120))


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


def command_arg_text(command: CommandObject | None) -> str:
    return (command.args or "").strip() if command else ""


def format_transaction_line(row: dict) -> str:
    sign = "+" if row["type"] == "income" else "-"
    card = f" *{row['card_last4']}" if row.get("card_last4") else ""
    return (
        f"ID {hcode(str(row['id']))}: {sign}{hcode(format_money(row['amount']))} | "
        f"{escape_html(row['category'])} | {escape_html(row.get('description') or '')}{escape_html(card)}"
    )


async def require_admin(message: Message) -> bool:
    user_id = user_id_from(message)
    if is_admin_user(user_id):
        return True
    await message.answer(
        "Bu buyruq faqat admin uchun.\n\n"
        f"Sizning Telegram ID: {hcode(str(user_id))}",
        reply_markup=main_keyboard(),
    )
    return False


async def format_category_limits(user_id: int) -> str:
    limits = await get_category_limits(user_id)
    if not limits:
        return (
            f"{hbold('Kategoriya limitlari')}\n\n"
            "Hali limit belgilanmagan.\n"
            f"Masalan: {hcode('/limit Ovqat 1000000')}"
        )
    lines = [hbold("Kategoriya limitlari"), ""]
    for category, amount in sorted(limits.items()):
        lines.append(f"- {escape_html(category)}: {hcode(format_money(amount))}")
    return "\n".join(lines)


async def build_ai_context(user_id: int, chat_id: int) -> str:
    balances = await get_card_balances(user_id)
    today_start, today_end, _ = period_range("today")
    month_start, month_end, _ = period_range("month")
    today_rows = await get_transactions(user_id, today_start, today_end)
    month_rows = await get_transactions(user_id, month_start, month_end)
    reminders = await list_pending_reminder_records(user_id, limit=5)
    prayer_setting = await get_prayer_setting(user_id, chat_id)

    def totals(rows: list[dict]) -> tuple[int, int]:
        income = sum(int(row["amount"]) for row in rows if row["type"] == "income")
        expense = sum(int(row["amount"]) for row in rows if row["type"] == "expense")
        return income, expense

    today_income, today_expense = totals(today_rows)
    month_income, month_expense = totals(month_rows)
    lines = [
        f"Bugun kirim: {format_money(today_income)}",
        f"Bugun chiqim: {format_money(today_expense)}",
        f"Oylik kirim: {format_money(month_income)}",
        f"Oylik chiqim: {format_money(month_expense)}",
        f"Karta jami balansi: {format_money(sum(int(row['amount']) for row in balances)) if balances else 'mavjud emas'}",
        f"Namoz shahri: {prayer_setting['city']}",
    ]
    if reminders:
        reminder_text = "; ".join(f"{format_local(parse_utc(row['due_at']))} - {row['message'][:60]}" for row in reminders[:3])
        lines.append(f"Yaqin eslatmalar: {reminder_text}")
    else:
        lines.append("Yaqin eslatmalar: yo'q")
    return "\n".join(lines)


def ai_cooldown_left(user_id: int) -> int:
    last = AI_COOLDOWNS.get(user_id)
    if not last:
        return 0
    seconds = int(os.getenv("OPENAI_USER_COOLDOWN_SECONDS", "20"))
    left = seconds - int((now_local() - last).total_seconds())
    return max(left, 0)


def mark_ai_used(user_id: int) -> None:
    AI_COOLDOWNS[user_id] = now_local()


async def send_long_answer(message: Message, text: str) -> None:
    chunks = [text[i : i + 3500] for i in range(0, len(text), 3500)] or [text]
    for chunk in chunks:
        await message.answer(escape_html(chunk), reply_markup=main_keyboard())


register_admin_handlers(
    router,
    AdminHandlerDeps(
        main_keyboard=main_keyboard,
        require_admin=require_admin,
        user_id_from=user_id_from,
        command_arg_text=command_arg_text,
        escape_html=escape_html,
        collect_health=collect_health,
        health_text=health_text,
        bot_stats_text=bot_stats_text,
        create_db_backup=create_db_backup,
    ),
)


@router.message(Command("exportcsv"))
async def finance_export_csv(message: Message) -> None:
    path = await export_transactions_csv_file(user_id_from(message))
    await message.answer_document(
        FSInputFile(path),
        caption="Moliya CSV export tayyor.",
        reply_markup=main_keyboard(),
    )


@router.message(Command("undo"))
async def finance_undo_last(message: Message) -> None:
    row = await delete_last_transaction(user_id_from(message))
    if not row:
        await message.answer("O'chirish uchun operatsiya topilmadi.", reply_markup=main_keyboard())
        return
    await message.answer(
        hbold("Oxirgi operatsiya o'chirildi") + "\n\n"
        f"{format_transaction_line(row)}\n\n"
        "Eslatma: karta balansi alohida saqlanadi. Bank aniq balans yuborsa, balans avtomatik yangilanadi.",
        reply_markup=main_keyboard(),
    )


@router.message(Command("setcat"))
async def finance_set_category(message: Message, command: CommandObject) -> None:
    raw = command_arg_text(command)
    match = re.match(r"(\d+)\s+(.+)", raw)
    if not match:
        await message.answer(f"Namuna: {hcode('/setcat 15 Ovqat')}", reply_markup=main_keyboard())
        return
    tx_id = int(match.group(1))
    category = match.group(2).strip()[:60] or "Boshqa"
    row = await get_transaction_by_id(user_id_from(message), tx_id)
    if not row:
        await message.answer("Bu ID bo'yicha operatsiya topilmadi.", reply_markup=main_keyboard())
        return
    ok = await update_transaction(
        user_id_from(message),
        tx_id,
        row["type"],
        int(row["amount"]),
        category,
        row.get("description") or category,
        row["occurred_at"],
    )
    await message.answer(
        f"Kategoriya yangilandi: {hcode(category)}" if ok else "Kategoriya yangilanmadi.",
        reply_markup=main_keyboard(),
    )


@router.message(Command("limit"))
async def finance_category_limit(message: Message, command: CommandObject) -> None:
    raw = command_arg_text(command)
    match = re.match(r"(.+?)\s+([0-9][0-9\s'.,]*)$", raw)
    if not match:
        await message.answer(f"Namuna: {hcode('/limit Ovqat 1000000')}", reply_markup=main_keyboard())
        return
    category = match.group(1).strip()[:60] or "Boshqa"
    amount = clean_amount(match.group(2))
    await set_category_limit(user_id_from(message), category, amount)
    if amount <= 0:
        await message.answer("Limit 0 bo'lsa, signal berilmaydi.", reply_markup=main_keyboard())
        return
    await message.answer(
        f"Limit saqlandi: {escape_html(category)} - {hcode(format_money(amount))}",
        reply_markup=main_keyboard(),
    )


@router.message(Command("limits"))
async def finance_limits(message: Message) -> None:
    await message.answer(await format_category_limits(user_id_from(message)), reply_markup=main_keyboard())


@router.message(Command("ai_status"))
async def ai_status(message: Message) -> None:
    if not openai_configured():
        await message.answer(
            "OpenAI API ulanmagan. Server .env faylida OPENAI_API_KEY yozilishi kerak.",
            reply_markup=main_keyboard(),
        )
        return
    status = await message.answer(f"OpenAI tekshirilyapti...\nModel: {hcode(openai_model())}")
    try:
        answer = await ping_openai()
        await status.edit_text(f"OpenAI ishlayapti.\nModel: {hcode(openai_model())}\nJavob: {escape_html(answer)}")
    except Exception as exc:
        await status.edit_text(f"OpenAI ishlamadi.\n\n{escape_html(friendly_ai_error(exc))}")


@router.message(Command("ai"))
async def ai_answer(message: Message, command: CommandObject) -> None:
    question = command_arg_text(command)
    if not question:
        await message.answer(
            f"AI yordamchi uchun savolni shu ko'rinishda yozing:\n{hcode('/ai bugungi xarajatlarimni tahlil qil')}",
            reply_markup=main_keyboard(),
        )
        return
    if len(question) > 1200:
        await message.answer("Savol juda uzun. 1200 belgidan qisqaroq yozing.", reply_markup=main_keyboard())
        return
    user_id = user_id_from(message)
    left = ai_cooldown_left(user_id)
    if left:
        await message.answer(f"AI limit: {left} soniyadan keyin qayta urinib ko'ring.", reply_markup=main_keyboard())
        return
    mark_ai_used(user_id)
    status = await message.answer("AI javob tayyorlayapti...")
    try:
        context = await build_ai_context(user_id, message.chat.id)
        answer = await ask_openai(question, context)
    except Exception as exc:
        await status.edit_text(escape_html(friendly_ai_error(exc)))
        return
    try:
        await status.delete()
    except Exception:
        await status.edit_text("AI javob tayyor.")
    await send_long_answer(message, answer)


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


async def answer_quick_question(message: Message, text: str) -> bool:
    raw = text.strip().lower()
    if not raw:
        return False
    user_id = user_id_from(message)
    finance_words = ["hisobot", "xarajat", "chiqim", "kirim", "moliya", "sarfl", "operatsiya", "yozuv"]

    if any(word in raw for word in ["balans", "kartalar", "kartam"]) or (
        "pul" in raw and any(word in raw for word in ["qancha", "qoldi", "qoldiq"])
    ):
        await message.answer(await format_card_balances(user_id), reply_markup=main_keyboard())
        return True

    if "bugun" in raw and any(word in raw for word in finance_words):
        await message.answer(await format_report(user_id, "today"), reply_markup=main_keyboard())
        return True

    if any(word in raw for word in ["hafta", "haftalik"]) and any(word in raw for word in finance_words):
        await message.answer(await format_report(user_id, "week"), reply_markup=main_keyboard())
        return True

    if any(word in raw for word in ["oy", "oylik", "may", "aprel"]) and any(word in raw for word in finance_words):
        await message.answer(await format_report(user_id, "month"), reply_markup=main_keyboard())
        return True

    if any(word in raw for word in ["oxirgi", "so'nggi", "songgi"]) and any(word in raw for word in ["operatsiya", "yozuv", "tranzaksiya"]):
        await message.answer(await format_last_transactions(user_id), reply_markup=main_keyboard())
        return True

    if "limit" in raw and any(word in raw for word in ["ko'r", "kor", "qanaqa", "qancha", "ro'yxat", "royxat"]):
        await message.answer(await format_category_limits(user_id), reply_markup=main_keyboard())
        return True

    if any(word in raw for word in ["namoz", "bomdod", "peshin", "asr", "shom", "xufton"]):
        setting = await get_prayer_setting(user_id, message.chat.id)
        await message.answer(format_prayer_times(setting["city"]), reply_markup=main_keyboard())
        return True

    if raw in {"salom", "assalomu alaykum", "assalom alaykum", "hello", "hi"}:
        await message.answer(
            "Assalomu alaykum. Bank xabari, eslatma yoki moliya savolini yozing. Mini App uchun /app.",
            reply_markup=main_keyboard(),
        )
        return True

    return False


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

    if await answer_quick_question(message, text):
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
    dp = Dispatcher(storage=SQLiteFSMStorage())
    router.message.outer_middleware(UserProfileMiddleware())
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    miniapp_runner = await start_miniapp_server()
    await configure_miniapp_menu_button(bot)
    await configure_known_user_menu_buttons(bot)
    reminders_task = asyncio.create_task(reminder_loop(bot))
    prayer_task = asyncio.create_task(prayer_loop(bot))
    daily_report_task = asyncio.create_task(daily_report_loop(bot))
    backup_task = asyncio.create_task(backup_loop(bot))
    health_task = asyncio.create_task(health_monitor_loop(bot))
    try:
        await dp.start_polling(bot)
    finally:
        reminders_task.cancel()
        prayer_task.cancel()
        daily_report_task.cancel()
        backup_task.cancel()
        health_task.cancel()
        await asyncio.gather(
            reminders_task,
            prayer_task,
            daily_report_task,
            backup_task,
            health_task,
            return_exceptions=True,
        )
        await miniapp_runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
