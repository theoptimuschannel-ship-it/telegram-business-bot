from __future__ import annotations

import asyncio
import logging
import random

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.types import Message

from handlers.utils import esc, fmt_duration

log = logging.getLogger(__name__)

# Чаты, где сейчас идёт анимация (одна анимация на чат).
_active_chats: set[int] = set()
_stop_requests: set[int] = set()
# Правки/удаления, сделанные самим ботом: по ним не шлём уведомления.
suppressed_edits: set[tuple[int, int]] = set()
suppressed_deletions: set[tuple[int, int]] = set()

HEART_COLORS = ["❤️", "🧡", "💛", "💚", "💙", "💜", "🩷"]
BG = "⬜"
# Форма сердца, 7 колонок
SHAPE = [
    ".XX.XX.",
    "XXXXXXX",
    "XXXXXXX",
    ".XXXXX.",
    "..XXX..",
    "...X...",
]


def _render(cell) -> str:
    """cell(row, col) -> эмодзи или None (фон)."""
    lines = []
    for r, row in enumerate(SHAPE):
        lines.append("".join((cell(r, c) or BG) if ch == "X" else BG for c, ch in enumerate(row)))
    return "\n".join(lines)


def hearts_frames(text: str = "") -> list[str]:
    rng = random.Random()
    frames: list[str] = []
    # 1) сердце складывается снизу вверх из разноцветных сердечек (6 кадров)
    colors = {(r, c): rng.choice(HEART_COLORS) for r in range(len(SHAPE)) for c in range(7)}
    for top in range(len(SHAPE) - 1, -1, -1):
        frames.append(_render(lambda r, c, top=top: colors[(r, c)] if r >= top else None))
    # 2) смена цвета целиком (3 кадра)
    for color in ("💜", "💙", "💚"):
        frames.append(_render(lambda r, c, color=color: color))
    # 3) мигание (4 кадра)
    for color in ("🩷", "🤍", "🩷", "🤍"):
        frames.append(_render(lambda r, c, color=color: color))
    # 4) финал
    final = _render(lambda r, c: "❤️")
    if text.strip():
        final += "\n\n" + esc(text.strip())
    frames.append(final)
    return frames


def typing_frames(text: str = "") -> list[str]:
    text = text.strip()
    if not text:
        dots = ["печатает", "печатает.", "печатает..", "печатает..."]
        return [dots[i % 4] for i in range(12)] + ["💬"]
    step = max(1, -(-len(text) // 14))
    frames = [esc(text[:i]) + "▌" for i in range(step, len(text), step)]
    return ["печатает..."] + frames + [esc(text)]


SKY = "⬛"


def _grid(cells: dict, rows: int = 5, cols: int = 5, bg: str = SKY) -> str:
    return "\n".join("".join(cells.get((r, c), bg) for c in range(cols)) for r in range(rows))


def _tail(text: str, default: str) -> str:
    return default + ("\n\n" + esc(text.strip()) if text.strip() else "")


def loading_frames(text: str = "") -> list[str]:
    title = esc(text.strip()) or "Загрузка"
    frames = [f"⏳ {title}\n{'▓' * (p // 10)}{'░' * (10 - p // 10)} {p}%" for p in range(0, 100, 10)]
    return frames + [f"✅ {title}\n{'▓' * 10} 100%"]


def hack_frames(target: str = "") -> list[str]:
    name = esc(target.strip()) or "цель"
    return [
        f"💻 Подключение к {name}...",
        "🔍 Поиск уязвимостей...\n▓▓░░░░░░░░ 20%",
        "🔑 Подбор пароля...\n▓▓▓▓▓░░░░░ 50%",
        "🛡 Обход защиты...\n▓▓▓▓▓▓▓░░░ 75%",
        "📂 Скачивание данных...\n▓▓▓▓▓▓▓▓▓▓ 100%",
        f"✅ Взлом {name} завершён. Шутка 😄",
    ]


def rocket_frames(text: str = "") -> list[str]:
    rng = random.Random()
    frames = [_grid({(r, 2): "🚀"}) for r in (4, 3, 2, 1, 0)]
    frames.append(_grid({(0, 1): "💥", (0, 2): "💥", (0, 3): "💥"}))
    cells = [(r, c) for r in range(5) for c in range(5)]
    for _ in range(2):
        frames.append(_grid({rc: rng.choice(["✨", "💫", "⭐"]) for rc in rng.sample(cells, 12)}))
    frames.append(_tail(text, "🌟"))
    return frames


def moon_frames(text: str = "") -> list[str]:
    phases = "🌑🌒🌓🌔🌕🌖🌗🌘"
    return [phases[i % 8] for i in range(12)] + [_tail(text, "🌕")]


def clock_frames(text: str = "") -> list[str]:
    return list("🕐🕑🕒🕓🕔🕕🕖🕗🕘🕙🕚🕛") + [_tail(text, "⏰")]


def falling_frames(drop: str, final: str, text: str = "") -> list[str]:
    rng = random.Random()
    rows, cols = 5, 7
    grid: list[list[bool]] = [[False] * cols for _ in range(rows)]
    frames = []
    for _ in range(12):
        grid = [[rng.random() < 0.3 for _ in range(cols)]] + grid[:-1]
        frames.append("\n".join("".join(drop if x else SKY for x in row) for row in grid))
    return frames + [_tail(text, final)]


def coin_frames() -> list[str]:
    side = random.choice(["орёл", "решка"])
    frames = [f"🪙 {'орёл' if i % 2 == 0 else 'решка'}…" for i in range(6)]
    return frames + [f"🪙 Выпало: <b>{side}</b>"]


def choose_frames(options: list[str]) -> list[str]:
    pick = random.choice(options)
    frames = [f"🤔 {esc(random.choice(options))}…" for _ in range(6)]
    return frames + [f"🎯 Выбираю: <b>{esc(pick)}</b>"]


def timer_frames(total: int) -> tuple[list[str], int]:
    step = max(2, -(-total // 60))
    left = list(range(total, 0, -step))
    frames = [f"⏳ Осталось: <b>{fmt_duration(t)}</b>" for t in left]
    return frames + ["⏰ <b>Время вышло!</b>"], step



async def _retry(func, *args, **kwargs):
    """Вызов API с ожиданием при TelegramRetryAfter."""
    for _ in range(5):
        try:
            return await func(*args, **kwargs)
        except TelegramRetryAfter as e:
            log.warning("RetryAfter: жду %s с", e.retry_after)
            await asyncio.sleep(e.retry_after + 0.5)
    return await func(*args, **kwargs)


def request_stop(chat_id: int) -> bool:
    """Просит остановить анимацию в чате. False, если анимации нет."""
    if chat_id not in _active_chats:
        return False
    _stop_requests.add(chat_id)
    return True


async def delete_business_message(bot: Bot, conn_id: str, chat_id: int, message_id: int) -> bool:
    key = (chat_id, message_id)
    suppressed_deletions.add(key)
    asyncio.get_running_loop().call_later(120, suppressed_deletions.discard, key)
    try:
        await _retry(bot.delete_business_messages, business_connection_id=conn_id, message_ids=[message_id])
        return True
    except TelegramAPIError as e:
        suppressed_deletions.discard(key)
        log.warning("Не удалось удалить сообщение %s/%s: %s", chat_id, message_id, e)
        return False


async def _edit(bot: Bot, conn_id: str, chat_id: int, message_id: int, text: str) -> None:
    try:
        await _retry(
            bot.edit_message_text,
            text=text,
            business_connection_id=conn_id,
            chat_id=chat_id,
            message_id=message_id,
        )
    except TelegramBadRequest as e:
        if "not modified" not in str(e).lower():
            raise


_edit_ok: dict[str, bool] = {}  # connection_id -> можно ли править сообщения владельца


async def edit_or_replace(bot: Bot, message: Message, text: str) -> int:
    """Ставит text вместо сообщения владельца. Возвращает id итогового сообщения.

    Сначала editMessageText; если Telegram не даёт — удаляет исходное и шлёт новое
    от имени владельца. Выбранный способ запоминается для подключения.
    """
    chat_id, conn_id = message.chat.id, message.business_connection_id
    key = (chat_id, message.message_id)
    if _edit_ok.get(conn_id) is not False:
        suppressed_edits.add(key)
        try:
            await _edit(bot, conn_id, chat_id, message.message_id, text)
            _edit_ok[conn_id] = True
            return message.message_id
        except TelegramAPIError as e:
            suppressed_edits.discard(key)
            if isinstance(e, TelegramBadRequest):
                _edit_ok[conn_id] = False
            log.info("Редактирование невозможно (%s), запасной путь: удалить и отправить", e)
    await delete_business_message(bot, conn_id, chat_id, message.message_id)
    sent = await _retry(bot.send_message, chat_id=chat_id, text=text, business_connection_id=conn_id)
    return sent.message_id


async def run_animation(bot: Bot, message: Message, frames: list[str], delay: float) -> str:
    """Проигрывает анимацию на сообщении владельца: "ok" | "busy" | "failed"."""
    chat_id = message.chat.id
    conn_id = message.business_connection_id
    if chat_id in _active_chats:
        return "busy"
    _active_chats.add(chat_id)
    key = (chat_id, message.message_id)
    try:
        target_id = await edit_or_replace(bot, message, frames[0])
        key = (chat_id, target_id)
        suppressed_edits.add(key)
        for frame in frames[1:]:
            await asyncio.sleep(delay)
            if chat_id in _stop_requests:
                break
            await _edit(bot, conn_id, chat_id, target_id, frame)
        return "ok"
    except TelegramAPIError as e:
        log.error("Анимация прервана: %s", e)
        return "failed"
    finally:
        _active_chats.discard(chat_id)
        _stop_requests.discard(chat_id)
        # событие edited может прийти чуть позже последней правки
        asyncio.get_running_loop().call_later(5, suppressed_edits.discard, key)
