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
 "crypto_spot":{"name":"سبوت","provider":"binance","symbols":[]},
 "crypto_futures":{"name":"فيوتشر","provider":"binance_futures","symbols":[]},
 "us":{"name":"الأمريكي","provider":"yahoo","symbols":["AAPL","MSFT","NVDA","AMZN","META","TSLA","GOOGL","GOOG","AVGO","AMD","NFLX","JPM","WMT","COST","QQQ","SPY"]},
 "us_options":{"name":"الخيارات الأمريكية","provider":"yahoo_options","symbols":["AAPL","MSFT","NVDA","AMZN","META","TSLA","SPY","QQQ"]},
 "saudi":{"name":"السعودي","provider":"yahoo","symbols":["2222.SR","1120.SR","2010.SR","1180.SR","1150.SR","1211.SR","2082.SR","7010.SR","7020.SR","2380.SR"]},
 "forex":{"name":"الفوركس والذهب","provider":"yahoo","symbols":["EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCAD=X","USDCHF=X","NZDUSD=X","EURGBP=X","EURJPY=X","GBPJPY=X","GC=F","SI=F"]}
}

app=FastAPI(title="التداول الذكي PRO",version="9.0")
WORKER_SECRET=os.getenv("WORKER_SECRET","")
WORKER_TTL=int(os.getenv("WORKER_TTL","180"))

def db():