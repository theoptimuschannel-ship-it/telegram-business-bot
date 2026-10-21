from animations import hearts_frames
from handlers.commands import CommandContext, command


@command("сердечки", aliases=("hearts",), description="анимация из сердечек; текст после команды попадёт в финал")
async def hearts(ctx: CommandContext) -> None:
    await ctx.animate(hearts_frames(ctx.args))
