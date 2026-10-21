from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

log = logging.getLogger(__name__)

esc = html.escape


def clip(text: str | None, limit: int = 3500) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def fmt_dt(ts: int, tz: ZoneInfo) -> str:
    return datetime.fromtimestamp(ts, tz).strftime("%d.%m.%Y %H:%M")


async def notify_owner(bot: Bot, owner_id: int, text: str, **kwargs) -> bool:
    """Отправка владельцу в личку бота. Никогда не бросает исключений."""
    for _ in range(3):
        try:
            await bot.send_message(owner_id, text, **kwargs)
            return True
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 0.5)
        except TelegramAPIError as e:
            log.warning("Не удалось написать владельцу: %s", e)
            return False
    return False


async def fetch_json(url: str, **params):
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)


_DUR = re.compile(
    r"^((?:\d+\s*(?:секунд\w*|сек\w*|с|минут\w*|мин\w*|м|час\w*|ч|дн\w*|день|д|s|m|h|d)(?![a-zа-я])\s*)+)(.*)$",
    re.I | re.S,
)
_PART = re.compile(r"(\d+)\s*([a-zа-я]+)", re.I)
_UNIT = {"с": 1, "s": 1, "м": 60, "m": 60, "ч": 3600, "h": 3600, "д": 86400, "d": 86400}


def parse_leading_duration(text: str) -> tuple[int, str]:
    """'1ч30м текст' -> (5400, 'текст'). Если времени нет — (0, text)."""
    m = _DUR.match(text.strip())
    if not m:
        return 0, text
    total = sum(int(n) * _UNIT[u[0].lower()] for n, u in _PART.findall(m.group(1)))
    return total, m.group(2).strip()


def fmt_duration(sec: int) -> str:
    h, rem = divmod(max(0, int(sec)), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
