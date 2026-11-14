import random

from handlers.commands import CommandContext, command


def _loading_frames(success: bool) -> list[str]:
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

    # Финал
    if success:
        frames.append(
            "✨✨✨✨✨✨✨✨✨✨\n\n"
            "<b>ВОЗВРАТ УСПЕШЕН (ГАЛКА)</b>\n\n"
            "<b>ВЛАДИК ВЕРНЕТСЯ.</b>\n\n"
            "<b>ОЖИДАЙТЕ.</b> 🕊️"
        )
    else:
        frames.append("💥💥💥💥💥💥💥💥💥💥")
        frames.append(
            "💥💥💥💥💥💥💥💥💥💥\n\n"
            "<b>ВОЗВРАТ НЕВОЗМОЖЕН, ВЫ СЛИШКОМ ТОЛСТИ</b> 🐷"
        )

    return frames


@command("вернуть", aliases=("vernyt",), description="вернуть Владика")
async def vernyt(ctx: CommandContext) -> None:
    success = random.random() < 0.02  # 2% шанс успеха
    await ctx.animate(_loading_frames(success), delay=0.7)
