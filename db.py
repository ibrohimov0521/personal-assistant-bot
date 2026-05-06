from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import aiosqlite


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "assistant.db"
SQLITE_TIMEOUT_SECONDS = 30


def connect_db(path: Path = DB_PATH) -> aiosqlite.Connection:
    return aiosqlite.connect(path, timeout=SQLITE_TIMEOUT_SECONDS)


def utc_text(dt: datetime | None = None) -> str:
    value = dt or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def parse_utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(timezone.utc)
