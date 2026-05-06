from __future__ import annotations

import aiosqlite

from db import SQLITE_TIMEOUT_SECONDS, connect_db


async def init_db() -> None:
    async with connect_db() as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute(f"PRAGMA busy_timeout={SQLITE_TIMEOUT_SECONDS * 1000}")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                due_at TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                sent_at TEXT,
                repeat_rule TEXT NOT NULL DEFAULT ''
            )
            """
        )
        try:
            await db.execute("ALTER TABLE reminders ADD COLUMN repeat_rule TEXT NOT NULL DEFAULT ''")
        except aiosqlite.OperationalError:
            pass
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_reminders_due
            ON reminders(status, due_at)
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'UZS',
                source TEXT,
                card_last4 TEXT,
                description TEXT,
                category TEXT,
                balance_after INTEGER,
                raw_text TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_transactions_user_date
            ON transactions(user_id, occurred_at)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_transactions_dedupe
            ON transactions(user_id, occurred_at, type, amount, card_last4)
            """
        )
        await db.execute("UPDATE transactions SET raw_text = '' WHERE raw_text <> ''")
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS card_balances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                card_last4 TEXT NOT NULL,
                bank TEXT,
                owner TEXT,
                amount INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'UZS',
                raw_text TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, card_last4)
            )
            """
        )
        await db.execute(
            """
            DELETE FROM card_balances
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM card_balances
                GROUP BY user_id, card_last4
            )
            """
        )
        await db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_card_balances_user_last4
            ON card_balances(user_id, card_last4)
            """
        )
        await db.execute("UPDATE card_balances SET raw_text = '' WHERE raw_text <> ''")
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS prayer_settings (
                user_id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                city TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                prayers TEXT NOT NULL,
                minutes_before INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS prayer_sent (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                prayer_key TEXT NOT NULL,
                prayer_date TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                UNIQUE(user_id, prayer_key, prayer_date)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, key)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                chat_id INTEGER,
                first_name TEXT,
                last_name TEXT,
                username TEXT,
                language_code TEXT,
                is_bot INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                target_user_id INTEGER,
                details TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_audit_logs_created
            ON audit_logs(created_at DESC)
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_report_sent (
                user_id INTEGER NOT NULL,
                report_date TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY (user_id, report_date)
            )
            """
        )
        await db.commit()
