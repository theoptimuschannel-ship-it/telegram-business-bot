import animations
from handlers.commands import CommandContext, command


@command("стоп", aliases=("stop",), description="остановить идущую в этом чате анимацию")
async def stop(ctx: CommandContext) -> None:
    if not animations.request_stop(ctx.message.business_connection_id, ctx.message.chat.id):
        await ctx.reply_owner("ℹ️ В этом чате нет идущей анимации.")
    await ctx.delete_command_message()
