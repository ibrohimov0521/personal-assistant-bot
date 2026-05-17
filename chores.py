from __future__ import annotations

import re
from datetime import date


USERNAME_RE = re.compile(r"^@?[A-Za-z0-9_]{5,32}$")

TRASH_MEMBERS = [
    "Zafar",
    "Anvar",
    "Nuriddin",
    "Zikrillo",
    "Xushnud",
    "Laziz",
    "Shaxzod",
    "Javohir",
]

SUNDAY_CLEANING_PAIRS = [
    ("Laziz", "Nuriddin"),
    ("Zafar", "Anvar"),
    ("Xushnud", "Domlo"),
    ("Javohir", "Shaxzod"),
]

TRASH_START_DATE = date(2026, 5, 18)
CLEANING_START_DATE = date(2026, 5, 24)


def normalize_telegram_username(value: str) -> str:
    username = value.strip()
    if not username:
        raise ValueError("Telegram username kerak")
    if username.startswith("https://t.me/"):
        username = username.removeprefix("https://t.me/").strip("/")
    elif username.startswith("t.me/"):
        username = username.removeprefix("t.me/").strip("/")
    if not USERNAME_RE.fullmatch(username):
        raise ValueError("Username @username formatida bo'lishi kerak")
    return username if username.startswith("@") else f"@{username}"


def chore_member_for(members: list[str], day: date) -> str:
    names = [name.strip() for name in members if name.strip()]
    if not names:
        return "Navbatchi belgilanmagan"
    offset = (day - TRASH_START_DATE).days
    return names[offset % len(names)]


def trash_member_for(day: date) -> str:
    return chore_member_for(TRASH_MEMBERS, day)


def format_trash_message_for(member: str, period: str) -> str:
    period_text = "ertalabki" if period == "morning" else "kechki"
    return (
        "Musor navbati\n\n"
        f"{member}, {period_text} eslatma: bugun musorni olib chiqish sizning navbatingiz."
    )


def format_trash_message(day: date, period: str) -> str:
    return format_trash_message_for(trash_member_for(day), period)


def cleaning_pair_for(pairs: list[tuple[str, str]], day: date) -> tuple[str, str] | None:
    active_pairs = [(first.strip(), second.strip()) for first, second in pairs if first.strip() and second.strip()]
    if not active_pairs:
        return None
    weeks = max(0, (day - CLEANING_START_DATE).days // 7)
    return active_pairs[weeks % len(active_pairs)]


def format_cleaning_message_for_pair(pair: tuple[str, str] | None) -> str:
    if not pair:
        return "Yakshanba tozaligi\n\nJuftlik belgilanmagan."
    first, second = pair
    return (
        "Yakshanba tozaligi\n\n"
        f"{first} bilan {second}, bugun kvartirani yig'ishtirish navbati sizlarda."
    )


def format_cleaning_message_for_pairs(pairs: list[tuple[str, str]]) -> str:
    lines = ["Yakshanba tozaligi", ""]
    for first, second in pairs:
        lines.append(f"- {first} bilan {second}")
    lines.append("")
    lines.append("Bugun kvartirani yig'ishtirish navbati shu juftliklarda.")
    return "\n".join(lines)


def format_sunday_cleaning_message() -> str:
    return format_cleaning_message_for_pair(cleaning_pair_for(SUNDAY_CLEANING_PAIRS, CLEANING_START_DATE))
