import asyncio
import os
import subprocess
from pathlib import Path

async def get_video_metadata(filepath):
    """Obtem duração (s), largura e altura usando ffprobe"""
    duration, width, height = 0, 0, 0
    try:
        # Pega duraçao
        result = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(filepath),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, _ = await result.communicate()
        if out: duration = int(float(out.decode().strip()))

        # Pega resolução
        result = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(filepath),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, _ = await result.communicate()
        if out: 
            wh = out.decode().strip().split('x')
            width, height = int(wh[0]), int(wh[1])
            
    except Exception as e:
        print(f"Erro no ffprobe: {e}")
        
    return duration, width, height

async def generate_thumbnail(filepath, output_path):
    """Gera uma miniatura em 5% do video para evitar pegar introduçao escura"""
    try:
        duration, _, _ = await get_video_metadata(filepath)
        time_mark = "00:00:05" if duration < 100 else str(int(duration * 0.05)) # Pega logo o começo do filme
        
        result = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", str(filepath), "-ss", str(time_mark), "-vframes", "1", str(output_path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await result.communicate()
        if os.path.exists(output_path):
            return output_path
    except Exception as e:
        print(f"Erro ao gerar thumbnail: {e}")
    return None
