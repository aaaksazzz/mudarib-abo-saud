from datetime import datetime, timezone
from fastapi import Request
from passlib.context import CryptContext
from .db import connection
from .settings import settings
pwd=CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
def hash_password(v): return pwd.hash(v)
def verify_password(v,h):
    try:return pwd.verify(v,h)
    except Exception:return False
def bootstrap_admin():
    if not settings.database_url or not settings.admin_username or not settings.admin_password:return
    with connection() as conn:
        email=settings.admin_username if "@" in settings.admin_username else settings.admin_username+"@admin.local"
        row=conn.execute("SELECT id FROM users WHERE username=%s OR lower(email)=lower(%s) LIMIT 1",(settings.admin_username,email)).fetchone()
        hashed=hash_password(settings.admin_password)
        if row: conn.execute("UPDATE users SET username=%s,email=%s,password_hash=%s,is_admin=TRUE WHERE id=%s",(settings.admin_username,email,hashed,row["id"]))
        else: conn.execute("INSERT INTO users(username,email,name,password_hash,is_admin) VALUES(%s,%s,%s,%s,TRUE)",(settings.admin_username,email,"مدير الموقع",hashed))
def current_user(request:Request):
    uid=request.session.get("user_id")
    if not uid:return None
    with connection() as conn:return conn.execute("SELECT id,username,email,name,is_admin,subscription_until FROM users WHERE id=%s",(uid,)).fetchone()
def paid_markets():return ["futures","contracts","saudi","usmarket","forex"]
def has_market_access(user,market):
    if market not in paid_markets():return True
    return bool(user and (user["is_admin"] or (user["subscription_until"] and user["subscription_until"]>datetime.now(timezone.utc))))
