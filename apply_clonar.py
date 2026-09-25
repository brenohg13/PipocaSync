import re

with open('/home/ubuntu/torrent_telegram_bot/torrent_bot.py', 'r') as f:
    code = f.read()

new_clonar = r"""@app.on_message(filters.command("clonar", prefixes="/") & filters.me)
async def clonar_command(client, message):
    if len(message.command) < 2:
        return await message.reply("Uso:\n`/clonar <id_do_canal> <qtd>`\nOU\n`/clonar <link_da_mensagem>`")
    
    args = message.command[1:]
    
    # Modo de Link Único Direto (ex: /clonar https://t.me/c/1977503172/90)
    if args[0].startswith("http") or "t.me/" in args[0]:
        link = args[0]
        status = await message.reply(f"🧬 **Acessando Link Diretamente...**")
        try:
            match_priv = re.search(r't\.me/c/(\d+)/(\d+)', link)
            match_pub = re.search(r't\.me/([^/]+)/(\d+)', link)
            
            origem_id = None
            msg_id = None
            
            if match_priv:
                origem_id = int("-100" + match_priv.group(1))
                msg_id = int(match_priv.group(2))
            elif match_pub:
                origem_id = match_pub.group(1)
                msg_id = int(match_pub.group(2))
            else:
                return await status.edit_text("❌ Link não reconhecido. Formato inválido.")

            # Buscar a mensagem
            msg_obj = await client.get_messages(origem_id, msg_id)
            if not msg_obj or msg_obj.empty:
                return await status.edit_text("❌ Mensagem não encontrada. Tem certeza que o bot entrou nesse canal?")
            
            await msg_obj.copy(destino_upload)
            return await status.edit_text(f"✅ **Alvo Clonado com Sucesso!** (Post Único)")
            
        except Exception as e:
            return await status.edit_text(f"❌ **Erro na Clonagem Direta:**\n`{str(e)}`")

    # Modo Lote: clonar X mensagens do ID
    if len(args) < 2:
        return await message.reply("Uso em lote: `/clonar -100XXXXXXX 10`")
        
    try:
        origem_id = int(args[0])
        quantidade = int(args[1])
    except ValueError:
        return await message.reply("❌ IDs ou Quantidade devem ser números inteiros.")
    
    status = await message.reply(f"🧬 **Iniciando Clonagem Lote!**\nAlvo: `{origem_id}`\nQtd: `{quantidade}` mídias.")
    
    count = 0
    try:
        async for msg in client.get_chat_history(origem_id, limit=quantidade):
            if msg.video or msg.document or msg.photo:
                try:
                    await msg.copy(destino_upload)
                    count += 1
                    await asyncio.sleep(1.5)
                except Exception:
                    pass
        await status.edit_text(f"✅ **Clonagem Finalizada!**\nMídias copiadas: `{count}`")
    except Exception as e:
        await status.edit_text(f"❌ **Erro Fatal na Clonagem:**\n`{str(e)}`")"""

code = re.sub(
    r'@app\.on_message\(filters\.command\("clonar", prefixes="/"\) & filters\.me\)\nasync def clonar_command\(client, message\):.*?except Exception as e:\n\s+await status\.edit_text\(f"❌ \*\*Erro Fatal na Clonagem:\*\*\\n`\{str\(e\)\}`"\)',
    new_clonar,
    code,
    flags=re.DOTALL
)

with open('/home/ubuntu/torrent_telegram_bot/torrent_bot.py', 'w') as f:
    f.write(code)

print("Funcao Clonar atualizada para suportar links diretos!")
