"""Роутер команд «!». Новая команда = новый модуль в этой папке с @command(...)."""
from __future__ import annotations

import asyncio
import importlib
import logging
import pkgutil
from dataclasses import dataclass
from typing import Awaitable, Callable

from aiogram import Bot
from aiogram.types import Message

import animations
from config import Settings
from db import Database
from handlers.utils import notify_owner

log = logging.getLogger(__name__)

Handler = Callable[["CommandContext"], Awaitable[None]]


@dataclass
class Command:
    name: str
    aliases: tuple[str, ...]
    description: str
    handler: Handler


_registry: dict[str, Command] = {}
_tasks: set[asyncio.Task] = set()


def command(name: str, *, aliases: tuple[str, ...] = (), description: str = ""):
    def deco(fn: Handler) -> Handler:
        cmd = Command(name, aliases, description, fn)
        for n in (name, *aliases):
            _registry[n.lower()] = cmd
        return fn

    return deco


def all_commands() -> list[Command]:
    return list({id(c): c for c in _registry.values()}.values())


@dataclass
class CommandContext:
    bot: Bot
    db: Database
    settings: Settings
    message: Message
    command: str
    args: str

    @property
    def uid(self) -> int:
        """Владелец бизнес-аккаунта, который написал команду."""
        return self.message.from_user.id

    async def reply_owner(self, text: str, **kw) -> bool:
        """Ответ только автору команды — в личку с ботом."""
        return await notify_owner(self.bot, self.uid, text, **kw)

    async def delete_command_message(self) -> bool:
        m = self.message
        return await animations.delete_business_message(
            self.bot, m.business_connection_id, m.chat.id, m.message_id
        )

    @property
    def text_arg(self) -> str:
        """Текст после команды, а если его нет — текст сообщения, на которое ответили."""
        if self.args.strip():
            return self.args.strip()
        r = self.message.reply_to_message
        return ((r.text or r.caption or "") if r else "").strip()

    async def say(self, text: str) -> None:
        """Заменяет сообщение с командой на text (HTML) в чате."""
        await animations.edit_or_replace(self.bot, self.message, text[:4000])

    async def animate(self, frames: list[str], delay: float | None = None) -> None:
        status = await animations.run_animation(
            self.bot, self.message, frames, delay or self.settings.anim_delay
        )
        if status == "busy":
            await self.reply_owner("⏳ В этом чате уже идёт анимация.")
        elif status == "failed":
            await self.reply_owner("⚠️ Не удалось проиграть анимацию (см. логи). Проверьте права бота.")


def load_commands() -> None:
    for mod in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{mod.name}")
    log.info("Команды: %s", ", ".join(sorted(_registry)))


async def _run(cmd: Command, ctx: CommandContext) -> None:
    try:
        await cmd.handler(ctx)
    except Exception:
        log.exception("Ошибка в команде !%s", cmd.name)
        await ctx.reply_owner(f"⚠️ Ошибка в команде !{cmd.name}, подробности в логах.")


async def dispatch(bot: Bot, db: Database, settings: Settings, message: Message) -> bool:
    parts = (message.text or "").strip()[1:].split(maxsplit=1)
    if not parts:
        return False
    cmd = _registry.get(parts[0].lower())
    if not cmd:
        return False
    ctx = CommandContext(bot, db, settings, message, parts[0].lower(), parts[1] if len(parts) > 1 else "")
    task = asyncio.create_task(_run(cmd, ctx))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return True
