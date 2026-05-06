import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
forwarder_env = Path(os.getenv("FORWARDER_ENV_FILE", "forwarder.local.env")).expanduser()
if not forwarder_env.is_absolute():
    forwarder_env = BASE_DIR / forwarder_env
if forwarder_env.exists():
    load_dotenv(forwarder_env, override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "forwarder.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)


def get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f".env ichida {name} yozilmagan.")
    return value


def parse_usernames(raw: str) -> list[str]:
    usernames: list[str] = []
    for item in raw.split(","):
        username = item.strip()
        if username:
            usernames.append(username if username.startswith("@") else f"@{username}")
    return usernames


BANK_KEYWORDS = [
    "uzcard",
    "humo",
    "humocard",
    "cardxabar",
    "visa",
    "karta",
    "card",
    "balans",
    "balance",
    "so'm",
    "uzs",
]


def looks_like_bank_text(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in BANK_KEYWORDS) and any(char.isdigit() for char in text)


async def main() -> None:
    api_id = int(get_required_env("TG_API_ID"))
    api_hash = get_required_env("TG_API_HASH")
    assistant_bot_username = get_required_env("ASSISTANT_BOT_USERNAME")
    if not assistant_bot_username.startswith("@"):
        assistant_bot_username = f"@{assistant_bot_username}"
    source_usernames = parse_usernames(os.getenv("SOURCE_BOT_USERNAMES", ""))
    source_lookup = {username.lstrip("@").lower() for username in source_usernames}

    client = TelegramClient(str(BASE_DIR / "user_session"), api_id, api_hash)
    assistant_username = assistant_bot_username.lstrip("@").lower()

    async def maybe_forward_bank_message(event, event_type: str) -> None:
        text = event.raw_text or ""
        if not text.strip():
            return
        sender = await event.get_sender()
        sender_username = (getattr(sender, "username", "") or "").lower()
        if sender_username == assistant_username:
            return
        is_configured_source = sender_username in source_lookup
        is_bank_like_bot_message = bool(getattr(sender, "bot", False)) and looks_like_bank_text(text)
        if not is_configured_source and not is_bank_like_bot_message:
            return
        await client.send_message(assistant_bot_username, text)
        logging.info(
            "Forwarded %s from @%s (%s)",
            event_type,
            sender_username or "unknown",
            event.chat_id,
        )

    @client.on(events.NewMessage(incoming=True))
    async def forward_new_bank_message(event) -> None:
        await maybe_forward_bank_message(event, "new message")

    @client.on(events.MessageEdited(incoming=True))
    async def forward_edited_bank_message(event) -> None:
        await maybe_forward_bank_message(event, "edited message")

    await client.start()
    me = await client.get_me()
    if getattr(me, "bot", False):
        raise RuntimeError(
            "Forwarder bot token bilan login qilingan. "
            "Bu ishlamaydi, chunki Telegram bot boshqa bot xabarlarini o'qiy olmaydi. "
            "user_session.session faylini o'chiring yoki backup qiling, keyin run_forwarder.cmd ni "
            "qayta ishga tushirib, bot token emas, o'zingizning telefon raqamingiz bilan login qiling."
        )
    assistant_entity = await client.get_entity(assistant_bot_username)
    assistant_username = (getattr(assistant_entity, "username", "") or assistant_username).lower()
    logging.info("Forwarder ishlayapti. Kuzatilayotgan botlar: %s", ", ".join(source_usernames) or "bank-like bot messages")
    logging.info("Xabarlar yuboriladigan bot: %s", assistant_bot_username)
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
