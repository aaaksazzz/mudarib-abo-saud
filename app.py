from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
app=FastAPI(title='التداول الذكي PRO')
BASE=Path(__file__).parent
app.mount('/static',StaticFiles(directory=BASE/'static'),name='static')
@app.get('/health')
def health(): return {'status':'ok'}
@app.get('/')
def home(): return FileResponse(BASE/'static/index.html')
