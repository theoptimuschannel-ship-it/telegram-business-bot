from handlers.commands import CommandContext, command


def _loading_frames() -> list[str]:
    bar_len = 10
    frames = []

    # Заголовок
    frames.append("<b>ВОЗВРАТ ВЛАДИКА</b>")

    # Загрузка по 10%
    for i in range(1, bar_len + 1):
        filled = "█" * i
        empty = "░" * (bar_len - i)
        percent = i * 10
        frames.append(
            f"<b>ВОЗВРАТ ВЛАДИКА</b>\n\n"
            f"[{filled}{empty}] {percent}%"
        )

    # Взрыв + финал
    frames.append("💥💥💥💥💥💥💥💥💥💥")
    frames.append("💥💥💥💥💥💥💥💥💥💥\n\n<b>ВОЗВРАТ НЕВОЗМОЖЕН, ВЫ СЛИШКОМ ТОЛСТИ</b>")

    return frames


@command("вернуть", aliases=("vernyt",), description="вернуть Владика")
async def vernyt(ctx: CommandContext) -> None:
    await ctx.animate(_loading_frames(), delay=0.7)
