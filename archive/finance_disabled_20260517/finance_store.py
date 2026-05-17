from __future__ import annotations

import csv
import os
import re
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape
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


async def update_card_balance(
    user_id: int,
    card_last4: str,
    bank: str = "",
    owner: str = "",
    amount: int | None = None,
) -> bool:
    card_digits = re.sub(r"\D+", "", card_last4)[-4:]
    if not card_digits:
        return False
    fields = ["bank = ?", "owner = ?", "updated_at = ?"]
    params: list[object] = [bank.strip()[:80], owner.strip()[:120], utc_text()]
    if amount is not None:
        fields.insert(2, "amount = ?")
        params.insert(2, max(0, int(amount)))
    params.extend([user_id, card_digits])
    async with connect_db() as db:
        cursor = await db.execute(
            f"""
            UPDATE card_balances
            SET {", ".join(fields)}
            WHERE user_id = ? AND card_last4 = ?
            """,
            params,
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_card_balance(user_id: int, card_last4: str) -> bool:
    card_digits = re.sub(r"\D+", "", card_last4)[-4:]
    if not card_digits:
        return False
    async with connect_db() as db:
        cursor = await db.execute(
            "DELETE FROM card_balances WHERE user_id = ? AND card_last4 = ?",
            (user_id, card_digits),
        )
        await db.commit()
        return cursor.rowcount > 0


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


def _export_period_range(period: str) -> tuple[datetime | None, datetime | None, str]:
    now = datetime.now(LOCAL_TZ)
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc), "Bugun"
    if period == "week":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return start.astimezone(timezone.utc), (start + timedelta(days=7)).astimezone(timezone.utc), "Hafta"
    if period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        year = start.year + (1 if start.month == 12 else 0)
        month = 1 if start.month == 12 else start.month + 1
        end = start.replace(year=year, month=month)
        return start.astimezone(timezone.utc), end.astimezone(timezone.utc), "Oy"
    return None, None, "Barchasi"


def _xlsx_cell(value: object, row: int, column: int) -> str:
    col = ""
    number = column
    while number:
        number, rem = divmod(number - 1, 26)
        col = chr(65 + rem) + col
    ref = f"{col}{row}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}" s="1"><v>{value}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value if value is not None else ""))}</t></is></c>'


def _write_xlsx(path: Path, rows: list[list[object]]) -> None:
    sheet_rows = []
    for row_index, values in enumerate(rows, start=1):
        style = ' s="2"' if row_index == 1 else ""
        cells = "".join(_xlsx_cell(value, row_index, col_index) for col_index, value in enumerate(values, start=1))
        sheet_rows.append(f'<row r="{row_index}"{style}>{cells}</row>')
    sheet_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <cols>
    <col min="1" max="1" width="8"/>
    <col min="2" max="2" width="20"/>
    <col min="3" max="3" width="12"/>
    <col min="4" max="4" width="16"/>
    <col min="5" max="5" width="12"/>
    <col min="6" max="6" width="16"/>
    <col min="7" max="7" width="14"/>
    <col min="8" max="8" width="18"/>
    <col min="9" max="9" width="36"/>
  </cols>
  <sheetData>{''.join(sheet_rows)}</sheetData>
</worksheet>"""
    styles_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
  <fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/><xf numFmtId="3" fontId="0" fillId="0" borderId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0"/></cellXfs>
</styleSheet>"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>""")
        archive.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""")
        archive.writestr("xl/workbook.xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Operatsiyalar" sheetId="1" r:id="rId1"/></sheets>
</workbook>""")
        archive.writestr("xl/_rels/workbook.xml.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>""")
        archive.writestr("xl/styles.xml", styles_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)


async def export_transactions_xlsx_file(
    user_id: int,
    period: str = "all",
    tx_type: str = "all",
    target_dir: Path | None = None,
) -> tuple[Path, int]:
    start, end, period_label = _export_period_range(period)
    clean_type = tx_type if tx_type in {"income", "expense"} else None
    rows = await get_transactions(user_id, start, end, clean_type, limit=10000)
    folder = target_dir or (BASE_DIR / "exports")
    folder.mkdir(parents=True, exist_ok=True)
    suffix = datetime.now(LOCAL_TZ).strftime("%Y%m%d-%H%M%S")
    path = folder / f"transactions-{user_id}-{period or 'all'}-{tx_type or 'all'}-{suffix}.xlsx"
    table: list[list[object]] = [["ID", "Sana", "Turi", "Summa", "Valyuta", "Manba", "Karta", "Kategoriya", "Izoh"]]
    for row in rows:
        local_date = row["occurred_at"].astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
        table.append(
            [
                int(row["id"]),
                local_date,
                "Kirim" if row["type"] == "income" else "Chiqim",
                int(row["amount"]),
                row["currency"],
                row["source"],
                row["card_last4"],
                row["category"],
                row["description"],
            ]
        )
    table.append(["", "", "", "", "", "", "", "", ""])
    table.append(["Filtr", period_label, tx_type if tx_type in {"income", "expense"} else "Barchasi", "", "", "", "", "", ""])
    _write_xlsx(path, table)
    return path, len(rows)
