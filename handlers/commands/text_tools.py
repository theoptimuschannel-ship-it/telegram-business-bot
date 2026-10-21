from __future__ import annotations
"""Команды, которые переписывают текст сообщения: форматирование, раскладка, шрифты."""
from handlers.commands import CommandContext, command
from handlers.utils import esc

USAGE = "ℹ️ Напишите текст после команды или ответьте командой на сообщение."


async def _wrap(ctx: CommandContext, fmt: str) -> None:
    text = ctx.text_arg
    if not text:
        await ctx.reply_owner(USAGE)
        await ctx.delete_command_message()
        return
    await ctx.say(fmt.format(esc(text)))


@command("жирный", aliases=("bold",), description="сделать текст жирным")
async def bold(ctx: CommandContext) -> None:
    await _wrap(ctx, "<b>{}</b>")


@command("курсив", aliases=("italic",), description="сделать текст курсивом")
async def italic(ctx: CommandContext) -> None:
    await _wrap(ctx, "<i>{}</i>")


@command("код", aliases=("code",), description="моноширинный текст")
async def code(ctx: CommandContext) -> None:
    await _wrap(ctx, "<code>{}</code>")


@command("спойлер", aliases=("spoiler",), description="скрыть текст под спойлер")
async def spoiler(ctx: CommandContext) -> None:
    await _wrap(ctx, "<tg-spoiler>{}</tg-spoiler>")


# ---------- перевернуть ----------
_FLIP = dict(zip(
    "abcdefghijklmnopqrstuvwxyz.,?!'",
    "ɐqɔpǝɟƃɥᴉɾʞlɯuodbɹsʇnʌʍxʎz˙'¿¡,",
))


@command("переверни", aliases=("flip",), description="перевернуть текст вверх ногами (латиница)")
async def flip(ctx: CommandContext) -> None:
    text = ctx.text_arg
    if not text:
        await ctx.reply_owner(USAGE)
        await ctx.delete_command_message()
        return
    await ctx.say(esc("".join(_FLIP.get(ch.lower(), ch) for ch in reversed(text))))


# ---------- транслит ----------
_TR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "zh", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y",
    "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


@command("транслит", aliases=("translit",), description="кириллица → латиница (privet)")
async def translit(ctx: CommandContext) -> None:
    text = ctx.text_arg
    if not text:
        await ctx.reply_owner(USAGE)
        await ctx.delete_command_message()
        return
    out = []
    for ch in text:
        t = _TR.get(ch.lower())
        out.append(ch if t is None else (t.capitalize() if ch.isupper() else t))
    await ctx.say(esc("".join(out)))


# ---------- неверная раскладка ----------
_EN = "qwertyuiop[]asdfghjkl;'zxcvbnm,./`QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>?~"
_RU = "йцукенгшщзхъфывапролджэячсмитьбю.ёЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,Ё"
assert len(_EN) == len(_RU)
_EN2RU = dict(zip(_EN, _RU))
_RU2EN = dict(zip(_RU, _EN))


@command("раскладка", aliases=("layout",), description="исправить текст, набранный не в той раскладке")
async def layout(ctx: CommandContext) -> None:
    text = ctx.text_arg
    if not text:
        await ctx.reply_owner(USAGE)
        await ctx.delete_command_message()
        return
    cyr = sum(1 for ch in text if ch in _RU2EN)
    table = _RU2EN if cyr > len(text) / 3 else _EN2RU
    await ctx.say(esc("".join(table.get(ch, ch) for ch in text)))


# ---------- шрифты ----------
def _alpha(upper: int, lower: int, digits: int | None = None):
    m = {chr(65 + i): chr(upper + i) for i in range(26)}
    m.update({chr(97 + i): chr(lower + i) for i in range(26)})
    if digits:
        m.update({str(i): chr(digits + i) for i in range(10)})
    return m


FONTS = {
    "bold": _alpha(0x1D400, 0x1D41A, 0x1D7CE),
    "bolditalic": _alpha(0x1D468, 0x1D482),
    "script": _alpha(0x1D4D0, 0x1D4EA),
    "gothic": _alpha(0x1D56C, 0x1D586),
    "sans": _alpha(0x1D5A0, 0x1D5BA, 0x1D7E2),
    "mono": _alpha(0x1D670, 0x1D68A, 0x1D7F6),
    "circle": _alpha(0x24B6, 0x24D0),
    "wide": _alpha(0xFF21, 0xFF41, 0xFF10),
}
FONT_ALIASES = {"жирный": "bold", "рукопись": "script", "готика": "gothic", "кружки": "circle", "широкий": "wide", "моно": "mono"}


def _apply(font: str, text: str) -> str:
    return "".join(FONTS[font].get(ch, ch) for ch in text)


@command("шрифт", aliases=("font",), description="красивый шрифт (латиница): !шрифт текст — примеры в бота; !шрифт стиль текст — в чат")
async def font(ctx: CommandContext) -> None:
    first, _, rest = ctx.args.strip().partition(" ")
    name = FONT_ALIASES.get(first.lower(), first.lower())
    if name in FONTS and rest.strip():
        await ctx.say(esc(_apply(name, rest.strip())))
        return
    text = ctx.text_arg
    if not text:
        await ctx.reply_owner(USAGE)
    else:
        lines = [f"<code>{n}</code>: {esc(_apply(n, text))}" for n in FONTS]
        await ctx.reply_owner("🔤 Выберите стиль и повторите: <code>!шрифт стиль текст</code>\n\n" + "\n".join(lines))
    await ctx.delete_command_message()
