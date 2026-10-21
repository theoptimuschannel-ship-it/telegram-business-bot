"""Курс, погода, перевод — результат подставляется в чат вместо команды."""
import logging

from handlers.commands import CommandContext, command
from handlers.utils import esc, fetch_json

log = logging.getLogger(__name__)

CRYPTO = {
    "btc": "bitcoin", "eth": "ethereum", "ton": "the-open-network", "usdt": "tether",
    "sol": "solana", "bnb": "binancecoin", "xrp": "ripple", "doge": "dogecoin",
}


async def _fail(ctx: CommandContext, what: str) -> None:
    await ctx.reply_owner(f"⚠️ {what}")
    await ctx.delete_command_message()


@command("курс", aliases=("rate",), description="курс валют/крипты: !курс [usd eur btc ton ...]")
async def rate(ctx: CommandContext) -> None:
    codes = [c.lower() for c in ctx.args.replace(",", " ").split()] or ["usd", "eur", "btc", "eth"]
    fiat = [c for c in codes if c not in CRYPTO]
    crypto = [c for c in codes if c in CRYPTO]
    lines = []
    try:
        if fiat:
            data = (await fetch_json("https://www.cbr-xml-daily.ru/daily_json.js"))["Valute"]
            for c in fiat:
                v = data.get(c.upper())
                if v:
                    lines.append(f"💵 <b>{c.upper()}</b>: {v['Value'] / v['Nominal']:.2f} ₽")
                else:
                    lines.append(f"❔ {esc(c.upper())}: не найдено")
        if crypto:
            ids = ",".join(CRYPTO[c] for c in crypto)
            data = await fetch_json(
                "https://api.coingecko.com/api/v3/simple/price", ids=ids, vs_currencies="usd,rub"
            )
            for c in crypto:
                v = data.get(CRYPTO[c])
                if v:
                    lines.append(f"🪙 <b>{c.upper()}</b>: ${v['usd']:,.2f} · {v['rub']:,.0f} ₽")
    except Exception as e:
        log.warning("курс: %s", e)
        return await _fail(ctx, "Не удалось получить курс (сервис недоступен).")
    await ctx.say("📈 <b>Курс</b>\n" + "\n".join(lines))


def _weather(code: int) -> str:
    if code == 0:
        return "☀️ Ясно"
    if code == 1:
        return "🌤 Преимущественно ясно"
    if code == 2:
        return "⛅ Переменная облачность"
    if code == 3:
        return "☁️ Пасмурно"
    if code in (45, 48):
        return "🌫 Туман"
    if 51 <= code <= 57:
        return "🌦 Морось"
    if 61 <= code <= 67 or 80 <= code <= 82:
        return "🌧 Дождь"
    if 71 <= code <= 77 or code in (85, 86):
        return "🌨 Снег"
    if code >= 95:
        return "⛈ Гроза"
    return "🌡 Без осадков"


@command("погода", aliases=("weather",), description="погода: !погода Москва")
async def weather(ctx: CommandContext) -> None:
    city = ctx.text_arg
    if not city:
        return await _fail(ctx, "Формат: !погода Москва")
    try:
        geo = await fetch_json(
            "https://geocoding-api.open-meteo.com/v1/search", name=city, count=1, language="ru"
        )
        if not geo.get("results"):
            return await _fail(ctx, f"Город «{city}» не найден.")
        g = geo["results"][0]
        w = (await fetch_json(
            "https://api.open-meteo.com/v1/forecast",
            latitude=g["latitude"], longitude=g["longitude"], timezone="auto",
            current="temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
        ))["current"]
    except Exception as e:
        log.warning("погода: %s", e)
        return await _fail(ctx, "Не удалось получить погоду (сервис недоступен).")
    await ctx.say(
        f"{_weather(w['weather_code'])} — <b>{esc(g['name'])}</b>\n"
        f"🌡 {w['temperature_2m']:+.0f}° (ощущается {w['apparent_temperature']:+.0f}°)\n"
        f"💧 Влажность {w['relative_humidity_2m']}% · 💨 Ветер {w['wind_speed_10m']} км/ч"
    )


LANGS = {"ru", "en", "de", "fr", "es", "it", "pt", "uk", "pl", "tr", "zh", "ja", "ko", "ar"}


@command("перевод", aliases=("tr",), description="перевод: !перевод [en|ru|de...] текст (или ответом на сообщение)")
async def translate(ctx: CommandContext) -> None:
    first, _, rest = ctx.args.strip().partition(" ")
    target, text = (first.lower(), rest.strip()) if first.lower() in LANGS else (None, ctx.text_arg)
    if first.lower() in LANGS and not text:
        reply = ctx.message.reply_to_message
        text = ((reply.text or reply.caption or "") if reply else "").strip()
    if not text:
        return await _fail(ctx, "Формат: !перевод en привет (или ответом на сообщение)")
    if len(text) > 450:
        return await _fail(ctx, "Слишком длинный текст для перевода (максимум 450 символов).")
    cyr = any("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in text)
    src = "ru" if cyr else "en"
    target = target or ("en" if cyr else "ru")
    if target == src:
        src = "en" if target == "ru" else "ru"
    try:
        data = await fetch_json(
            "https://api.mymemory.translated.net/get", q=text, langpair=f"{src}|{target}"
        )
        result = data["responseData"]["translatedText"]
    except Exception as e:
        log.warning("перевод: %s", e)
        return await _fail(ctx, "Не удалось перевести (сервис недоступен).")
    await ctx.say(f"🌐 {src}→{target}\n{esc(text)}\n\n<b>{esc(result)}</b>")
