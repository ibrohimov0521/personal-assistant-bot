from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import FSInputFile, Message, ReplyKeyboardMarkup
from aiogram.utils.markdown import hbold, hcode

from access_control import (
    ALLOWED_USERS_FILE,
    admin_user_ids,
    allowed_user_ids,
    block_user,
    blocked_user_ids,
    grant_user_access,
    remove_allowed_user,
)
from user_store import add_audit_log, list_audit_logs


@dataclass(frozen=True)
class AdminHandlerDeps:
    main_keyboard: Callable[[], ReplyKeyboardMarkup]
    require_admin: Callable[[Message], Awaitable[bool]]
    user_id_from: Callable[[Message], int]
    command_arg_text: Callable[[CommandObject | None], str]
    escape_html: Callable[[object], str]
    collect_health: Callable[[], Awaitable[dict[str, str]]]
    health_text: Callable[[dict[str, str]], str]
    bot_stats_text: Callable[[], Awaitable[str]]
    create_db_backup: Callable[[str], Awaitable[Path]]


def register_admin_handlers(router: Router, deps: AdminHandlerDeps) -> None:
    @router.message(Command("admin"))
    async def admin_panel(message: Message) -> None:
        if not await deps.require_admin(message):
            return
        await message.answer(
            f"{hbold('Admin panel')}\n\n"
            f"{hcode('/health')} - bot, server va DB holati\n"
            f"{hcode('/stats')} - umumiy statistika\n"
            f"{hcode('/backup')} - DB backup yaratish\n"
            f"{hcode('/users')} - ruxsat berilgan userlar\n"
            f"{hcode('/audit')} - admin harakatlari tarixi\n"
            f"{hcode('/allow 123456789')} - userga ruxsat berish\n"
            f"{hcode('/deny 123456789')} - userni bloklash\n\n"
            f"{hbold('Guruh navbatchiligi')}\n"
            f"{hcode('/chore_setup')} - guruhda yoqish\n"
            f"{hcode('/chore_status')} - jadval holati\n"
            f"{hcode('/chore_now')} - hozir eslatish",
            reply_markup=deps.main_keyboard(),
        )

    @router.message(Command("health"))
    async def admin_health(message: Message) -> None:
        if not await deps.require_admin(message):
            return
        await message.answer(deps.health_text(await deps.collect_health()), reply_markup=deps.main_keyboard())

    @router.message(Command("stats"))
    async def admin_stats(message: Message) -> None:
        if not await deps.require_admin(message):
            return
        await message.answer(f"{hbold('Statistika')}\n\n{await deps.bot_stats_text()}", reply_markup=deps.main_keyboard())

    @router.message(Command("users"))
    async def admin_users(message: Message) -> None:
        if not await deps.require_admin(message):
            return
        allowed = sorted(allowed_user_ids())
        admins = sorted(admin_user_ids())
        blocked = sorted(blocked_user_ids())
        allowed_text = ", ".join(map(str, allowed)) or "bo'sh"
        admins_text = ", ".join(map(str, admins)) or "bo'sh"
        blocked_text = ", ".join(map(str, blocked)) or "bo'sh"
        await message.answer(
            f"{hbold('Userlar')}\n\n"
            f"Ruxsat berilganlar: {hcode(allowed_text)}\n"
            f"Adminlar: {hcode(admins_text)}\n\n"
            f"Bloklanganlar: {hcode(blocked_text)}\n\n"
            f"Ruxsat fayli: {hcode(str(ALLOWED_USERS_FILE.name))}",
            reply_markup=deps.main_keyboard(),
        )

    @router.message(Command("audit"))
    async def admin_audit(message: Message) -> None:
        if not await deps.require_admin(message):
            return
        rows = await list_audit_logs(15)
        if not rows:
            await message.answer("Audit tarixi hali bo'sh.", reply_markup=deps.main_keyboard())
            return
        lines = [hbold("Audit tarixi"), ""]
        for row in rows:
            target = f" -> {row['target_user_id']}" if row.get("target_user_id") else ""
            details = f" | {deps.escape_html(row['details'])}" if row.get("details") else ""
            lines.append(
                f"{hcode(str(row['id']))}. {deps.escape_html(row['created_at_text'])} | "
                f"{hcode(str(row['actor_user_id']))} | {deps.escape_html(row['action'])}"
                f"{deps.escape_html(target)}{details}"
            )
        await message.answer("\n".join(lines), reply_markup=deps.main_keyboard())

    @router.message(Command("allow"))
    async def admin_allow_user(message: Message, command: CommandObject) -> None:
        if not await deps.require_admin(message):
            return
        raw = deps.command_arg_text(command)
        if not raw.isdigit():
            await message.answer(f"User ID yozing. Masalan: {hcode('/allow 6388458077')}")
            return
        target_id = int(raw)
        action, status_message = grant_user_access(target_id)
        await add_audit_log(deps.user_id_from(message), action, target_id, f"Telegram command: {status_message}")
        await message.answer(
            f"{deps.escape_html(status_message)}\nID: {hcode(str(target_id))}",
            reply_markup=deps.main_keyboard(),
        )

    @router.message(Command("deny"))
    async def admin_deny_user(message: Message, command: CommandObject) -> None:
        if not await deps.require_admin(message):
            return
        raw = deps.command_arg_text(command)
        if not raw.isdigit():
            await message.answer(f"User ID yozing. Masalan: {hcode('/deny 123456789')}")
            return
        target_id = int(raw)
        if target_id in admin_user_ids():
            await message.answer("Adminni bloklab bo'lmaydi.", reply_markup=deps.main_keyboard())
            return
        remove_allowed_user(target_id)
        blocked = block_user(target_id)
        await add_audit_log(deps.user_id_from(message), "block_user", target_id, "Telegram command")
        text = "User bloklandi" if blocked else "Adminni bloklab bo'lmaydi"
        await message.answer(f"{text}: {hcode(raw)}", reply_markup=deps.main_keyboard())

    @router.message(Command("backup"))
    async def admin_backup(message: Message) -> None:
        if not await deps.require_admin(message):
            return
        backup_path = await deps.create_db_backup("manual")
        await message.answer_document(
            FSInputFile(backup_path),
            caption=f"Backup tayyor: {backup_path.name}",
            reply_markup=deps.main_keyboard(),
        )
