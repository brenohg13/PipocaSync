import re

with open("/home/ubuntu/torrent_telegram_bot/torrent_bot.py", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Update DOWNLOAD_DIR to RAM disk
code = code.replace(
    'DOWNLOAD_DIR = BASE_DIR / "downloads"',
    'DOWNLOAD_DIR = Path("/mnt/ramdisk/downloads")'
)

# 2. Add dependencies right after module imports
code = code.replace(
    'import libtorrent as lt',
    'import libtorrent as lt\nfrom utils.tmdb_helper import init_tmdb, get_metadata\nfrom utils.video_helper import get_video_metadata, generate_thumbnail\nfrom utils.db_helper import init_db, save_upload, get_all_uploads'
)

# 3. Add send_video with streaming capabilities in process_torrent
old_send = '''            if poster_url:
                await client.send_photo(chat_id=destino_upload, photo=poster_url, caption=caption)
                # O documento vai sem legenda para não repetir, ou com legenda simplificada
                await client.send_document(
                    chat_id=destino_upload,
                    document=str(fpath),
                    caption=f"🎥 **Arquivo:** `{new_name}`",
                    progress=progress_for_pyrogram,
                    progress_args=(upload_msg, new_name, "Enviando pro Canal")
                )
            else:
                await client.send_document(
                    chat_id=destino_upload,
                    document=str(fpath),
                    caption=caption,
                    progress=progress_for_pyrogram,
                    progress_args=(upload_msg, new_name, "Enviando pro Canal")
                )'''

streaming_send = '''            # Gerar thumbnail e infos do FFmpeg
            await upload_msg.edit_text(f"⏳ Processando metadados de vídeo para streaming...")
            duration, width, height = await get_video_metadata(fpath)
            thumb_path = await generate_thumbnail(fpath, f"{fpath}.jpg")
            
            if poster_url:
                await client.send_photo(chat_id=destino_upload, photo=poster_url, caption=caption)
                
            sent_msg = await client.send_video(
                chat_id=destino_upload,
                video=str(fpath),
                caption=caption if not poster_url else f"🎥 **Arquivo:** `{new_name}`",
                duration=duration,
                width=width,
                height=height,
                thumb=thumb_path,
                supports_streaming=True,
                progress=progress_for_pyrogram,
                progress_args=(upload_msg, new_name, "Enviando Vídeo (Streaming)")
            )
            
            # DB LOG
            await save_upload(new_name, sent_msg.id, destino_upload, is_serie=False)  # Melhorar detecção de série dps
            
            if thumb_path and os.path.exists(thumb_path):
                os.remove(thumb_path)'''

code = code.replace(old_send, streaming_send)

# 4. Initialize DB at startup
code = code.replace(
    'await app.start()',
    'await app.start()\n    await init_db()'
)

with open("/home/ubuntu/torrent_telegram_bot/torrent_bot.py", "w", encoding="utf-8") as f:
    f.write(code)

