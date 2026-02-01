from fastapi import FastAPI, Form, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
import os
import uuid
import time
import glob

app = FastAPI()

# Разрешаем CORS для корректной работы интерфейса
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="templates")

def clear_old_files():
    # Очистка временных файлов при запуске
    files = glob.glob("file_*.mp4") + glob.glob("file_*.mp3")
    for f in files:
        try:
            os.remove(f)
        except:
            pass

@app.on_event("startup")
async def startup_event():
    clear_old_files()

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/get_trending")
async def get_trending():
    try:
        # Быстрый поиск популярных видео для ленты
        ydl_opts = {
            'quiet': True, 
            'extract_flat': True, 
            'playlistend': 15, 
            'skip_download': True,
            'nocheckcertificate': True
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info("ytsearch15:popular videos", download=False)
            videos = []
            for entry in info.get('entries', []):
                if entry.get('id'):
                    videos.append({
                        'title': entry.get('title')[:40],
                        'thumbnail': f"https://i.ytimg.com/vi/{entry.get('id')}/mqdefault.jpg",
                        'url': f"https://www.youtube.com/watch?v={entry.get('id')}"
                    })
            return {"videos": videos}
    except Exception as e:
        return {"videos": []}

@app.post("/get_formats")
async def get_formats(url: str = Form(...)):
    try:
        # Ускоренный анализ ссылки специально для Vercel
        ydl_opts = {
            'quiet': True, 
            'nocheckcertificate': True, 
            'no_warnings': True,
            'skip_download': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Сначала берем общую инфу
            info = ydl.extract_info(url, download=False)
            formats = []
            
            # Фильтруем форматы только с видео и разрешением
            for f in info.get('formats', []):
                if f.get('vcodec') != 'none' and f.get('height'):
                    h = f.get('height')
                    formats.append({
                        "id": f['format_id'], 
                        "res": f"{h}p (mp4)", 
                        "h": h
                    })
            
            # Убираем дубликаты разрешений
            unique_fmts = {f['res']: f for f in formats}.values()
            sorted_fmts = sorted(unique_fmts, key=lambda x: x['h'], reverse=True)
            
            return {
                "title": info.get('title'),
                "formats": sorted_fmts, 
                "thumbnail": info.get('thumbnail')
            }
    except Exception as e:
        return {"error": str(e)}

@app.post("/download")
async def download_video(background_tasks: BackgroundTasks, url: str = Form(...), format_id: str = Form(...), mode: str = Form(...)):
    try:
        temp_id = uuid.uuid4().hex[:8]
        ext = "mp3" if mode == "audio" else "mp4"
        output = f"file_{temp_id}.{ext}"
        
        # Настройки скачивания (Vercel может не потянуть тяжелые файлы более 50мб)
        ydl_opts = {
            'outtmpl': output, 
            'nopart': True,
            'nocheckcertificate': True
        }

        if mode == "audio":
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192'
                }],
            })
        elif mode == "video_only":
            ydl_opts.update({
                'format': format_id, 
                'postprocessor_args': ['-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p']
            })
        else:
            # Склейка видео и аудио
            ydl_opts.update({
                'format': f"{format_id}+bestaudio/best", 
                'merge_output_format': 'mp4', 
                'postprocessor_args': ['-c:v', 'libx264', '-c:a', 'aac', '-pix_fmt', 'yuv420p']
            })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Находим итоговый файл
        found_files = glob.glob(f"file_{temp_id}.*")
        if not found_files:
            return {"error": "Файл не был создан"}
            
        actual_file = found_files[0]
        download_name = f"audio_{temp_id}.mp3" if mode == "audio" else f"video_{temp_id}.mp4"
        
        # Удаляем файл через 2 минуты, чтобы не забивать место на сервере
        background_tasks.add_task(lambda f: (time.sleep(120), os.remove(f) if os.path.exists(f) else None), actual_file)
        
        return FileResponse(
            actual_file, 
            filename=download_name, 
            media_type="audio/mpeg" if mode == "audio" else "video/mp4"
        )
    except Exception as e:
        return {"error": str(e)}
