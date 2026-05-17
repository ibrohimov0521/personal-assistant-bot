from __future__ import annotations

import aiosqlite

from chores import SUNDAY_CLEANING_PAIRS, TRASH_MEMBERS
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
                photo_url TEXT NOT NULL DEFAULT '',
                phone_number TEXT NOT NULL DEFAULT '',
                is_bot INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        for column_sql in (
            "ALTER TABLE user_profiles ADD COLUMN photo_url TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE user_profiles ADD COLUMN phone_number TEXT NOT NULL DEFAULT ''",
        ):
            try:
                await db.execute(column_sql)
            except Exception:
                pass
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
            CREATE TABLE IF NOT EXISTS group_chore_settings (
                chat_id INTEGER PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS group_chore_sent (
                chat_id INTEGER NOT NULL,
                chore_key TEXT NOT NULL,
                sent_date TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY (chat_id, chore_key, sent_date)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS group_chore_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                position INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS group_chore_pairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT NOT NULL,
                second_name TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        rows = await db.execute_fetchall("SELECT COUNT(*) FROM group_chore_members")
        if not rows or int(rows[0][0]) == 0:
            await db.executemany(
                """
                INSERT INTO group_chore_members (name, position, created_at)
                VALUES (?, ?, datetime('now'))
                """,
                [(name, index) for index, name in enumerate(TRASH_MEMBERS)],
            )
        rows = await db.execute_fetchall("SELECT COUNT(*) FROM group_chore_pairs")
        if not rows or int(rows[0][0]) == 0:
            await db.executemany(
                """
                INSERT INTO group_chore_pairs (first_name, second_name, position, created_at)
                VALUES (?, ?, ?, datetime('now'))
                """,
                [(first, second, index) for index, (first, second) in enumerate(SUNDAY_CLEANING_PAIRS)],
            )
        await db.commit()
