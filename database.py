import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection: sqlite3.Connection | None = None
        self.lock = asyncio.Lock()

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        async with self.lock:
            self.connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_guild ON messages(guild_id);
                CREATE TABLE IF NOT EXISTS settings (
                    guild_id INTEGER PRIMARY KEY,
                    reply_chance REAL NOT NULL DEFAULT 2,
                    bot_tone TEXT NOT NULL DEFAULT 'jokey'
                );
                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
                """
            )
            settings_columns = {
                str(row[1])
                for row in self.connection.execute("PRAGMA table_info(settings)").fetchall()
            }
            if "bot_tone" not in settings_columns:
                self.connection.execute(
                    "ALTER TABLE settings ADD COLUMN bot_tone TEXT NOT NULL DEFAULT 'jokey'"
                )
            self.connection.commit()

    async def close(self) -> None:
        if self.connection:
            async with self.lock:
                self.connection.close()
                self.connection = None

    async def save_message(self, guild_id: int, channel_id: int, text: str) -> None:
        if not self.connection:
            return
        async with self.lock:
            self.connection.execute(
                "INSERT INTO messages(guild_id, channel_id, text, timestamp) VALUES (?, ?, ?, ?)",
                (guild_id, channel_id, text, datetime.now(timezone.utc).isoformat()),
            )
            self.connection.commit()

    async def save_image(self, guild_id: int, url: str) -> None:
        if not self.connection:
            return
        async with self.lock:
            self.connection.execute(
                "INSERT INTO images(guild_id, url, timestamp) VALUES (?, ?, ?)",
                (guild_id, url, datetime.now(timezone.utc).isoformat()),
            )
            self.connection.commit()

    async def get_messages(self, guild_id: int, limit: int = 5000) -> list[str]:
        if not self.connection:
            return []
        async with self.lock:
            rows = self.connection.execute(
                "SELECT text FROM messages WHERE guild_id = ? ORDER BY id DESC LIMIT ?",
                (guild_id, limit),
            ).fetchall()
        return [str(row["text"]) for row in reversed(rows)]

    async def get_chance(self, guild_id: int, default: float) -> float:
        if not self.connection:
            return default
        async with self.lock:
            row = self.connection.execute(
                "SELECT reply_chance FROM settings WHERE guild_id = ?", (guild_id,)
            ).fetchone()
        return float(row["reply_chance"]) if row else default

    async def get_tone(self, guild_id: int, default: str = "jokey") -> str:
        if not self.connection:
            return default
        async with self.lock:
            row = self.connection.execute(
                "SELECT bot_tone FROM settings WHERE guild_id = ?", (guild_id,)
            ).fetchone()
        return str(row["bot_tone"]) if row else default

    async def set_chance(self, guild_id: int, value: float) -> None:
        if not self.connection:
            return
        async with self.lock:
            self.connection.execute(
                "INSERT INTO settings(guild_id, reply_chance, bot_tone) VALUES (?, ?, COALESCE((SELECT bot_tone FROM settings WHERE guild_id = ?), 'jokey')) "
                "ON CONFLICT(guild_id) DO UPDATE SET reply_chance = excluded.reply_chance",
                (guild_id, value, guild_id),
            )
            self.connection.commit()

    async def set_tone(self, guild_id: int, value: str) -> None:
        tone = value.lower()
        if tone not in {"jokey", "toxic", "friendly"}:
            tone = "jokey"
        if not self.connection:
            return
        async with self.lock:
            self.connection.execute(
                "INSERT INTO settings(guild_id, reply_chance, bot_tone) VALUES (?, 2, ?) "
                "ON CONFLICT(guild_id) DO UPDATE SET bot_tone = excluded.bot_tone",
                (guild_id, tone),
            )
            self.connection.commit()
