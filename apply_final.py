import re

with open('/home/ubuntu/torrent_telegram_bot/utils/tmdb_helper.py', 'r') as f:
    tmdb_content = f.read()

new_clean = r"""def clean_filename(filename):
    from pathlib import Path
    import re
    name = Path(filename).stem
    
    name = re.sub(r'\[.*?\]|\(.*?\)', ' ', name)
    name = re.sub(r'(1080p|720p|2160p|4k|HDR)', '', name, flags=re.IGNORECASE)
    name = re.sub(r'(WEBRip|Bluray|BDRip|WEB-DL|WEB|x264|x265|HEVC|Dublado|Legendado|Dual|Audio|DDP5\.1|H\.?264)', '', name, flags=re.IGNORECASE)
    name = re.sub(r'-[a-zA-Z0-9_]+$', '', name)
    
    name = name.replace('.', ' ').replace('_', ' ').replace('-', ' ')
    name = re.sub(r'\s+', ' ', name).strip()
    
    year_match = re.search(r'(19\d{2}|20\d{2})', name)
    year = year_match.group(1) if year_match else None
    name = re.sub(r'(19\d{2}|20\d{2})', '', name).strip()

    return name, year"""

tmdb_content = re.sub(r'def clean_filename\(filename\):.*?(?=def get_metadata)', lambda m: new_clean + '\n\n', tmdb_content, flags=re.DOTALL)

with open('/home/ubuntu/torrent_telegram_bot/utils/tmdb_helper.py', 'w') as f:
    f.write(tmdb_content)

with open('/home/ubuntu/torrent_telegram_bot/torrent_bot.py', 'r') as f:
    bot_content = f.read()

bot_content = re.sub(r'# ================= NOVO PACOTE DE COMANDOS ADMINISTRATIVOS =================.*?# ===========================================================================', '', bot_content, flags=re.DOTALL)

new_progress = r"""async def progress_for_pyrogram(current, total, status_msg, file_name, prefix="", start_time=None):
    import time
    now = time.time()
    if not hasattr(progress_for_pyrogram, "last_update"):
        progress_for_pyrogram.last_update = now

    if (now - progress_for_pyrogram.last_update) > 3 or current == total:
        percent = (current / total) * 100 if total > 0 else 0
        
        if start_time:
            diff = now - start_time
            speed = (current / diff) if diff > 0 else 0
            speed_str = f"{format_bytes(speed)}/s"
        else:
            speed_str = "Calculando..."

        text = f"☁️ **{prefix}**\n\n**Arquivo:** `{file_name}`\n**Progresso:** {percent:.1f}% ({format_bytes(current)} / {format_bytes(total)})\n🚀 **Velocidade Upload:** {speed_str}"
        try:
            await status_msg.edit_text(text)
            progress_for_pyrogram.last_update = now
        except Exception: pass
"""
bot_content = re.sub(r'async def progress_for_pyrogram\(.*?except Exception: pass', lambda m: new_progress, bot_content, flags=re.DOTALL)

bot_content = bot_content.replace('progress_args=(upload_msg, new_name, "Enviando Vídeo (Streaming)")', 'progress_args=(upload_msg, new_name, "Enviando Vídeo (Streaming)", time.time())')

clonar_str = r"""
@app.on_message(filters.command("entrar", prefixes="/") & filters.me)
async def entrar_command(client, message):
    if len(message.command) < 2: return await message.reply("Uso: `/entrar t.me/+LinkConvite`")
    link = message.command[1]
    msg = await message.reply("⏳ Tentando entrar no grupo/canal...")
    try:
        chat = await client.join_chat(link)
        await msg.edit_text(f"✅ **Sucesso!** O bot agora é membro de: **{chat.title}**\nVocê já pode usar `/clonar` para os links de lá.")
    except Exception as e:
        await msg.edit_text(f"❌ **Erro ao entrar:** {e}")

@app.on_message(filters.command("clonar", prefixes="/") & filters.me)
async def clonar_command(client, message):
    if len(message.command) < 2: return await message.reply("Uso: `/clonar https://t.me/c/12345/678`")
    link = message.command[1].rstrip('/')
    parts = link.split('/')
    msg = await message.reply("🕵️‍♂️ **Pescando Arquivo [Clone Ninja]...**")
    
    try:
        msg_id = int(parts[-1])
        if '/c/' in link:
            chat_id = int(f"-100{parts[-2]}")
        else:
            chat_id = parts[-2]
            
        target = await client.get_messages(chat_id, msg_id)
        if not target or (not target.video and not target.document):
            return await msg.edit_text("❌ Nenhum vídeo encontrado no link.")
            
        import time
        start_dl = time.time()
        file_path = await target.download(file_name=str(DOWNLOAD_DIR) + "/", progress=progress_for_pyrogram, progress_args=(msg, "Clone.mp4", "📥 Baixando (Telegram -> RAM)", start_dl))
        
        if file_path:
            await msg.edit_text("✅ Arquivo clonado p/ VPS! Enviando para o processador TMDB...")
            from utils.video_helper import get_video_metadata, generate_thumbnail
            from utils.tmdb_helper import get_metadata
            import os
            
            f_name = os.path.basename(file_path)
            new_name = smart_rename(f_name)
            new_path = Path(file_path).parent / new_name
            if file_path != str(new_path):
                os.rename(file_path, str(new_path))
            
            clean_title, year, _ = extract_metadata(new_name)
            tmdb_data = await fetch_tmdb_data(clean_title)
            
            if tmdb_data:
                final_title = tmdb_data['title']
                overview = tmdb_data['overview']
                poster_url = tmdb_data['poster']
            else:
                final_title = clean_title; overview = "Nenhuma sinopse"; poster_url = None
                
            caption = f"🎬 **{final_title}**\n📝 **Sinopse:** {overview}\n\n🤖 *Acervo VIP*"
            
            await msg.edit_text("☁️ **Subindo pro Canal VIP...**")
            duration, w, h = await get_video_metadata(str(new_path))
            thumb_path = await generate_thumbnail(str(new_path), f"{new_path}.jpg")
            
            if poster_url:
                await client.send_photo(chat_id=destino_upload, photo=poster_url, caption=caption)
                
            sent_msg = await client.send_video(
                chat_id=destino_upload,
                video=str(new_path),
                caption=f"🎥 **Clone:** `{new_name}`",
                duration=duration, width=w, height=h, thumb=thumb_path,
                supports_streaming=True,
                progress=progress_for_pyrogram, progress_args=(msg, new_name, "Enviando Vídeo Ninja", time.time())
            )
            
            from utils.db_helper import save_upload
            await save_upload(new_name, sent_msg.id, destino_upload, is_serie=False)
            
            await msg.edit_text("✅ **Clone Finalizado Supremo!**\nPego de grupo externo e upado localmente blindado.")
            try:
                os.remove(new_path)
                if thumb_path and os.path.exists(thumb_path): os.remove(thumb_path)
            except: pass
            
    except Exception as e:
        await msg.edit_text(f"❌ Erro Clone Ninja: {e}")
"""

bot_content = bot_content.replace('# ================= COMANDOS TELEGRAM =================', '# ================= COMANDOS TELEGRAM =================\n' + clonar_str)

with open('/home/ubuntu/torrent_telegram_bot/torrent_bot.py', 'w') as f:
    f.write(bot_content)

