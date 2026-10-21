"""Автоответчик (по расписанию) и ответы по ключевым словам на входящие сообщения."""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from config import Settings
from db import Database

log = logging.getLogger(__name__)

AWAY_COOLDOWN = 6 * 3600
KEYWORD_COOLDOWN = 30
_last: dict[tuple, float] = {}


def parse_hours(value: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", value or "")
    if not m:
        return None
    a, b, c, d = map(int, m.groups())
    if a > 23 or c > 23 or b > 59 or d > 59:
        return None
    return a * 60 + b, c * 60 + d


def in_hours(value: str, now: datetime) -> bool:
    """Пустая строка — всегда. Поддерживает интервалы через полночь (23:00-08:00)."""
    parsed = parse_hours(value)
    if not parsed:
        return True
    start, end = parsed
    cur = now.hour * 60 + now.minute
    return start <= cur < end if start <= end else (cur >= start or cur < end)


def _cooldown_ok(key: tuple, seconds: int) -> bool:
    now = time.time()
    if now - _last.get(key, 0) < seconds:
        return False
    _last[key] = now
    return True


async def maybe_autoreply(bot: Bot, db: Database, settings: Settings, message: Message, uid: int) -> None:
    if message.chat.type != "private" or not message.from_user or message.from_user.is_bot:
        return
    chat_id, conn = message.chat.id, message.business_connection_id
    text = (message.text or message.caption or "").lower()

    async def send(reply: str) -> None:
        try:
            await bot.send_message(chat_id, reply, business_connection_id=conn, parse_mode=None)
        except TelegramAPIError as e:
            log.warning("Автоответ не отправлен: %s", e)

    if text:
        for r in await db.list_autoreplies(uid):
            if r["keyword"] in text and _cooldown_ok((uid, chat_id, "kw", r["id"]), KEYWORD_COOLDOWN):
                await send(r["response"])
                return
    if await db.get_bool(uid, "away_enabled"):
        hours = await db.get_setting(uid, "away_hours") or ""
        if in_hours(hours, datetime.now(settings.tz)) and _cooldown_ok((uid, chat_id, "away"), AWAY_COOLDOWN):
            await send(await db.get_setting(uid, "away_text") or "")
