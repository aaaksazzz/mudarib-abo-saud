from datetime import datetime,timezone
from fastapi import APIRouter,Request,HTTPException
from .auth import current_user,has_market_access,hash_password,verify_password,bootstrap_admin,paid_markets
from .db import connection
from .schemas import LoginIn,RegisterIn,PaymentIn
from .scanner import scan_market
from .trades import register_signals,list_trades,stats
from .settings import settings
api=APIRouter(prefix="/api")
def require_admin(request):
    u=current_user(request)
    if not u or not u["is_admin"]:raise HTTPException(403,"غير مصرح")
    return u
@api.get("/health")
def health():
    try:
        with connection() as c:c.execute("SELECT 1")
        return {"ok":True,"database":True}
    except Exception:return {"ok":True,"database":False}
@api.get("/status")
def status():return {"ok":True,"service":"web","database":"postgresql","cache":"redis"}
@api.get("/me")
def me(request:Request):
    u=current_user(request)
    active=bool(u and u["subscription_until"] and u["subscription_until"]>datetime.now(timezone.utc))
    return {"ok":True,"user":dict(u) if u else None,"admin":bool(u and u["is_admin"]),"paid_markets":paid_markets(),"subscription_active":active}
@api.post("/auth/register")
def register(data:RegisterIn,request:Request):
    with connection() as c:
        try:r=c.execute("INSERT INTO users(email,name,password_hash) VALUES(%s,%s,%s) RETURNING id",(data.email.strip().lower(),data.name.strip(),hash_password(data.password))).fetchone()
        except Exception:raise HTTPException(409,"البريد مستخدم مسبقاً")
    request.session["user_id"]=r["id"];return {"ok":True}
@api.post("/auth/login")
def login(data:LoginIn,request:Request):
    with connection() as c:u=c.execute("SELECT * FROM users WHERE lower(email)=lower(%s) LIMIT 1",(data.email.strip(),)).fetchone()
    if not u or not verify_password(data.password,u["password_hash"]):raise HTTPException(401,"بيانات الدخول غير صحيحة")
    request.session["user_id"]=u["id"];return {"ok":True}
@api.post("/auth/logout")
def logout(request:Request):request.session.clear();return {"ok":True}
@api.get("/ai/signals")
async def signals(request:Request,market="crypto",interval="15m",limit:int=20):
    u=current_user(request)
    if not has_market_access(u,market):raise HTTPException(403,"هذا القسم يحتاج اشتراكاً فعالاً")
    rows=await scan_market(market,interval,min(limit,settings.max_signals));register_signals(rows)
    return {"ok":True,"results":rows[:min(limit,settings.max_signals)],"market":market,"interval":interval,"count":len(rows)}
@api.get("/trades")
def trades():return {"ok":True,"trades":list_trades(),"stats":stats()}
@api.get("/home/overview")
def overview():
    from .cache import get_json
    out=[]
    for m,i in [("crypto","15m"),("futures","15m"),("contracts","15m"),("saudi","1D"),("usmarket","1D"),("forex","1H")]:
        rows=get_json(f"signals:{m}:{i}") or [];up=sum(x.get("direction")=="شراء" for x in rows);down=sum(x.get("direction")=="بيع" for x in rows);neutral=sum(x.get("direction")=="حيادي" for x in rows);top=max(rows,key=lambda x:float(x.get("confidence",0))) if rows else None
        out.append({"market":m,"interval":i,"total":len(rows),"up":up,"down":down,"neutral":neutral,"top":top.get("displayName",top.get("symbol")) if top else "لا توجد","confidence":top.get("confidence",0) if top else 0})
    return {"ok":True,"markets":out,"updatedAt":datetime.now(timezone.utc).isoformat()}
@api.get("/home/opportunities")
async def opportunities():
    rows=await scan_market("crypto","15m",settings.max_signals);register_signals(rows);return {"ok":True,"opportunities":rows[:5],"updatedAt":datetime.now(timezone.utc).isoformat()}
@api.get("/subscription")
def subscription():return {"ok":True,"plans":{"7d":{"days":7,"price":10},"30d":{"days":30,"price":20},"90d":{"days":90,"price":30}},"payment":{"trc20":getattr(settings,"trc20_address",""),"binancePay":getattr(settings,"binance_pay_id","")}}
@api.post("/subscription/request")
def subscription_request(data:PaymentIn,request:Request):
    u=current_user(request)
    if not u:raise HTTPException(401,"سجل الدخول أولاً")
    if data.plan not in ("7d","30d","90d"):raise HTTPException(400,"الباقة غير صحيحة")
    with connection() as c:c.execute("INSERT INTO payments(user_id,plan,txid) VALUES(%s,%s,%s)",(u["id"],data.plan,data.txid.strip()))
    return {"ok":True}
@api.get("/admin/stats")
def admin_stats(request):require_admin(request)
    # placeholder
