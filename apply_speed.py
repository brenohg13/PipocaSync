import re

with open('/home/ubuntu/torrent_telegram_bot/torrent_bot.py', 'r') as f:
    bot_content = f.read()

# Substituir Progresso de Download do Torrent
old_download_text = """            text = (
                f"📥 **Download Torrent**\\n\\n"
                f"**Nome:** `{file_name}`\\n"
                f"**Status:** {state_str.upper()}\\n"
                f"**Progresso:** {s.progress*100:.1f}% de {format_bytes(s.total_wanted)}\\n"
                f"**Velocidade:** {format_bytes(s.download_rate)}/s\\n"
                f"**Peers:** {s.num_peers} ativos\\n"
                f"\\n⚠️ _Anti-Zumbi: Aborta se parar em {time_left_zumbi}s_"
            )"""

new_download_text = """            speed_mb = s.download_payload_rate / (1024 * 1024)
            current_mb = s.total_wanted_done / (1024 * 1024)
            total_mb = s.total_wanted / (1024 * 1024)
            text = (
                f"📥 **Download Torrent**\\n\\n"
                f"**Nome:** `{file_name}`\\n"
                f"**Status:** {state_str.upper()}\\n"
                f"⏳ **Progresso:** {s.progress*100:.1f}% ({current_mb:.1f} MB / {total_mb:.1f} MB)\\n"
                f"🚀 **Velocidade:** {speed_mb:.1f} MB/s\\n"
                f"👥 **Peers:** {s.num_peers} ativos\\n\\n"
                f"⏱️ _Zumbi TimeLeft: {time_left_zumbi}s_"
            )"""
            
bot_content = bot_content.replace(old_download_text, new_download_text)

# Substituir Visual Progresso Upload
old_upload_text = """        text = f"☁️ **{prefix}**\\n\\n**Arquivo:** `{file_name}`\\n**Progresso:** {percent:.1f}% ({format_bytes(current)} / {format_bytes(total)})\\n🚀 **Velocidade Upload:** {speed_str}"
        try:
            await status_msg.edit_text(text)"""
            
new_upload_text = """        text = f"☁️ **{prefix}**\\n\\n**Arquivo:** `{file_name}`\\n⏳ **Progresso:** {percent:.1f}% ({format_bytes(current)} / {format_bytes(total)})\\n🚀 **Velocidade:** {speed_str}"
        try:
            await status_msg.edit_text(text)"""

bot_content = bot_content.replace(old_upload_text, new_upload_text)

with open('/home/ubuntu/torrent_telegram_bot/torrent_bot.py', 'w') as f:
    f.write(bot_content)
