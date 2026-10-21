from __future__ import annotations

import asyncio
import logging
import os
import time
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent

from config import Settings, load_settings
from db import Database
from handlers import business, private
from handlers.commands import load_commands
from handlers.utils import esc, notify_owner

log = logging.getLogger("bot")


def setup_logging(path: str) -> None:
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_h = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    console = logging.StreamHandler()
    for h in (file_h, console):
        h.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[file_h, console])


async def cleanup_loop(db: Database, settings: Settings) -> None:
    while True:
        try:
            removed = await db.cleanup(int(time.time()) - settings.retention_days * 86400)
            if removed:
                log.info("Автоочистка: удалено записей %s", removed)
        except Exception:
            log.exception("Ошибка автоочистки")
        await asyncio.sleep(3600)


async def reminder_loop(bot: Bot, db: Database, settings: Settings) -> None:
    while True:
        try:
            for r in await db.due_reminders(int(time.time())):
                sent = await notify_owner(bot, r["uid"], f"⏰ <b>Напоминание:</b> {esc(r['text'])}")
                if sent or not await db.is_allowed(r["uid"]):
                    await db.delete_reminder(None, r["id"])
        except Exception:
            log.exception("Ошибка цикла напоминаний")
        await asyncio.sleep(5)


async def main() -> None:
    settings = load_settings()
    setup_logging(settings.log_file)
    db = Database(settings.db_path, settings.owner_id)
    await db.connect()

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(db=db, settings=settings)
    dp.include_router(business.router)
    dp.include_router(private.router)
    load_commands()

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        log.error("Необработанная ошибка в хендлере", exc_info=event.exception)
        return True

    cleaner = asyncio.create_task(cleanup_loop(db, settings))
    reminders = asyncio.create_task(reminder_loop(bot, db, settings))
    try:
        me = await bot.get_me()
        log.info("Запущен @%s, владелец %s", me.username, settings.owner_id)
        await bot.delete_webhook()
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        cleaner.cancel()
        reminders.cancel()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
