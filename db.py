import os, re, hashlib, hmac, secrets
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, Integer, String, select
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

def database_url():
    raw=os.getenv("DATABASE_URL","").strip()
    if raw.startswith("postgres://"): raw="postgresql+asyncpg://"+raw[len("postgres://"):]
    elif raw.startswith("postgresql://"): raw="postgresql+asyncpg://"+raw[len("postgresql://"):]
    return raw or "sqlite+aiosqlite:///./mudarib.db"

class Base(DeclarativeBase): pass
class TradeRecord(Base):
    __tablename__="trade_records"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    symbol: Mapped[str]=mapped_column(String(40),index=True)
    market: Mapped[str]=mapped_column(String(30),default="spot",index=True)
    timeframe: Mapped[str]=mapped_column(String(20),index=True)
    side: Mapped[str]=mapped_column(String(10))
    entry: Mapped[float]=mapped_column(Float)
    tp1: Mapped[float]=mapped_column(Float)
    tp2: Mapped[float]=mapped_column(Float)
    tp3: Mapped[float]=mapped_column(Float)
    stop: Mapped[float]=mapped_column(Float)
    confidence: Mapped[float]=mapped_column(Float,default=0)
    rsi: Mapped[float]=mapped_column(Float,default=0)
    status: Mapped[str]=mapped_column(String(20),default="open",index=True)
    reached_tp1: Mapped[bool]=mapped_column(Boolean,default=False)
    reached_tp2: Mapped[bool]=mapped_column(Boolean,default=False)
    reached_tp3: Mapped[bool]=mapped_column(Boolean,default=False)
    opened_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
    closed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    close_price: Mapped[float|None]=mapped_column(Float,nullable=True)
    pnl_pct: Mapped[float]=mapped_column(Float,default=0)

class Subscription(Base):
    __tablename__="subscriptions"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    user_id: Mapped[int]=mapped_column(Integer,index=True)
    plan: Mapped[str]=mapped_column(String(40),default="30d")
    started_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
    status: Mapped[str]=mapped_column(String(20),default="active")

class SiteSetting(Base):
    __tablename__="site_settings"
    key: Mapped[str]=mapped_column(String(80),primary_key=True)
    value: Mapped[str]=mapped_column(String(1000),default="")

class User(Base):
    __tablename__="users"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    name: Mapped[str]=mapped_column(String(100))
    email: Mapped[str]=mapped_column(String(254),unique=True,index=True)
    password_hash: Mapped[str]=mapped_column(String(300))
    is_admin: Mapped[bool]=mapped_column(Boolean,default=False)
    is_active: Mapped[bool]=mapped_column(Boolean,default=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))

engine=create_async_engine(database_url(),pool_pre_ping=True)
SessionLocal=async_sessionmaker(engine,expire_on_commit=False)

def hash_password(password):
    salt=secrets.token_bytes(16); digest=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,240000)
    return "pbkdf2$240000$"+salt.hex()+"$"+digest.hex()

def verify_password(password,stored):
    try:
        algo,iterations,salt_hex,digest_hex=stored.split("$",3)
        if algo!="pbkdf2": return False
        digest=hashlib.pbkdf2_hmac("sha256",password.encode(),bytes.fromhex(salt_hex),int(iterations))
        return hmac.compare_digest(digest.hex(),digest_hex)
    except Exception: return False

EMAIL_RE=re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
def valid_email(email): return bool(EMAIL_RE.fullmatch(email)) and len(email)<=254

async def init_db():
    # Avoid SQLAlchemy's run_sync/greenlet requirement during startup.
    # This keeps the app compatible with Northflank's Python 3.14 runtime.
    async with engine.begin() as conn:
        dialect = engine.sync_engine.dialect
        for table in Base.metadata.sorted_tables:
            ddl = str(CreateTable(table, if_not_exists=True).compile(dialect=dialect))
            await conn.exec_driver_sql(ddl)
        for table in Base.metadata.sorted_tables:
            for index in table.indexes:
                ddl = str(CreateIndex(index, if_not_exists=True).compile(dialect=dialect))
                await conn.exec_driver_sql(ddl)
    admin_email=os.getenv("ADMIN_EMAIL","").strip().lower(); admin_password=os.getenv("ADMIN_PASSWORD","")
    if admin_email and admin_password and valid_email(admin_email) and len(admin_password)>=8:
        async with SessionLocal() as s:
            existing=(await s.execute(select(User).where(User.email==admin_email))).scalar_one_or_none()
            if not existing:
                s.add(User(name="Admin",email=admin_email,password_hash=hash_password(admin_password),is_admin=True)); await s.commit()

async def get_user(user_id):
    if not user_id: return None
    async with SessionLocal() as s:
        return (await s.execute(select(User).where(User.id==int(user_id),User.is_active.is_(True)))).scalar_one_or_none()

async def find_user(email):
    async with SessionLocal() as s:
        return (await s.execute(select(User).where(User.email==email))).scalar_one_or_none()
