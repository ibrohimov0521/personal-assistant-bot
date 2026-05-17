from __future__ import annotations

from dataclasses import dataclass


FINANCE_DISABLED_MESSAGE = "Moliya bo'limi arxivlangan va botdan olib tashlangan."


@dataclass
class ParsedTransaction:
    type: str = "expense"
    amount: int = 0
    category: str = "Boshqa"
    source: str = "DISABLED"
    card_last4: str = ""
    description: str = ""
    balance_after: int | None = None


@dataclass
class ParsedBalance:
    source: str = "DISABLED"
    card_last4: str = ""
    amount: int = 0
    bank: str = ""
    owner: str = ""


def clean_amount(value: str) -> int:
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits or "0")


def detect_category(_: str) -> str:
    return "Boshqa"


def looks_like_bank_message(_: str) -> bool:
    return False


def parse_bank_message(*_: object, **__: object) -> ParsedTransaction | None:
    return None
