from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from db import connect_db


FINANCE_DISABLED_MESSAGE = "Moliya bo'limi arxivlangan va botdan olib tashlangan."


def category_limit_key(category: str) -> str:
    return "category_limit:" + category.strip().lower()


async def get_transactions(*_: Any, **__: Any) -> list[dict]:
    return []


async def get_card_balances(*_: Any, **__: Any) -> list[dict]:
    return []


async def get_category_limits(*_: Any, **__: Any) -> dict[str, int]:
    return {}


async def get_user_setting(_: int, __: str, default: str = "") -> str:
    return default


async def set_user_setting(*_: Any, **__: Any) -> None:
    return None


async def delete_user_setting(*_: Any, **__: Any) -> None:
    return None


async def set_category_limit(*_: Any, **__: Any) -> None:
    return None


async def clear_user_data(*_: Any, **__: Any) -> None:
    user_id = int(_[0]) if _ else 0
    scope = str(_[1]) if len(_) > 1 else ""
    if scope == "finance":
        raise ValueError(FINANCE_DISABLED_MESSAGE)
    if scope not in {"reminders", "all"}:
        raise ValueError("Unknown clear scope")
    async with connect_db() as db:
        await db.execute("DELETE FROM reminders WHERE user_id = ?", (user_id,))
        await db.commit()


async def delete_transaction(*_: Any, **__: Any) -> bool:
    return False


async def get_transaction_by_id(*_: Any, **__: Any) -> dict | None:
    return None


async def update_transaction(*_: Any, **__: Any) -> bool:
    return False


async def create_manual_transaction(*_: Any, **__: Any) -> int:
    raise RuntimeError(FINANCE_DISABLED_MESSAGE)


async def update_card_balance(*_: Any, **__: Any) -> bool:
    return False


async def delete_card_balance(*_: Any, **__: Any) -> bool:
    return False


async def save_finance_text(*_: Any, **__: Any) -> tuple[None, None, list, int, bool]:
    return None, None, [], 0, False


async def save_transaction(*_: Any, **__: Any) -> int:
    raise RuntimeError(FINANCE_DISABLED_MESSAGE)


async def export_transactions_csv_file(*_: Any, **__: Any) -> Path:
    raise RuntimeError(FINANCE_DISABLED_MESSAGE)


async def export_transactions_xlsx_file(*_: Any, **__: Any) -> tuple[Path, int]:
    raise RuntimeError(FINANCE_DISABLED_MESSAGE)
