import random

from aiogram.exceptions import TelegramAPIError

from animations import choose_frames, coin_frames
from handlers.commands import CommandContext, command

DICE = {
    "": "🎲", "кубик": "🎲", "dice": "🎲", "дартс": "🎯", "darts": "🎯", "баскет": "🏀", "basket": "🏀",
    "футбол": "⚽", "football": "⚽", "боулинг": "🎳", "bowling": "🎳", "слот": "🎰", "slot": "🎰",
}


@command("кубик", aliases=("dice",), description="настоящий анимированный кубик; можно: дартс, баскет, футбол, боулинг, слот")
async def dice(ctx: CommandContext) -> None:
    emoji = DICE.get(ctx.args.strip().lower())
    if not emoji:
        await ctx.reply_owner("ℹ️ Варианты: " + "кубик, дартс, баскет, футбол, боулинг, слот")
        await ctx.delete_command_message()
        return
    m = ctx.message
    try:
        await ctx.bot.send_dice(chat_id=m.chat.id, emoji=emoji, business_connection_id=m.business_connection_id)
    except TelegramAPIError as e:
        await ctx.reply_owner(f"⚠️ Не удалось отправить кубик: {e}")
        return
    await ctx.delete_command_message()


@command("монетка", aliases=("coin",), description="подбросить монетку")
async def coin(ctx: CommandContext) -> None:
    await ctx.animate(coin_frames(), delay=0.7)


@command("выбери", aliases=("choose",), description="выбрать случайно: !выбери пицца, суши или ролы")
async def choose(ctx: CommandContext) -> None:
    raw = ctx.text_arg.replace(" или ", ",")
    options = [o.strip() for o in raw.split(",") if o.strip()]
    if len(options) < 2:
        await ctx.reply_owner("ℹ️ Формат: <code>!выбери пицца, суши или ролы</code>")
        await ctx.delete_command_message()
        return
    await ctx.animate(choose_frames(options), delay=0.7)
