import os,time,sqlite3,asyncio
from typing import Optional
from pathlib import Path
import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse,JSONResponse

ROOT=Path(__file__).parent
DATA=Path(os.getenv("DATA_DIR","/data"))
try:
    DATA.mkdir(parents=True,exist_ok=True)
except Exception:
    DATA=ROOT/"data"; DATA.mkdir(exist_ok=True)
DB=DATA/"trading.db"

TFS=["15m","30m","1h","4h","1d","1w","1M"]
PIPELINE_TFS=["15m","30m","1h","4h","1d","1w","1M"]
EXCLUDE={"USDCUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT","USDEUSDT","BUSDUSDT","USDEUSDT","USD1USDT","PYUSDUSDT","USDDUSDT","EURUSDT","AEURUSDT","EURIUSDT","XUSDUSDT","USDSUSDT","USTCUSDT","FRAXUSDT"}
MARKETS={
 "crypto_spot":{"name":"سبوت","provider":"binance","symbols":[]}
}

app=FastAPI(title="التداول الذكي PRO",version="9.0")
WORKER_SECRET=os.getenv("WORKER_SECRET","")
WORKER_TTL=int(os.getenv("WORKER_TTL","180"))

def db():