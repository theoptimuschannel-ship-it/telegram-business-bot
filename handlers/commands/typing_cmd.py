from animations import typing_frames
from handlers.commands import CommandContext, command


@command("печатает", aliases=("typing",), description="анимация «печатает...»; с текстом — эффект печатной машинки")
async def typing(ctx: CommandContext) -> None:
    await ctx.animate(typing_frames(ctx.args), delay=0.7)
