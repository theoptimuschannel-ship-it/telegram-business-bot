from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    owner_id: int
    retention_days: int
    tz: ZoneInfo
    anim_delay: float
    db_path: str
    log_file: str


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    owner = os.getenv("OWNER_ID", "").strip()
    if not token or not owner.lstrip("-").isdigit():
        raise RuntimeError("Заполните BOT_TOKEN и OWNER_ID в .env (см. .env.example)")
    return Settings(
        bot_token=token,
        owner_id=int(owner),
        retention_days=int(os.getenv("RETENTION_DAYS", "30")),
        tz=ZoneInfo(os.getenv("TIMEZONE", "UTC")),
        anim_delay=max(0.6, float(os.getenv("ANIM_DELAY", "0.8"))),
        db_path=os.getenv("DB_PATH", "data/bot.db"),
        log_file=os.getenv("LOG_FILE", "data/logs/bot.log"),
    )
