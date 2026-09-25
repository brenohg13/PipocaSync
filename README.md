# 🍿 PipocaSync

**PipocaSync** é um poderoso UserBot em Python para Telegram focado em lidar com distribuição contínua e turbinada de mídia. Ele se encarrega de ler URLs ou Magnet Links de Torrents, baixá-los de forma estruturada no seu ambiente servidor (VPS) e orquestrar um despejo ultrarrápido dessa mídia diretamente no coração do seu Telegram mantendo um fluxo arquitetural moderno de *"Vitrine & Gaveta"*.

---

## ⚡ Principais Funcionalidades

* 🚀 **Turbo Upload (Async Semaphore):** O gargalo do `send_video` de episódios foi dizimado! O envio que demoraria horas rodando episódio por episódio na fila agora faz a injeção em paralelo de até **3 envios simultâneos** pro Telegram sem congelar a fila principal garantindo entregas mais rápidas de temporada completas.
* 📦 **Arquitetura Vitrine & Gaveta:** Chega de um Canal VIP bagunçado.
  * **A Gaveta:** Toda vez que um seriado é enviado, o bot cria **instantaneamente um subcanal silencioso** focado unicamente em guardar o arquivo de vídeo pesado + os links de controle.
  * **A Vitrine:** No canal inicial que o bot gerencia, ao invés da temporada pesar a timeline dos seus membros, ele despeja a Capa Inteligente da Temporada (poster), a Sinopse em PT-BR limpa e insere automaticamente um link direto para o Canal-Gaveta que acabou de criar.
* 🧲 **O Clone:** Suporte completo para links do tipo `t.me/c/id/msg`. O bot identifica mensagens externas que você comanda via `/clonar <link>`, captura e salva dentro do seu ecossistema.
* 📡 **RSS Radar Stealth:** O Pipoca corre solto nas sombras. Fica ouvindo endpoints do site *filmestorrent.tv* a cada 5 minutinhos e te chama primeiro no PV sempre que as novidades fresquinhas caem lá, te entregando a URL sem você fazer esforço.
* 🎬 **Smart TMDB ID & Renaming:** Uma engrenagem de RegEx polida pega nomes feios dos torrents (ex: *TThe.W4lking.D34d.S12E01.720p.Mkv*) e transforma perfeitamente limpando as chaves pro *TMDB API*, caçando a Capa Brasileira em HD e o Resumo correto da obra de cinema.

---

## ⚙️ Tecnologias e Bibliotecas

* **Python 3.12+**
* [Pyrogram](https://docs.pyrogram.org/) via MTProto para UserBot Session.
* [Libtorrent](https://libtorrent.org/) manipulando DHT para resolver o peer-to-peer.
* [TMDB API] Integrador de Capas e Informações Nativas.
* `aiosqlite` para as tabelas das nossas *Series_Channels* que conectam Nomes às suas Gavetas.
* `Asyncio` ditando o ritmo pra não faltar ar pro Core do Servidor.

---

## 🚀 Como Executar

> **Nota:** Protegido contra PEP 668 *Externally-Managed-Environment*, então usamos virtual environments explícitos.

**1. Clone e Prepare o VENV**
```bash
git clone https://github.com/brenohg13/PipocaSync.git
cd PipocaSync
python3 -m venv venv
```

**2. Instale**
```bash
venv/bin/pip install -r requirements.txt
# Ou manualmente as deps padrões do projeto
venv/bin/pip install pyrogram tgcrypto libtorrent aiohttp aiosqlite requests
```

**3. Configure as Credenciais**
Modifique seu arquivo `config.ini` mantendo a estrutura original (Nunca suba isso nas nuvens):
```ini
[pyrogram]
api_id = SEU_API_ID
api_hash = SUA_API_HASH

[tmdb]
api_key = SUA_API_KEY
```

**4. O Tiro de Partida em Background**
```bash
./start_bot.sh
```
Fique de olho em `tail -f bot.log` pro acompanhamento visual.

---

## 🔮 Roadmap / Ideias para o Futuro (O que pode ser alterado/melhorado)

1. **Dashboard UI de Progresso no Chat:** O bot poderia atualizar ("Editar a mensagem") de tempos em tempos num Torrent longo pra você ver a _Status Bar_ correndo até o fim via inline-text com porcentagens (`[████████--] 80%`).
2. **Auto-Extração e Embid de Legendas:** Torrents gringos que pedem legendas separadas (SRT) poderiam ser encapsulados nativamente pelo PipocaSync já num arquivo MUXADO direto usando FFMPEG antes do `send_video`.
3. **Cortes de Vídeo e Samples:** Ferramenta fatiando os primeiros 10-20 segundos do filme criando Gifs nativos do Telegram (SAMPLES) pra enviar junto ao Poster de lançamento na **Vitrine**.
4. **Resolução Inteligente (The Size Limiter):** Usuários Free no Telegram limitam-se a 2GB por arquivo. Podemos adaptar o bot pro upload premium via Telegram API (4GB files) bloqueando Torrents Remux.
5. **Busca e Sugestão em botões embutidos ("Inline Keyboards"):** Se a resposta do TMDB vier errada em filmes parecidos, o bot devolve inline buttons pro Usuário apontar se é "Filme de 1999" ou "Filme Remake de 2024".

---
*Esculpido e desenhado para subir as mais pesadas temporadas. Aproveite seu pacote de pipocas! 🍿*