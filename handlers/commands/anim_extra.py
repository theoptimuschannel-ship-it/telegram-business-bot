from animations import (
    clock_frames, falling_frames, hack_frames, loading_frames, moon_frames, rocket_frames, timer_frames,
)
from handlers.commands import CommandContext, command
from handlers.utils import parse_leading_duration


@command("ракета", aliases=("rocket",), description="ракета взлетает и взрывается салютом; [текст] в финале")
async def rocket(ctx: CommandContext) -> None:
    await ctx.animate(rocket_frames(ctx.args))


@command("луна", aliases=("moon",), description="фазы луны; [текст] в финале")
async def moon(ctx: CommandContext) -> None:
    await ctx.animate(moon_frames(ctx.args))


@command("часы", aliases=("clock",), description="крутящиеся стрелки часов; [текст] в финале")
async def clock(ctx: CommandContext) -> None:
    await ctx.animate(clock_frames(ctx.args))


@command("дождь", aliases=("rain",), description="падающий дождь; [текст] в финале")
async def rain(ctx: CommandContext) -> None:
    await ctx.animate(falling_frames("💧", "☔", ctx.args))


@command("снег", aliases=("snow",), description="падающий снег; [текст] в финале")
async def snow(ctx: CommandContext) -> None:
    await ctx.animate(falling_frames("❄️", "⛄", ctx.args))


@command("загрузка", aliases=("loading",), description="полоса прогресса; [текст] — заголовок")
async def loading(ctx: CommandContext) -> None:
    await ctx.animate(loading_frames(ctx.args))


@command("взлом", aliases=("hack",), description="шуточный «взлом»; [имя цели]")
async def hack(ctx: CommandContext) -> None:
    await ctx.animate(hack_frames(ctx.args), delay=1.0)


@command("таймер", aliases=("timer",), description="обратный отсчёт в чате: !таймер 5м (до 1 часа)")
async def timer(ctx: CommandContext) -> None:
    total, _ = parse_leading_duration(ctx.args)
    if not 4 <= total <= 3600:
        await ctx.reply_owner("ℹ️ Формат: <code>!таймер 5м</code> (от 4 секунд до 1 часа; м, с, ч).")
        await ctx.delete_command_message()
        return
    frames, step = timer_frames(total)
    await ctx.animate(frames, delay=step)
