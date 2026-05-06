import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

from aiohttp import web


def validate_telegram_init_user(init_data: str, bot_token: str) -> dict | None:
    if not init_data or not bot_token:
        return None
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None
    data_check_string = "\n".join(f"{key}={parsed[key]}" for key in sorted(parsed))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        return None
    try:
        auth_date = int(parsed.get("auth_date", "0"))
    except ValueError:
        return None
    max_age = int(os.getenv("MINIAPP_AUTH_MAX_AGE_SECONDS", "86400"))
    if not auth_date or (max_age > 0 and time.time() - auth_date > max_age):
        return None
    try:
        user = json.loads(parsed.get("user", "{}"))
        int(user["id"])
        return user if isinstance(user, dict) else None
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def validate_telegram_init_data(init_data: str, bot_token: str) -> int | None:
    user = validate_telegram_init_user(init_data, bot_token)
    if not user:
        return None
    try:
        return int(user["id"])
    except (KeyError, TypeError, ValueError):
        return None


def no_store_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store, max-age=0"}


async def request_json(request: web.Request) -> dict:
    try:
        body = await request.json()
    except (TypeError, ValueError, json.JSONDecodeError):
        raise web.HTTPBadRequest(text="JSON body required")
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="JSON object required")
    return body
