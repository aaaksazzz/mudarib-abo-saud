import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    database_url:str=os.getenv("DATABASE_URL","")
    redis_url:str=os.getenv("REDIS_URL","redis://localhost:6379/0")
    public_base_url:str=os.getenv("PUBLIC_BASE_URL","http://localhost:8080").rstrip("/")
    admin_username:str=os.getenv("ADMIN_USERNAME","")
    admin_password:str=os.getenv("ADMIN_PASSWORD","")
    session_secret:str=os.getenv("SECRET_KEY","")
    binance_base_url:str=os.getenv("BINANCE_BASE_URL","https://api.binance.com").rstrip("/")
    trc20_address:str=os.getenv("TRC20_ADDRESS","")
    binance_pay_id:str=os.getenv("BINANCE_PAY_ID","")
    scan_interval_seconds:int=int(os.getenv("SCAN_INTERVAL_SECONDS","180"))
    trade_review_seconds:int=int(os.getenv("TRADE_REVIEW_SECONDS","15"))
    max_signals:int=int(os.getenv("MAX_SIGNALS","70"))

settings=Settings()
