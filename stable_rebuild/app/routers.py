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
    if not u or not u["is_admin"]: raise HTTPException(403,"غير مصرح")
    return u

@api.get("/health")
def health():
    try:
        with connection() as c:c.execute("SELECT 1")
        return {"ok":True,"database":True}
    except Exception:return {"ok":True,"database":False}

@api.get("/status")
def status():
    from .cache import ping,_client
    worker=False
    try: worker=bool(_client.get("worker:heartbeat"))
    except Exception: pass
    return {"ok":True,"service":"web","database":"postgresql","cache":"redis","redis":ping(),"worker":worker}

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
def logout(request:Request): request.session.clear();return {"ok":True}

@api.get("/ai/signals")
def signals(request:Request,market="crypto",interval="15m",limit:int=20):
    u=current_user(request)
    if not has_market_access(u,market):raise HTTPException(403,"هذا القسم يحتاج اشتراكاً فعالاً")
    from .cache import get_json
    rows=get_json(f"signals:{market}:{interval}") or []
    return {"ok":True,"results":rows[:min(limit,settings.max_signals)],"market":market,"interval":interval,"count":len(rows)}

@api.get("/trades")
def trades():return {"ok":True,"trades":list_trades(),"stats":stats()}

@api.get("/home/overview")
def overview():
    from .cache import get_json
    out=[]
    for m,i in [("crypto","15m"),("futures","15m"),("contracts","15m"),("saudi","1D"),("usmarket","1D"),("forex","1H")]:
        rows=get_json(f"signals:{m}:{i}") or []
        up=sum(x.get("direction")=="شراء" for x in rows);down=sum(x.get("direction")=="بيع" for x in rows);neutral=sum(x.get("direction")=="حيادي" for x in rows)
        top=max(rows,key=lambda x:float(x.get("confidence",0))) if rows else None
        out.append({"market":m,"interval":i,"total":len(rows),"up":up,"down":down,"neutral":neutral,"top":top.get("displayName",top.get("symbol")) if top else "لا توجد","confidence":top.get("confidence",0) if top else 0})
    return {"ok":True,"markets":out,"updatedAt":datetime.now(timezone.utc).isoformat()}

@api.get("/home/opportunities")
async def opportunities():
    rows=await scan_market("crypto","15m",settings.max_signals);register_signals(rows)
    return {"ok":True,"opportunities":rows[:5],"updatedAt":datetime.now(timezone.utc).isoformat()}

@api.get("/subscription")
def subscription():
    return {"ok":True,"plans":{"7d":{"days":7,"price":10},"30d":{"days":30,"price":20},"90d":{"days":90,"price":30}},"payment":{"trc20":getattr(settings,"trc20_address",""),"binancePay":getattr(settings,"binance_pay_id","")}}

@api.post("/subscription/request")
def subscription_request(data:PaymentIn,request:Request):
    u=current_user(request)
    if not u:raise HTTPException(401,"سجل الدخول أولاً")
    if data.plan not in ("7d","30d","90d"):raise HTTPException(400,"الباقة غير صحيحة")
    with connection() as c:c.execute("INSERT INTO payments(user_id,plan,txid) VALUES(%s,%s,%s)",(u["id"],data.plan,data.txid.strip()))
    return {"ok":True}

@api.get("/admin/stats")
def admin_stats(request:Request):
    require_admin(request)
    with connection() as c:
        users=c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        active=c.execute("SELECT COUNT(*) n FROM users WHERE subscription_until>NOW()").fetchone()["n"]
        pending=c.execute("SELECT COUNT(*) n FROM payments WHERE status='pending'").fetchone()["n"]
    return {"ok":True,"users":users,"active_subscriptions":active,"pending_payments":pending}

@api.get("/admin/payments")
def admin_payments(request:Request):
    require_admin(request)
    with connection() as c:rows=c.execute("SELECT p.id,u.username,p.plan,p.txid,p.status,p.created_at FROM payments p LEFT JOIN users u ON u.id=p.user_id ORDER BY p.id DESC LIMIT 200").fetchall()
    return {"ok":True,"payments":[dict(x) for x in rows]}

@api.post("/admin/payments/approve")
def approve_payment(data:dict,request:Request):
    require_admin(request)
    with connection() as c:
        p=c.execute("SELECT * FROM payments WHERE id=%s",(data.get("id"),)).fetchone()
        if not p:raise HTTPException(404,"الطلب غير موجود")
        days={"7d":7,"30d":30,"90d":90}.get(p["plan"],7)
        c.execute("UPDATE payments SET status='approved' WHERE id=%s",(p["id"],))
        c.execute("UPDATE users SET subscription_until=GREATEST(COALESCE(subscription_until,NOW()),NOW())+(%s*INTERVAL '1 day') WHERE id=%s",(days,p["user_id"]))
    return {"ok":True}

@api.post("/admin/payments/reject")
def reject_payment(data:dict,request:Request):
    require_admin(request)
    with connection() as c:c.execute("UPDATE payments SET status='rejected' WHERE id=%s",(data.get("id"),))
    return {"ok":True}

@api.get("/admin/users")
def admin_users(request:Request):
    require_admin(request)
    with connection() as c:rows=c.execute("SELECT id,username,email,name,subscription_until FROM users ORDER BY id DESC").fetchall()
    return {"ok":True,"users":[dict(x) for x in rows]}

@api.post("/admin/users/extend")
def extend_user(data:dict,request:Request):
    require_admin(request)
    with connection() as c:c.execute("UPDATE users SET subscription_until=GREATEST(COALESCE(subscription_until,NOW()),NOW())+(%s*INTERVAL '1 day') WHERE id=%s",(int(data.get("days",30)),data.get("id")))
    return {"ok":True}

@api.post("/admin/users/delete")
def delete_user(data:dict,request:Request):
    require_admin(request)
    with connection() as c:c.execute("DELETE FROM users WHERE id=%s",(data.get("id"),))
    return {"ok":True}

@api.post("/admin/login")
def admin_login(data:dict,request:Request):
    u=current_user(request)
    if u and u["is_admin"]:return {"ok":True}
    username=str(data.get("username","")).strip();password=str(data.get("password",""))
    with connection() as c:u=c.execute("SELECT * FROM users WHERE username=%s LIMIT 1",(username,)).fetchone()
    if not u or not u["is_admin"] or not verify_password(password,u["password_hash"]):raise HTTPException(401,"بيانات المشرف غير صحيحة")
    request.session["user_id"]=u["id"];return {"ok":True}

@api.post("/admin/logout")
def admin_logout(request:Request):request.session.clear();return {"ok":True}

@api.get("/news")
def news():
    with connection() as c:
        rows=c.execute("SELECT id,slug,title,content,description,source,category,link,published_at AS published FROM news ORDER BY id DESC LIMIT 50").fetchall()
    return {"ok":True,"news":[dict(x) for x in rows]}

@api.get("/live-news")
def live_news():
    return news()

@api.post("/admin/news")
def add_news(data:dict,request:Request):
    require_admin(request)
    title=str(data.get("title","")).strip();content=str(data.get("content","")).strip()
    if not title or not content: raise HTTPException(400,"عنوان الخبر ومحتواه مطلوبان")
    slug=str(data.get("slug") or title).strip().lower().replace(" ","-")[:180]
    with connection() as c:
        c.execute("INSERT INTO news(slug,title,content,description,source,category) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(slug) DO UPDATE SET title=EXCLUDED.title,content=EXCLUDED.content,description=EXCLUDED.description",
                  (slug,title,content,content[:300],str(data.get("source") or "المضارب ذكي"),str(data.get("category") or "أخبار الأسواق")))
    return {"ok":True,"slug":slug}

@api.get("/blog")
def blog_api():
    with connection() as c:
        rows=c.execute("SELECT id,slug,title,excerpt,category,cover_url,author,created_at,updated_at FROM blog_posts WHERE published=TRUE ORDER BY id DESC LIMIT 50").fetchall()
    return {"ok":True,"posts":[dict(x) for x in rows]}

@api.get("/admin/blog")
def admin_blog(request:Request):
    require_admin(request)
    with connection() as c: rows=c.execute("SELECT * FROM blog_posts ORDER BY id DESC LIMIT 200").fetchall()
    return {"ok":True,"posts":[dict(x) for x in rows]}

@api.post("/admin/blog")
def add_blog(data:dict,request:Request):
    require_admin(request)
    title=str(data.get("title","")).strip();content=str(data.get("content","")).strip()
    if not title or not content: raise HTTPException(400,"العنوان والمحتوى مطلوبان")
    slug=str(data.get("slug") or title).strip().lower().replace(" ","-")[:180]
    with connection() as c:
        c.execute("INSERT INTO blog_posts(slug,title,excerpt,content,category,cover_url,author) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(slug) DO UPDATE SET title=EXCLUDED.title,excerpt=EXCLUDED.excerpt,content=EXCLUDED.content,updated_at=NOW()",
                  (slug,title,str(data.get("excerpt") or ""),content,str(data.get("category") or "عام"),str(data.get("cover_url") or ""),str(data.get("author") or "المضارب ذكي")))
    return {"ok":True,"slug":slug}

@api.post("/admin/telegram/test")
def telegram_test(request:Request):
    require_admin(request)
    return {"ok":True,"message":"خدمة تيليجرام جاهزة للربط عبر متغيرات البيئة"}

@api.get("/news/{slug}")
def news_detail(slug:str):
    with connection() as c:
        row=c.execute("SELECT id,slug,title,content,description,source,category,link,published_at AS published FROM news WHERE slug=%s LIMIT 1",(slug,)).fetchone()
    if not row:raise HTTPException(404,"الخبر غير موجود")
    return {"ok":True,"news":dict(row)}

@api.get("/blog/{slug}")
def blog_detail(slug:str):
    with connection() as c:
        row=c.execute("SELECT id,slug,title,excerpt,content,category,cover_url,author,created_at,updated_at FROM blog_posts WHERE slug=%s AND published=TRUE LIMIT 1",(slug,)).fetchone()
    if not row:raise HTTPException(404,"المقال غير موجود")
    return {"ok":True,"post":dict(row)}
