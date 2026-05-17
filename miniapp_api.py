from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiohttp import web

from access_control import (
    admin_user_ids,
    allowed_user_ids,
    block_user,
    blocked_user_ids,
    grant_user_access,
    is_admin_user,
    permitted_user_ids,
    unblock_user,
)
from db import parse_utc
from finance import clean_amount
from finance_store import (
    category_limit_key,
    clear_user_data,
    create_manual_transaction,
    delete_card_balance,
    delete_transaction,
    delete_user_setting,
    get_transactions,
    set_category_limit,
    set_user_setting,
    update_card_balance,
    update_transaction,
)
from miniapp_auth import no_store_headers, request_json, validate_telegram_init_user
from prayer_times import DEFAULT_PRAYER_KEYS, normalize_prayer_city


@dataclass
class MiniAppContext:
    miniapp_dir: Path
    dashboard_payload: Callable[[int], Awaitable[dict]]
    save_user_profile_from_webapp_user: Callable[[dict], Awaitable[None]]
    admin_user_rows: Callable[[], Awaitable[list[dict]]]
    list_audit_logs: Callable[[int], Awaitable[list[dict]]]
    add_audit_log: Callable[[int, str, int | None, str], Awaitable[None]]
    delete_reminder: Callable[[int, int], Awaitable[bool]]
    update_reminder: Callable[[int, int, Any, str, str], Awaitable[bool]]
    send_transactions_export: Callable[[int, str, str], Awaitable[dict]]
    get_prayer_setting: Callable[..., Awaitable[dict]]
    save_prayer_setting: Callable[..., Awaitable[dict]]
    group_chore_payload: Callable[[], Awaitable[dict]]
    add_chore_member: Callable[[str], Awaitable[dict]]
    delete_chore_member: Callable[[int], Awaitable[dict]]
    add_chore_pair: Callable[[str, str], Awaitable[dict]]
    delete_chore_pair: Callable[[int], Awaitable[dict]]


@web.middleware
async def miniapp_error_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception as exc:
        logging.exception("Mini App request failed: %s %s: %s", request.method, request.path, exc)
        return web.Response(status=500, text="Mini App server error", headers=no_store_headers())


class MiniAppApi:
    def __init__(self, ctx: MiniAppContext) -> None:
        self.ctx = ctx

    def finance_gone(self) -> None:
        raise web.HTTPGone(text="Moliya bo'limi arxivlangan va Mini App'dan olib tashlangan.")

    def local_dev_user_id(self, request: web.Request) -> int | None:
        preview_enabled = os.getenv("MINIAPP_ALLOW_LOCAL_PREVIEW", "").strip().lower()
        if preview_enabled not in {"1", "true", "yes", "on"}:
            return None
        if request.remote not in {"127.0.0.1", "::1", "localhost"}:
            return None
        host = request.headers.get("Host", "").split(":", 1)[0].strip("[]").lower()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return None
        if request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For"):
            return None
        raw = os.getenv("MINIAPP_DEV_USER_ID", "").strip()
        if raw.isdigit():
            return int(raw)
        allowed = allowed_user_ids()
        if len(allowed) == 1:
            return next(iter(allowed))
        return None

    async def user_id(self, request: web.Request) -> int:
        token = os.getenv("BOT_TOKEN", "").strip()
        init_data = request.headers.get("X-Telegram-Init-Data", "")
        webapp_user = validate_telegram_init_user(init_data, token)
        user_id = int(webapp_user["id"]) if webapp_user else self.local_dev_user_id(request)
        if not user_id:
            raise web.HTTPUnauthorized(text="Mini App auth failed")
        permitted = permitted_user_ids()
        if permitted and user_id not in permitted:
            raise web.HTTPForbidden(text="User is not allowed")
        if user_id in blocked_user_ids() and not is_admin_user(user_id):
            raise web.HTTPForbidden(text="User is blocked")
        if webapp_user:
            await self.ctx.save_user_profile_from_webapp_user(webapp_user)
        return user_id

    async def admin_user_id(self, request: web.Request) -> int:
        user_id = await self.user_id(request)
        if not is_admin_user(user_id):
            raise web.HTTPForbidden(text="Admin only")
        return user_id

    async def index(self, _: web.Request) -> web.FileResponse:
        return web.FileResponse(self.ctx.miniapp_dir / "index.html", headers=no_store_headers())

    async def asset(self, request: web.Request) -> web.FileResponse:
        filename = request.match_info["filename"]
        path = (self.ctx.miniapp_dir / filename).resolve()
        root = self.ctx.miniapp_dir.resolve()
        try:
            path.relative_to(root)
        except ValueError:
            raise web.HTTPNotFound()
        if not path.exists() or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers=no_store_headers())

    async def dashboard(self, request: web.Request) -> web.Response:
        user_id = await self.user_id(request)
        payload = await self.ctx.dashboard_payload(user_id)
        return web.json_response(payload, headers=no_store_headers())

    async def admin_users(self, request: web.Request) -> web.Response:
        await self.admin_user_id(request)
        return web.json_response(
            {
                "ok": True,
                "users": await self.ctx.admin_user_rows(),
                "audit_logs": await self.ctx.list_audit_logs(20),
                "allowed_count": len(allowed_user_ids()),
                "blocked_count": len(blocked_user_ids()),
                "chores": await self.ctx.group_chore_payload(),
            },
            headers=no_store_headers(),
        )

    async def admin_allow(self, request: web.Request) -> web.Response:
        admin_id = await self.admin_user_id(request)
        body = await request_json(request)
        try:
            target_user_id = int(str(body.get("user_id", "")).strip())
        except ValueError:
            raise web.HTTPBadRequest(text="User id required")
        if target_user_id <= 0:
            raise web.HTTPBadRequest(text="Invalid user id")
        action, message = grant_user_access(target_user_id)
        await self.ctx.add_audit_log(admin_id, action, target_user_id, f"Mini App: {message}")
        return web.json_response(
            {
                "ok": True,
                "message": message,
                "users": await self.ctx.admin_user_rows(),
                "audit_logs": await self.ctx.list_audit_logs(20),
            },
            headers=no_store_headers(),
        )

    async def admin_block(self, request: web.Request) -> web.Response:
        admin_id = await self.admin_user_id(request)
        body = await request_json(request)
        try:
            target_user_id = int(str(body.get("user_id", "")).strip())
        except ValueError:
            raise web.HTTPBadRequest(text="User id required")
        if target_user_id == admin_id or target_user_id in admin_user_ids():
            raise web.HTTPBadRequest(text="Admin user cannot be blocked")
        if target_user_id <= 0:
            raise web.HTTPBadRequest(text="Invalid user id")
        block_user(target_user_id)
        await self.ctx.add_audit_log(admin_id, "block_user", target_user_id, "Mini App")
        return web.json_response(
            {"ok": True, "users": await self.ctx.admin_user_rows(), "audit_logs": await self.ctx.list_audit_logs(20)},
            headers=no_store_headers(),
        )

    async def admin_unblock(self, request: web.Request) -> web.Response:
        admin_id = await self.admin_user_id(request)
        body = await request_json(request)
        try:
            target_user_id = int(str(body.get("user_id", "")).strip())
        except ValueError:
            raise web.HTTPBadRequest(text="User id required")
        unblock_user(target_user_id)
        await self.ctx.add_audit_log(admin_id, "unblock_user", target_user_id, "Mini App")
        return web.json_response(
            {"ok": True, "users": await self.ctx.admin_user_rows(), "audit_logs": await self.ctx.list_audit_logs(20)},
            headers=no_store_headers(),
        )

    async def chore_member_add(self, request: web.Request) -> web.Response:
        admin_id = await self.admin_user_id(request)
        body = await request_json(request)
        name = str(body.get("name", "")).strip()
        try:
            await self.ctx.add_chore_member(name)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        await self.ctx.add_audit_log(admin_id, "chore_member_add", None, name)
        chore = await self.ctx.group_chore_payload()
        return web.json_response({"ok": True, "chores": chore}, headers=no_store_headers())

    async def chore_member_delete(self, request: web.Request) -> web.Response:
        admin_id = await self.admin_user_id(request)
        body = await request_json(request)
        try:
            member_id = int(body.get("id"))
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="Member id required")
        await self.ctx.delete_chore_member(member_id)
        await self.ctx.add_audit_log(admin_id, "chore_member_delete", None, str(member_id))
        chore = await self.ctx.group_chore_payload()
        return web.json_response({"ok": True, "chores": chore}, headers=no_store_headers())

    async def chore_pair_add(self, request: web.Request) -> web.Response:
        admin_id = await self.admin_user_id(request)
        body = await request_json(request)
        first_name = str(body.get("first_name", "")).strip()
        second_name = str(body.get("second_name", "")).strip()
        try:
            await self.ctx.add_chore_pair(first_name, second_name)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        await self.ctx.add_audit_log(admin_id, "chore_pair_add", None, f"{first_name} / {second_name}")
        chore = await self.ctx.group_chore_payload()
        return web.json_response({"ok": True, "chores": chore}, headers=no_store_headers())

    async def chore_pair_delete(self, request: web.Request) -> web.Response:
        admin_id = await self.admin_user_id(request)
        body = await request_json(request)
        try:
            pair_id = int(body.get("id"))
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="Pair id required")
        await self.ctx.delete_chore_pair(pair_id)
        await self.ctx.add_audit_log(admin_id, "chore_pair_delete", None, str(pair_id))
        chore = await self.ctx.group_chore_payload()
        return web.json_response({"ok": True, "chores": chore}, headers=no_store_headers())

    async def reminder_delete(self, request: web.Request) -> web.Response:
        user_id = await self.user_id(request)
        body = await request_json(request)
        try:
            reminder_id = int(body.get("id"))
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="Reminder id required")
        ok = await self.ctx.delete_reminder(user_id, reminder_id)
        return web.json_response({"ok": ok}, headers=no_store_headers())

    async def reminder_update(self, request: web.Request) -> web.Response:
        user_id = await self.user_id(request)
        body = await request_json(request)
        try:
            reminder_id = int(body.get("id"))
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="Reminder id required")
        text = str(body.get("text", "")).strip()[:500]
        due_raw = str(body.get("due_at", "")).strip()
        if not text or not due_raw:
            raise web.HTTPBadRequest(text="Reminder text and date required")
        try:
            due_at = parse_utc(due_raw)
        except ValueError:
            raise web.HTTPBadRequest(text="Invalid reminder date")
        repeat_rule = str(body.get("repeat_rule", "")).strip()
        ok = await self.ctx.update_reminder(user_id, reminder_id, due_at, text, repeat_rule)
        return web.json_response({"ok": ok}, headers=no_store_headers())

    async def transaction_delete(self, request: web.Request) -> web.Response:
        self.finance_gone()

    async def transaction_update(self, request: web.Request) -> web.Response:
        self.finance_gone()

    async def card_update(self, request: web.Request) -> web.Response:
        self.finance_gone()

    async def card_delete(self, request: web.Request) -> web.Response:
        self.finance_gone()

    async def transaction_create(self, request: web.Request) -> web.Response:
        self.finance_gone()

    async def category_limit_set(self, request: web.Request) -> web.Response:
        self.finance_gone()

    async def category_limit_delete(self, request: web.Request) -> web.Response:
        self.finance_gone()

    async def daily_limit(self, request: web.Request) -> web.Response:
        self.finance_gone()

    async def daily_report_setting(self, request: web.Request) -> web.Response:
        self.finance_gone()

    async def export_transactions(self, request: web.Request) -> web.Response:
        self.finance_gone()

    async def clear_data(self, request: web.Request) -> web.Response:
        user_id = await self.user_id(request)
        body = await request_json(request)
        scope = str(body.get("scope", "")).strip()
        try:
            await clear_user_data(user_id, scope)
        except ValueError:
            raise web.HTTPBadRequest(text="Unknown clear scope")
        return web.json_response({"ok": True, "scope": scope}, headers=no_store_headers())

    async def prayer_toggle(self, request: web.Request) -> web.Response:
        user_id = await self.user_id(request)
        body = await request_json(request)
        enabled = bool(body.get("enabled"))
        prayers = ",".join(DEFAULT_PRAYER_KEYS) if enabled else ""
        setting = await self.ctx.save_prayer_setting(user_id, 0, enabled=enabled, prayers=prayers)
        return web.json_response({"ok": True, "enabled": setting["enabled"]}, headers=no_store_headers())

    async def prayer_key(self, request: web.Request) -> web.Response:
        user_id = await self.user_id(request)
        body = await request_json(request)
        key = str(body.get("key", "")).strip()
        if key not in DEFAULT_PRAYER_KEYS:
            raise web.HTTPBadRequest(text="Unknown prayer key")
        setting = await self.ctx.get_prayer_setting(user_id)
        enabled_keys = {item for item in setting["prayers"].split(",") if item in DEFAULT_PRAYER_KEYS}
        if bool(body.get("enabled")):
            enabled_keys.add(key)
        else:
            enabled_keys.discard(key)
        ordered = [item for item in DEFAULT_PRAYER_KEYS if item in enabled_keys]
        updated = await self.ctx.save_prayer_setting(
            user_id,
            0,
            prayers=",".join(ordered),
            enabled=bool(ordered),
        )
        return web.json_response({"ok": True, "enabled": updated["enabled"], "enabled_keys": ordered}, headers=no_store_headers())

    async def prayer_city(self, request: web.Request) -> web.Response:
        user_id = await self.user_id(request)
        body = await request_json(request)
        city = normalize_prayer_city(str(body.get("city", "")))
        if not city:
            raise web.HTTPBadRequest(text="Unknown city")
        setting = await self.ctx.save_prayer_setting(user_id, 0, city=city)
        return web.json_response({"ok": True, "city": setting["city"]}, headers=no_store_headers())

    async def prayer_lead_time(self, request: web.Request) -> web.Response:
        user_id = await self.user_id(request)
        body = await request_json(request)
        try:
            minutes = int(body.get("minutes", 0))
        except (TypeError, ValueError):
            minutes = 0
        if minutes not in {0, 5, 10, 15}:
            raise web.HTTPBadRequest(text="Allowed values: 0, 5, 10, 15")
        setting = await self.ctx.save_prayer_setting(user_id, 0, minutes_before=minutes)
        return web.json_response({"ok": True, "minutes_before": setting["minutes_before"]}, headers=no_store_headers())

    def register_routes(self, app: web.Application) -> None:
        app.router.add_get("/", self.index)
        app.router.add_get("/api/dashboard", self.dashboard)
        app.router.add_get("/api/admin/users", self.admin_users)
        app.router.add_post("/api/admin/allow", self.admin_allow)
        app.router.add_post("/api/admin/block", self.admin_block)
        app.router.add_post("/api/admin/unblock", self.admin_unblock)
        app.router.add_post("/api/admin/chore-members/add", self.chore_member_add)
        app.router.add_post("/api/admin/chore-members/delete", self.chore_member_delete)
        app.router.add_post("/api/admin/chore-pairs/add", self.chore_pair_add)
        app.router.add_post("/api/admin/chore-pairs/delete", self.chore_pair_delete)
        app.router.add_post("/api/reminders/delete", self.reminder_delete)
        app.router.add_post("/api/reminders/update", self.reminder_update)
        app.router.add_post("/api/transactions/create", self.transaction_create)
        app.router.add_post("/api/transactions/delete", self.transaction_delete)
        app.router.add_post("/api/transactions/update", self.transaction_update)
        app.router.add_post("/api/cards/update", self.card_update)
        app.router.add_post("/api/cards/delete", self.card_delete)
        app.router.add_post("/api/category-limits/set", self.category_limit_set)
        app.router.add_post("/api/category-limits/delete", self.category_limit_delete)
        app.router.add_post("/api/settings/daily-limit", self.daily_limit)
        app.router.add_post("/api/settings/daily-report", self.daily_report_setting)
        app.router.add_post("/api/export/transactions.xlsx", self.export_transactions)
        app.router.add_post("/api/data/clear", self.clear_data)
        app.router.add_post("/api/prayer/toggle", self.prayer_toggle)
        app.router.add_post("/api/prayer/key", self.prayer_key)
        app.router.add_post("/api/prayer/city", self.prayer_city)
        app.router.add_post("/api/prayer/lead-time", self.prayer_lead_time)
        app.router.add_get("/{filename:.*\\.(?:css|js|png|jpg|jpeg|webp|svg|ico)}", self.asset)
