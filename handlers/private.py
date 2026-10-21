from __future__ import annotations

import json
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, User,
)

from config import Settings
from db import Database
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


async def _gate(message: Message, db: Database) -> int | None:
    """Telegram ID, если пользователю разрешено пользоваться ботом; иначе молча None."""
    u = message.from_user
    return u.id if u and await db.is_allowed(u.id) else None


def _is_admin(user: User | None, settings: Settings) -> bool:
    return bool(user and user.id == settings.owner_id)


# ---------- старт и доступ ----------
@router.message(CommandStart())
async def start(message: Message, db: Database, settings: Settings):
    u = message.from_user
    if not u:
        return
    if not await db.is_allowed(u.id):
        if await db.get_user(u.id):  # добавлен администратором — активируем
            await db.accept_user(u.id, u.full_name, u.username)
            await message.answer("✅ Доступ активирован.")
        else:
            await message.answer(
                "🔒 Доступ закрыт. Попросите администратора бота добавить ваш ID: "
                f"<code>{u.id}</code>"
            )
            return
    conns = await db.list_connections(u.id)
    if not conns:
        await message.answer(
            "👋 Бот пока не подключён.\n"
            "Настройки → Telegram для бизнеса → Чат-боты → выберите этого бота.\n\n/help — все команды"
        )
        return
    parts = ["👋 <b>Статус подключения</b>"]
    for c in conns:
        state = "✅ активно" if c["is_enabled"] else "❌ отключено"
        parts.append(f"\n{state} (обновлено {fmt_dt(c['updated_at'], settings.tz)})\n{format_rights(json.loads(c['rights']))}")
    parts.append("\n/help — все команды, «!help» в любом чате — «!»-команды")
    await message.answer("\n".join(parts))


# ---------- администратор ----------
async def _admin_target(message: Message, command: CommandObject) -> int | None:
    arg = (command.args or "").strip()
    if not arg.lstrip("-").isdigit():
        await message.answer("Укажите числовой Telegram ID, например: /adduser 123456789")
        return None
    return int(arg)


@router.message(Command("adduser"))
async def adduser(message: Message, command: CommandObject, db: Database, settings: Settings):
    if not _is_admin(message.from_user, settings):
        return
    uid = await _admin_target(message, command)
    if uid is None:
        return
    if uid == settings.owner_id:
        await message.answer("Это вы — администратор, доступ уже есть.")
        return
    added = await db.add_user(uid)
    await message.answer(
        ("✅ Добавлен: " if added else "ℹ️ Уже в списке: ")
        + f"<code>{uid}</code>\nПусть откроет бота и нажмёт /start — после этого доступ включится."
    )


@router.message(Command("removeuser"))
async def removeuser(message: Message, command: CommandObject, db: Database, settings: Settings):
    if not _is_admin(message.from_user, settings):
        return
    uid = await _admin_target(message, command)
    if uid is None:
        return
    if uid == settings.owner_id or not await db.get_user(uid):
        await message.answer("Такого пользователя нет в списке.")
        return
    await db.remove_user(uid)
    await message.answer(f"🗑 Пользователь <code>{uid}</code> удалён вместе со всеми его данными.")


@router.message(Command("users"))
async def users_cmd(message: Message, db: Database, settings: Settings):
    if not _is_admin(message.from_user, settings):
        return
    rows = await db.list_users()
    lines = [f"👑 <code>{settings.owner_id}</code> (вы) — сообщений: {await db.count_messages(settings.owner_id)}"]
    for r in rows:
        who = esc(r["name"] or "ещё не нажал /start")
        uname = f" @{r['username']}" if r["username"] else ""
        state = "✅" if r["accepted"] else "⏳"
        lines.append(f"{state} <code>{r['user_id']}</code> {who}{uname} — сообщений: {await db.count_messages(r['user_id'])}")
    await message.answer(
        "👥 <b>Пользователи</b> (содержимое их сообщений вам не показывается)\n" + "\n".join(lines)
        + "\n\n/adduser id · /removeuser id"
    )


# ---------- удаление своих данных ----------
@router.message(Command("deletedata"))
async def deletedata(message: Message, db: Database):
    if await _gate(message, db) is None:
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🗑 Да, удалить всё", callback_data="wipe:yes")]]
    )
    await message.answer(
        "Будут удалены ваши сохранённые сообщения, заметки, напоминания, автоответы и настройки. Это необратимо.",
        reply_markup=kb,
    )


@router.callback_query(F.data == "wipe:yes")
async def wipe(cb: CallbackQuery, db: Database):
    if not await db.is_allowed(cb.from_user.id):
        await cb.answer()
        return
    await db.wipe_user_data(cb.from_user.id)
    await cb.answer("Удалено")
    if cb.message:
        await cb.message.answer("🗑 Все ваши данные удалены.")


# ---------- настройки ----------
def _settings_kb(states: dict[str, bool]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{'✅' if states[k] else '❌'} {label}", callback_data=f"toggle:{k}")]
            for k, label in TOGGLES.items()
        ]
    )


async def _states(db: Database, uid: int) -> dict[str, bool]:
    return {k: await db.get_bool(uid, k) for k in TOGGLES}


@router.message(Command("settings"))
async def settings_cmd(message: Message, db: Database):
    uid = await _gate(message, db)
    if uid is None:
        return
    await message.answer("⚙️ Настройки:", reply_markup=_settings_kb(await _states(db, uid)))


@router.callback_query(F.data.startswith("toggle:"))
async def toggle(cb: CallbackQuery, db: Database):
    uid = cb.from_user.id
    if not await db.is_allowed(uid):
        await cb.answer()
        return
    key = cb.data.split(":", 1)[1]
    if key in TOGGLES:
        await db.toggle(uid, key)
    if cb.message:
        try:
            await cb.message.edit_reply_markup(reply_markup=_settings_kb(await _states(db, uid)))
        except Exception as e:  # например «message is not modified»
            log.debug("edit_reply_markup: %s", e)
    await cb.answer("Сохранено")


@router.message(Command("stats"))
async def stats(message: Message, db: Database, settings: Settings):
    uid = await _gate(message, db)
    if uid is None:
        return
    text = (
        "📊 <b>Статистика</b>\n"
        f"Сообщений в бэкапе: {await db.count_messages(uid)}\n"
        f"Поймано удалений: {await db.counter(uid, 'stat_deleted')}\n"
        f"Поймано изменений: {await db.counter(uid, 'stat_edited')}\n"
        f"Хранение: {settings.retention_days} дн."
    )
    if _is_admin(message.from_user, settings):
        text += f"\nПользователей (кроме вас): {len(await db.list_users())}"
    await message.answer(text)


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
    "/reply — ответы по ключевым словам (add/list/del)\n"
    "/deletedata — удалить все мои данные\n\n"
    "В любом чате напишите <code>!help</code> — список «!»-команд."
)
ADMIN_HELP = "\n\n👑 <b>Администратор:</b> /adduser id · /removeuser id · /users"


@router.message(Command("help"))
async def help_cmd(message: Message, db: Database, settings: Settings):
    if await _gate(message, db) is None:
        return
    await message.answer(HELP + (ADMIN_HELP if _is_admin(message.from_user, settings) else ""))


# ---------- бэкап: поиск, чат, экспорт ----------
def _label(row) -> str:
    uname = f" @{row['sender_username']}" if row["sender_username"] else ""
    return f"{esc(row['sender_name'] or '?')}{uname} (<code>{row['chat_id']}</code>)"


async def _resolve_chat(message: Message, db: Database, uid: int, query: str):
    rows = await db.find_chats(uid, query)
    if not rows:
        await message.answer("Чат не найден в бэкапе.")
        return None
    if len(rows) > 1:
        await message.answer("Найдено несколько, уточните (можно id):\n" + "\n".join(_label(r) for r in rows))
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
    uid = await _gate(message, db)
    if uid is None:
        return
    if not command.args:
        await message.answer("Формат: /chat имя | @username | id")
        return
    chat = await _resolve_chat(message, db, uid, command.args)
    if not chat:
        return
    rows = await db.chat_messages(uid, chat["chat_id"], 20)
    text = f"💬 <b>{_label(chat)}</b>, последние {len(rows)}:\n\n" + "\n".join(_line(r, settings) for r in rows)
    await message.answer(clip(text, 4000))


@router.message(Command("search"))
async def search_cmd(message: Message, command: CommandObject, db: Database, settings: Settings):
    uid = await _gate(message, db)
    if uid is None:
        return
    if not command.args:
        await message.answer("Формат: /search слово")
        return
    rows = await db.search(uid, command.args, 20)
    if not rows:
        await message.answer("Ничего не найдено.")
        return
    out = [f"🔎 <b>{esc(command.args)}</b>: найдено {len(rows)} (последние)\n"]
    for r in rows:
        out.append(f"<b>{esc(r['chat_name'] or r['chat_id'])}</b> · {_line(r, settings)}")
    await message.answer(clip("\n".join(out), 4000))


@router.message(Command("export"))
async def export_cmd(message: Message, command: CommandObject, db: Database, settings: Settings):
    uid = await _gate(message, db)
    if uid is None:
        return
    chat_id = None
    if command.args:
        chat = await _resolve_chat(message, db, uid, command.args)
        if not chat:
            return
        chat_id = chat["chat_id"]
    rows = await db.export_rows(uid, chat_id)
    if not rows:
        await message.answer("Бэкап пуст.")
        return
    for r in rows:
        r["date_iso"] = fmt_dt(r["date"], settings.tz)
        r.pop("uid", None)
    data = json.dumps(rows, ensure_ascii=False, indent=1).encode()
    await message.answer_document(BufferedInputFile(data, filename="backup.json"), caption=f"Сообщений: {len(rows)}")


# ---------- мьют и режим призрака ----------
@router.message(Command("mute"))
async def mute_cmd(message: Message, command: CommandObject, db: Database):
    uid = await _gate(message, db)
    if uid is None:
        return
    if not command.args:
        rows = await db.list_muted(uid)
        await message.answer(
            "🔇 В муте:\n" + "\n".join(f"{esc(r['title'])} (<code>{r['chat_id']}</code>)" for r in rows)
            if rows else "Мьютов нет. Формат: /mute имя | @username | id"
        )
        return
    chat = await _resolve_chat(message, db, uid, command.args)
    if not chat:
        return
    muted = await db.toggle_mute(uid, chat["chat_id"], chat["sender_name"] or str(chat["chat_id"]))
    await message.answer(("🔇 Уведомления отключены: " if muted else "🔔 Уведомления включены: ") + _label(chat))


@router.message(Command("ghost"))
async def ghost_cmd(message: Message, db: Database):
    uid = await _gate(message, db)
    if uid is None:
        return
    on = await db.toggle(uid, "ghost")
    await db.set_setting(uid, "notify_deleted", "1")
    await db.set_setting(uid, "notify_edited", "0" if on else "1")
    await message.answer("👻 Режим призрака: только удаления." if on else "👻 Выключен: удаления и изменения.")


# ---------- автоответчик ----------
@router.message(Command("away"))
async def away_cmd(message: Message, command: CommandObject, db: Database, settings: Settings):
    uid = await _gate(message, db)
    if uid is None:
        return
    arg = (command.args or "").strip()
    head, _, rest = arg.partition(" ")
    head, rest = head.lower(), rest.strip()
    if head in ("on", "off"):
        await db.set_setting(uid, "away_enabled", "1" if head == "on" else "0")
    elif head == "text" and rest:
        await db.set_setting(uid, "away_text", rest)
    elif head == "hours":
        if rest.lower() in ("off", "always"):
            await db.set_setting(uid, "away_hours", "")
        elif parse_hours(rest):
            await db.set_setting(uid, "away_hours", rest)
        else:
            await message.answer("Формат: /away hours 23:00-08:00 (или off — всегда)")
            return
    elif arg:
        await message.answer("Формат: /away on|off, /away text Текст, /away hours 23:00-08:00")
        return
    state = "✅ включён" if await db.get_bool(uid, "away_enabled") else "❌ выключен"
    hours = await db.get_setting(uid, "away_hours") or "всегда"
    await message.answer(
        f"🕒 Автоответчик {state}\nЧасы: {esc(hours)} ({settings.tz.key})\n"
        f"Текст: {esc(await db.get_setting(uid, 'away_text') or '')}\n"
        "Отвечает раз в 6 часов на чат. Нужно право «отвечать»."
    )


# ---------- ответы по ключевым словам ----------
@router.message(Command("reply"))
async def reply_cmd(message: Message, command: CommandObject, db: Database):
    uid = await _gate(message, db)
    if uid is None:
        return
    arg = (command.args or "").strip()
    head, _, rest = arg.partition(" ")
    if head.lower() == "add" and "=" in rest:
        kw, _, resp = rest.partition("=")
        if kw.strip() and resp.strip():
            rid = await db.add_autoreply(uid, kw.strip(), resp.strip())
            await message.answer(f"✅ #{rid}: «{esc(kw.strip())}» → {esc(resp.strip())}")
            return
    elif head.lower() in ("del", "delete") and rest.strip().isdigit():
        ok = await db.delete_autoreply(uid, int(rest))
        await message.answer("🗑 Удалено." if ok else "Нет такого.")
        return
    elif head.lower() == "list" or not arg:
        rows = await db.list_autoreplies(uid)
        await message.answer(
            "💬 <b>Ответы</b>\n" + "\n".join(f"#{r['id']} «{esc(r['keyword'])}» → {esc(r['response'])}" for r in rows)
            if rows else "Ответов нет.\n/reply add слово = ответ\n/reply del N"
        )
        return
    await message.answer("Формат: /reply add слово = ответ | /reply list | /reply del N")
