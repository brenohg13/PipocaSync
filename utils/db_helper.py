import sqlite3
import aiosqlite
from pathlib import Path

DB_FILE = Path("/home/ubuntu/torrent_telegram_bot/database.db")

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS uploads
                            (filename TEXT, message_id INTEGER, chat_id INTEGER, is_serie BOOLEAN)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS series_channels
                            (name TEXT PRIMARY KEY, chat_id INTEGER, invite_link TEXT)''')
        await db.commit()

async def save_upload(filename, message_id, chat_id, is_serie):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT INTO uploads VALUES (?, ?, ?, ?)", (filename, message_id, chat_id, is_serie))
        await db.commit()

async def get_all_uploads():
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT filename, message_id, chat_id, is_serie FROM uploads") as cursor:
            return await cursor.fetchall()

async def save_serie_channel(name, chat_id, invite_link):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT OR REPLACE INTO series_channels VALUES (?, ?, ?)", (name, chat_id, invite_link))
        await db.commit()

async def get_serie_channel(name):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT chat_id, invite_link FROM series_channels WHERE name = ?", (name,)) as cursor:
            row = await cursor.fetchone()
            return {"chat_id": row[0], "invite_link": row[1]} if row else None
