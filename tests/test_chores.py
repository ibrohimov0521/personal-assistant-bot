from datetime import date

import pytest

from chores import (
    cleaning_pair_for,
    format_sunday_cleaning_message,
    format_trash_message,
    normalize_telegram_username,
    trash_member_for,
)


def test_trash_rotation_starts_with_zafar() -> None:
    assert trash_member_for(date(2026, 5, 18)) == "Zafar"
    assert trash_member_for(date(2026, 5, 19)) == "Anvar"
    assert trash_member_for(date(2026, 5, 25)) == "Javohir"
    assert trash_member_for(date(2026, 5, 26)) == "Zafar"


def test_trash_message_contains_period_and_member() -> None:
    text = format_trash_message(date(2026, 5, 18), "evening")
    assert "Zafar" in text
    assert "kechki" in text
    assert "musorni olib chiqish" in text


def test_sunday_cleaning_pair_rotation() -> None:
    pairs = [
        ("Laziz", "Nuriddin"),
        ("Zafar", "Anvar"),
        ("Xushnud", "Domlo"),
        ("Javohir", "Shaxzod"),
    ]
    assert cleaning_pair_for(pairs, date(2026, 5, 24)) == ("Laziz", "Nuriddin")
    assert cleaning_pair_for(pairs, date(2026, 5, 31)) == ("Zafar", "Anvar")
    assert cleaning_pair_for(pairs, date(2026, 6, 7)) == ("Xushnud", "Domlo")
    assert cleaning_pair_for(pairs, date(2026, 6, 14)) == ("Javohir", "Shaxzod")
    assert cleaning_pair_for(pairs, date(2026, 6, 21)) == ("Laziz", "Nuriddin")


def test_sunday_cleaning_message_uses_current_pair() -> None:
    text = format_sunday_cleaning_message()
    assert "Laziz bilan Nuriddin" in text
    assert "kvartirani yig'ishtirish" in text


def test_normalize_telegram_username() -> None:
    assert normalize_telegram_username("zafar_aka") == "@zafar_aka"
    assert normalize_telegram_username("@anvar_aka") == "@anvar_aka"
    assert normalize_telegram_username("https://t.me/nuriddin_aka") == "@nuriddin_aka"
    with pytest.raises(ValueError):
        normalize_telegram_username("Ali")
