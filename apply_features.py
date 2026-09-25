import re

with open('/home/ubuntu/torrent_telegram_bot/torrent_bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add global variable for abort mechanism
content = content.replace(
    'download_queue = asyncio.Queue()',
    'download_queue = asyncio.Queue()\nabort_current_download = False'
)

# 2. Add Anti-Zombie to Metadata loop (5 min = 300s)
old_meta_loop = '''    while not handle.status().has_metadata:
        await asyncio.sleep(1)'''
new_meta_loop = '''    global abort_current_download
    abort_current_download = False
    start_meta_time = time.time()

    while not handle.status().has_metadata:
        if abort_current_download:
            ses.remove_torrent(handle)
            raise Exception("🛑 Abortado manualmente pelo usuário (/cancelar).")
        if time.time() - start_meta_time > 300:  # 5 Minutos
            ses.remove_torrent(handle)
            raise Exception("🧟 Timeout: Magnet Link morto, não conseguiu metadados em 5 minutos.")
        await asyncio.sleep(1)'''
content = content.replace(old_meta_loop, new_meta_loop)

# 3. Add Anti-Zombie to Download loop (5 min = 300s sem avanço)
old_dl_loop = '''    while handle.status().state != lt.torrent_status.seeding:
        s = handle.status()
        now = time.time()
        if now - last_update > 4:'''
new_dl_loop = '''    last_progress_time = time.time()
    last_total_done = 0

    while handle.status().state != lt.torrent_status.seeding:
        s = handle.status()
        now = time.time()
        
        # Checagens do Anti-Zumbi / Cancela
        if abort_current_download:
            ses.remove_torrent(handle)
            raise Exception("🛑 Abortado manualmente pelo usuário (/cancelar).")
            
        if s.total_done > last_total_done:
            last_total_done = s.total_done
            last_progress_time = now
        elif now - last_progress_time > 300: # 5 Minutos cravado
            ses.remove_torrent(handle)
            raise Exception("🧟 Timeout Zumbi: O download travou por falta de seeds há 5 minutos. Descartando e indo pro próximo!")

        if now - last_update > 4:'''
content = content.replace(old_dl_loop, new_dl_loop)

# 4. Enhance Worker queue to catch the new Exception and warn the user
old_worker = '''async def queue_worker():
    print("👷‍♂️ Worker da fila de Torrent iniciado!")
    while True:
        task = await download_queue.get()
        try:
            if "link" in task:
                await process_torrent(task["client"], task["message"], link=task["link"])
            else:
                await process_torrent(task["client"], task["message"], torrent_file=task["file"])
        except Exception as e:
            print(f"Erro processando item da fila: {e}")
        finally:
            download_queue.task_done()'''

new_worker = '''async def queue_worker():
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
                    await msg.reply(f"⚠️ **Falha/Abortado no Download:**\\n{e}")
                except Exception:
                    pass
            print(f"Erro processando item da fila: {e}")
        finally:
            download_queue.task_done()'''
content = content.replace(old_worker, new_worker)

# 5. Inject new commands
commands = '''

# ================= NOVO PACOTE DE COMANDOS ADMINISTRATIVOS =================

@app.on_message(filters.command("cancelar", prefixes="/") & filters.me)
async def cancel_command(client, message):
    global abort_current_download
    abort_current_download = True
    await message.reply("🛑 Sinal de cancelamento enviado! O download no topo da fila será morto instantaneamente.")

@app.on_message(filters.command("limpar", prefixes="/") & filters.me)
async def clear_command(client, message):
    global download_queue
    # Limpa a fila
    q_size = download_queue.qsize()
    download_queue = asyncio.Queue()
    
    # Limpa os arquivos fisicos da RAM
    import shutil
    try:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        msg_text = f"🧹 **Limpeza Total Realizada!**\\n- Fila Descartada ({q_size} itens cancelados)\\n- Memória RAM Disk Zerada"
    except Exception as e:
        msg_text = f"❌ Erro ao limpar RAM Disk: {e}"
    await message.reply(msg_text)

@app.on_message(filters.command("status", prefixes="/") & filters.me)
async def status_command(client, message):
    import shutil
    import aiosqlite
    try:
        total, used, free = shutil.disk_usage(DOWNLOAD_DIR)
        q_size = download_queue.qsize()
        
        total_uploads = 0
        async with aiosqlite.connect("/home/ubuntu/torrent_telegram_bot/bot_database.db") as db:
             async with db.execute("SELECT COUNT(*) FROM uploads") as cursor:
                  r = await cursor.fetchone()
                  total_uploads = r[0] if r else 0
                  
        status_text = (
            f"📊 **Status da Operação (VPS)**\\n\\n"
            f"🛸 **Memória RAM Disk:**\\n"
            f"  • Usado: `{format_bytes(used)}`\\n"
            f"  • Livre: `{format_bytes(free)}`\\n"
            f"  • Máximo: `{format_bytes(total)}`\\n\\n"
            f"⏱️ **Fila Atual:** `{q_size}` aguardando.\\n"
            f"📦 **Uploads Bem Sucedidos:** `{total_uploads}` cadastrados."
        )
        await message.reply(status_text)
    except Exception as e:
        await message.reply(f"❌ Erro status: {e}")

@app.on_message(filters.command("gerar_indice", prefixes="/") & filters.me)
async def index_command(client, message):
    await message.reply("⏳ Gerando catálogo mágico do SQLite...")
    try:
        itens = await get_all_uploads()
        if not itens:
            return await message.reply("📭 Nenhum filme catalogado no banco de dados!")
            
        lines = ["🎬 **CATÁLOGO DO CANAL** 🎬\\n"]
        for row in itens:
            filename, message_id, chat_id, is_serie = row
            cid = str(chat_id).replace("-100", "")
            link = f"https://t.me/c/{cid}/{message_id}"
            lines.append(f"▪️ [{filename}]({link})")
            
        full_text = "\\n".join(lines)
        
        # Splitting para evitar limite do Telegram de 4096 char
        for i in range(0, len(full_text), 4000):
            await message.reply(full_text[i:i+4000], disable_web_page_preview=True)
            
    except Exception as e:
        await message.reply(f"❌ Erro ao puxar DB: {e}")

# ===========================================================================
'''

content = content.replace(
    '@app.on_message(filters.command("setcanal", prefixes="/") & filters.me)',
    commands + '\n@app.on_message(filters.command("setcanal", prefixes="/") & filters.me)'
)

with open('/home/ubuntu/torrent_telegram_bot/torrent_bot.py', 'w', encoding='utf-8') as f:
    f.write(content)
