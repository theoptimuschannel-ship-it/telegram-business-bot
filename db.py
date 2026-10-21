from __future__ import annotations

import json
import logging
import os
import time

import aiosqlite

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS connections (
    id           TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL,
    user_chat_id INTEGER,
    is_enabled   INTEGER NOT NULL DEFAULT 1,
    rights       TEXT NOT NULL DEFAULT '{}',
    updated_at   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    chat_id         INTEGER NOT NULL,
    message_id      INTEGER NOT NULL,
    connection_id   TEXT,
    sender_id       INTEGER,
    sender_name     TEXT,
    sender_username TEXT,
    date            INTEGER NOT NULL,
    text            TEXT,
    media_type      TEXT,
    file_id         TEXT,
    reply_to        INTEGER,
    is_own          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date);
CREATE TABLE IF NOT EXISTS notes (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    text    TEXT NOT NULL,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    due  INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS muted_chats (
    chat_id INTEGER PRIMARY KEY,
    title   TEXT
);
CREATE TABLE IF NOT EXISTS autoreplies (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword  TEXT NOT NULL,
    response TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "notify_deleted": "1",
    "notify_edited": "1",
    "notify_own": "0",
    "ghost": "0",
    "away_enabled": "0",
    "away_text": "Привет! Сейчас я не на связи, отвечу позже.",
    "away_hours": "",
}


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "БД не открыта"
        return self._conn

    async def connect(self) -> None:
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.create_function("pylower", 1, lambda v: v.lower() if isinstance(v, str) else v)
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    # --- connections ---
    async def upsert_connection(
        self, conn_id: str, user_id: int, user_chat_id: int | None, is_enabled: bool, rights: dict
    ) -> None:
        await self.conn.execute(
            """INSERT INTO connections (id, user_id, user_chat_id, is_enabled, rights, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET user_id=excluded.user_id,
                 user_chat_id=excluded.user_chat_id, is_enabled=excluded.is_enabled,
                 rights=excluded.rights, updated_at=excluded.updated_at""",
            (conn_id, user_id, user_chat_id, int(is_enabled), json.dumps(rights), int(time.time())),
        )
        await self.conn.commit()

    async def get_connection(self, conn_id: str):
        async with self.conn.execute("SELECT * FROM connections WHERE id=?", (conn_id,)) as cur:
            return await cur.fetchone()

    async def list_connections(self):
        async with self.conn.execute("SELECT * FROM connections ORDER BY updated_at DESC") as cur:
            return await cur.fetchall()

    # --- messages ---
    async def save_message(self, rec: dict) -> None:
        await self.conn.execute(
            """INSERT OR REPLACE INTO messages
               (chat_id, message_id, connection_id, sender_id, sender_name, sender_username,
                date, text, media_type, file_id, reply_to, is_own)
               VALUES (:chat_id, :message_id, :connection_id, :sender_id, :sender_name,
                       :sender_username, :date, :text, :media_type, :file_id, :reply_to, :is_own)""",
            rec,
        )
        await self.conn.commit()

    async def get_message(self, chat_id: int, message_id: int):
        async with self.conn.execute(
            "SELECT * FROM messages WHERE chat_id=? AND message_id=?", (chat_id, message_id)
        ) as cur:
            return await cur.fetchone()

    async def get_messages(self, chat_id: int, ids: list[int]):
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        async with self.conn.execute(
            f"SELECT * FROM messages WHERE chat_id=? AND message_id IN ({marks}) ORDER BY message_id",
            (chat_id, *ids),
        ) as cur:
            return await cur.fetchall()

    async def count_messages(self) -> int:
        async with self.conn.execute("SELECT COUNT(*) FROM messages") as cur:
            return (await cur.fetchone())[0]

    async def cleanup(self, older_than_ts: int) -> int:
        cur = await self.conn.execute("DELETE FROM messages WHERE date < ?", (older_than_ts,))
        await self.conn.commit()
        return cur.rowcount

    # --- поиск по бэкапу ---
    async def find_chats(self, query: str):
        q = query.strip().lstrip("@").lower()
        async with self.conn.execute(
            """SELECT chat_id, sender_name, sender_username, MAX(date) AS last FROM messages
               WHERE is_own=0 AND (pylower(sender_name) LIKE ? OR pylower(sender_username) LIKE ?
                                   OR CAST(chat_id AS TEXT)=?)
               GROUP BY chat_id ORDER BY last DESC LIMIT 5""",
            (f"%{q}%", f"%{q}%", q),
        ) as cur:
            return await cur.fetchall()

    async def chat_messages(self, chat_id: int, limit: int = 20):
        async with self.conn.execute(
            "SELECT * FROM messages WHERE chat_id=? ORDER BY date DESC, message_id DESC LIMIT ?",
            (chat_id, limit),
        ) as cur:
            return list(reversed(await cur.fetchall()))

    async def search(self, word: str, limit: int = 20):
        async with self.conn.execute(
            """SELECT m.*, (SELECT sender_name FROM messages p WHERE p.chat_id=m.chat_id AND p.is_own=0
                            ORDER BY p.date DESC LIMIT 1) AS chat_name
               FROM messages m WHERE pylower(m.text) LIKE ? ORDER BY m.date DESC LIMIT ?""",
            (f"%{word.lower()}%", limit),
        ) as cur:
            return await cur.fetchall()

    async def export_rows(self, chat_id: int | None = None):
        sql = "SELECT * FROM messages" + (" WHERE chat_id=?" if chat_id is not None else "") + " ORDER BY date"
        async with self.conn.execute(sql, (chat_id,) if chat_id is not None else ()) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # --- заметки / напоминания ---
    async def add_note(self, text: str) -> int:
        cur = await self.conn.execute("INSERT INTO notes (text, created) VALUES (?, ?)", (text, int(time.time())))
        await self.conn.commit()
        return cur.lastrowid

    async def list_notes(self):
        async with self.conn.execute("SELECT * FROM notes ORDER BY id") as cur:
            return await cur.fetchall()

    async def delete_note(self, note_id: int) -> bool:
        cur = await self.conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
        await self.conn.commit()
        return cur.rowcount > 0

    async def add_reminder(self, due: int, text: str) -> int:
        cur = await self.conn.execute("INSERT INTO reminders (due, text) VALUES (?, ?)", (due, text))
        await self.conn.commit()
        return cur.lastrowid

    async def list_reminders(self):
        async with self.conn.execute("SELECT * FROM reminders ORDER BY due") as cur:
            return await cur.fetchall()

    async def due_reminders(self, now: int):
        async with self.conn.execute("SELECT * FROM reminders WHERE due<=? ORDER BY due", (now,)) as cur:
            return await cur.fetchall()

    async def delete_reminder(self, rid: int) -> bool:
        cur = await self.conn.execute("DELETE FROM reminders WHERE id=?", (rid,))
        await self.conn.commit()
        return cur.rowcount > 0

    # --- мьют чатов ---
    async def is_muted(self, chat_id: int) -> bool:
        async with self.conn.execute("SELECT 1 FROM muted_chats WHERE chat_id=?", (chat_id,)) as cur:
            return await cur.fetchone() is not None

    async def toggle_mute(self, chat_id: int, title: str) -> bool:
        """True — чат теперь в муте."""
        if await self.is_muted(chat_id):
            await self.conn.execute("DELETE FROM muted_chats WHERE chat_id=?", (chat_id,))
            muted = False
        else:
            await self.conn.execute("INSERT INTO muted_chats (chat_id, title) VALUES (?, ?)", (chat_id, title))
            muted = True
        await self.conn.commit()
        return muted

    async def list_muted(self):
        async with self.conn.execute("SELECT * FROM muted_chats") as cur:
            return await cur.fetchall()

    # --- автоответы по ключевым словам ---
    async def add_autoreply(self, keyword: str, response: str) -> int:
        cur = await self.conn.execute(
            "INSERT INTO autoreplies (keyword, response) VALUES (?, ?)", (keyword.lower(), response)
        )
        await self.conn.commit()
        return cur.lastrowid

    async def list_autoreplies(self):
        async with self.conn.execute("SELECT * FROM autoreplies ORDER BY id") as cur:
            return await cur.fetchall()

    async def delete_autoreply(self, rid: int) -> bool:
        cur = await self.conn.execute("DELETE FROM autoreplies WHERE id=?", (rid,))
        await self.conn.commit()
        return cur.rowcount > 0

    # --- settings / counters ---
    async def get_setting(self, key: str) -> str | None:
        async with self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
        return row[0] if row else DEFAULT_SETTINGS.get(key)

    async def get_bool(self, key: str) -> bool:
        return (await self.get_setting(key)) == "1"

    async def set_setting(self, key: str, value: str) -> None:
        await self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await self.conn.commit()

    async def toggle(self, key: str) -> bool:
        new = not await self.get_bool(key)
        await self.set_setting(key, "1" if new else "0")
        return new

    async def incr(self, key: str, n: int = 1) -> None:
        await self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+CAST(excluded.value AS INTEGER)",
            (key, str(n)),
        )
        await self.conn.commit()

    async def counter(self, key: str) -> int:
        async with self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0
