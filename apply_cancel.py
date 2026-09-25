import re

with open('/home/ubuntu/torrent_telegram_bot/torrent_bot.py', 'r') as f:
    code = f.read()

new_prog = """async def progress_for_pyrogram(current, total, status_msg, file_name, prefix="", start_time=None):
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

        text = f"☁️ **{prefix}**\\n\\n**Arquivo:** `{file_name}`\\n⏳ **Progresso:** {percent:.1f}% ({format_bytes(current)} / {format_bytes(total)})\\n🚀 **Velocidade Upload:** {speed_str}"
        try:
            await status_msg.edit_text(text)
            progress_for_pyrogram.last_update = now
        except MessageNotModified:
            pass
        except Exception: 
            pass
"""

code = re.sub(r'async def progress_for_pyrogram.*?except Exception: pass', new_prog, code, flags=re.DOTALL)

with open('/home/ubuntu/torrent_telegram_bot/torrent_bot.py', 'w') as f:
    f.write(code)
