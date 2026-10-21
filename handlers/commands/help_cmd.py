from handlers.commands import CommandContext, all_commands, command
from handlers.utils import esc


@command("help", aliases=("помощь",), description="список команд (приходит только в бота)")
async def help_cmd(ctx: CommandContext) -> None:
    lines = ["<b>Команды (пишутся в любом чате):</b>"]
    for c in sorted(all_commands(), key=lambda c: c.name):
        names = " / ".join(f"!{n}" for n in (c.name, *c.aliases))
        lines.append(f"{esc(names)} — {esc(c.description)}")
    await ctx.reply_owner("\n".join(lines))
    await ctx.delete_command_message()  # убрать «!help» из чата, если есть права
