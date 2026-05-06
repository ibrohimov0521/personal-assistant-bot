from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


LOCAL_TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tashkent"))


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
