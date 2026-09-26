import os, hashlib, hmac, secrets, re
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, DateTime, Boolean, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

def database_url():
    raw=os.getenv("DATABASE_URL","").strip()
    if raw.startswith("postgres://"): return "postgresql+asyncpg://"+raw[11:]
    if raw.startswith("postgresql://"): return "postgresql+asyncpg://"+raw[13:]
    return raw or "sqlite+aiosqlite:///./mudarib.db"

engine=create_async_engine(database_url(),pool_pre_ping=True)
SessionLocal=async_sessionmaker(engine,expire_on_commit=False)

class Base(DeclarativeBase): pass
class User(Base):
    __tablename__="users"
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    email:Mapped[str]=mapped_column(String(190),unique=True,index=True)
    password_hash:Mapped[str]=mapped_column(String(255))
    is_admin:Mapped[bool]=mapped_column(Boolean,default=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
class TradeRecord(Base):
    __tablename__="trade_records"
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    market:Mapped[str]=mapped_column(String(30),index=True)
    symbol:Mapped[str]=mapped_column(String(80),index=True)
    timeframe:Mapped[str]=mapped_column(String(20),index=True)
    side:Mapped[str]=mapped_column(String(20))
    entry:Mapped[float]=mapped_column(Float)
    tp1:Mapped[float]=mapped_column(Float)
    tp2:Mapped[float]=mapped_column(Float)
    tp3:Mapped[float]=mapped_column(Float)
    stop:Mapped[float]=mapped_column(Float)
    confidence:Mapped[float]=mapped_column(Float,default=0)
    status:Mapped[str]=mapped_column(String(20),default="open")
    pnl_pct:Mapped[float]=mapped_column(Float,default=0)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
    closed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
class Subscription(Base):
    __tablename__="subscriptions"
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    email:Mapped[str]=mapped_column(String(190),index=True)
    plan:Mapped[str]=mapped_column(String(30))
    status:Mapped[str]=mapped_column(String(20),default="pending")
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
class SiteSetting(Base):
    __tablename__="site_settings"
    key:Mapped[str]=mapped_column(String(80),primary_key=True)
    value:Mapped[str]=mapped_column(String(1000),default="")

def hash_password(password):
    salt=secrets.token_bytes(16)
    return salt.hex()+":"+hashlib.pbkdf2_hmac("sha256",password.encode(),salt,210000).hex()
def verify_password(password,stored):
    try:
        salt_hex,digest=stored.split(":",1)
        salt=bytes.fromhex(salt_hex)
        return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256",password.encode(),salt,210000).hex(),digest)
    except Exception:return False
def valid_email(v): return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",v.strip()))
async def init_db():
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    admin=os.getenv("ADMIN_EMAIL","").strip().lower()
    pwd=os.getenv("ADMIN_PASSWORD","")
    if admin and pwd and valid_email(admin):
        async with SessionLocal() as s:
            u=await s.scalar(select(User).where(User.email==admin))
            if not u:
                s.add(User(email=admin,password_hash=hash_password(pwd),is_admin=True)); await s.commit()
