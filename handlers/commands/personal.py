import time

from handlers.commands import CommandContext, command
from handlers.utils import clip, esc, fmt_dt, parse_leading_duration


async def _private(ctx: CommandContext, text: str) -> None:
    """Ответ только владельцу в бота, команда из чата убирается."""
    await ctx.reply_owner(text)
    await ctx.delete_command_message()


@command("напомни", aliases=("remind",), description="напоминание в бота: !напомни 10м позвонить (без аргументов — список)")
async def remind(ctx: CommandContext) -> None:
    seconds, text = parse_leading_duration(ctx.args)
    if not ctx.args.strip():
        rows = await ctx.db.list_reminders()
        body = "\n".join(
            f"#{r['id']} {fmt_dt(r['due'], ctx.settings.tz)} — {esc(clip(r['text'], 200))}" for r in rows
        ) or "Напоминаний нет."
        await _private(ctx, "⏰ <b>Напоминания</b>\n" + body + "\n\nУдалить: <code>!напомни удалить N</code>")
        return
    first, _, rest = ctx.args.strip().partition(" ")
    if first.lower() in ("удалить", "del") and rest.strip().isdigit():
        ok = await ctx.db.delete_reminder(int(rest))
        await _private(ctx, "🗑 Удалено." if ok else "Такого напоминания нет.")
        return
    if not seconds or not text:
        await _private(ctx, "ℹ️ Формат: <code>!напомни 10м текст</code> (с, м, ч, д; можно <code>1ч30м</code>)")
        return
    due = int(time.time()) + seconds
    rid = await ctx.db.add_reminder(due, text)
    await _private(ctx, f"⏰ Напомню {fmt_dt(due, ctx.settings.tz)} (#{rid}): {esc(clip(text, 500))}")


@command("заметка", aliases=("note",), description="сохранить заметку: !заметка текст (удалить: !заметка удалить N)")
async def note(ctx: CommandContext) -> None:
    text = ctx.text_arg
    first, _, rest = text.partition(" ")
    if first.lower() in ("удалить", "del") and rest.strip().isdigit():
        ok = await ctx.db.delete_note(int(rest))
        await _private(ctx, "🗑 Заметка удалена." if ok else "Такой заметки нет.")
        return
    if not text:
        await _private(ctx, "ℹ️ Формат: <code>!заметка текст</code> (или ответом на сообщение)")
        return
    nid = await ctx.db.add_note(text)
    await _private(ctx, f"📝 Заметка #{nid} сохранена.")


@command("заметки", aliases=("notes",), description="показать все заметки (в бота)")
async def notes(ctx: CommandContext) -> None:
    rows = await ctx.db.list_notes()
    body = "\n\n".join(f"<b>#{r['id']}</b> ({fmt_dt(r['created'], ctx.settings.tz)})\n{esc(clip(r['text'], 800))}" for r in rows)
    await _private(ctx, "📝 <b>Заметки</b>\n\n" + clip(body, 3500) if rows else "Заметок пока нет.")
