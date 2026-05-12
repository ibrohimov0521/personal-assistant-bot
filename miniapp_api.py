from __future__ import annotations

import csv
import io
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
    delete_transaction,
    delete_user_setting,
    get_transactions,
    set_category_limit,
    set_user_setting,
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
    get_prayer_setting: Callable[..., Awaitable[dict]]
    save_prayer_setting: Callable[..., Awaitable[dict]]


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

    async def reminder_delete(self, request: web.Request) -> web.Response:
        user_id = await self.user_id(request)
        body = await request_json(request)
        try:
            reminder_id = int(body.get("id"))
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="Reminder id required")
        ok = await self.ctx.delete_reminder(user_id, reminder_id)
        return web.json_response({"ok": ok}, headers=no_store_headers())

    async def transaction_delete(self, request: web.Request) -> web.Response:
        user_id = await self.user_id(request)
        body = await request_json(request)
        try:
            transaction_id = int(body.get("id"))
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="Transaction id required")
        ok = await delete_transaction(user_id, transaction_id)
        return web.json_response({"ok": ok}, headers=no_store_headers())

    async def transaction_update(self, request: web.Request) -> web.Response:
        user_id = await self.user_id(request)
        body = await request_json(request)
        try:
            transaction_id = int(body.get("id"))
            amount = int(clean_amount(str(body.get("amount", ""))))
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="Transaction id and amount required")
        tx_type = str(body.get("type", "")).strip()
        category = str(body.get("category", "Boshqa")).strip()[:60] or "Boshqa"
        description = str(body.get("description", "")).strip()[:120]
        occurred_at = None
        occurred_raw = str(body.get("occurred_at", "")).strip()
        if occurred_raw:
            try:
                occurred_at = parse_utc(occurred_raw)
            except ValueError:
                occurred_at = None
        ok = await update_transaction(user_id, transaction_id, tx_type, amount, category, description, occurred_at)
        return web.json_response({"ok": ok}, headers=no_store_headers())

    async def transaction_create(self, request: web.Request) -> web.Response:
        user_id = await self.user_id(request)
        body = await request_json(request)
        tx_type = str(body.get("type", "")).strip()
        if tx_type not in {"income", "expense"}:
            raise web.HTTPBadRequest(text="Transaction type required")
        amount = clean_amount(str(body.get("amount", "")))
        if amount <= 0:
            raise web.HTTPBadRequest(text="Amount required")
        category = str(body.get("category", "Boshqa")).strip()[:60] or "Boshqa"
        description = str(body.get("description", "")).strip()[:120]
        card_last4 = re.sub(r"\D+", "", str(body.get("card_last4", "")))[-4:]
        occurred_at = None
        occurred_raw = str(body.get("occurred_at", "")).strip()
        if occurred_raw:
            try:
                occurred_at = parse_utc(occurred_raw)
            except ValueError:
                occurred_at = None
        tx_id = await create_manual_transaction(user_id, tx_type, amount, category, description, card_last4, occurred_at)
        return web.json_response({"ok": True, "id": tx_id}, headers=no_store_headers())

    async def category_limit_set(self, request: web.Request) -> web.Response:
        user_id = await self.user_id(request)
        body = await request_json(request)
        category = str(body.get("category", "")).strip()[:60]
        if not category:
            raise web.HTTPBadRequest(text="Category required")
        amount = clean_amount(str(body.get("amount", "")))
        await set_category_limit(user_id, category, amount)
        return web.json_response({"ok": True, "category": category, "amount": amount}, headers=no_store_headers())

    async def category_limit_delete(self, request: web.Request) -> web.Response:
        user_id = await self.user_id(request)
        body = await request_json(request)
        category = str(body.get("category", "")).strip()[:60]
        if not category:
            raise web.HTTPBadRequest(text="Category required")
        await delete_user_setting(user_id, category_limit_key(category))
        return web.json_response({"ok": True, "category": category}, headers=no_store_headers())

    async def daily_limit(self, request: web.Request) -> web.Response:
        user_id = await self.user_id(request)
        body = await request_json(request)
        amount = clean_amount(str(body.get("amount", "")))
        await set_user_setting(user_id, "daily_expense_limit", str(max(amount, 0)))
        return web.json_response({"ok": True, "amount": amount}, headers=no_store_headers())

    async def daily_report_setting(self, request: web.Request) -> web.Response:
        user_id = await self.user_id(request)
        body = await request_json(request)
        enabled = bool(body.get("enabled"))
        await set_user_setting(user_id, "daily_report_enabled", "1" if enabled else "0")
        return web.json_response({"ok": True, "enabled": enabled}, headers=no_store_headers())

    async def export_transactions(self, request: web.Request) -> web.Response:
        user_id = await self.user_id(request)
        rows = await get_transactions(user_id, limit=10000)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "date", "type", "amount", "currency", "source", "card_last4", "category", "description"])
        for row in rows:
            writer.writerow(
                [
                    row["id"],
                    row["occurred_at"].isoformat(),
                    row["type"],
                    row["amount"],
                    row["currency"],
                    row["source"],
                    row["card_last4"],
                    row["category"],
                    row["description"],
                ]
            )
        headers = no_store_headers()
        headers["Content-Disposition"] = 'attachment; filename="assistant-transactions.csv"'
        return web.Response(text=output.getvalue(), content_type="text/csv", charset="utf-8", headers=headers)

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
        app.router.add_post("/api/reminders/delete", self.reminder_delete)
        app.router.add_post("/api/transactions/create", self.transaction_create)
        app.router.add_post("/api/transactions/delete", self.transaction_delete)
        app.router.add_post("/api/transactions/update", self.transaction_update)
        app.router.add_post("/api/category-limits/set", self.category_limit_set)
        app.router.add_post("/api/category-limits/delete", self.category_limit_delete)
        app.router.add_post("/api/settings/daily-limit", self.daily_limit)
        app.router.add_post("/api/settings/daily-report", self.daily_report_setting)
        app.router.add_get("/api/export/transactions.csv", self.export_transactions)
        app.router.add_post("/api/data/clear", self.clear_data)
        app.router.add_post("/api/prayer/toggle", self.prayer_toggle)
        app.router.add_post("/api/prayer/key", self.prayer_key)
        app.router.add_post("/api/prayer/city", self.prayer_city)
        app.router.add_post("/api/prayer/lead-time", self.prayer_lead_time)
        app.router.add_get("/{filename:.*\\.(?:css|js|png|jpg|jpeg|webp|svg|ico)}", self.asset)
