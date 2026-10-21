from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from config import Settings
from db import Database
import json

from handlers.auto import parse_hours
from handlers.business import MEDIA_LABELS, format_rights
from handlers.utils import clip, esc, fmt_dt

log = logging.getLogger(__name__)
router = Router(name="private")
router.message.filter(F.chat.type == "private")

TOGGLES = {
    "notify_deleted": "Уведомления об удалениях",
    "notify_edited": "Уведомления об изменениях",
    "notify_own": "Уведомления о своих сообщениях",
}


def _is_owner(user, settings: Settings) -> bool:
    return bool(user and user.id == settings.owner_id)


@router.message(CommandStart())
async def start(message: Message, db: Database, settings: Settings):
    if not _is_owner(message.from_user, settings):
        return
    conns = [c for c in await db.list_connections() if c["user_id"] == settings.owner_id]
    if not conns:
        await message.answer(
            "👋 Бот пока не подключён.\n"
            "Настройки → Telegram для бизнеса → Чат-боты → выберите этого бота."
        )
        return
    parts = ["👋 <b>Статус подключения</b>"]
    for c in conns:
        state = "✅ активно" if c["is_enabled"] else "❌ отключено"
        parts.append(f"\n{state} (обновлено {fmt_dt(c['updated_at'], settings.tz)})\n{format_rights(json.loads(c['rights']))}")
    parts.append("\n/settings — уведомления, /stats — статистика, «!help» в любом чате — команды")
    await message.answer("\n".join(parts))


def _settings_kb(states: dict[str, bool]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{'✅' if states[k] else '❌'} {label}", callback_data=f"toggle:{k}")]
            for k, label in TOGGLES.items()
        ]
    )


async def _states(db: Database) -> dict[str, bool]:
    return {k: await db.get_bool(k) for k in TOGGLES}


@router.message(Command("settings"))
async def settings_cmd(message: Message, db: Database, settings: Settings):
    if not _is_owner(message.from_user, settings):
        return
    await message.answer("⚙️ Настройки:", reply_markup=_settings_kb(await _states(db)))


@router.callback_query(F.data.startswith("toggle:"))
async def toggle(cb: CallbackQuery, db: Database, settings: Settings):
    if not _is_owner(cb.from_user, settings):
        await cb.answer()
        return
    key = cb.data.split(":", 1)[1]
    if key in TOGGLES:
        await db.toggle(key)
    if cb.message:
        try:
            await cb.message.edit_reply_markup(reply_markup=_settings_kb(await _states(db)))
        except Exception as e:  # например «message is not modified»
            log.debug("edit_reply_markup: %s", e)
    await cb.answer("Сохранено")


@router.message(Command("stats"))
async def stats(message: Message, db: Database, settings: Settings):
    if not _is_owner(message.from_user, settings):
        return
    await message.answer(
        "📊 <b>Статистика</b>\n"
        f"Сообщений в бэкапе: {await db.count_messages()}\n"
        f"Поймано удалений: {await db.counter('stat_deleted')}\n"
        f"Поймано изменений: {await db.counter('stat_edited')}\n"
        f"Хранение: {settings.retention_days} дн."
    )


# ---------- помощь ----------
HELP = (
    "🤖 <b>Команды бота</b>\n"
    "/start — статус подключения\n"
    "/settings — уведомления\n"
    "/stats — статистика\n"
    "/chat <i>имя|@username|id</i> — последние сообщения из бэкапа\n"
    "/search <i>слово</i> — поиск по бэкапу\n"
    "/export [<i>имя</i>] — выгрузка бэкапа в JSON\n"
    "/mute [<i>имя</i>] — не уведомлять об удалениях в этом чате (повтор — вернуть)\n"
    "/ghost — режим «только удаления»\n"
    "/away — автоответчик (on/off, text, hours)\n"
    "/reply — ответы по ключевым словам (add/list/del)\n\n"
    "В любом чате напишите <code>!help</code> — список «!»-команд."
)


@router.message(Command("help"))
async def help_cmd(message: Message, settings: Settings):
    if _is_owner(message.from_user, settings):
        await message.answer(HELP)


# ---------- бэкап: поиск, чат, экспорт ----------
def _label(row) -> str:
    uname = f" @{row['sender_username']}" if row["sender_username"] else ""
    return f"{esc(row['sender_name'] or '?')}{uname} (<code>{row['chat_id']}</code>)"


async def _resolve_chat(message: Message, db: Database, query: str):
    rows = await db.find_chats(query)
    if not rows:
        await message.answer("Чат не найден в бэкапе.")
        return None
    if len(rows) > 1:
        await message.answer(
            "Найдено несколько, уточните (можно id):\n" + "\n".join(_label(r) for r in rows)
        )
        return None
    return rows[0]


def _line(r, settings: Settings) -> str:
    body = r["text"] or ""
    if r["media_type"]:
        body = f"[{MEDIA_LABELS.get(r['media_type'], r['media_type'])}] {body}".strip()
    who = "Вы" if r["is_own"] else (r["sender_name"] or "?")
    return f"<i>{fmt_dt(r['date'], settings.tz)}</i> <b>{esc(who)}</b>: {esc(clip(body, 300))}"


@router.message(Command("chat"))
async def chat_cmd(message: Message, command: CommandObject, db: Database, settings: Settings):
    if not _is_owner(message.from_user, settings):
        return
    if not command.args:
        await message.answer("Формат: /chat имя | @username | id")
        return
    chat = await _resolve_chat(message, db, command.args)
    if not chat:
        return
    rows = await db.chat_messages(chat["chat_id"], 20)
    text = f"💬 <b>{_label(chat)}</b>, последние {len(rows)}:\n\n" + "\n".join(_line(r, settings) for r in rows)
    await message.answer(clip(text, 4000))


@router.message(Command("search"))
async def search_cmd(message: Message, command: CommandObject, db: Database, settings: Settings):
    if not _is_owner(message.from_user, settings):
        return
    if not command.args:
        await message.answer("Формат: /search слово")
        return
    rows = await db.search(command.args, 20)
    if not rows:
        await message.answer("Ничего не найдено.")
        return
    out = [f"🔎 <b>{esc(command.args)}</b>: найдено {len(rows)} (последние)\n"]
    for r in rows:
        out.append(f"<b>{esc(r['chat_name'] or r['chat_id'])}</b> · {_line(r, settings)}")
    await message.answer(clip("\n".join(out), 4000))


@router.message(Command("export"))
async def export_cmd(message: Message, command: CommandObject, db: Database, settings: Settings):
    if not _is_owner(message.from_user, settings):
        return
    chat_id = None
    if command.args:
        chat = await _resolve_chat(message, db, command.args)
        if not chat:
            return
        chat_id = chat["chat_id"]
    rows = await db.export_rows(chat_id)
    if not rows:
        await message.answer("Бэкап пуст.")
        return
    for r in rows:
        r["date_iso"] = fmt_dt(r["date"], settings.tz)
    data = json.dumps(rows, ensure_ascii=False, indent=1).encode()
    await message.answer_document(BufferedInputFile(data, filename="backup.json"), caption=f"Сообщений: {len(rows)}")


# ---------- мьют и режим призрака ----------
@router.message(Command("mute"))
async def mute_cmd(message: Message, command: CommandObject, db: Database, settings: Settings):
    if not _is_owner(message.from_user, settings):
        return
    if not command.args:
        rows = await db.list_muted()
        await message.answer(
            "🔇 В муте:\n" + "\n".join(f"{esc(r['title'])} (<code>{r['chat_id']}</code>)" for r in rows)
            if rows else "Мьютов нет. Формат: /mute имя | @username | id"
        )
        return
    chat = await _resolve_chat(message, db, command.args)
    if not chat:
        return
    muted = await db.toggle_mute(chat["chat_id"], chat["sender_name"] or str(chat["chat_id"]))
    await message.answer(("🔇 Уведомления отключены: " if muted else "🔔 Уведомления включены: ") + _label(chat))


@router.message(Command("ghost"))
async def ghost_cmd(message: Message, db: Database, settings: Settings):
    if not _is_owner(message.from_user, settings):
        return
    on = await db.toggle("ghost")
    await db.set_setting("notify_deleted", "1")
    await db.set_setting("notify_edited", "0" if on else "1")
    await message.answer("👻 Режим призрака: только удаления." if on else "👻 Выключен: удаления и изменения.")


# ---------- автоответчик ----------
@router.message(Command("away"))
async def away_cmd(message: Message, command: CommandObject, db: Database, settings: Settings):
    if not _is_owner(message.from_user, settings):
        return
    arg = (command.args or "").strip()
    head, _, rest = arg.partition(" ")
    head, rest = head.lower(), rest.strip()
    if head in ("on", "off"):
        await db.set_setting("away_enabled", "1" if head == "on" else "0")
    elif head == "text" and rest:
        await db.set_setting("away_text", rest)
    elif head == "hours":
        if rest.lower() in ("off", "always"):
            await db.set_setting("away_hours", "")
        elif parse_hours(rest):
            await db.set_setting("away_hours", rest)
        else:
            await message.answer("Формат: /away hours 23:00-08:00 (или off — всегда)")
            return
    elif arg:
        await message.answer("Формат: /away on|off, /away text Текст, /away hours 23:00-08:00")
        return
    state = "✅ включён" if await db.get_bool("away_enabled") else "❌ выключен"
    hours = await db.get_setting("away_hours") or "всегда"
    await message.answer(
        f"🕒 Автоответчик {state}\nЧасы: {esc(hours)} ({settings.tz.key})\n"
        f"Текст: {esc(await db.get_setting('away_text') or '')}\n"
        "Отвечает раз в 6 часов на чат. Нужно право «отвечать»."
    )


# ---------- ответы по ключевым словам ----------
@router.message(Command("reply"))
async def reply_cmd(message: Message, command: CommandObject, db: Database, settings: Settings):
    if not _is_owner(message.from_user, settings):
        return
    arg = (command.args or "").strip()
    head, _, rest = arg.partition(" ")
    if head.lower() == "add" and "=" in rest:
        kw, _, resp = rest.partition("=")
        if kw.strip() and resp.strip():
            rid = await db.add_autoreply(kw.strip(), resp.strip())
            await message.answer(f"✅ #{rid}: «{esc(kw.strip())}» → {esc(resp.strip())}")
            return
    elif head.lower() in ("del", "delete") and rest.strip().isdigit():
        ok = await db.delete_autoreply(int(rest))
        await message.answer("🗑 Удалено." if ok else "Нет такого.")
        return
    elif head.lower() == "list" or not arg:
        rows = await db.list_autoreplies()
        await message.answer(
            "💬 <b>Ответы</b>\n" + "\n".join(f"#{r['id']} «{esc(r['keyword'])}» → {esc(r['response'])}" for r in rows)
            if rows else "Ответов нет.\n/reply add слово = ответ\n/reply del N"
        )
        return
    await message.answer("Формат: /reply add слово = ответ | /reply list | /reply del N")
