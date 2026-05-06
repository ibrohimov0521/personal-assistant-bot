from __future__ import annotations

import csv
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from db import connect_db, parse_utc, utc_text
from finance import (
    ParsedBalance,
    ParsedTransaction,
    detect_category,
    parse_balance_message,
    parse_bank_message,
)


BASE_DIR = Path(__file__).resolve().parent
LOCAL_TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tashkent"))


async def save_transaction(user_id: int, tx: ParsedTransaction) -> int:
    async with connect_db() as db:
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
    async with connect_db() as db:
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
    async with connect_db() as db:
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
    async with connect_db() as db:
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
    async with connect_db() as db:
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


async def get_transaction_by_id(user_id: int, transaction_id: int) -> dict | None:
    async with connect_db() as db:
        rows = await db.execute_fetchall(
            """
            SELECT id, occurred_at, type, amount, currency, source, card_last4, description, category, balance_after
            FROM transactions
            WHERE user_id = ? AND id = ?
            LIMIT 1
            """,
            (user_id, transaction_id),
        )
    if not rows:
        return None
    row = rows[0]
    return {
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


async def delete_transaction(user_id: int, transaction_id: int) -> bool:
    async with connect_db() as db:
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
    async with connect_db() as db:
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
    async with connect_db() as db:
        rows = await db.execute_fetchall(
            "SELECT value FROM user_settings WHERE user_id = ? AND key = ? LIMIT 1",
            (user_id, key),
        )
    return str(rows[0][0]) if rows else default


async def set_user_setting(user_id: int, key: str, value: str) -> None:
    async with connect_db() as db:
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


async def delete_user_setting(user_id: int, key: str) -> bool:
    async with connect_db() as db:
        cursor = await db.execute(
            "DELETE FROM user_settings WHERE user_id = ? AND key = ?",
            (user_id, key),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_user_settings_by_prefix(user_id: int, prefix: str) -> dict[str, str]:
    async with connect_db() as db:
        rows = await db.execute_fetchall(
            """
            SELECT key, value
            FROM user_settings
            WHERE user_id = ? AND key LIKE ?
            ORDER BY key ASC
            """,
            (user_id, f"{prefix}%"),
        )
    return {str(row[0]): str(row[1]) for row in rows}


def category_limit_key(category: str) -> str:
    cleaned = re.sub(r"\s+", " ", category.strip())[:60] or "Boshqa"
    return f"category_limit:{cleaned}"


async def set_category_limit(user_id: int, category: str, amount: int) -> None:
    key = category_limit_key(category)
    await set_user_setting(user_id, key, str(max(amount, 0)))


async def get_category_limits(user_id: int) -> dict[str, int]:
    rows = await get_user_settings_by_prefix(user_id, "category_limit:")
    result: dict[str, int] = {}
    for key, value in rows.items():
        category = key.split(":", 1)[1].strip()
        try:
            amount = int(value)
        except ValueError:
            amount = 0
        if category and amount > 0:
            result[category] = amount
    return result


async def clear_user_data(user_id: int, scope: str) -> None:
    if scope not in {"finance", "reminders", "all"}:
        raise ValueError("Unknown clear scope")
    async with connect_db() as db:
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


async def create_manual_transaction(
    user_id: int,
    tx_type: str,
    amount: int,
    category: str,
    description: str,
    card_last4: str = "",
    occurred_at: datetime | None = None,
) -> int:
    card_digits = re.sub(r"\D+", "", card_last4)[-4:]
    tx = ParsedTransaction(
        type=tx_type,
        amount=amount,
        currency="UZS",
        occurred_at_utc=occurred_at or datetime.now(timezone.utc),
        source="MANUAL",
        card_last4=card_digits,
        description=description.strip()[:120] or ("Kirim" if tx_type == "income" else "Xarajat"),
        category=category.strip()[:60] or "Boshqa",
        balance_after=None,
        raw_text="",
    )
    tx_id = await save_transaction(user_id, tx)
    estimated = await estimated_balance_from_transaction(user_id, tx)
    if estimated:
        await save_balances(user_id, [estimated])
    return tx_id


async def export_transactions_csv_file(user_id: int, target_dir: Path | None = None) -> Path:
    rows = await get_transactions(user_id, limit=10000)
    folder = target_dir or (BASE_DIR / "exports")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"transactions-{user_id}-{datetime.now(LOCAL_TZ).strftime('%Y%m%d-%H%M%S')}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["id", "date", "type", "amount", "currency", "source", "card_last4", "category", "description"])
        for row in rows:
            writer.writerow(
                [
                    row["id"],
                    row["occurred_at"].astimezone(LOCAL_TZ).isoformat(),
                    row["type"],
                    row["amount"],
                    row["currency"],
                    row["source"],
                    row["card_last4"],
                    row["category"],
                    row["description"],
                ]
            )
    return path
