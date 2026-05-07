from __future__ import annotations

import os
from dataclasses import dataclass

import aiohttp


class AiNotConfiguredError(RuntimeError):
    pass


@dataclass(frozen=True)
class AiRequestError(RuntimeError):
    status: int | None
    message: str
    code: str = ""

    def __str__(self) -> str:
        return self.message


def openai_api_key() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip()


def openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-5.4-mini").strip() or "gpt-5.4-mini"


def openai_configured() -> bool:
    return bool(openai_api_key())


def extract_output_text(payload: dict) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    chunks: list[str] = []
    for item in payload.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str) and text:
                chunks.append(text)
    return "\n".join(chunks).strip()


def friendly_ai_error(exc: Exception) -> str:
    if isinstance(exc, AiNotConfiguredError):
        return "OpenAI API kaliti ulanmagan. Server .env faylida OPENAI_API_KEY kerak."
    if isinstance(exc, AiRequestError):
        lower = f"{exc.message} {exc.code}".lower()
        if exc.status == 429 or "quota" in lower or "rate" in lower:
            return "OpenAI quota yoki limit yetmayapti. Billing/quota faollashgandan keyin ishlaydi."
        if exc.status == 401:
            return "OpenAI API kaliti noto'g'ri yoki bekor qilingan."
        if exc.status == 403:
            return "OpenAI API bu loyiha yoki model uchun ruxsat bermayapti."
        if "model" in lower:
            return "OpenAI modeli topilmadi. OPENAI_MODEL qiymatini almashtirish kerak."
        return f"OpenAI xatosi: {exc.message}"
    return f"AI xatosi: {exc}"


async def ask_openai(question: str, context: str = "") -> str:
    api_key = openai_api_key()
    if not api_key:
        raise AiNotConfiguredError()

    system_prompt = (
        "Sen Telegram ichidagi shaxsiy yordamchi botsan. "
        "Foydalanuvchiga o'zbek tilida, qisqa va amaliy javob ber. "
        "Agar berilgan kontekstda aniq ma'lumot bo'lmasa, taxmin qilma va qanday ma'lumot kerakligini ayt."
    )
    user_prompt = question.strip()
    if context.strip():
        user_prompt = f"Kontekst:\n{context.strip()}\n\nSavol:\n{user_prompt}"

    body = {
        "model": openai_model(),
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_output_tokens": int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "700")),
    }
    timeout = aiohttp.ClientTimeout(total=int(os.getenv("OPENAI_TIMEOUT_SECONDS", "45")))
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post("https://api.openai.com/v1/responses", headers=headers, json=body) as response:
            payload = await response.json(content_type=None)
            if response.status >= 400:
                error = payload.get("error") if isinstance(payload, dict) else None
                message = str(error.get("message") if isinstance(error, dict) else payload)
                code = str(error.get("code") if isinstance(error, dict) else "")
                raise AiRequestError(response.status, message, code)

    text = extract_output_text(payload if isinstance(payload, dict) else {})
    if not text:
        raise AiRequestError(None, "OpenAI javobida matn topilmadi.")
    return text


async def ping_openai() -> str:
    return await ask_openai("Faqat bitta so'z bilan javob ber: ishladi")
