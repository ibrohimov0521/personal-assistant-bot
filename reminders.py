from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


LOCAL_TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tashkent"))


def now_local() -> datetime:
    return datetime.now(LOCAL_TZ)

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

