import asyncio
import aiohttp
import xml.etree.ElementTree as ET
from pathlib import Path

RSS_STATE_FILE = Path("/home/ubuntu/torrent_telegram_bot/rss_state.txt")

async def rss_monitor_loop(client, get_destino_func):
    url = "https://filmestorrent.tv/feed/"
    print("🔔 Monitoramento de RSS Iniciado!")

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30) as resp:
                    if resp.status == 200:
                        xml_text = await resp.text()

                        # Fix encoding in case it crashes ET
                        xml_text = xml_text.strip()
                        if xml_text.startswith("<?xml"):
                            end_decl = xml_text.find("?>")
                            xml_text = xml_text[end_decl+2:].strip()

                        # Limpeza básica em caso de erros de HTML injetados no XML
                        try:
                            root = ET.fromstring(xml_text)
                        except ET.ParseError:
                            # Se falhar o parse do XML, usaremos regex como fallback ninja
                            import re
                            titles = re.findall(r'<item>.*?<title>(.*?)</title>', xml_text, re.DOTALL)
                            links = re.findall(r'<item>.*?<link>(.*?)</link>', xml_text, re.DOTALL)
                            if titles and links:
                                top_title = titles[0].replace("<![CDATA[", "").replace("]]>", "").strip()
                                top_link = links[0].strip()
                                root = None
                                items = [{'title': top_title, 'link': top_link, 'guid': top_link}]
                            else:
                                root = None
                                items = []
                        else:
                            items = []
                            for item in root.findall('.//item'):
                                t = item.find('title').text
                                l = item.find('link').text
                                g_elem = item.find('guid')
                                g = g_elem.text if g_elem is not None else l
                                items.append({'title': t, 'link': l, 'guid': g})

                        if items:
                            top_item = items[0]
                            title = top_item['title']
                            link = top_item['link']
                            guid = top_item['guid']

                            # Logica para não repetir
                            last_guid = ""
                            if RSS_STATE_FILE.exists():
                                with open(RSS_STATE_FILE, "r", encoding="utf-8") as f:
                                    last_guid = f.read().strip()

                            if guid and guid != last_guid:
                                with open(RSS_STATE_FILE, "w", encoding="utf-8") as f:
                                    f.write(guid)

                                # Só notifica se não for o primeiro loop da vida do bot
                                if last_guid != "":
                                    msg = f"🔔 **NOVO LANÇAMENTO DETECTADO**\n\n🎬 `{title}`\n🔗 [Acessar a Página]({link})\n\n_Para tentar baixar, acesse, copie o magnet link e me envie com_ `/torrent <link>`"
                                    # Pega o destino de upload em tempo real
                                    chat_destino = get_destino_func()
                                    await client.send_message(chat_id=chat_destino, text=msg, disable_web_page_preview=True)
        except Exception as e:
            print(f"Erro RSS Monitor: {e}")

        # Espera 5 minutos para sondar o site de novo
        await asyncio.sleep(300)
