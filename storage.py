import sqlite3
import os

DB_PATH = os.getenv("DB_PATH", "channels.db")


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                channel_id INTEGER PRIMARY KEY,
                chat_url   TEXT NOT NULL
            )
        """)
        conn.commit()


def get_channels() -> dict[int, str]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT channel_id, chat_url FROM channels"
        ).fetchall()
    return {row[0]: row[1] for row in rows}


def add_channel(channel_id: int, chat_url: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO channels (channel_id, chat_url) VALUES (?, ?)",
            (channel_id, chat_url),
        )
        conn.commit()


def remove_channel(channel_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "DELETE FROM channels WHERE channel_id = ?", (channel_id,)
        )
        conn.commit()
    return cur.rowcount > 0
