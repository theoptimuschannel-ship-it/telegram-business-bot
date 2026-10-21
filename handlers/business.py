from __future__ import annotations

import asyncio
import io
import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import BufferedInputFile, BusinessConnection, BusinessMessagesDeleted, Message

import animations
from config import Settings
from db import Database
from handlers.auto import maybe_autoreply
from handlers.commands import dispatch
from handlers.utils import clip, esc, fmt_dt, notify_owner

log = logging.getLogger(__name__)
router = Router(name="business")

RIGHTS_LABELS = {
    "can_reply": "отвечать на сообщения",
    "can_read_messages": "читать сообщения",
    "can_delete_sent_messages": "удалять отправленные сообщения",
    "can_delete_outgoing_messages": "удалять исходящие сообщения",
    "can_delete_all_messages": "удалять любые сообщения",
    "can_edit_name": "менять имя",
    "can_edit_bio": "менять описание",
    "can_edit_profile_photo": "менять фото профиля",
    "can_edit_username": "менять username",
    "can_change_gift_settings": "настройки подарков",
    "can_view_gifts_and_stars": "видеть подарки и звёзды",
    "can_convert_gifts_to_stars": "конвертировать подарки в звёзды",
    "can_transfer_and_upgrade_gifts": "передавать и улучшать подарки",
    "can_transfer_stars": "переводить звёзды",
    "can_manage_stories": "управлять историями",
}

MEDIA_LABELS = {
    "photo": "фото", "video": "видео", "document": "файл", "audio": "аудио", "voice": "голосовое",
    "video_note": "кружок", "animation": "GIF", "sticker": "стикер",
}
# media_type -> (метод отправки, имя параметра)
MEDIA_SEND = {k: (f"send_{k}", k) for k in MEDIA_LABELS}
NO_CAPTION = {"video_note", "sticker"}


def format_rights(rights: dict) -> str:
    if not rights:
        return "—"
    return "\n".join(
        f"{'✅' if rights.get(k) else '❌'} {label}" for k, label in RIGHTS_LABELS.items() if k in rights
    ) or "—"


def extract_media(m: Message) -> tuple[str | None, str | None]:
    if m.photo:
        return "photo", m.photo[-1].file_id
    for kind in ("video", "document", "audio", "voice", "video_note", "animation", "sticker"):
        obj = getattr(m, kind, None)
        if obj:
            return kind, obj.file_id
    return None, None


def to_record(m: Message, uid: int) -> dict:
    u = m.from_user
    media_type, file_id = extract_media(m)
    return {
        "uid": uid,
        "chat_id": m.chat.id,
        "message_id": m.message_id,
        "connection_id": m.business_connection_id,
        "sender_id": u.id if u else None,
        "sender_name": u.full_name if u else m.chat.full_name,
        "sender_username": u.username if u else None,
        "date": int(m.date.timestamp()),
        "text": m.text or m.caption,
        "media_type": media_type,
        "file_id": file_id,
        "reply_to": m.reply_to_message.message_id if m.reply_to_message else None,
        "is_own": int(bool(u and u.id == uid)),
    }


async def store_connection(db: Database, bc: BusinessConnection) -> dict:
    rights = bc.rights.model_dump(exclude_none=True) if getattr(bc, "rights", None) else {}
    if not rights and getattr(bc, "can_reply", None) is not None:
        rights = {"can_reply": bc.can_reply}
    await db.upsert_connection(bc.id, bc.user.id, bc.user_chat_id, bc.is_enabled, rights)
    return rights


async def connection_user(bot: Bot, db: Database, conn_id: str | None) -> int | None:
    """Чьё это подключение. None — чужое/неразрешённое, такие события игнорируем."""
    if not conn_id:
        return None
    row = await db.get_connection(conn_id)
    if row:
        return row["user_id"] if await db.is_allowed(row["user_id"]) else None
    try:
        bc = await bot.get_business_connection(conn_id)
    except TelegramAPIError as e:
        log.warning("get_business_connection(%s) не удался: %s", conn_id, e)
        return None
    if not await db.is_allowed(bc.user.id):
        return None
    await store_connection(db, bc)
    return bc.user.id


# ---------- подключение ----------
@router.business_connection()
async def on_connection(bc: BusinessConnection, bot: Bot, db: Database, settings: Settings):
    uid = bc.user.id
    if not await db.is_allowed(uid):
        log.info("Игнорирую подключение неразрешённого аккаунта %s", uid)
        if await db.get_user(uid):  # добавлен владельцем, но ещё не нажал /start
            await notify_owner(
                bot, bc.user_chat_id,
                "👋 Вас добавили в бота, но доступ ещё не активирован. Откройте бота и нажмите /start.",
            )
        return
    rights = await store_connection(db, bc)
    if bc.is_enabled:
        text = f"✅ <b>Бот подключён</b> к аккаунту.\n\nПрава:\n{format_rights(rights)}"
        if not rights.get("can_read_messages"):
            text += "\n\n⚠️ Без права «читать сообщения» бэкап работать не будет."
    else:
        text = "❌ <b>Бот отключён</b> от аккаунта."
    await notify_owner(bot, uid, text)


# ---------- медиа «по ответу» (в т.ч. одноразовое 🔥) ----------
_saved_replies: set[tuple[int, int, int]] = set()
REPLY_MEDIA = ("photo", "video", "voice", "video_note", "animation", "audio", "document")


async def save_replied_media(bot: Bot, db: Database, settings: Settings, message: Message, uid: int) -> None:
    """Владелец ответил на чужое медиа — присылаем это медиа ему в бота."""
    r = message.reply_to_message
    if not r or (r.from_user and r.from_user.id == uid):
        return
    media_type, file_id = extract_media(r)
    if media_type not in REPLY_MEDIA or not file_id:
        present = [k for k, v in r.model_dump(exclude_none=True).items() if v not in (None, [], {}, False)]
        log.info("Ответ на сообщение без доступного медиа (одноразовое?). Поля: %s", present)
        return
    if not await db.get_bool(uid, "save_replied_media"):
        return
    key = (uid, message.chat.id, r.message_id)
    if key in _saved_replies:
        return
    if len(_saved_replies) > 5000:
        _saved_replies.clear()
    _saved_replies.add(key)

    name = (r.from_user.full_name if r.from_user else None) or message.chat.full_name or "?"
    when = fmt_dt(int(r.date.timestamp()), settings.tz)
    caption = f"🔥 <b>{esc(name)}</b> · {when}\nМедиа, на которое вы ответили"
    if r.caption:
        caption += f"\n{esc(clip(r.caption, 700))}"
    if media_type in NO_CAPTION:
        await notify_owner(bot, uid, caption)
    sent = await resend_media(bot, uid, media_type, file_id, caption)
    if not sent:  # запасной путь: скачать и загрузить заново
        try:
            buf = io.BytesIO()
            await bot.download(file_id, destination=buf)
            method, param = MEDIA_SEND[media_type]
            kwargs = {"chat_id": uid, param: BufferedInputFile(buf.getvalue(), filename=f"{media_type}")}
            if media_type not in NO_CAPTION:
                kwargs["caption"] = caption
            await getattr(bot, method)(**kwargs)
            sent = True
        except Exception as e:
            log.warning("Не удалось сохранить медиа из ответа: %s", e)
    if not sent:
        _saved_replies.discard(key)
        await notify_owner(
            bot, uid,
            f"⚠️ Не удалось выгрузить {MEDIA_LABELS.get(media_type, media_type)} от <b>{esc(name)}</b>: "
            "Telegram не отдал файл боту.",
        )


# ---------- новые сообщения ----------
@router.business_message()
async def on_message(message: Message, bot: Bot, db: Database, settings: Settings):
    uid = await connection_user(bot, db, message.business_connection_id)
    if uid is None:
        return
    rec = to_record(message, uid)
    try:
        await db.save_message(rec)
    except Exception:
        log.exception("Не удалось сохранить сообщение")
    if rec["is_own"]:
        if message.reply_to_message:
            try:
                await save_replied_media(bot, db, settings, message, uid)
            except Exception:
                log.exception("Ошибка сохранения медиа из ответа")
        if message.chat.type == "private" and (message.text or "").startswith("!"):
            await dispatch(bot, db, settings, message)
    else:
        try:
            await maybe_autoreply(bot, db, settings, message, uid)
        except Exception:
            log.exception("Ошибка автоответа")


# ---------- изменённые ----------
@router.edited_business_message()
async def on_edited(message: Message, bot: Bot, db: Database, settings: Settings):
    uid = await connection_user(bot, db, message.business_connection_id)
    if uid is None:
        return
    if (message.business_connection_id, message.chat.id, message.message_id) in animations.suppressed_edits:
        return
    old = await db.get_message(uid, message.chat.id, message.message_id)
    rec = to_record(message, uid)
    await db.save_message(rec)

    old_text = old["text"] if old else None
    if old and (old_text or "") == (rec["text"] or "") and old["media_type"] == rec["media_type"]:
        return
    await db.incr(uid, "stat_edited")
    if not await db.get_bool(uid, "notify_edited") or await db.is_muted(uid, message.chat.id):
        return
    if rec["is_own"] and not await db.get_bool(uid, "notify_own"):
        return
    name = esc(rec["sender_name"] or "?")
    new = esc(clip(rec["text"] or f"[{MEDIA_LABELS.get(rec['media_type'], 'без текста')}]", 1800))
    if old:
        was = esc(clip(old_text or f"[{MEDIA_LABELS.get(old['media_type'], 'без текста')}]", 1800))
        text = f"✏️ <b>{name}</b> изменил сообщение:\n<b>было:</b> {was}\n<b>→ стало:</b> {new}"
    else:
        text = f"✏️ <b>{name}</b> изменил сообщение (старой версии нет в бэкапе):\n<b>стало:</b> {new}"
    await notify_owner(bot, uid, text)


# ---------- удалённые ----------
async def resend_media(bot: Bot, owner_id: int, media_type: str, file_id: str, caption: str | None) -> bool:
    method, param = MEDIA_SEND[media_type]
    kwargs = {"chat_id": owner_id, param: file_id}
    if caption and media_type not in NO_CAPTION:
        kwargs["caption"] = caption
    for _ in range(3):
        try:
            await getattr(bot, method)(**kwargs)
            return True
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 0.5)
        except TelegramAPIError as e:
            log.warning("Не удалось переотправить %s: %s", media_type, e)
            return False
    return False


@router.deleted_business_messages()
async def on_deleted(event: BusinessMessagesDeleted, bot: Bot, db: Database, settings: Settings):
    uid = await connection_user(bot, db, event.business_connection_id)
    if uid is None:
        return
    chat_id = event.chat.id
    conn_id = event.business_connection_id
    rows = await db.get_messages(uid, chat_id, list(event.message_ids))
    found = {r["message_id"] for r in rows}
    ids = [i for i in event.message_ids if (conn_id, chat_id, i) not in animations.suppressed_deletions]
    rows = [r for r in rows if r["message_id"] in ids]
    missing = [i for i in ids if i not in found]
    if not rows and not missing:
        return
    await db.incr(uid, "stat_deleted", len(rows))

    if not await db.get_bool(uid, "notify_deleted") or await db.is_muted(uid, chat_id):
        return
    notify_own = await db.get_bool(uid, "notify_own")
    owner = uid
    for r in rows:
        if r["is_own"] and not notify_own:
            continue
        name = esc(r["sender_name"] or "?")
        when = fmt_dt(r["date"], settings.tz)
        mt = r["media_type"]
        body = r["text"] or ("" if mt else "[без текста]")
        header = f"🗑 <b>{name}</b> удалил сообщение ({when}):"
        if not mt:
            await notify_owner(bot, owner, f"{header}\n{esc(clip(body))}")
            continue
        label = MEDIA_LABELS.get(mt, mt)
        caption = f"{header}\n[{label}] {esc(body)}".strip()
        inline = mt not in NO_CAPTION and len(caption) <= 1024
        ok = await resend_media(bot, owner, mt, r["file_id"], caption if inline else None)
        if ok and not inline:
            await notify_owner(bot, owner, f"{header}\n[{label}] {esc(clip(body))}")
        elif not ok:
            await notify_owner(
                bot, owner,
                f"{header}\n[{label}] {esc(clip(body))}\n⚠️ Не удалось переотправить медиа: file_id больше не работает.",
            )
    if missing:
        await notify_owner(
            bot, owner,
            f"🗑 В чате с <b>{esc(event.chat.full_name or str(chat_id))}</b> удалено сообщений, "
            f"которых нет в бэкапе: {len(missing)}",
        )
