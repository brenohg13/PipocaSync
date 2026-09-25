# -*- coding: utf-8 -*-
import os
import asyncio
import time
import re
import shutil
from pathlib import Path
import configparser
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message
import libtorrent as lt

# ===== CONFIGURAÇÕES GERAIS =====
BASE_DIR = Path("/home/ubuntu/torrent_telegram_bot")
DOWNLOAD_DIR = Path("/mnt/ramdisk/downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Importando Módulos Hardcore
from utils.tmdb_helper import init_tmdb, get_metadata
from utils.video_helper import get_video_metadata, generate_thumbnail
from utils.db_helper import init_db, save_upload, get_all_uploads, get_serie_channel, save_serie_channel
from utils.rss_helper import rss_monitor_loop

# Lendo credenciais
config = configparser.ConfigParser()
config.read(BASE_DIR / "config.ini")
API_ID = int(config.get("pyrogram", "api_id"))
API_HASH = config.get("pyrogram", "api_hash")
TMDB_API_KEY = config.get("tmdb", "api_key", fallback=None)

if TMDB_API_KEY:
    init_tmdb(TMDB_API_KEY)

# Cliente como UserBot
app = Client(
    "torrent_userbot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    workdir=str(BASE_DIR)
)

# Estado Global e Controles
destino_upload = -1003945657445
download_queue = asyncio.Queue()
abort_current_download = False
upload_semaphore = asyncio.Semaphore(3) # Turbo: Máximo de 3 uploads simultâneos


# Flags para cancelamento e timeouts globais
current_torrent_handle = None
cancel_current_torrent = False
current_status_msg = None

def format_bytes(size):
    power = 2**10
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f} {power_labels.get(n, '')}B"

def smart_rename(filename):
    ext = Path(filename).suffix
    patterns = [
        re.compile(r'[Ss](\d{1,2})[Xx\s._-]*[Ee](\d{1,3})', re.IGNORECASE),
        re.compile(r'(\d{1,2})[xX](\d{1,3})', re.IGNORECASE)
    ]
    for pattern in patterns:
        match = pattern.search(filename)
        if match:
            s_num = str(int(match.group(1))).zfill(2)
            e_num = str(int(match.group(2))).zfill(2)

            # Recupera o nome da série que vem antes do S01E01 para não perdê-lo
            base_name = filename[:match.start()].replace(".", " ").replace("_", " ").strip()
            if not base_name:
                base_name = "Serie"

            return f"{base_name} S{s_num}E{e_num}{ext}"

    return filename

def check_series_and_basename(filename):
    # Procura pelo padrao S01E01 gerado pelo smart_rename
    match = re.search(r'(S\d{2}E\d{2})', filename, re.IGNORECASE)
    if match:
        base_name = filename[:match.start()].strip()
        ep_tag = match.group(1)
        return True, base_name, ep_tag
    return False, filename, ""

def extract_metadata(filename):
    name = Path(filename).stem
    qualities_map = ['2160p', '4k', '1080p', '720p', '480p', 'Web-DL', 'WEBRip', 'BluRay', 'HDTV']
    found_q = []
    for q in qualities_map:
        if q.lower() in name.lower():
            found_q.append(q)
    quality_str = " / ".join(found_q) if found_q else "Qualidade Padrão"
    
    clean_name = name.replace('.', ' ').replace('_', ' ')
    match = re.search(r'\b(19\d{2}|20\d{2})\b', clean_name)
    year = ""
    if match:
        year = match.group(1)
        clean_name = clean_name[:match.start()].strip()
    
    for junk in qualities_map + ['dual', 'audio', 'dublado', 'legendado', 'x264', 'hevc', '10bit', '5.1', 'aac', 'yify', 'rarbg']:
        clean_name = re.sub(rf'\b{junk}\b', '', clean_name, flags=re.IGNORECASE)
    
    clean_name = " ".join(clean_name.split()).title()
    if not clean_name: 
        clean_name = name

    return clean_name, year, quality_str

async def fetch_tmdb_data(query):
    if not TMDB_API_KEY:
        return None
    url = "https://api.themoviedb.org/3/search/movie"
    params = {"api_key": TMDB_API_KEY, "query": query, "language": "pt-BR"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data['results']:
                        movie = data['results'][0]
                        return {
                            "title": movie.get("title"),
                            "overview": movie.get("overview"),
                            "poster": f"https://image.tmdb.org/t/p/w500{movie.get('poster_path')}" if movie.get("poster_path") else None,
                            "release_date": movie.get("release_date", "")
                        }
    except Exception as e:
        print(f"Erro TMDB: {e}")
    return None

async def progress_for_pyrogram(current, total, status_msg, file_name, prefix="", start_time=None):
    from pyrogram.errors import MessageNotModified
    global cancel_current_torrent
    if cancel_current_torrent:
        await status_msg.edit_text("⛔ **Upload Cancelado Manualmente!** (Abortando envio...)")
        raise Exception("Upload cancelado à força pelo comando /cancelar")

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

        text = (
            f"☁️ **{prefix}**\n\n"
            f"**Arquivo:** `{file_name}`\n"
            f"⏳ **Progresso:** {percent:.1f}% ({format_bytes(current)} / {format_bytes(total)})\n"
            f"🚀 **Velocidade Upload:** {speed_str}"
        )
        try:
            await status_msg.edit_text(text)
            progress_for_pyrogram.last_update = now
        except MessageNotModified:
            pass
        except Exception: 
            pass




async def upload_video_task(client, message, fpath):
    global cancel_current_torrent, upload_semaphore
    
    # Renomeação
    new_name = smart_rename(fpath.name)
    new_path = fpath.parent / new_name
    if fpath != new_path:
        try: os.rename(fpath, new_path); fpath = new_path
        except Exception: pass
        
    upload_msg = await message.reply(f"☁️ Na fila do Turbo: `{new_name}`...")
    
    try:
        size_bytes = fpath.stat().st_size
        if size_bytes > 4294967296:
            await upload_msg.edit_text(f"⚠️ `{new_name}` é maior que 4GB! Pulando...")
            return

        clean_title, year, quality = extract_metadata(fpath.name)
        is_serie, base_name, ep_tag = check_series_and_basename(new_name)
        search_title = base_name if is_serie else clean_title
        
        tmdb_data = await fetch_tmdb_data(search_title)
        if tmdb_data:
            final_title = tmdb_data['title']
            overview = tmdb_data['overview']
            release_year = tmdb_data['release_date'][:4] if tmdb_data['release_date'] else year
            poster_url = tmdb_data['poster']
        else:
            final_title = search_title
            overview = "Sinopse não encontrada."
            release_year = year
            poster_url = None

        ano_str = f" ({release_year})" if release_year else ""
        actual_upload_target = destino_upload
        
        if is_serie:
            serie_db = await get_serie_channel(base_name)
            if not serie_db:
                await upload_msg.edit_text(f"📺 Criando Sub-Canal para: `{base_name}`...")
                try:
                    new_channel = await client.create_channel(f"📺 {final_title} - Acervo")
                    invite_link = await client.export_chat_invite_link(new_channel.id)
                    await save_serie_channel(base_name, new_channel.id, invite_link)
                    serie_db = {"chat_id": new_channel.id, "invite_link": invite_link}
                    
                    vitrine_caption = (
                        f"🎬 **{final_title}**{ano_str} (Série)\n\n"
                        f"📝 **Sinopse:** {overview}\n\n"
                        f"📁 **Acessar Episódios:** [Acessar Acervo]({invite_link})"
                    )
                    if poster_url: await client.send_photo(chat_id=destino_upload, photo=poster_url, caption=vitrine_caption)
                    else: await client.send_message(chat_id=destino_upload, text=vitrine_caption, disable_web_page_preview=True)
                except Exception: pass
            
            if serie_db: actual_upload_target = serie_db["chat_id"]
            caption = f"🎥 **{final_title}** - `{ep_tag}`\n📺 `{quality}` | 📦 `{format_bytes(size_bytes)}`"
            poster_url_upload = None
        else:
            caption = (
                f"🎬 **{final_title}**{ano_str}\n\n"
                f"📝 **Sinopse:** {overview}\n\n"
                f"📦 **Tamanho:** `{format_bytes(size_bytes)}`\n"
                f"📺 **Qualidade:** `{quality}`\n\n"
                f"🤖 *Acervo VIP*"
            )
            poster_url_upload = poster_url

        # O TURBO: Apenas 3 uploads por vez
        async with upload_semaphore:
            if cancel_current_torrent: return
            await upload_msg.edit_text(f"⏳ Processando e enviando: `{new_name}`...")
            duration, width, height = await get_video_metadata(fpath)
            thumb_path = await generate_thumbnail(fpath, f"{fpath}.jpg")
            
            if poster_url_upload:
                await client.send_photo(chat_id=actual_upload_target, photo=poster_url_upload, caption=caption)
                
            sent_msg = await client.send_video(
                chat_id=actual_upload_target,
                video=str(fpath),
                caption=caption if (is_serie or not poster_url_upload) else f"🎥 **Arquivo:** `{new_name}`",
                duration=duration,
                width=width,
                height=height,
                thumb=thumb_path,
                supports_streaming=True,
                progress=progress_for_pyrogram,
                progress_args=(upload_msg, new_name, "Enviando (Turbo)", time.time())
            )
            
            await save_upload(new_name, sent_msg.id, actual_upload_target, is_serie=is_serie)
            if thumb_path and __import__("os").path.exists(thumb_path): __import__("os").remove(thumb_path)
            await upload_msg.edit_text(f"✅ **Enviado!** `{new_name}`")

    except Exception as e:
        if "cancelado" in str(e).lower(): await upload_msg.edit_text(f"🛑 **Envio Cancelado:** `{new_name}`")
        else: await upload_msg.edit_text(f"❌ **Erro no envio:** `{new_name}`\n{str(e)}")
    finally:
        try: __import__("os").remove(fpath)
        except: pass

async def process_torrent(client: Client, message: Message, link: str = None, torrent_file: str = None):
    global current_torrent_handle, cancel_current_torrent, current_status_msg
    cancel_current_torrent = False
    
    status_msg = await message.reply("🔄 Inicializando motor de Torrent (Processando na Fila)...")
    current_status_msg = status_msg

    ses = lt.session({'listen_interfaces': '0.0.0.0:6881'})

    if link and link.startswith("magnet:"):
        await status_msg.edit_text("🧲 Resolvendo Magnet Link...")
        params = lt.parse_magnet_uri(link)
        params.save_path = str(DOWNLOAD_DIR)
        handle = ses.add_torrent(params)
    elif torrent_file:
        await status_msg.edit_text("📄 Lendo arquivo .torrent...")
        info = lt.torrent_info(torrent_file)
        handle = ses.add_torrent({'ti': info, 'save_path': str(DOWNLOAD_DIR)})
    else:
        await status_msg.edit_text("❌ Formato não suportado.")
        return

    current_torrent_handle = handle

    # TIMEOUT DE METADATA (Se ficar 2 minutos sem achar info do Magnet)
    meta_start = time.time()
    while not handle.status().has_metadata:
        if cancel_current_torrent:
            await status_msg.edit_text("⛔ **Download Cancelado Manualmente!** Pulando para o próximo.")
            ses.remove_torrent(handle)
            return
        if time.time() - meta_start > 120:
            await status_msg.edit_text("❌ **Abortado:** Tempo limite esgotado ao buscar metadata (Magnet Link possivelmente morto).")
            ses.remove_torrent(handle)
            return
        await asyncio.sleep(1)

    file_name = handle.status().name
    last_update = time.time()
    
    # SETUP DO ANTI-ZUMBI
    last_progress_value = -1
    last_progress_time = time.time()

    while handle.status().state != lt.torrent_status.seeding:
        if cancel_current_torrent:
            await status_msg.edit_text("⛔ **Download Cancelado Manualmente!** Pulando para o próximo.")
            ses.remove_torrent(handle)
            # Limpeza
            tgt_path = DOWNLOAD_DIR / file_name
            if tgt_path.exists():
                if tgt_path.is_file(): os.remove(tgt_path)
                else: shutil.rmtree(tgt_path, ignore_errors=True)
            return

        s = handle.status()
        now = time.time()
        
        # CHECAGEM DO ANTI-ZUMBI (Se travou por mais de 5 minutos == 300 segundos sem progresso real)
        if s.total_done > last_progress_value:
            last_progress_value = s.total_done
            last_progress_time = now
        elif (now - last_progress_time) > 300: # 5 Minutos cravados
            await status_msg.edit_text(f"❌ **Abortado pelo Sistema Anti-Zumbi:** O torrent `{file_name}` ficou 5 minutos sem receber dados. Limpando lixo e indo pro próximo...")
            ses.remove_torrent(handle)
            tgt_path = DOWNLOAD_DIR / file_name
            if tgt_path.exists():
                if tgt_path.is_file(): os.remove(tgt_path)
                else: shutil.rmtree(tgt_path, ignore_errors=True)
            return

        if now - last_update > 4:
            state_str = ['queued', 'checking', 'metadata', 'downloading', 'finished', 'seeding', 'allocating'][s.state]
            # Formatação do Tempo Restante do Zumbi
            time_left_zumbi = 300 - int(now - last_progress_time)
            speed_mb = s.download_payload_rate / (1024 * 1024)
            current_mb = s.total_wanted_done / (1024 * 1024)
            total_mb = s.total_wanted / (1024 * 1024)
            text = (
                f"📥 **Download Torrent**\n\n"
                f"**Nome:** `{file_name}`\n"
                f"**Status:** {state_str.upper()}\n"
                f"⏳ **Progresso:** {s.progress*100:.1f}% ({current_mb:.1f} MB / {total_mb:.1f} MB)\n"
                f"🚀 **Velocidade:** {speed_mb:.1f} MB/s\n"
                f"👥 **Peers:** {s.num_peers} ativos\n\n"
                f"⏱️ _Zumbi TimeLeft: {time_left_zumbi}s_"
            )
            try: await status_msg.edit_text(text)
            except Exception: pass
            last_update = now
        await asyncio.sleep(1)

    await status_msg.edit_text(f"✅ **Download Concluído:** `{file_name}`!")
    
    # Processo final do arquivo
    target_path = DOWNLOAD_DIR / file_name
    files_to_upload = []
    if target_path.is_file(): files_to_upload.append(target_path)
    elif target_path.is_dir():
        for root, dirs, files in os.walk(target_path):
            for f in files:
                if f.lower().endswith(('.mp4', '.mkv', '.avi')):
                    files_to_upload.append(Path(root) / f)

    if not files_to_upload:
        await status_msg.edit_text("⚠️ Download concluído, nenhum vídeo encontrado. (Pasta limpada automatica)")
        return

    # ORDENAÇÃO DE SEQUÊNCIA: Garante que S01E01 venha antes de S01E02
    files_to_upload.sort(key=lambda x: x.name)

    async def run_single_upload(fpath):
        if cancel_current_torrent: return

        new_name = smart_rename(fpath.name)
        new_path = fpath.parent / new_name
        if fpath != new_path:
            os.rename(fpath, new_path)
            fpath = new_path

        upload_msg = await message.reply(f"☁️ Preparando envio: `{new_name}`...")
        size_bytes = fpath.stat().st_size
        if size_bytes > 4294967296: # 4GB LIMIT
            await upload_msg.edit_text(f"⚠️ `{new_name}` é maior que 4GB! Pulando...")
            return

        clean_title, year, quality = extract_metadata(fpath.name)

        is_serie, base_name, ep_tag = check_series_and_basename(new_name)
        search_title = base_name if is_serie else clean_title

        tmdb_data = await fetch_tmdb_data(search_title)

        if tmdb_data:
            final_title = tmdb_data['title']
            overview = tmdb_data['overview']
            release_year = tmdb_data['release_date'][:4] if tmdb_data['release_date'] else year
            poster_url = tmdb_data['poster']
        else:
            final_title = search_title
            overview = "Sinopse não encontrada no TMDB."
            release_year = year
            poster_url = None

        ano_str = f" ({release_year})" if release_year else ""

        # =========== ARQUITETURA VITRINE/GAVETA ===========
        actual_upload_target = destino_upload
        vitrine_caption = ""

        if is_serie:
            serie_db = await get_serie_channel(base_name)

            if not serie_db:
                await upload_msg.edit_text(f"📺 Criando Sub-Canal na nuvem para a Série: `{base_name}`...")
                try:
                    new_channel = await client.create_channel(f"📺 {final_title} - Acervo")
                    invite_link = await client.export_chat_invite_link(new_channel.id)
                    await save_serie_channel(base_name, new_channel.id, invite_link)
                    serie_db = {"chat_id": new_channel.id, "invite_link": invite_link}

                    vitrine_caption = (
                        f"🎬 **{final_title}**{ano_str} (Série)\n\n"
                        f"📝 **Sinopse:** {overview}\n\n"
                        f"📁 **Assistir Episódios:** [Acessar Pasta Exclusiva]({invite_link})"
                    )
                    if poster_url:
                        await client.send_photo(chat_id=destino_upload, photo=poster_url, caption=vitrine_caption)
                    else:
                        await client.send_message(chat_id=destino_upload, text=vitrine_caption, disable_web_page_preview=True)
                except Exception as e:
                    print(f"Falha ao criar subcanal para {base_name}: {e}")
                    pass

            if serie_db:
                actual_upload_target = serie_db["chat_id"]

            caption = f"🎥 **{final_title}** - `{ep_tag}`\n📺 `{quality}` | 📦 `{format_bytes(size_bytes)}`"
            poster_url_upload = None
        else:
            caption = (
                f"🎬 **{final_title}**{ano_str}\n\n"
                f"📝 **Sinopse:** {overview}\n\n"
                f"📦 **Tamanho:** `{format_bytes(size_bytes)}`\n"
                f"📺 **Qualidade:** `{quality}`\n\n"
                f"🤖 *Acervo VIP*"
            )
            poster_url_upload = poster_url

        try:
            await upload_msg.edit_text(f"⏳ Processando metadados de vídeo para streaming...")
            duration, width, height = await get_video_metadata(fpath)
            thumb_path = await generate_thumbnail(fpath, f"{fpath}.jpg")

            if poster_url_upload:
                await client.send_photo(chat_id=actual_upload_target, photo=poster_url_upload, caption=caption)

            # TRAVA DE SEGURANCA DO SEMAFORO ANTES DE INICIAR O UPLOAD PESADO
            async with upload_semaphore:
                sent_msg = await client.send_video(
                    chat_id=actual_upload_target,
                    video=str(fpath),
                    caption=caption if (is_serie or not poster_url_upload) else f"🎥 **Arquivo:** `{new_name}`",
                    duration=duration,
                    width=width,
                    height=height,
                    thumb=thumb_path,
                    supports_streaming=True,
                    progress=progress_for_pyrogram,
                    progress_args=(upload_msg, new_name, "Enviando Vídeo (Streaming)", time.time())
                )

            await save_upload(new_name, sent_msg.id, actual_upload_target, is_serie=is_serie)

            if thumb_path and os.path.exists(thumb_path):
                os.remove(thumb_path)
            await upload_msg.edit_text(f"✅ **Enviado {'para a sub-GAVETA' if is_serie else 'para a VITRINE'}!**")
        except Exception as e:
            if "cancelado" in str(e).lower():
                await upload_msg.edit_text(f"🛑 **Envio Cancelado:** `{new_name}` (Abortado pelo usuário)")
            else:
                await upload_msg.edit_text(f"❌ **Erro no envio:** `{new_name}`\n{str(e)}")

        try: os.remove(fpath)
        except: pass

    # Inicia todas as tarefas de upload de forma paralela usando Gather!
    upload_tasks = [run_single_upload(f) for f in files_to_upload]
    await asyncio.gather(*upload_tasks)

    await status_msg.delete()
    try: shutil.rmtree(target_path, ignore_errors=True)
    except: pass
    
    current_torrent_handle = None
    current_status_msg = None


async def queue_worker():
    print("👷‍♂️ Worker da fila de Torrent iniciado!")
    while True:
        task = await download_queue.get()
        try:
            if "link" in task:
                await process_torrent(task["client"], task["message"], link=task["link"])
            else:
                await process_torrent(task["client"], task["message"], torrent_file=task["file"])
        except Exception as e:
            msg = task.get("message")
            if msg:
                try:
                    await msg.reply(f"⚠️ **Falha/Abortado no Download:**\n{e}")
                except Exception:
                    pass
            print(f"Erro processando item da fila: {e}")
        finally:
            download_queue.task_done()


@app.on_message(filters.command("entrar", prefixes="/") & filters.me)
async def entrar_command(client, message):
    if len(message.command) < 2:
        return await message.reply("Uso: `/entrar <link_de_convite>`")
    link = message.command[1]
    status = await message.reply("⏳ Tentando entrar no grupo/canal...")
    try:
        chat = await client.join_chat(link)
        await status.edit_text(f"✅ **Sucesso!** Entrei em sob o ID `{chat.id}`\n**Nome:** {chat.title}")
    except Exception as e:
        await status.edit_text(f"❌ **Erro ao entrar:**\n`{str(e)}`")

@app.on_message(filters.command("clonar", prefixes="/") & filters.me)
async def clonar_command(client, message):
    if len(message.command) < 2:
        return await message.reply("Uso: `/clonar <link_da_mensagem>` ou `/clonar <canal_id> <quantidade>`")

    # Verifica se o primeiro argumento parece um link do Telegram ou formato ID/MsgID
    # Ex: https://t.me/c/1977503172/90 ou 1895992934/19838
    match = re.search(r'(?:c/)?(-?\d+)/(\d+)', message.command[1])

    if match and len(message.command) == 2:
        chat_id_str, msg_id_str = match.group(1), match.group(2)
        origem_id = int(chat_id_str)

        # Ajusta IDs de canais privados copiados do link que não possuem prefixo -100
        if not str(origem_id).startswith("-100") and not str(origem_id).startswith("-"):
            origem_id = int(f"-100{origem_id}")

        msg_id = int(msg_id_str)
        status = await message.reply(f"🧬 **Iniciando Clonagem Específica!**\nCanal: `{origem_id}` | MSG: `{msg_id}`")

        try:
            msg = await client.get_messages(chat_id=origem_id, message_ids=msg_id)
            if msg and not msg.empty and (msg.video or msg.document or msg.photo):
                await msg.copy(destino_upload)
                return await status.edit_text("✅ **Mídia clonada com sucesso!**")
            else:
                return await status.edit_text("❌ **Falha:** Mensagem não encontrada ou não possui vídeos/fotos/documentos.")
        except Exception as e:
            return await status.edit_text(f"❌ **Erro fatal ao clonar mensagem:**\n`{str(e)}`")

    # Caso contrário, fluxo de clonagem em lote
    if len(message.command) < 3:
        return await message.reply("Uso em lote: `/clonar <id_do_canal> <quantidade>`\nUso unitário: `/clonar https://t.me/c/1977503172/90`")

    try:
        origem_id = int(message.command[1])
        quantidade = int(message.command[2])
    except ValueError:
        return await message.reply("❌ IDs ou Quantidade devem ser números inteiros.")

    status = await message.reply(f"🧬 **Iniciando Clonagem!**\nAlvo: `{origem_id}`\nQuantidade: `{quantidade}` mídias.")

    count = 0
    try:
        # Pega as últimas mensagens de vídeo/documento
        async for msg in client.get_chat_history(origem_id, limit=quantidade):
            if msg.video or msg.document or msg.photo:
                try:
                    await msg.copy(destino_upload)
                    count += 1
                    await asyncio.sleep(1.5)  # Evitar FloodWait
                except Exception as e:
                    print(f"Erro copiando mensagem: {e}")
                    pass
        await status.edit_text(f"✅ **Clonagem Finalizada!**\nMídias copiadas: `{count}`")
    except Exception as e:
        await status.edit_text(f"❌ **Erro Fatal na Clonagem:**\n`{str(e)}`")

# ==================== COMANDOS TELEGRAM ====================





@app.on_message(filters.command("setcanal", prefixes="/") & filters.me)
async def set_canal_command(client, message):
    if len(message.command) < 2: return await message.reply("Uso: `/setcanal -100XXXXXXXXXX`")
    try:
        new_id = int(message.command[1])
        global destino_upload; destino_upload = new_id
        await message.reply(f"✅ Destino alterado para: `{destino_upload}`")
    except ValueError: await message.reply("❌ ID Inválido.")

@app.on_message(filters.command("torrent", prefixes="/") & filters.me)
async def torrent_command(client, message):
    if len(message.command) < 2: return await message.reply("Uso: `/torrent <magnet_link>`")
    link = " ".join(message.command[1:])
    q_size = download_queue.qsize()
    await message.reply(f"⏳ **Link adicionado à fila!** (Posição: {q_size + 1})")
    await download_queue.put({"client": client, "message": message, "link": link})

@app.on_message(filters.document & filters.me)
async def torrent_file_handler(client, message):
    if message.document.file_name.endswith(".torrent"):
        status = await message.reply("⬇️ Baixando arquivo .torrent para a fila...")
        file_path = await message.download(file_name=str(DOWNLOAD_DIR) + "/")
        q_size = download_queue.qsize()
        await status.edit_text(f"⏳ **Torrent adicionado à fila!** (Posição: {q_size + 1})")
        await download_queue.put({"client": client, "message": message, "file": file_path})

@app.on_message(filters.command("cancelar", prefixes="/") & filters.me)
async def cancelar_command(client, message):
    global cancel_current_torrent
    if not current_torrent_handle and download_queue.empty():
        return await message.reply("⚠️ Não há nenhum torrent rodando no momento nem itens na fila!")
    
    cancel_current_torrent = True
    
    # Se quiser limpar a fila inteira ao mesmo tempo: /cancelar fila
    clean_queue_count = 0
    if len(message.command) > 1 and message.command[1].lower() == "fila":
        while not download_queue.empty():
            download_queue.get_nowait()
            download_queue.task_done()
            clean_queue_count += 1
            
    res_text = "🛑 **Sinal de cancelamento enviado!** O torrent atual e todo seu registro temporário serão abortados."
    if clean_queue_count > 0:
        res_text += f"\n🗑️ A fila também foi esvaziada: `{clean_queue_count}` itens removidos."
        
    await message.reply(res_text)


@app.on_message(filters.command("status", prefixes="/") & filters.me)
async def status_command(client, message):
    # Uso do RAM Disk
    total, used, free = shutil.disk_usage(DOWNLOAD_DIR)
    
    db_items = await get_all_uploads()
    total_enviados = len(db_items)
    
    q_size = download_queue.qsize()
    if current_torrent_handle:
        rodando_agora = f"Em processamento: `{current_torrent_handle.status().name}`"
    else:
        rodando_agora = "Ocioso."

    status_text = (
        f"📊 **Painel de Controle VPS**\n\n"
        f"🖥️ **Memória RAMDisk:**\n"
        f"├ Usado: `{format_bytes(used)}`\n"
        f"└ Livre: `{format_bytes(free)}`\n\n"
        f"🚧 **Andamento Atual:**\n"
        f"├ {rodando_agora}\n"
        f"└ Fila de Espera: `{q_size} items`\n\n"
        f"📁 **Banco de Dados:**\n"
        f"└ Total no Acervo VIP: `{total_enviados} envios`"
    )
    await message.reply(status_text)

@app.on_message(filters.command("limpar", prefixes="/") & filters.me)
async def limpar_command(client, message):
    await message.reply("🧹 **Realizando limpeza profunda do sistema...**")
    limpados = 0
    for file in DOWNLOAD_DIR.iterdir():
        try:
            if file.is_file(): file.unlink()
            elif file.is_dir(): shutil.rmtree(file)
            limpados += 1
        except Exception: pass
    
    # Tentativa de Esvaziar a Queue caso se queria flush geral
    clean_queue_count = 0
    if len(message.command) > 1 and message.command[1].lower() == "fila":
        while not download_queue.empty():
            download_queue.get_nowait()
            download_queue.task_done()
            clean_queue_count += 1
            
    res_text = f"✅ Limpeza concluída!\nLixo removido do RAMDisk: `{limpados} itens`."
    if clean_queue_count > 0:
        res_text += f"\nItens esvaziados da fila: `{clean_queue_count}`."
        
    await message.reply(res_text)

@app.on_message(filters.command("gerar_indice", prefixes="/") & filters.me)
async def gerar_indice_command(client, message):
    items = await get_all_uploads()
    if not items:
        return await message.reply("⚠️ Nenhum upload salvo no banco de dados!")
    
    status = await message.reply("⏳ Gerando índice formatado...")
    
    texto = "🎬 **CATÁLOGO DO ACERVO VIP** 🎬\n\n"
    for item in items:
        # DB format: filename, message_id, chat_id, is_serie
        filename, msg_id, chat_id, _ = item
        
        # Criação do link base
        # IDs de canais ou grupos para o link clicável
        chat_id_str = str(chat_id).replace("-100", "") 
        link = f"https://t.me/c/{chat_id_str}/{msg_id}"
        
        # Limpa o filme para exibir bonitinho
        clean_name, _, _ = extract_metadata(filename)
        texto += f"🍿 [{clean_name}]({link})\n"

    # Se o texto for gigante (Limite Telegram é 4096), precisamos dividir (aqui apenas corta por segurança, vc pode avançar paginando dps)
    if len(texto) > 4000:
        texto = texto[:4000] + "\n...(Índice truncado por tamanho limite)..."
        
    await status.edit_text(texto, disable_web_page_preview=True)


async def main():
    await init_db()
    await app.start()
    asyncio.create_task(queue_worker())
    asyncio.create_task(rss_monitor_loop(app, lambda: destino_upload))
    from pyrogram import idle
    await idle()
    await app.stop()

if __name__ == "__main__":
    print("🚀 Iniciando UserBot de Torrents v2 (ANTI-ZUMBI)!")
    app.run(main())

    # Cria uma tarefa paralela para cada arquivo de video baixado!
    tasks = []
    for fpath in files_to_upload:
        if cancel_current_torrent: break
        tasks.append(asyncio.create_task(upload_video_task(client, message, fpath)))
        
    if tasks:
        await status_msg.edit_text(f"✅ **Download Concluído!** Iniciando {len(tasks)} uploads Turbo em segundo plano...")
        await asyncio.gather(*tasks)
    else:
        await status_msg.edit_text(f"✅ Download finalizado, nada para enviar.")

    try: shutil.rmtree(target_path, ignore_errors=True)
    except: pass
    
current_torrent_handle = None
cancel_current_torrent = False
current_status_msg = None

def format_bytes(size):
    power = 2**10
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f} {power_labels.get(n, '')}B"

def smart_rename(filename):
    ext = Path(filename).suffix
    patterns = [
        re.compile(r'[Ss](\d{1,2})[Xx\s._-]*[Ee](\d{1,3})', re.IGNORECASE),
        re.compile(r'(\d{1,2})[xX](\d{1,3})', re.IGNORECASE)
    ]
    for pattern in patterns:
        match = pattern.search(filename)
        if match:
            s_num = str(int(match.group(1))).zfill(2)
            e_num = str(int(match.group(2))).zfill(2)

            # Recupera o nome da série que vem antes do S01E01 para não perdê-lo
            base_name = filename[:match.start()].replace(".", " ").replace("_", " ").strip()
            if not base_name:
                base_name = "Serie"

            return f"{base_name} S{s_num}E{e_num}{ext}"

    return filename

def check_series_and_basename(filename):
    # Procura pelo padrao S01E01 gerado pelo smart_rename
    match = re.search(r'(S\d{2}E\d{2})', filename, re.IGNORECASE)
    if match:
        base_name = filename[:match.start()].strip()
        ep_tag = match.group(1)
        return True, base_name, ep_tag
    return False, filename, ""

def extract_metadata(filename):
    name = Path(filename).stem
    qualities_map = ['2160p', '4k', '1080p', '720p', '480p', 'Web-DL', 'WEBRip', 'BluRay', 'HDTV']
    found_q = []
    for q in qualities_map:
        if q.lower() in name.lower():
            found_q.append(q)
    quality_str = " / ".join(found_q) if found_q else "Qualidade Padrão"
    
    clean_name = name.replace('.', ' ').replace('_', ' ')
    match = re.search(r'\b(19\d{2}|20\d{2})\b', clean_name)
    year = ""
    if match:
        year = match.group(1)
        clean_name = clean_name[:match.start()].strip()
    
    for junk in qualities_map + ['dual', 'audio', 'dublado', 'legendado', 'x264', 'hevc', '10bit', '5.1', 'aac', 'yify', 'rarbg']:
        clean_name = re.sub(rf'\b{junk}\b', '', clean_name, flags=re.IGNORECASE)
    
    clean_name = " ".join(clean_name.split()).title()
    if not clean_name: 
        clean_name = name

    return clean_name, year, quality_str

async def fetch_tmdb_data(query):
    if not TMDB_API_KEY:
        return None
    url = "https://api.themoviedb.org/3/search/movie"
    params = {"api_key": TMDB_API_KEY, "query": query, "language": "pt-BR"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data['results']:
                        movie = data['results'][0]
                        return {
                            "title": movie.get("title"),
                            "overview": movie.get("overview"),
                            "poster": f"https://image.tmdb.org/t/p/w500{movie.get('poster_path')}" if movie.get("poster_path") else None,
                            "release_date": movie.get("release_date", "")
                        }
    except Exception as e:
        print(f"Erro TMDB: {e}")
    return None

async def progress_for_pyrogram(current, total, status_msg, file_name, prefix="", start_time=None):
    from pyrogram.errors import MessageNotModified
    global cancel_current_torrent
    if cancel_current_torrent:
        await status_msg.edit_text("⛔ **Upload Cancelado Manualmente!** (Abortando envio...)")
        raise Exception("Upload cancelado à força pelo comando /cancelar")

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

        text = (
            f"☁️ **{prefix}**\n\n"
            f"**Arquivo:** `{file_name}`\n"
            f"⏳ **Progresso:** {percent:.1f}% ({format_bytes(current)} / {format_bytes(total)})\n"
            f"🚀 **Velocidade Upload:** {speed_str}"
        )
        try:
            await status_msg.edit_text(text)
            progress_for_pyrogram.last_update = now
        except MessageNotModified:
            pass
        except Exception: 
            pass




async def upload_video_task(client, message, fpath):
    global cancel_current_torrent, upload_semaphore
    
    # Renomeação
    new_name = smart_rename(fpath.name)
    new_path = fpath.parent / new_name
    if fpath != new_path:
        try: os.rename(fpath, new_path); fpath = new_path
        except Exception: pass
        
    upload_msg = await message.reply(f"☁️ Na fila do Turbo: `{new_name}`...")
    
    try:
        size_bytes = fpath.stat().st_size
        if size_bytes > 4294967296:
            await upload_msg.edit_text(f"⚠️ `{new_name}` é maior que 4GB! Pulando...")
            return

        clean_title, year, quality = extract_metadata(fpath.name)
        is_serie, base_name, ep_tag = check_series_and_basename(new_name)
        search_title = base_name if is_serie else clean_title
        
        tmdb_data = await fetch_tmdb_data(search_title)
        if tmdb_data:
            final_title = tmdb_data['title']
            overview = tmdb_data['overview']
            release_year = tmdb_data['release_date'][:4] if tmdb_data['release_date'] else year
            poster_url = tmdb_data['poster']
        else:
            final_title = search_title
            overview = "Sinopse não encontrada."
            release_year = year
            poster_url = None

        ano_str = f" ({release_year})" if release_year else ""
        actual_upload_target = destino_upload
        
        if is_serie:
            serie_db = await get_serie_channel(base_name)
            if not serie_db:
                await upload_msg.edit_text(f"📺 Criando Sub-Canal para: `{base_name}`...")
                try:
                    new_channel = await client.create_channel(f"📺 {final_title} - Acervo")
                    invite_link = await client.export_chat_invite_link(new_channel.id)
                    await save_serie_channel(base_name, new_channel.id, invite_link)
                    serie_db = {"chat_id": new_channel.id, "invite_link": invite_link}
                    
                    vitrine_caption = (
                        f"🎬 **{final_title}**{ano_str} (Série)\n\n"
                        f"📝 **Sinopse:** {overview}\n\n"
                        f"📁 **Acessar Episódios:** [Acessar Acervo]({invite_link})"
                    )
                    if poster_url: await client.send_photo(chat_id=destino_upload, photo=poster_url, caption=vitrine_caption)
                    else: await client.send_message(chat_id=destino_upload, text=vitrine_caption, disable_web_page_preview=True)
                except Exception: pass
            
            if serie_db: actual_upload_target = serie_db["chat_id"]
            caption = f"🎥 **{final_title}** - `{ep_tag}`\n📺 `{quality}` | 📦 `{format_bytes(size_bytes)}`"
            poster_url_upload = None
        else:
            caption = (
                f"🎬 **{final_title}**{ano_str}\n\n"
                f"📝 **Sinopse:** {overview}\n\n"
                f"📦 **Tamanho:** `{format_bytes(size_bytes)}`\n"
                f"📺 **Qualidade:** `{quality}`\n\n"
                f"🤖 *Acervo VIP*"
            )
            poster_url_upload = poster_url

        # O TURBO: Apenas 3 uploads por vez
        async with upload_semaphore:
            if cancel_current_torrent: return
            await upload_msg.edit_text(f"⏳ Processando e enviando: `{new_name}`...")
            duration, width, height = await get_video_metadata(fpath)
            thumb_path = await generate_thumbnail(fpath, f"{fpath}.jpg")
            
            if poster_url_upload:
                await client.send_photo(chat_id=actual_upload_target, photo=poster_url_upload, caption=caption)
                
            sent_msg = await client.send_video(
                chat_id=actual_upload_target,
                video=str(fpath),
                caption=caption if (is_serie or not poster_url_upload) else f"🎥 **Arquivo:** `{new_name}`",
                duration=duration,
                width=width,
                height=height,
                thumb=thumb_path,
                supports_streaming=True,
                progress=progress_for_pyrogram,
                progress_args=(upload_msg, new_name, "Enviando (Turbo)", time.time())
            )
            
            await save_upload(new_name, sent_msg.id, actual_upload_target, is_serie=is_serie)
            if thumb_path and __import__("os").path.exists(thumb_path): __import__("os").remove(thumb_path)
            await upload_msg.edit_text(f"✅ **Enviado!** `{new_name}`")

    except Exception as e:
        if "cancelado" in str(e).lower(): await upload_msg.edit_text(f"🛑 **Envio Cancelado:** `{new_name}`")
        else: await upload_msg.edit_text(f"❌ **Erro no envio:** `{new_name}`\n{str(e)}")
    finally:
        try: __import__("os").remove(fpath)
        except: pass

async def process_torrent(client: Client, message: Message, link: str = None, torrent_file: str = None):
    global current_torrent_handle, cancel_current_torrent, current_status_msg
    cancel_current_torrent = False
    
    status_msg = await message.reply("🔄 Inicializando motor de Torrent (Processando na Fila)...")
    current_status_msg = status_msg

    ses = lt.session({'listen_interfaces': '0.0.0.0:6881'})

    if link and link.startswith("magnet:"):
        await status_msg.edit_text("🧲 Resolvendo Magnet Link...")
        params = lt.parse_magnet_uri(link)
        params.save_path = str(DOWNLOAD_DIR)
        handle = ses.add_torrent(params)
    elif torrent_file:
        await status_msg.edit_text("📄 Lendo arquivo .torrent...")
        info = lt.torrent_info(torrent_file)
        handle = ses.add_torrent({'ti': info, 'save_path': str(DOWNLOAD_DIR)})
    else:
        await status_msg.edit_text("❌ Formato não suportado.")
        return

    current_torrent_handle = handle

    # TIMEOUT DE METADATA (Se ficar 2 minutos sem achar info do Magnet)
    meta_start = time.time()
    while not handle.status().has_metadata:
        if cancel_current_torrent:
            await status_msg.edit_text("⛔ **Download Cancelado Manualmente!** Pulando para o próximo.")
            ses.remove_torrent(handle)
            return
        if time.time() - meta_start > 120:
            await status_msg.edit_text("❌ **Abortado:** Tempo limite esgotado ao buscar metadata (Magnet Link possivelmente morto).")
            ses.remove_torrent(handle)
            return
        await asyncio.sleep(1)

    file_name = handle.status().name
    last_update = time.time()
    
    # SETUP DO ANTI-ZUMBI
    last_progress_value = -1
    last_progress_time = time.time()

    while handle.status().state != lt.torrent_status.seeding:
        if cancel_current_torrent:
            await status_msg.edit_text("⛔ **Download Cancelado Manualmente!** Pulando para o próximo.")
            ses.remove_torrent(handle)
            # Limpeza
            tgt_path = DOWNLOAD_DIR / file_name
            if tgt_path.exists():
                if tgt_path.is_file(): os.remove(tgt_path)
                else: shutil.rmtree(tgt_path, ignore_errors=True)
            return

        s = handle.status()
        now = time.time()
        
        # CHECAGEM DO ANTI-ZUMBI (Se travou por mais de 5 minutos == 300 segundos sem progresso real)
        if s.total_done > last_progress_value:
            last_progress_value = s.total_done
            last_progress_time = now
        elif (now - last_progress_time) > 300: # 5 Minutos cravados
            await status_msg.edit_text(f"❌ **Abortado pelo Sistema Anti-Zumbi:** O torrent `{file_name}` ficou 5 minutos sem receber dados. Limpando lixo e indo pro próximo...")
            ses.remove_torrent(handle)
            tgt_path = DOWNLOAD_DIR / file_name
            if tgt_path.exists():
                if tgt_path.is_file(): os.remove(tgt_path)
                else: shutil.rmtree(tgt_path, ignore_errors=True)
            return

        if now - last_update > 4:
            state_str = ['queued', 'checking', 'metadata', 'downloading', 'finished', 'seeding', 'allocating'][s.state]
            # Formatação do Tempo Restante do Zumbi
            time_left_zumbi = 300 - int(now - last_progress_time)
            speed_mb = s.download_payload_rate / (1024 * 1024)
            current_mb = s.total_wanted_done / (1024 * 1024)
            total_mb = s.total_wanted / (1024 * 1024)
            text = (
                f"📥 **Download Torrent**\n\n"
                f"**Nome:** `{file_name}`\n"
                f"**Status:** {state_str.upper()}\n"
                f"⏳ **Progresso:** {s.progress*100:.1f}% ({current_mb:.1f} MB / {total_mb:.1f} MB)\n"
                f"🚀 **Velocidade:** {speed_mb:.1f} MB/s\n"
                f"👥 **Peers:** {s.num_peers} ativos\n\n"
                f"⏱️ _Zumbi TimeLeft: {time_left_zumbi}s_"
            )
            try: await status_msg.edit_text(text)
            except Exception: pass
            last_update = now
        await asyncio.sleep(1)

    await status_msg.edit_text(f"✅ **Download Concluído:** `{file_name}`!")
    
    # Processo final do arquivo
    target_path = DOWNLOAD_DIR / file_name
    files_to_upload = []
    if target_path.is_file(): files_to_upload.append(target_path)
    elif target_path.is_dir():
        for root, dirs, files in os.walk(target_path):
            for f in files:
                if f.lower().endswith(('.mp4', '.mkv', '.avi')):
                    files_to_upload.append(Path(root) / f)

    if not files_to_upload:
        await status_msg.edit_text("⚠️ Download concluído, nenhum vídeo encontrado. (Pasta limpada automatica)")
        return

    # ORDENAÇÃO DE SEQUÊNCIA: Garante que S01E01 venha antes de S01E02
    files_to_upload.sort(key=lambda x: x.name)

    async def run_single_upload(fpath):
        if cancel_current_torrent: return

        new_name = smart_rename(fpath.name)
        new_path = fpath.parent / new_name
        if fpath != new_path:
            os.rename(fpath, new_path)
            fpath = new_path

        upload_msg = await message.reply(f"☁️ Preparando envio: `{new_name}`...")
        size_bytes = fpath.stat().st_size
        if size_bytes > 4294967296: # 4GB LIMIT
            await upload_msg.edit_text(f"⚠️ `{new_name}` é maior que 4GB! Pulando...")
            return

        clean_title, year, quality = extract_metadata(fpath.name)

        is_serie, base_name, ep_tag = check_series_and_basename(new_name)
        search_title = base_name if is_serie else clean_title

        tmdb_data = await fetch_tmdb_data(search_title)

        if tmdb_data:
            final_title = tmdb_data['title']
            overview = tmdb_data['overview']
            release_year = tmdb_data['release_date'][:4] if tmdb_data['release_date'] else year
            poster_url = tmdb_data['poster']
        else:
            final_title = search_title
            overview = "Sinopse não encontrada no TMDB."
            release_year = year
            poster_url = None

        ano_str = f" ({release_year})" if release_year else ""

        # =========== ARQUITETURA VITRINE/GAVETA ===========
        actual_upload_target = destino_upload
        vitrine_caption = ""

        if is_serie:
            serie_db = await get_serie_channel(base_name)

            if not serie_db:
                await upload_msg.edit_text(f"📺 Criando Sub-Canal na nuvem para a Série: `{base_name}`...")
                try:
                    new_channel = await client.create_channel(f"📺 {final_title} - Acervo")
                    invite_link = await client.export_chat_invite_link(new_channel.id)
                    await save_serie_channel(base_name, new_channel.id, invite_link)
                    serie_db = {"chat_id": new_channel.id, "invite_link": invite_link}

                    vitrine_caption = (
                        f"🎬 **{final_title}**{ano_str} (Série)\n\n"
                        f"📝 **Sinopse:** {overview}\n\n"
                        f"📁 **Assistir Episódios:** [Acessar Pasta Exclusiva]({invite_link})"
                    )
                    if poster_url:
                        await client.send_photo(chat_id=destino_upload, photo=poster_url, caption=vitrine_caption)
                    else:
                        await client.send_message(chat_id=destino_upload, text=vitrine_caption, disable_web_page_preview=True)
                except Exception as e:
                    print(f"Falha ao criar subcanal para {base_name}: {e}")
                    pass

            if serie_db:
                actual_upload_target = serie_db["chat_id"]

            caption = f"🎥 **{final_title}** - `{ep_tag}`\n📺 `{quality}` | 📦 `{format_bytes(size_bytes)}`"
            poster_url_upload = None
        else:
            caption = (
                f"🎬 **{final_title}**{ano_str}\n\n"
                f"📝 **Sinopse:** {overview}\n\n"
                f"📦 **Tamanho:** `{format_bytes(size_bytes)}`\n"
                f"📺 **Qualidade:** `{quality}`\n\n"
                f"🤖 *Acervo VIP*"
            )
            poster_url_upload = poster_url

        try:
            await upload_msg.edit_text(f"⏳ Processando metadados de vídeo para streaming...")
            duration, width, height = await get_video_metadata(fpath)
            thumb_path = await generate_thumbnail(fpath, f"{fpath}.jpg")

            if poster_url_upload:
                await client.send_photo(chat_id=actual_upload_target, photo=poster_url_upload, caption=caption)

            # TRAVA DE SEGURANCA DO SEMAFORO ANTES DE INICIAR O UPLOAD PESADO
            async with upload_semaphore:
                sent_msg = await client.send_video(
                    chat_id=actual_upload_target,
                    video=str(fpath),
                    caption=caption if (is_serie or not poster_url_upload) else f"🎥 **Arquivo:** `{new_name}`",
                    duration=duration,
                    width=width,
                    height=height,
                    thumb=thumb_path,
                    supports_streaming=True,
                    progress=progress_for_pyrogram,
                    progress_args=(upload_msg, new_name, "Enviando Vídeo (Streaming)", time.time())
                )

            await save_upload(new_name, sent_msg.id, actual_upload_target, is_serie=is_serie)

            if thumb_path and os.path.exists(thumb_path):
                os.remove(thumb_path)
            await upload_msg.edit_text(f"✅ **Enviado {'para a sub-GAVETA' if is_serie else 'para a VITRINE'}!**")
        except Exception as e:
            if "cancelado" in str(e).lower():
                await upload_msg.edit_text(f"🛑 **Envio Cancelado:** `{new_name}` (Abortado pelo usuário)")
            else:
                await upload_msg.edit_text(f"❌ **Erro no envio:** `{new_name}`\n{str(e)}")

        try: os.remove(fpath)
        except: pass

    # Inicia todas as tarefas de upload de forma paralela usando Gather!
    upload_tasks = [run_single_upload(f) for f in files_to_upload]
    await asyncio.gather(*upload_tasks)

    await status_msg.delete()
    try: shutil.rmtree(target_path, ignore_errors=True)
    except: pass
    
    current_torrent_handle = None
    current_status_msg = None


async def queue_worker():
    print("👷‍♂️ Worker da fila de Torrent iniciado!")
    while True:
        task = await download_queue.get()
        try:
            if "link" in task:
                await process_torrent(task["client"], task["message"], link=task["link"])
            else:
                await process_torrent(task["client"], task["message"], torrent_file=task["file"])
        except Exception as e:
            msg = task.get("message")
            if msg:
                try:
                    await msg.reply(f"⚠️ **Falha/Abortado no Download:**\n{e}")
                except Exception:
                    pass
            print(f"Erro processando item da fila: {e}")
        finally:
            download_queue.task_done()


@app.on_message(filters.command("entrar", prefixes="/") & filters.me)
async def entrar_command(client, message):
    if len(message.command) < 2:
        return await message.reply("Uso: `/entrar <link_de_convite>`")
    link = message.command[1]
    status = await message.reply("⏳ Tentando entrar no grupo/canal...")
    try:
        chat = await client.join_chat(link)
        await status.edit_text(f"✅ **Sucesso!** Entrei em sob o ID `{chat.id}`\n**Nome:** {chat.title}")
    except Exception as e:
        await status.edit_text(f"❌ **Erro ao entrar:**\n`{str(e)}`")

@app.on_message(filters.command("clonar", prefixes="/") & filters.me)
async def clonar_command(client, message):
    if len(message.command) < 2:
        return await message.reply("Uso: `/clonar <link_da_mensagem>` ou `/clonar <canal_id> <quantidade>`")

    # Verifica se o primeiro argumento parece um link do Telegram ou formato ID/MsgID
    # Ex: https://t.me/c/1977503172/90 ou 1895992934/19838
    match = re.search(r'(?:c/)?(-?\d+)/(\d+)', message.command[1])

    if match and len(message.command) == 2:
        chat_id_str, msg_id_str = match.group(1), match.group(2)
        origem_id = int(chat_id_str)

        # Ajusta IDs de canais privados copiados do link que não possuem prefixo -100
        if not str(origem_id).startswith("-100") and not str(origem_id).startswith("-"):
            origem_id = int(f"-100{origem_id}")

        msg_id = int(msg_id_str)
        status = await message.reply(f"🧬 **Iniciando Clonagem Específica!**\nCanal: `{origem_id}` | MSG: `{msg_id}`")

        try:
            msg = await client.get_messages(chat_id=origem_id, message_ids=msg_id)
            if msg and not msg.empty and (msg.video or msg.document or msg.photo):
                await msg.copy(destino_upload)
                return await status.edit_text("✅ **Mídia clonada com sucesso!**")
            else:
                return await status.edit_text("❌ **Falha:** Mensagem não encontrada ou não possui vídeos/fotos/documentos.")
        except Exception as e:
            return await status.edit_text(f"❌ **Erro fatal ao clonar mensagem:**\n`{str(e)}`")

    # Caso contrário, fluxo de clonagem em lote
    if len(message.command) < 3:
        return await message.reply("Uso em lote: `/clonar <id_do_canal> <quantidade>`\nUso unitário: `/clonar https://t.me/c/1977503172/90`")

    try:
        origem_id = int(message.command[1])
        quantidade = int(message.command[2])
    except ValueError:
        return await message.reply("❌ IDs ou Quantidade devem ser números inteiros.")

    status = await message.reply(f"🧬 **Iniciando Clonagem!**\nAlvo: `{origem_id}`\nQuantidade: `{quantidade}` mídias.")

    count = 0
    try:
        # Pega as últimas mensagens de vídeo/documento
        async for msg in client.get_chat_history(origem_id, limit=quantidade):
            if msg.video or msg.document or msg.photo:
                try:
                    await msg.copy(destino_upload)
                    count += 1
                    await asyncio.sleep(1.5)  # Evitar FloodWait
                except Exception as e:
                    print(f"Erro copiando mensagem: {e}")
                    pass
        await status.edit_text(f"✅ **Clonagem Finalizada!**\nMídias copiadas: `{count}`")
    except Exception as e:
        await status.edit_text(f"❌ **Erro Fatal na Clonagem:**\n`{str(e)}`")

# ==================== COMANDOS TELEGRAM ====================





@app.on_message(filters.command("setcanal", prefixes="/") & filters.me)
async def set_canal_command(client, message):
    if len(message.command) < 2: return await message.reply("Uso: `/setcanal -100XXXXXXXXXX`")
    try:
        new_id = int(message.command[1])
        global destino_upload; destino_upload = new_id
        await message.reply(f"✅ Destino alterado para: `{destino_upload}`")
    except ValueError: await message.reply("❌ ID Inválido.")

@app.on_message(filters.command("torrent", prefixes="/") & filters.me)
async def torrent_command(client, message):
    if len(message.command) < 2: return await message.reply("Uso: `/torrent <magnet_link>`")
    link = " ".join(message.command[1:])
    q_size = download_queue.qsize()
    await message.reply(f"⏳ **Link adicionado à fila!** (Posição: {q_size + 1})")
    await download_queue.put({"client": client, "message": message, "link": link})

@app.on_message(filters.document & filters.me)
async def torrent_file_handler(client, message):
    if message.document.file_name.endswith(".torrent"):
        status = await message.reply("⬇️ Baixando arquivo .torrent para a fila...")
        file_path = await message.download(file_name=str(DOWNLOAD_DIR) + "/")
        q_size = download_queue.qsize()
        await status.edit_text(f"⏳ **Torrent adicionado à fila!** (Posição: {q_size + 1})")
        await download_queue.put({"client": client, "message": message, "file": file_path})

@app.on_message(filters.command("cancelar", prefixes="/") & filters.me)
async def cancelar_command(client, message):
    global cancel_current_torrent
    if not current_torrent_handle and download_queue.empty():
        return await message.reply("⚠️ Não há nenhum torrent rodando no momento nem itens na fila!")
    
    cancel_current_torrent = True
    
    # Se quiser limpar a fila inteira ao mesmo tempo: /cancelar fila
    clean_queue_count = 0
    if len(message.command) > 1 and message.command[1].lower() == "fila":
        while not download_queue.empty():
            download_queue.get_nowait()
            download_queue.task_done()
            clean_queue_count += 1
            
    res_text = "🛑 **Sinal de cancelamento enviado!** O torrent atual e todo seu registro temporário serão abortados."
    if clean_queue_count > 0:
        res_text += f"\n🗑️ A fila também foi esvaziada: `{clean_queue_count}` itens removidos."
        
    await message.reply(res_text)


@app.on_message(filters.command("status", prefixes="/") & filters.me)
async def status_command(client, message):
    # Uso do RAM Disk
    total, used, free = shutil.disk_usage(DOWNLOAD_DIR)
    
    db_items = await get_all_uploads()
    total_enviados = len(db_items)
    
    q_size = download_queue.qsize()
    if current_torrent_handle:
        rodando_agora = f"Em processamento: `{current_torrent_handle.status().name}`"
    else:
        rodando_agora = "Ocioso."

    status_text = (
        f"📊 **Painel de Controle VPS**\n\n"
        f"🖥️ **Memória RAMDisk:**\n"
        f"├ Usado: `{format_bytes(used)}`\n"
        f"└ Livre: `{format_bytes(free)}`\n\n"
        f"🚧 **Andamento Atual:**\n"
        f"├ {rodando_agora}\n"
        f"└ Fila de Espera: `{q_size} items`\n\n"
        f"📁 **Banco de Dados:**\n"
        f"└ Total no Acervo VIP: `{total_enviados} envios`"
    )
    await message.reply(status_text)

@app.on_message(filters.command("limpar", prefixes="/") & filters.me)
async def limpar_command(client, message):
    await message.reply("🧹 **Realizando limpeza profunda do sistema...**")
    limpados = 0
    for file in DOWNLOAD_DIR.iterdir():
        try:
            if file.is_file(): file.unlink()
            elif file.is_dir(): shutil.rmtree(file)
            limpados += 1
        except Exception: pass
    
    # Tentativa de Esvaziar a Queue caso se queria flush geral
    clean_queue_count = 0
    if len(message.command) > 1 and message.command[1].lower() == "fila":
        while not download_queue.empty():
            download_queue.get_nowait()
            download_queue.task_done()
            clean_queue_count += 1
            
    res_text = f"✅ Limpeza concluída!\nLixo removido do RAMDisk: `{limpados} itens`."
    if clean_queue_count > 0:
        res_text += f"\nItens esvaziados da fila: `{clean_queue_count}`."
        
    await message.reply(res_text)

@app.on_message(filters.command("gerar_indice", prefixes="/") & filters.me)
async def gerar_indice_command(client, message):
    items = await get_all_uploads()
    if not items:
        return await message.reply("⚠️ Nenhum upload salvo no banco de dados!")
    
    status = await message.reply("⏳ Gerando índice formatado...")
    
    texto = "🎬 **CATÁLOGO DO ACERVO VIP** 🎬\n\n"
    for item in items:
        # DB format: filename, message_id, chat_id, is_serie
        filename, msg_id, chat_id, _ = item
        
        # Criação do link base
        # IDs de canais ou grupos para o link clicável
        chat_id_str = str(chat_id).replace("-100", "") 
        link = f"https://t.me/c/{chat_id_str}/{msg_id}"
        
        # Limpa o filme para exibir bonitinho
        clean_name, _, _ = extract_metadata(filename)
        texto += f"🍿 [{clean_name}]({link})\n"

    # Se o texto for gigante (Limite Telegram é 4096), precisamos dividir (aqui apenas corta por segurança, vc pode avançar paginando dps)
    if len(texto) > 4000:
        texto = texto[:4000] + "\n...(Índice truncado por tamanho limite)..."
        
    await status.edit_text(texto, disable_web_page_preview=True)


async def main():
    await init_db()
    await app.start()
    asyncio.create_task(queue_worker())
    asyncio.create_task(rss_monitor_loop(app, lambda: destino_upload))
    from pyrogram import idle
    await idle()
    await app.stop()

if __name__ == "__main__":
    print("🚀 Iniciando UserBot de Torrents v2 (ANTI-ZUMBI)!")
    app.run(main())

