from __future__ import annotations

import json
import logging
import os
import time

import aiosqlite

log = logging.getLogger(__name__)

# Все пользовательские данные привязаны к uid — Telegram ID владельца бизнес-аккаунта.
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    name        TEXT,
    username    TEXT,
    added_at    INTEGER NOT NULL,
    accepted    INTEGER NOT NULL DEFAULT 0,
    accepted_at INTEGER
);
CREATE TABLE IF NOT EXISTS connections (
    id           TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL,
    user_chat_id INTEGER,
    is_enabled   INTEGER NOT NULL DEFAULT 1,
    rights       TEXT NOT NULL DEFAULT '{}',
    updated_at   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    uid             INTEGER NOT NULL,
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
    PRIMARY KEY (uid, chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date);
CREATE TABLE IF NOT EXISTS notes (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    uid     INTEGER NOT NULL,
    text    TEXT NOT NULL,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    uid  INTEGER NOT NULL,
    due  INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS muted_chats (
    uid     INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    title   TEXT,
    PRIMARY KEY (uid, chat_id)
);
CREATE TABLE IF NOT EXISTS autoreplies (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    uid      INTEGER NOT NULL,
    keyword  TEXT NOT NULL,
    response TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    uid   INTEGER NOT NULL,
    key   TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (uid, key)
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

USER_TABLES = ("messages", "notes", "reminders", "muted_chats", "autoreplies", "settings")


class Database:
    def __init__(self, path: str, admin_id: int):
        self.path = path
        self.admin_id = admin_id
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
        await self._migrate_legacy()
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _migrate_legacy(self) -> None:
        """Одиночная версия бота → многопользовательская: все данные уходят администратору."""
        async with self.conn.execute("PRAGMA table_info(messages)") as cur:
            cols = {r["name"] for r in await cur.fetchall()}
        if not cols or "uid" in cols:
            return
        log.info("Миграция БД на многопользовательскую схему (владелец %s)", self.admin_id)
        c = self.conn
        await c.execute("DROP INDEX IF EXISTS idx_messages_date")
        for t in USER_TABLES:
            await c.execute(f"ALTER TABLE {t} RENAME TO {t}_old")
        await c.executescript(SCHEMA)
        a = self.admin_id
        await c.execute(
            """INSERT INTO messages (uid, chat_id, message_id, connection_id, sender_id, sender_name,
                 sender_username, date, text, media_type, file_id, reply_to, is_own)
               SELECT ?, chat_id, message_id, connection_id, sender_id, sender_name, sender_username,
                 date, text, media_type, file_id, reply_to, is_own FROM messages_old""", (a,))
        await c.execute("INSERT INTO notes (id, uid, text, created) SELECT id, ?, text, created FROM notes_old", (a,))
        await c.execute("INSERT INTO reminders (id, uid, due, text) SELECT id, ?, due, text FROM reminders_old", (a,))
        await c.execute("INSERT INTO muted_chats (uid, chat_id, title) SELECT ?, chat_id, title FROM muted_chats_old", (a,))
        await c.execute("INSERT INTO autoreplies (id, uid, keyword, response) SELECT id, ?, keyword, response FROM autoreplies_old", (a,))
        await c.execute("INSERT INTO settings (uid, key, value) SELECT ?, key, value FROM settings_old", (a,))
        for t in USER_TABLES:
            await c.execute(f"DROP TABLE {t}_old")
        await c.commit()

    # --- пользователи и доступ ---
    async def get_user(self, user_id: int):
        async with self.conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as cur:
            return await cur.fetchone()

    async def add_user(self, user_id: int) -> bool:
        """True — добавлен, False — уже был в списке."""
        cur = await self.conn.execute(
            "INSERT OR IGNORE INTO users (user_id, added_at) VALUES (?, ?)", (user_id, int(time.time()))
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def accept_user(self, user_id: int, name: str | None, username: str | None) -> None:
        await self.conn.execute(
            "UPDATE users SET accepted=1, accepted_at=?, name=?, username=? WHERE user_id=?",
            (int(time.time()), name, username, user_id),
        )
        await self.conn.commit()

    async def is_allowed(self, user_id: int | None) -> bool:
        """Администратор или пользователь, которого добавили и который согласился с условиями."""
        if user_id is None:
            return False
        if user_id == self.admin_id:
            return True
        row = await self.get_user(user_id)
        return bool(row and row["accepted"])

    async def list_users(self):
        async with self.conn.execute("SELECT * FROM users ORDER BY added_at") as cur:
            return await cur.fetchall()

    async def wipe_user_data(self, uid: int) -> None:
        for t in USER_TABLES:
            await self.conn.execute(f"DELETE FROM {t} WHERE uid=?", (uid,))
        await self.conn.execute("DELETE FROM connections WHERE user_id=?", (uid,))
        await self.conn.commit()

    async def remove_user(self, uid: int) -> None:
        await self.wipe_user_data(uid)
        await self.conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
        await self.conn.commit()

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

    async def list_connections(self, uid: int):
        async with self.conn.execute(
            "SELECT * FROM connections WHERE user_id=? ORDER BY updated_at DESC", (uid,)
        ) as cur:
            return await cur.fetchall()

    # --- messages ---
    async def save_message(self, rec: dict) -> None:
        await self.conn.execute(
            """INSERT OR REPLACE INTO messages
               (uid, chat_id, message_id, connection_id, sender_id, sender_name, sender_username,
                date, text, media_type, file_id, reply_to, is_own)
               VALUES (:uid, :chat_id, :message_id, :connection_id, :sender_id, :sender_name,
                       :sender_username, :date, :text, :media_type, :file_id, :reply_to, :is_own)""",
            rec,
        )
        await self.conn.commit()

    async def get_message(self, uid: int, chat_id: int, message_id: int):
        async with self.conn.execute(
            "SELECT * FROM messages WHERE uid=? AND chat_id=? AND message_id=?", (uid, chat_id, message_id)
        ) as cur:
            return await cur.fetchone()

    async def get_messages(self, uid: int, chat_id: int, ids: list[int]):
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        async with self.conn.execute(
            f"SELECT * FROM messages WHERE uid=? AND chat_id=? AND message_id IN ({marks}) ORDER BY message_id",
            (uid, chat_id, *ids),
        ) as cur:
            return await cur.fetchall()

    async def count_messages(self, uid: int | None = None) -> int:
        sql, args = ("SELECT COUNT(*) FROM messages WHERE uid=?", (uid,)) if uid is not None else (
            "SELECT COUNT(*) FROM messages", ())
        async with self.conn.execute(sql, args) as cur:
            return (await cur.fetchone())[0]

    async def cleanup(self, older_than_ts: int) -> int:
        cur = await self.conn.execute("DELETE FROM messages WHERE date < ?", (older_than_ts,))
        await self.conn.commit()
        return cur.rowcount

    # --- поиск по бэкапу ---
    async def find_chats(self, uid: int, query: str):
        q = query.strip().lstrip("@").lower()
        async with self.conn.execute(
            """SELECT chat_id, sender_name, sender_username, MAX(date) AS last FROM messages
               WHERE uid=? AND is_own=0 AND (pylower(sender_name) LIKE ? OR pylower(sender_username) LIKE ?
                                   OR CAST(chat_id AS TEXT)=?)
               GROUP BY chat_id ORDER BY last DESC LIMIT 5""",
            (uid, f"%{q}%", f"%{q}%", q),
        ) as cur:
            return await cur.fetchall()

    async def chat_messages(self, uid: int, chat_id: int, limit: int = 20):
        async with self.conn.execute(
            "SELECT * FROM messages WHERE uid=? AND chat_id=? ORDER BY date DESC, message_id DESC LIMIT ?",
            (uid, chat_id, limit),
        ) as cur:
            return list(reversed(await cur.fetchall()))

    async def search(self, uid: int, word: str, limit: int = 20):
        async with self.conn.execute(
            """SELECT m.*, (SELECT sender_name FROM messages p WHERE p.uid=m.uid AND p.chat_id=m.chat_id
                            AND p.is_own=0 ORDER BY p.date DESC LIMIT 1) AS chat_name
               FROM messages m WHERE m.uid=? AND pylower(m.text) LIKE ? ORDER BY m.date DESC LIMIT ?""",
            (uid, f"%{word.lower()}%", limit),
        ) as cur:
            return await cur.fetchall()

    async def export_rows(self, uid: int, chat_id: int | None = None):
        sql = "SELECT * FROM messages WHERE uid=?" + (" AND chat_id=?" if chat_id is not None else "") + " ORDER BY date"
        args = (uid, chat_id) if chat_id is not None else (uid,)
        async with self.conn.execute(sql, args) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # --- заметки / напоминания ---
    async def add_note(self, uid: int, text: str) -> int:
        cur = await self.conn.execute(
            "INSERT INTO notes (uid, text, created) VALUES (?, ?, ?)", (uid, text, int(time.time()))
        )
        await self.conn.commit()
        return cur.lastrowid

    async def list_notes(self, uid: int):
        async with self.conn.execute("SELECT * FROM notes WHERE uid=? ORDER BY id", (uid,)) as cur:
            return await cur.fetchall()

    async def delete_note(self, uid: int, note_id: int) -> bool:
        cur = await self.conn.execute("DELETE FROM notes WHERE id=? AND uid=?", (note_id, uid))
        await self.conn.commit()
        return cur.rowcount > 0

    async def add_reminder(self, uid: int, due: int, text: str) -> int:
        cur = await self.conn.execute("INSERT INTO reminders (uid, due, text) VALUES (?, ?, ?)", (uid, due, text))
        await self.conn.commit()
        return cur.lastrowid

    async def list_reminders(self, uid: int):
        async with self.conn.execute("SELECT * FROM reminders WHERE uid=? ORDER BY due", (uid,)) as cur:
            return await cur.fetchall()

    async def due_reminders(self, now: int):
        """Для всех пользователей: цикл напоминаний."""
        async with self.conn.execute("SELECT * FROM reminders WHERE due<=? ORDER BY due", (now,)) as cur:
            return await cur.fetchall()

    async def delete_reminder(self, uid: int | None, rid: int) -> bool:
        if uid is None:
            cur = await self.conn.execute("DELETE FROM reminders WHERE id=?", (rid,))
        else:
            cur = await self.conn.execute("DELETE FROM reminders WHERE id=? AND uid=?", (rid, uid))
        await self.conn.commit()
        return cur.rowcount > 0

    # --- мьют чатов ---
    async def is_muted(self, uid: int, chat_id: int) -> bool:
        async with self.conn.execute(
            "SELECT 1 FROM muted_chats WHERE uid=? AND chat_id=?", (uid, chat_id)
        ) as cur:
            return await cur.fetchone() is not None

    async def toggle_mute(self, uid: int, chat_id: int, title: str) -> bool:
        """True — чат теперь в муте."""
        if await self.is_muted(uid, chat_id):
            await self.conn.execute("DELETE FROM muted_chats WHERE uid=? AND chat_id=?", (uid, chat_id))
            muted = False
        else:
            await self.conn.execute(
                "INSERT INTO muted_chats (uid, chat_id, title) VALUES (?, ?, ?)", (uid, chat_id, title)
            )
            muted = True
        await self.conn.commit()
        return muted

    async def list_muted(self, uid: int):
        async with self.conn.execute("SELECT * FROM muted_chats WHERE uid=?", (uid,)) as cur:
            return await cur.fetchall()

    # --- автоответы по ключевым словам ---
    async def add_autoreply(self, uid: int, keyword: str, response: str) -> int:
        cur = await self.conn.execute(
            "INSERT INTO autoreplies (uid, keyword, response) VALUES (?, ?, ?)", (uid, keyword.lower(), response)
        )
        await self.conn.commit()
        return cur.lastrowid

    async def list_autoreplies(self, uid: int):
        async with self.conn.execute("SELECT * FROM autoreplies WHERE uid=? ORDER BY id", (uid,)) as cur:
            return await cur.fetchall()

    async def delete_autoreply(self, uid: int, rid: int) -> bool:
        cur = await self.conn.execute("DELETE FROM autoreplies WHERE id=? AND uid=?", (rid, uid))
        await self.conn.commit()
        return cur.rowcount > 0

    # --- settings / counters ---
    async def get_setting(self, uid: int, key: str) -> str | None:
        async with self.conn.execute("SELECT value FROM settings WHERE uid=? AND key=?", (uid, key)) as cur:
            row = await cur.fetchone()
        return row[0] if row else DEFAULT_SETTINGS.get(key)

    async def get_bool(self, uid: int, key: str) -> bool:
        return (await self.get_setting(uid, key)) == "1"

    async def set_setting(self, uid: int, key: str, value: str) -> None:
        await self.conn.execute(
            "INSERT INTO settings (uid, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(uid, key) DO UPDATE SET value=excluded.value",
            (uid, key, value),
        )
        await self.conn.commit()

    async def toggle(self, uid: int, key: str) -> bool:
        new = not await self.get_bool(uid, key)
        await self.set_setting(uid, key, "1" if new else "0")
        return new

    async def incr(self, uid: int, key: str, n: int = 1) -> None:
        await self.conn.execute(
            "INSERT INTO settings (uid, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(uid, key) DO UPDATE SET value=CAST(value AS INTEGER)+CAST(excluded.value AS INTEGER)",
            (uid, key, str(n)),
        )
        await self.conn.commit()

    async def counter(self, uid: int, key: str) -> int:
        async with self.conn.execute("SELECT value FROM settings WHERE uid=? AND key=?", (uid, key)) as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0
