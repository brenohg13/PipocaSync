import re
import os

def update_tmdb_helper():
    TMDB_PATH = "/home/ubuntu/torrent_telegram_bot/utils/tmdb_helper.py"
    with open(TMDB_PATH, "r") as f:
        content = f.read()

    new_clean = r"""
def clean_filename(filename):
    \"\"\"Limpa o nome do arquivo para melhorar a busca no TMDB\"\"\"
    name = Path(filename).stem
    
    # Remove colchetes e parenteses ex: [RARBG], (2023)
    name = re.sub(r'\[.*?\]|\(.*?\)', ' ', name)
    
    # Remove resoluções
    name = re.sub(r'(1080p|720p|2160p|4k|HDR)', '', name, flags=re.IGNORECASE)
    # Remove tags comuns de release
    name = re.sub(r'(WEBRip|Bluray|BDRip|WEB-DL|WEB|x264|x265|HEVC|Dublado|Legendado|Dual|Audio|DDP5\.1|H\.?264)', '', name, flags=re.IGNORECASE)
    
    # Remove traços no final que indicam grupos rippers (Ex: -ROSE, -NTb)
    name = re.sub(r'-[a-zA-Z0-9_]+$', '', name)
    name = name.replace('-', ' ') # Remove outros hífens
    
    # Remove anos que sobraram
    year_match = re.search(r'(19\d{2}|20\d{2})', name)
    year = year_match.group(1) if year_match else None
    name = re.sub(r'(19\d{2}|20\d{2})', '', name)
    
    # Troca pontos por espaços
    name = name.replace('.', ' ').replace('_', ' ')
    name = re.sub(r'\s+', ' ', name).strip()
    return name, year
"""
    content = re.sub(r'def clean_filename\(filename\):.*?(?=def get_metadata)', lambda m: new_clean, content, flags=re.DOTALL)
    
    with open(TMDB_PATH, "w") as f:
        f.write(content)

def update_torrent_bot():
    BOT_PATH = "/home/ubuntu/torrent_telegram_bot/torrent_bot.py"
    with open(BOT_PATH, "r") as f:
        content = f.read()

    new_progress = r"""
import time
import math

async def progress(current, total, msg, text="Processando", start_time=None):
    now = time.time()
    diff = now - start_time if start_time else 1
    diff = diff if diff > 0 else 1
    
    speed = current / diff
    
    # Previne divisão por zero
    if total == 0:
        return
        
    percentage = current * 100 / total
    
    speed_mb = speed / (1024 * 1024)
    current_mb = current / (1024 * 1024)
    total_mb = total / (1024 * 1024)

    progress_str = f"[{'#' * math.floor(percentage / 10)}{'-' * (10 - math.floor(percentage / 10))}]"
    
    status_text = f"{text}\n\n" \
                  f"⏳ **Progresso:** {percentage:.1f}%\n" \
                  f"{progress_str}\n" \
                  f"📦 **Tamanho:** {current_mb:.1f} MB / {total_mb:.1f} MB\n" \
                  f"🚀 **Velocidade:** {speed_mb:.1f} MB/s"

    try:
        if not hasattr(msg, 'last_update_time'):
            msg.last_update_time = 0
            
        if now - msg.last_update_time > 5:
            await msg.edit_text(status_text)
            msg.last_update_time = now
    except Exception as e:
        pass
"""
    content = re.sub(r'async def progress\(current, total, msg, text="Baixando"\):.*?(?=@app\.on_message)', lambda m: new_progress, content, flags=re.DOTALL)

    new_commands = r"""
@app.on_message(filters.command("entrar") & filters.user(ADMIN_USER_ID))
async def entrar_command(client, message):
    link = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else ""
    if not link:
        return await message.reply("Uso: /entrar t.me/+LinkDeConvite")
    
    msg = await message.reply("⏳ Tentando entrar no grupo/canal...")
    try:
        chat = await app.join_chat(link)
        await msg.edit_text(f"✅ **Sucesso!** O bot agora é membro de: **{chat.title}**\n\nAgora você pode usar `/clonar` para copiar vídeos de lá.")
    except Exception as e:
        await msg.edit_text(f"❌ **Erro ao entrar:** {e}")

@app.on_message(filters.command("clonar") & filters.user(ADMIN_USER_ID))
async def clonar_command(client, message):
    link = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else ""
    if not link:
        return await message.reply("Uso: /clonar https://t.me/c/12345/678")
    
    msg_status = await message.reply("🕵️‍♂️ **Iniciando Clone Ninja...**")
    
    try:
        link = link.rstrip('/')
        parts = link.split('/')
        message_id = int(parts[-1])
        
        chat_id = None
        if '/c/' in link:
            chat_id = int(f"-100{parts[-2]}")
        else:
            chat_id = parts[-2]
            
        target_msg = await app.get_messages(chat_id, message_id)
        if not target_msg or (not target_msg.video and not target_msg.document):
            return await msg_status.edit_text("❌ Nenhum vídeo encontrado nessa mensagem.")
            
        import time
        start_time = time.time()
        
        await msg_status.edit_text("📥 **Pescando Arquivo [Invisível]...**\nTransferindo para a memória RAM (VPS).")
        file_path = await target_msg.download(
            file_name=f"{RAMDISK_DIR}/",
            progress=progress,
            progress_args=(msg_status, "📥 **Pescando (Download do Telegram)**", start_time)
        )
        
        if not file_path:
             return await msg_status.edit_text("❌ Erro ao baixar arquivo clonado.")
             
        await msg_status.edit_text("🎬 **Processando TMDB, Thumbnail e Metadados...**")
        
        import os
        from utils.video_helper import extract_video_metadata, generate_thumbnail
        from utils.tmdb_helper import get_metadata
        
        filename = os.path.basename(file_path)
        caption, poster_url, is_serie = get_metadata(filename)
        width, height, duration = await extract_video_metadata(file_path)
        thumb_path = await generate_thumbnail(file_path)
        
        upload_start = time.time()
        sended_msg = await app.send_video(
            chat_id=DESTINATION_CHANNEL,
            video=file_path,
            caption=caption,
            thumb=thumb_path,
            width=width,
            height=height,
            duration=duration,
            supports_streaming=True,
            progress=progress,
            progress_args=(msg_status, "☁️ **Subindo pro Canal VIP**", upload_start)
        )
        
        from utils.db_helper import salvar_upload
        import re
        
        clean_name = re.sub(r'\[.*?\]|\(.*?\)|\-.*$', '', filename).replace('.', ' ').strip()
        final_title = clean_name
        
        if is_serie:
            serie_match = re.search(r'[Ss](\d{1,2})[Ee](\d{1,2})', filename, re.IGNORECASE)
            if serie_match:
               final_title = f"{clean_name} S{serie_match.group(1)}E{serie_match.group(2)}"
               
        await salvar_upload(final_title, DESTINATION_CHANNEL, sended_msg.id)
        
        await msg_status.edit_text("✅ **Clone Finalizado! Arquivo cirurgicamente roubado e postado.**")
        
        try:
            os.remove(file_path)
            if thumb_path and os.path.exists(thumb_path):
                os.remove(thumb_path)
        except:
            pass

    except Exception as e:
        await msg_status.edit_text(f"❌ **Erro no Clone Ninja:** {str(e)}")

"""
    content = content.replace('@app.on_message(filters.command("gerar_indice")', new_commands + '\n@app.on_message(filters.command("gerar_indice")')
    
    dl_status_str = r"""
            speed_mb = s.download_payload_rate / (1024 * 1024)
            current_mb = s.total_wanted_done / (1024 * 1024)
            total_mb = s.total_wanted / (1024 * 1024)
            
            if not hasattr(msg_status, 'last_update_time'):
                msg_status.last_update_time = 0
            
            if now - msg_status.last_update_time > 5:
                try:
                    await msg_status.edit_text(f"⏳ **Baixando Torrent:** {s.progress * 100:.2f}%\n\n"
                                               f"📦 **Tamanho:** {current_mb:.1f} MB / {total_mb:.1f} MB\n"
                                               f"🚀 **Velocidade:** {speed_mb:.1f} MB/s")
                    msg_status.last_update_time = now
                except Exception:
                    pass
"""
    old_loop_update = r"try:\s*await msg_status\.edit_text\(f\"⏳ \*\*Baixando Torrent:\*\* \{s\.progress \* 100:\.2f\}%\\nStatus: \{s\.state\.name\}\"\)\s*except Exception:\s*pass"
    content = re.sub(old_loop_update, lambda m: dl_status_str, content)

    content = re.sub(
        r'progress_args=\(msg_status,\s*"Subindo pro canal"\)',
        r'progress_args=(msg_status, "☁️ **Subindo pro Canal VIP**", time.time())',
        content
    )

    with open(BOT_PATH, "w") as f:
        f.write(content)

if __name__ == "__main__":
    update_tmdb_helper()
    update_torrent_bot()
    print("Atualização concluída.")
