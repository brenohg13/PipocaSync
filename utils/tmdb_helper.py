import re
from tmdbv3api import TMDb, Movie, TV
from pathlib import Path

def init_tmdb(api_key):
    tmdb = TMDb()
    tmdb.api_key = api_key
    tmdb.language = 'pt-BR'

def clean_filename(filename):
    """Limpa o nome do arquivo para melhorar a busca no TMDB"""
    name = Path(filename).stem
    
    # Remove colchetes e parenteses (ex: [RARBG], (2023))
    name = re.sub(r'\[.*?\]|\(.*?\)', ' ', name)
    
    # Remove resoluções e metadados
    name = re.sub(r'(1080p|720p|2160p|4k|HDR)', '', name, flags=re.IGNORECASE)
    name = re.sub(r'(WEBRip|Bluray|BDRip|WEB-DL|WEB|x264|x265|HEVC|Dublado|Legendado|Dual|Audio|DDP5\.1|H\.?264)', '', name, flags=re.IGNORECASE)
    
    # Remove a assinatura de Rippers gringos no final (ex: -ROSE, -NTb)
    name = re.sub(r'-[a-zA-Z0-9_]+$', '', name)
    
    # Troca pontos e hifens por espaços
    name = name.replace('.', ' ').replace('_', ' ').replace('-', ' ')
    name = re.sub(r'\s+', ' ', name).strip()
    
    # Extrai ano se houver
    year_match = re.search(r'(19\d{2}|20\d{2})', name)
    year = year_match.group(1) if year_match else None
    name = re.sub(r'(19\d{2}|20\d{2})', '', name).strip()

    return name, year

def get_metadata(filename):
    clean_name, year = clean_filename(filename)
    movie = Movie()
    tv = TV()
    
    print(f"Buscando capa e infos para: {clean_name}")
    
    serie_match = re.search(r'[Ss](\d{1,2})[Ee](\d{1,2})', filename, re.IGNORECASE)
    
    try:
        if serie_match:
            s_name = re.split(r'[Ss]\d{1,2}[Ee]\d{1,2}', clean_name, flags=re.IGNORECASE)[0].strip()
            results = tv.search(s_name)
            if results:
                item = next((r for r in results), None)
                if item:
                    caption_text = f"📺 **{item.name}**\n\n"
                    caption_text += f"**Temporada:** {serie_match.group(1)} | **Episódio:** {serie_match.group(2)}\n"
                    caption_text += f"**Nota TMDB:** ⭐ {item.vote_average:.1f}/10\n\n"
                    if hasattr(item, 'overview') and item.overview:
                        caption_text += f"_{item.overview}_\n\n"
                    
                    poster_path = f"https://image.tmdb.org/t/p/w500{item.poster_path}" if hasattr(item, 'poster_path') and item.poster_path else None
                    return caption_text, poster_path, True
        else:
            if year:
                results = movie.search(clean_name, year=year)
            else:
                results = movie.search(clean_name)
            
            if results:
                item = next((r for r in results), None)
                if item:
                    caption_text = f"🎬 **{item.title}**"
                    if hasattr(item, 'release_date') and item.release_date:
                        caption_text += f" ({item.release_date[:4]})"
                    caption_text += "\n\n"
                    caption_text += f"**Nota TMDB:** ⭐ {item.vote_average:.1f}/10\n\n"
                    if hasattr(item, 'overview') and item.overview:
                        caption_text += f"_{item.overview}_\n\n"
                    
                    poster_path = f"https://image.tmdb.org/t/p/w500{item.poster_path}" if hasattr(item, 'poster_path') and item.poster_path else None
                    return caption_text, poster_path, False
    except Exception as e:
        print(f"Erro ao buscar TMDB: {e}")
    
    return f"🎥 **{filename}**", None, False
