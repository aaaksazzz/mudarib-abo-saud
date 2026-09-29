CSS="""*{box-sizing:border-box}html{scroll-behavior:smooth;background:#030712}body{margin:0;background:radial-gradient(circle at 10% 0%,rgba(22,101,52,.16),transparent 28%),radial-gradient(circle at 90% 10%,rgba(37,99,235,.16),transparent 30%),#030712;color:#eef6ff;font-family:Tahoma,Arial,sans-serif;min-height:100vh;direction:rtl;text-align:right;overflow-x:hidden}body:before{content:"";position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(rgba(255,255,255,.018) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.018) 1px,transparent 1px);background-size:40px 40px;mask-image:linear-gradient(to bottom,#000,transparent 75%);z-index:-1}a{color:inherit;text-decoration:none}button,a,.btn{touch-action:manipulation}.wrap{max-width:1500px;margin:auto;padding:18px}.top{position:sticky;top:0;z-index:50;background:rgba(3,7,18,.82);backdrop-filter:blur(22px);border-bottom:1px solid rgba(148,163,184,.12)}.brandbar{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:8px 0 12px}.brand{font-size:25px;font-weight:950;letter-spacing:-.5px}.brandmark{display:inline-flex;width:42px;height:42px;align-items:center;justify-content:center;border-radius:14px;background:linear-gradient(135deg,#16a34a,#2563eb);box-shadow:0 10px 35px rgba(37,99,235,.3);margin-left:9px}.brand small{display:block;color:#71849b;font-size:11px;font-weight:700;margin-top:4px}.pro{color:#60a5fa}.menu-btn{width:46px;height:46px;border:1px solid #28445f;border-radius:14px;background:linear-gradient(145deg,#0d1b2d,#07111d);color:#fff;cursor:pointer;font-size:22px;display:flex;align-items:center;justify-content:center;box-shadow:0 8px 25px rgba(0,0,0,.25)}.menu-btn:hover{border-color:#3b82f6;transform:translateY(-1px)}.nav{position:fixed;top:0;right:-330px;left:auto;width:305px;direction:rtl;height:100vh;display:flex;flex-direction:column;gap:7px;overflow-y:auto;padding:82px 16px 24px;background:rgba(3,7,18,.985);border-left:1px solid #20354d;box-shadow:-25px 0 70px rgba(0,0,0,.55);z-index:10000;transition:right .24s cubic-bezier(.2,.8,.2,1);pointer-events:none}.nav.open{right:0;pointer-events:auto}.menu-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.58);backdrop-filter:blur(3px);z-index:9998;display:none}.menu-backdrop.open{display:block}.nav a{display:flex;align-items:center;gap:11px;padding:12px 14px;position:relative;z-index:61;pointer-events:auto;cursor:pointer;border-radius:14px;background:rgba(12,25,42,.82);border:1px solid rgba(51,81,110,.42);white-space:nowrap;font-weight:850;color:#aebfd2;transition:.18s}.nav a:hover{background:linear-gradient(135deg,#102a45,#0b1a2d);border-color:#32658e;color:#fff;transform:translateX(-3px)}.nav a.admin-nav{border-color:rgba(245,196,81,.35);color:#f6d477}.nav .ico{width:22px;height:22px;display:inline-flex;align-items:center;justify-content:center;flex:0 0 22px}.nav svg{width:20px;height:20px;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.hero{position:relative;overflow:hidden;padding:34px;border-radius:28px;background:radial-gradient(circle at 82% 18%,rgba(37,99,235,.2),transparent 34%),radial-gradient(circle at 18% 85%,rgba(22,163,74,.13),transparent 30%),linear-gradient(145deg,#0d1b2d,#050d18 70%);border:1px solid #203c58;box-shadow:0 25px 80px rgba(0,0,0,.28);isolation:isolate}.hero:after{content:"";position:absolute;width:260px;height:260px;border-radius:50%;left:-110px;bottom:-150px;background:rgba(37,99,235,.1);filter:blur(15px);z-index:-1}.hero h1{font-size:clamp(30px,5vw,54px);margin:0 0 10px;letter-spacing:-1.5px}.hero p{max-width:820px;line-height:1.9}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(265px,1fr));gap:16px}.market-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:15px;margin:20px 0}.market-tile{position:relative;overflow:hidden;min-height:165px;padding:21px;border-radius:22px;background:linear-gradient(145deg,rgba(13,29,48,.96),rgba(6,15,26,.96));border:1px solid #1b354e;transition:.22s;box-shadow:0 14px 38px rgba(0,0,0,.18)}.market-tile:before{content:"";position:absolute;width:150px;height:150px;left:-70px;top:-80px;border-radius:50%;background:currentColor;opacity:.045}.market-tile:hover{transform:translateY(-4px);border-color:#356587;box-shadow:0 20px 50px rgba(0,0,0,.28)}.market-icon{width:60px;height:60px;border-radius:18px;display:flex;align-items:center;justify-content:center;margin-bottom:15px}.market-icon svg{width:35px;height:35px;stroke:currentColor;fill:none;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}.spot{background:rgba(34,197,94,.11);color:#4ade80}.futures{background:rgba(59,130,246,.12);color:#60a5fa}.contracts{background:rgba(168,85,247,.12);color:#c084fc}.american{background:rgba(96,165,250,.12);color:#93c5fd}.saudi{background:rgba(16,185,129,.12);color:#34d399}.forex{background:rgba(245,158,11,.12);color:#fbbf24}.card{background:linear-gradient(145deg,rgba(11,24,40,.96),rgba(6,15,26,.96));border:1px solid rgba(45,72,98,.62);border-radius:20px;padding:18px;box-shadow:0 14px 38px rgba(0,0,0,.16);transition:.2s}.card:hover{border-color:#315778;box-shadow:0 18px 45px rgba(0,0,0,.25)}.card h2,.card h3{margin-top:4px}.muted{color:#8195ab}.buy{color:#4ade80;font-weight:900}.gold{color:#f5c451}.danger{color:#fb7185;font-weight:900}.stat{font-size:31px;font-weight:950}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:13px;margin:18px 0}.statbox{padding:17px;border-radius:18px;background:linear-gradient(145deg,#0b1a2b,#07111d);border:1px solid #1b334b}.statbox small{display:block;color:#71869d;margin-bottom:7px}.btn{border:1px solid #284863;color:#fff;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:11px 16px;border-radius:13px;font-weight:900;transition:.18s}.btn:hover{transform:translateY(-2px)}.primary{background:linear-gradient(135deg,#1683ef,#1857a6);border-color:#3094f5;box-shadow:0 8px 25px rgba(37,99,235,.18)}.goldbg{background:#8a6619}.pill{display:inline-flex;align-items:center;padding:6px 10px;border-radius:999px;background:#0d2238;border:1px solid #21445f;color:#a9c2da;font-size:12px;font-weight:900}.signal{border-right:3px solid #34d399}.signal-head{display:flex;align-items:center;justify-content:space-between;gap:10px}.rank{font-weight:950;color:#f5c451}.price-row{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:13px 0}.price-box{padding:11px;border-radius:13px;background:#07111d;border:1px solid #172d43}.price-box small{display:block;color:#71869d;margin-bottom:4px}.price-box b{font-size:13px}.table{width:100%;border-collapse:separate;border-spacing:0;overflow:hidden}.table td,.table th{padding:12px;border-bottom:1px solid #162d43;text-align:right}.table th{color:#8fa6bd;background:#091827}.footer{padding:38px 18px;text-align:center;color:#617890}.section-title{display:flex;align-items:end;justify-content:space-between;gap:10px;margin:30px 0 13px}.section-title h2{margin:0}.top-opportunity{border:1px solid rgba(245,196,81,.25);box-shadow:0 14px 45px rgba(245,196,81,.07)}input,textarea,select{width:100%;padding:13px;margin:6px 0;background:#06111f;color:white;border:1px solid #294967;border-radius:12px;outline:none}input:focus,textarea:focus,select:focus{border-color:#3b82f6;box-shadow:0 0 0 3px rgba(59,130,246,.12)}@media(max-width:900px){.market-grid{grid-template-columns:repeat(2,1fr)}.stats{grid-template-columns:repeat(2,1fr)}}@media(max-width:600px){.wrap{padding:12px}.brandbar{padding-bottom:9px}.brand{font-size:20px}.brand small{font-size:10px}.nav{width:min(88vw,305px);padding:78px 13px 22px}.nav a{padding:12px 13px;font-size:14px}.hero{padding:23px;border-radius:20px}.market-grid,.grid{grid-template-columns:1fr}.price-row{grid-template-columns:repeat(2,1fr)}.stats{grid-template-columns:repeat(2,1fr)}.card{border-radius:17px}.footer{padding-bottom:80px}}@media(prefers-reduced-motion:reduce){*,*:before,*:after{scroll-behavior:auto!important;transition:none!important;animation:none!important}}.home-hero{min-height:430px;display:flex;align-items:center}.home-hero-inner{width:100%;display:flex;align-items:center;justify-content:space-between;gap:35px;position:relative;z-index:2}.home-copy{max-width:760px}.live-badge{display:inline-flex;align-items:center;gap:8px;padding:7px 12px;border:1px solid rgba(74,222,128,.25);border-radius:999px;background:rgba(34,197,94,.08);color:#8ee8ad;font-size:12px;font-weight:900}.live-badge span{width:8px;height:8px;border-radius:50%;background:#4ade80;box-shadow:0 0 14px #4ade80}.hero-sub{font-size:17px!important;color:#91a6bc;margin:0 0 24px}.hero-actions,.hero-mini{display:flex;gap:10px;flex-wrap:wrap}.hero-btn{padding:13px 18px}.hero-mini{margin-top:20px;color:#71879e;font-size:12px}.hero-orbit{width:310px;height:310px;position:relative;display:flex;align-items:center;justify-content:center;flex:0 0 310px}.orbit-ring{position:absolute;inset:18px;border:1px solid rgba(96,165,250,.22);border-radius:50%;box-shadow:0 0 70px rgba(37,99,235,.14)}.orbit-ring:before{content:"";position:absolute;inset:35px;border:1px dashed rgba(74,222,128,.2);border-radius:50%}.orbit-core{width:125px;height:125px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:31px;font-weight:950;background:radial-gradient(circle,#1d4ed8,#071225 68%);border:1px solid #3b82f6;box-shadow:0 0 70px rgba(37,99,235,.35)}.orbit-label{position:absolute;padding:8px 11px;border-radius:12px;background:rgba(7,17,29,.9);border:1px solid #24445f;font-size:12px;font-weight:900;box-shadow:0 10px 30px rgba(0,0,0,.25)}.label-1{top:15px;right:18px}.label-2{bottom:25px;left:10px}.label-3{bottom:18px;right:20px}.home-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0}.home-stats>div{padding:16px;text-align:center;border:1px solid #19334b;border-radius:18px;background:linear-gradient(145deg,#0b1a2b,#06111d)}.home-stats b{display:block;font-size:25px}.home-stats small{color:#71869d}.channel-card{display:flex;align-items:center;justify-content:space-between;gap:15px;margin:22px 0;padding:20px;border-radius:21px;border:1px solid rgba(37,99,235,.35);background:linear-gradient(120deg,rgba(37,99,235,.15),rgba(22,163,74,.07));box-shadow:0 18px 55px rgba(0,0,0,.2)}.channel-card strong{font-size:19px}.channel-card p{margin:6px 0 0;color:#8195ab}@media(max-width:800px){.home-hero{min-height:auto}.home-hero-inner{display:block}.hero-orbit{width:220px;height:220px;min-width:220px;margin:28px auto 0;transform:scale(.86)}.home-stats{grid-template-columns:repeat(2,1fr)}.channel-card{align-items:flex-start;flex-direction:column}.channel-card .btn{width:100%}}"""

def icon(kind):
    paths={
      "home":'<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
      "trade":'<path d="M4 17 9 12l4 3 7-8"/><path d="M17 7h3v3"/>',
      "scan":'<circle cx="11" cy="11" r="6"/><path d="m16 16 5 5"/>',
      "spot":'<circle cx="12" cy="12" r="8"/><path d="M8 12h8M12 8v8"/>',
      "futures":'<path d="M4 16V8m5 11V5m6 14v-8m5 5V4"/><path d="m3 12 5-5 4 3 7-7"/>',
      "contract":'<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v5h5M9 13h6M9 17h6"/>',
      "us":'<path d="M4 18V7h16v11"/><path d="M7 11h10M7 14h10"/><path d="m6 7 2-3 2 3 2-3 2 3 2-3 2 3"/>',
      "sa":'<path d="M4 18V9h16v9"/><path d="M8 9V5h8v4M7 14h10"/>',
      "fx":'<circle cx="9" cy="10" r="5"/><circle cx="15" cy="14" r="5"/><path d="m12 7 2-2m-2 12 2 2"/>',
      "news":'<path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h8M8 16h5"/>',
      "blog":'<path d="M5 3h11l3 3v15H5z"/><path d="M9 12h6M9 16h6M16 3v4h3"/>',
      "star":'<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z"/>',
      "user":'<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
      "admin":'<path d="M12 3 20 6v6c0 5-3.3 8-8 9-4.7-1-8-4-8-9V6z"/><path d="m9 12 2 2 4-5"/>',
      "login":'<path d="M10 17l5-5-5-5M15 12H3"/><path d="M13 3h6v18h-6"/>'
    }
    return f'<span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true">{paths.get(kind,"")}</svg></span>'
def page(req,title,body):
    u=user(req); role=u["role"] if u else ""
    nav=[("home","الرئيسية","/"),("trade","بوت السبوت","/bot"),("scan","الماسح","/scanner"),("spot","السبوت","/market/spot"),("futures","الفيوتشر","/market/futures"),("contract","العقود","/market/contracts"),("us","الأمريكي","/market/american"),("sa","السعودي","/market/saudi"),("fx","فوركس وذهب","/market/forex"),("news","الأخبار","/news"),("blog","المدونة","/blog"),("star","الاشتراكات","/subscriptions")]
    if u:nav += [("user","حسابي","/account"),("support","الدعم الفني","/support")]
    if role=="admin":nav += [("admin","الإدارة","/admin"),("support","طلبات الدعم","/admin/support")]
    if not u:nav += [("login","دخول","/login"),("user","تسجيل","/register")]
    n="".join(f'<a class="{"admin-nav" if x[0]=="admin" else ""}" href="{x[2]}">{icon(x[0])}<span>{x[1]}</span></a>' for x in nav)
    canonical=str(req.url).split("?")[0]
    desc="منصة مضارب ذكي PRO لتحليل الأسواق والإشارات والصفقات متعددة الفريمات."
    return f'''<!doctype html><html lang="ar-SA" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="{esc(desc)}"><meta name="robots" content="index,follow"><link rel="canonical" href="{esc(canonical)}"><meta property="og:title" content="{esc(title)} | مضارب ذكي PRO"><meta property="og:description" content="{esc(desc)}"><meta property="og:type" content="website"><title>{esc(title)} | مضارب ذكي PRO</title><style>{CSS}.support-fab{{position:fixed;left:18px;bottom:18px;width:54px;height:54px;border-radius:50%;display:flex;align-items:center;justify-content:center;text-decoration:none;font-size:24px;background:linear-gradient(135deg,#111827,#2563eb);border:1px solid rgba(255,255,255,.18);box-shadow:0 10px 30px rgba(0,0,0,.35);z-index:9999}}.support-fab:hover{{transform:translateY(-2px)}}@media(max-width:600px){{.support-fab{{left:14px;bottom:14px;width:50px;height:50px;font-size:22px}}}}</style><header class="top"><div class="wrap"><div class="brandbar"><div><span class="brandmark">{icon("trade")}</span><span class="brand">مضارب ذكي <span class="pro">PRO</span></span><small>منصة تحليل أسواق متعددة</small></div><button class="menu-btn" type="button" aria-label="فتح القائمة" onclick="document.querySelector('.nav').classList.toggle('open');document.querySelector('.menu-backdrop').classList.toggle('open')">☰</button></div><div class="menu-backdrop" onclick="document.querySelector('.nav').classList.remove('open');this.classList.remove('open')"></div><nav class="nav">{n}</nav></div></header><main class="wrap">{body}</main><a class="support-fab" href="/support" title="الدعم الفني" aria-label="الدعم الفني">💬</a><footer class="footer">مضارب ذكي PRO · تحليل وفرز أسواق متعددة</footer></html>'''
def require(req,role=None):
    u=user(req)
    if not u:return RedirectResponse("/login",303)
    if role and u["role"]!=role:return RedirectResponse("/",303)
    return u

@app.get("/",response_class=HTMLResponse)
def home(req:Request):
    sig=db().execute("SELECT * FROM signals WHERE status='open' ORDER BY confidence DESC,change15 DESC,id DESC LIMIT 9").fetchall()
    def medal(i):
        return "👑" if i==1 else ("🥈" if i==2 else ("🥉" if i==3 else f"#{i}"))
    markets=[
        ("spot","₿","السبوت","شراء","/market/spot"),
        ("futures","↕","الفيوتشر","شراء وبيع","/market/futures"),
        ("contracts","◫","العقود","شراء وبيع","/market/contracts"),
        ("american","🇺🇸","الأمريكي","شراء","/market/american"),
        ("saudi","🇸🇦","السعودي","شراء","/market/saudi"),
        ("forex","💱","فوركس وذهب","شراء وبيع","/market/forex")
    ]
    tiles=""
    for cls,ico,name,mode,url in markets:
        tiles+=f'<a class="market-tile {cls}" href="{url}"><div class="market-icon"><span style="font-size:30px">{ico}</span></div><h3>{name}</h3><p class="muted">{mode} · تحليل متعدد الفريمات</p><span class="pill">دخول السوق ←</span></a>'
    cards=""
    for i,x in enumerate(sig,1):
        side="شراء" if x["side"]=="BUY" else "بيع"
        sidecls="buy" if x["side"]=="BUY" else "danger"
        cards+=f'<div class="card signal top-opportunity"><div class="signal-head"><b class="gold">{medal(i)}</b><span class="pill">{esc(x["timeframe"])} · {side}</span></div><h3 style="font-size:21px;margin:14px 0 5px">{esc(x["symbol"])}</h3><div class="{sidecls}">{side}</div><div class="price-row"><div class="price-box"><small>دخول</small><b>{float(x["entry"] or 0):.6g}</b></div><div class="price-box"><small>وقف</small><b>{float(x["stop"] or 0):.6g}</b></div><div class="price-box"><small>TP1</small><b>{float(x["tp1"] or 0):.6g}</b></div><div class="price-box"><small>AI%</small><b class="gold">{float(x["confidence"] or 0):.0f}%</b></div></div></div>'
    body=f'''<section class="hero">
<div style="display:flex;align-items:center;justify-content:space-between;gap:25px;flex-wrap:wrap">
<div style="flex:1;min-width:270px">
<span class="pill">● LIVE · مضارب ذكي PRO</span>
<h1 style="margin:14px 0 10px">السوق قدامك.<br><span class="gold">والفرص أوضح.</span></h1>
<p class="muted" style="font-size:16px;max-width:720px">منصة واحدة تجمع الأسواق والإشارات والماسح الذكي في تجربة سريعة وواضحة.</p>
<div style="display:flex;gap:9px;flex-wrap:wrap;margin-top:20px"><a class="btn primary" href="/scanner">🔎 ابدأ الماسح</a><a class="btn" href="/market/spot">₿ استكشف الأسواق</a></div>
</div>
<div class="card" style="min-width:190px;text-align:center;background:rgba(4,12,23,.7)"><div style="font-size:38px">⚡</div><div class="stat">{len(sig)}</div><div class="muted">فرص نشطة</div></div>
</div></section>
<div class="section-title"><h2>🌐 الأسواق</h2><span class="muted">كل شيء من مكان واحد</span></div>
<div class="market-grid">{tiles}</div>
<div class="section-title"><h2>👑 الفرص المميزة</h2><a class="pill" href="/scanner">عرض الكل</a></div>
<div class="grid">{cards or '<div class="card"><h3>⏳ جاري التحليل</h3><p class="muted">المحركات تجمع أحدث بيانات الأسواق.</p></div>'}</div>
<a href="https://t.me/tadol1" target="_blank" rel="noopener" style="text-decoration:none;color:inherit"><div class="card" style="margin:22px 0;background:linear-gradient(135deg,rgba(37,99,235,.18),rgba(22,163,74,.08));border-color:rgba(59,130,246,.35)"><div style="display:flex;justify-content:space-between;align-items:center;gap:15px;flex-wrap:wrap"><div><h2 style="margin:0 0 5px">📣 قناة مضارب ذكي</h2><p class="muted" style="margin:0">الإشارات والتنبيهات والتحديثات.</p></div><span class="btn primary">الدخول للقناة ←</span></div></div></a>'''
    return page(req,"الرئيسية",body)

@app.get("/market/{market}",response_class=HTMLResponse)
def market(req:Request,market:str,tf:str="all"):
    names={"spot":"السبوت","futures":"الفيوتشر","contracts":"العقود","american":"السوق الأمريكي","saudi":"السوق السعودي","forex":"الفوركس والذهب"}
    if market not in names:return RedirectResponse("/",303)
    if tf not in TIMEFRAMES:tf="all"
    c=db();
    if tf=="all": rows=c.execute("SELECT * FROM signals WHERE market=? ORDER BY id DESC LIMIT 30",(market,)).fetchall()
    else: rows=c.execute("SELECT * FROM signals WHERE market=? AND timeframe=? ORDER BY id DESC LIMIT 30",(market,tf)).fetchall()
    tabs=" ".join(f'<a class="pill" href="/market/{market}?tf={x}">{x}</a>' for x in TIMEFRAMES)
    cards="".join(f'<div class="card signal"><h3>{esc(x["symbol"])}</h3><span class="pill">{("بيع" if x["side"]=="SELL" else "شراء")} · {esc(x["timeframe"])}</span><p>دخول: {float(x["entry"] or 0):.5f}</p><p>وقف: {float(x["stop"] or 0):.5f} · TP1: {float(x["tp1"] or 0):.5f} · TP2: {float(x["tp2"] or 0):.5f} · TP3: {float(x["tp3"] or 0):.5f}</p><p>تغير الفريم: {float(x["change15"] or 0):.2f}% · AI: {float(x["confidence"] or 0):.0f}%</p></div>' for x in rows)
    return page(req,names[market],f'<h1>{names[market]}</h1><p class="muted">كل الفريمات — اختر الفريم لعرض صفقاته</p><div style="display:flex;gap:6px;flex-wrap:wrap;margin:12px 0">{tabs}</div><div class="grid">{cards or "<div class=card>لا توجد صفقات لهذا الفريم حاليًا.</div>"}</div>')

@app.get("/bot",response_class=HTMLResponse)
def bot_page(req:Request):
    rows=db().execute("SELECT * FROM signals WHERE status='open' ORDER BY confidence DESC,change15 DESC,id DESC LIMIT 20").fetchall()
    items=""
    for i,x in enumerate(rows,1):
        side="شراء" if x["side"]=="BUY" else "بيع"
        cls="buy" if x["side"]=="BUY" else "danger"
        items += '<div class="card"><div style="display:flex;justify-content:space-between;gap:10px;align-items:center"><b>'+str(i)+' · '+esc(x["symbol"])+'</b><span class="'+cls+'">'+side+'</span></div><p class="muted">'+esc(x["timeframe"])+' · AI%: <b>'+str(round(float(x["confidence"] or 0),1))+'%</b></p><p>دخول: <b>'+format_price(x["entry"])+'</b> · وقف: <b>'+format_price(x["stop"])+'</b></p><p>TP1: <b>'+format_price(x["tp1"])+'</b> · TP2: <b>'+format_price(x["tp2"])+'</b> · TP3: <b>'+format_price(x["tp3"])+'</b></p></div>'
    if not items:
        items='<div class="card"><h3>🤖 البوت جاهز</h3><p class="muted">لا توجد إشارات مفتوحة حاليًا. المحرك مستمر في مراقبة الأسواق.</p><a class="btn primary" href="/scanner">🔎 افتح الماسح</a></div>'
    body='<section class="hero"><div class="live-badge"><span></span> LIVE · بوت السبوت</div><h1>🤖 بوت السبوت <span class="gold">PRO</span></h1><p class="hero-sub">صفحة البوت لعرض إشارات السبوت المحفوظة ومتابعة الفرص الحالية.</p><div class="hero-actions"><a class="btn primary" href="/scanner">🔎 الماسح الذكي</a><a class="btn" href="/market/spot">₿ سوق السبوت</a></div></section><div class="section-title"><h2>📡 إشارات البوت الحالية</h2><span class="pill">'+str(len(rows))+' إشارة</span></div><div class="grid">'+items+'</div>'
    return page(req,"بوت السبوت",body)

@app.get("/scanner",response_class=HTMLResponse)
def scanner(req:Request,tf:str="all"):
    if tf not in TIMEFRAMES:tf="all"
    c=db();
    if tf=="all": rows=c.execute("SELECT market,symbol,side,timeframe,entry,tp,stop,tp1,tp2,tp3,confidence,change15,created_at FROM signals WHERE status='open' ORDER BY change15 DESC,confidence DESC,id DESC LIMIT 100").fetchall()
    else: rows=c.execute("SELECT market,symbol,side,timeframe,entry,tp,stop,tp1,tp2,tp3,confidence,change15,created_at FROM signals WHERE status='open' AND timeframe=? ORDER BY change15 DESC,confidence DESC,id DESC LIMIT 100",(tf,)).fetchall()
    names={"spot":"السبوت","futures":"الفيوتشر","contracts":"العقود","american":"الأمريكي","saudi":"السعودي","forex":"فوركس وذهب"}
    tabs=" ".join(f'<a class="pill" href="/scanner?tf={x}">{x}</a>' for x in TIMEFRAMES)
    cards="".join(f'<div class="card signal"><div class="gold"><b>#{i}</b> · {names.get(x["market"],x["market"])}</div><h3>{esc(x["symbol"])}</h3><div class="{("buy" if x["side"]=="BUY" else "danger")}">{esc(x["side"])} · {esc(x["timeframe"])}</div><p>دخول {x["entry"]:.6g} · وقف {x["stop"]:.6g} · TP1 {x["tp1"]:.6g} · TP2 {x["tp2"]:.6g} · TP3 {x["tp3"]:.6g}</p><p>تغير الفريم: <b>{x["change15"]:.2f}%</b></p><p>AI%: <b>{x["confidence"]:.0f}%</b></p></div>' for i,x in enumerate(rows,1))
    return page(req,"الماسح",f'<div class="hero"><h1>الماسح الذكي</h1><p>كل الأسواق · كل الفريمات · كل فريم يطبق الاستراتيجية بشكل مستقل</p><div style="display:flex;gap:6px;flex-wrap:wrap;margin:12px 0">{tabs}</div></div><div class="grid">{cards or "<div class=card>لا توجد إشارات لهذا الفريم حاليًا.</div>"}</div>')
@app.get("/trades",response_class=HTMLResponse)
def trades_page(req:Request):
    c=db()
    open_rows=c.execute("SELECT * FROM trades WHERE status='open' ORDER BY confidence DESC, id DESC LIMIT 100").fetchall()
    recent=c.execute("SELECT * FROM trades WHERE status='closed' ORDER BY closed_at DESC, id DESC LIMIT 20").fetchall()
    closed=c.execute("SELECT COUNT(*) n, COALESCE(SUM(pnl_pct),0) pnl FROM trades WHERE status='closed'").fetchone()
    def period_stats(days):
        cutoff=(datetime.now(timezone.utc)-__import__("datetime").timedelta(days=days)).isoformat()
        r=c.execute("SELECT COUNT(*) n, COALESCE(SUM(pnl_pct),0) pnl FROM trades WHERE status='closed' AND closed_at>=?",(cutoff,)).fetchone()
        return int(r["n"] or 0),float(r["pnl"] or 0)
    day_n,day_pnl=period_stats(1); week_n,week_pnl=period_stats(7); month_n,month_pnl=period_stats(30); year_n,year_pnl=period_stats(365)
    wins=c.execute("SELECT COUNT(*) n FROM trades WHERE status='closed' AND pnl_pct>0").fetchone()["n"]
    losses=c.execute("SELECT COUNT(*) n FROM trades WHERE status='closed' AND pnl_pct<=0").fetchone()["n"]
    total=closed["n"] or 0
    winrate=(wins/total*100) if total else 0

    def num(v):
        return "—" if v is None else f"{float(v):.8g}"
    def pct(v):
        return "—" if v is None else f"{float(v):+.2f}%"
    def market_label(m):
        return {"spot":"السبوت","futures":"الفيوتشر","contracts":"العقود","american":"الأمريكي","saudi":"السعودي","forex":"فوركس وذهب"}.get(m,m)
    def trade_card(x,i):
        tps=[x["tp1"],x["tp2"],x["tp3"]]
        entry=float(x["entry"] or 0); stop=float(x["stop"] or 0); side=x["side"] or "BUY"
        is_sell=side=="SELL"
        stop_pct=((entry-stop)/entry*100) if is_sell and entry else ((stop-entry)/entry*100 if entry else 0)
        def level_pct(v):
            if not entry or v is None:return 0
            return ((entry-float(v))/entry*100) if is_sell else ((float(v)-entry)/entry*100)
        tp_html="".join(f'<div class="tp-item"><span>TP{j}</span><b>{num(v)}</b><em>{level_pct(v):+.2f}%</em></div>' for j,v in enumerate(tps,1) if v is not None)
        direction="بيع" if is_sell else "شراء"
        tone="sell" if is_sell else "buy"
        return f'''
        <article class="trade-card {tone}">
          <div class="trade-top">
            <div class="rank">{("👑" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i:02d}")}</div>
            <div class="asset"><strong>{esc(x["symbol"])}</strong><span>{market_label(x["market"])} · {esc(x["timeframe"] or "—")}</span></div>
            <div class="direction"><b>{direction}</b><small>● مفتوحة</small><em>صفقة ذكية</em></div>
          </div>
          <div class="trade-entry">
            <div><small>الدخول</small><strong>{num(x["entry"])}</strong></div>
            <div class="ai"><small>AI</small><strong>{float(x["confidence"] or 0):.0f}%</strong></div>
          </div>
          <div class="risk-row">
            <div class="stop-box"><span>🛑 وقف الخسارة</span><b>{num(x["stop"])}</b><em>{stop_pct:+.2f}%</em></div>
          </div>
          <div class="targets-title"><span>الأهداف</span><small>الربح المحتمل من الدخول</small></div>
          <div class="targets">{tp_html}</div>
          <div class="trade-meta"><span>تغير الفريم <b>{pct(x["change15"])}</b></span><span>فتح {esc((x["opened_at"] or "")[:16])}</span></div>
        </article>'''
    def closed_card(x):
        pnl=float(x["pnl_pct"] or 0)
        cls="profit" if pnl>0 else "loss"
        return f'<div class="closed-row"><div><strong>{esc(x["symbol"])}</strong><span>{market_label(x["market"])}</span></div><div><span>{esc(x["side"] or "BUY")}</span><span>{esc(x["closed_at"] or "")[:16]}</span></div><b class="{cls}">{pnl:+.2f}%</b></div>'

    cards="".join(trade_card(x,i) for i,x in enumerate(open_rows,1))
    history="".join(closed_card(x) for x in recent)
    body=f'''
    <style>
      .trades-wrap{{max-width:1220px;margin:auto}}
      .trades-hero{{padding:28px 0 20px;display:flex;justify-content:space-between;align-items:end;gap:18px}}
      .trades-hero h1{{margin:0;font-size:clamp(28px,4vw,42px);letter-spacing:-1.4px}}
      .trades-hero p{{margin:8px 0 0;color:#8290a4}}
      .live-dot{{display:inline-flex;align-items:center;gap:8px;padding:10px 14px;border:1px solid #223047;border-radius:999px;background:#0c1521;color:#b8c4d4;font-size:12px}}
      .live-dot i{{width:7px;height:7px;border-radius:50%;background:#2fe08a;box-shadow:0 0 12px #2fe08a}}
      .trade-stats{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:4px 0 30px}}
      .trade-stat{{padding:17px 18px;border:1px solid #1e2b3d;background:#0c1521;border-radius:16px}}
      .trade-stat small{{display:block;color:#718097;margin-bottom:8px}}.trade-stat strong{{font-size:24px}}.trade-stat .green{{color:#38dc91}}.trade-stat .red{{color:#ff6678}}
      .section-title{{display:flex;justify-content:space-between;align-items:center;margin:24px 0 12px}}.section-title h2{{margin:0;font-size:20px}}.section-title span{{color:#718097;font-size:12px}}
      .trade-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}
      .trade-card{{position:relative;overflow:hidden;border:1px solid #263a52;border-radius:22px;background:radial-gradient(circle at 100% 0,#172a3d 0,#111d2b 35%,#09121d 78%);padding:19px;box-shadow:0 18px 45px rgba(0,0,0,.22)}}
      .trade-card:after{{content:"";position:absolute;inset:0 auto 0 0;width:3px;background:#29d789}}.trade-card.sell:after{{background:#ff5e70}}
      .trade-top{{display:flex;align-items:center;gap:11px}}.rank{{width:38px;height:38px;display:grid;place-items:center;border-radius:12px;background:#172438;font-size:15px;font-weight:900}}.asset{{flex:1;min-width:0}}.asset strong{{display:block;font-size:19px}}.asset span{{display:block;color:#718097;font-size:11px;margin-top:3px}}.direction{{text-align:left;min-width:76px}}.direction b{{display:block;font-size:12px;color:#35dc91}}.trade-card.sell .direction b{{color:#ff6879}}.direction small{{display:block;color:#69778d;font-size:10px;margin-top:3px}}.direction em{{display:inline-block;margin-top:6px;padding:3px 7px;border-radius:999px;background:#173126;color:#55dfa2;font-size:8px;font-style:normal}}.trade-card.sell .direction em{{background:#351d25;color:#ff8290}}
      .trade-entry{{display:grid;grid-template-columns:1fr 92px;gap:9px;margin-top:15px}}.trade-entry>div{{padding:13px 14px;border:1px solid #1b2a3d;background:#0b1521;border-radius:14px}}.trade-entry small{{display:block;color:#708097;font-size:10px}}.trade-entry strong{{display:block;font-size:21px;margin-top:5px}}.trade-entry .ai{{text-align:center;border-color:#24403a}}.trade-entry .ai strong{{color:#45dfa0;font-size:20px}}
      .risk-row{{margin-top:9px}}.stop-box{{display:grid;grid-template-columns:1fr auto auto;align-items:center;gap:10px;padding:11px 13px;background:#15151e;border:1px solid #39232c;border-radius:12px}}.stop-box span{{color:#a6aebe;font-size:11px}}.stop-box b{{color:#ff7180;font-size:13px}}.stop-box em{{color:#ff7180;font-size:11px;font-style:normal}}
      .targets-title{{display:flex;justify-content:space-between;align-items:center;margin:16px 2px 8px}}.targets-title span{{font-size:13px;font-weight:800}}.targets-title small{{color:#65748a;font-size:10px}}.targets{{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}}.tp-item{{text-align:center;padding:10px 5px;border:1px solid #1d3540;background:#0b1920;border-radius:11px}}.tp-item span{{display:block;color:#55dca4;font-size:10px;font-weight:800}}.tp-item b{{display:block;font-size:13px;margin:4px 0}}.tp-item em{{font-style:normal;color:#42d99b;font-size:11px}}
      .trade-meta{{display:flex;justify-content:space-between;gap:10px;margin-top:13px;padding-top:11px;border-top:1px solid #192638;color:#68778d;font-size:10px}}.trade-meta b{{color:#cdd7e4}}
      .closed-list{{border:1px solid #202d3f;border-radius:16px;overflow:hidden;background:#0d1622}}.closed-row{{display:grid;grid-template-columns:1fr 1fr auto;align-items:center;gap:10px;padding:13px 15px;border-bottom:1px solid #1a2636}}.closed-row:last-child{{border-bottom:0}}.closed-row strong,.closed-row span{{display:block}}.closed-row span{{color:#77869b;font-size:11px;margin-top:3px}}.closed-row>div:nth-child(2){{display:flex;gap:15px}}.closed-row .profit{{color:#35d98a}}.closed-row .loss{{color:#ff6574}}.empty-trades{{padding:40px;text-align:center;color:#7f8da3;border:1px dashed #26364c;border-radius:16px;background:#0c1520}}
      @media(max-width:800px){{.trade-stats{{grid-template-columns:repeat(2,1fr)}}.trade-grid{{grid-template-columns:1fr}}.trades-hero{{align-items:flex-start;flex-direction:column}}}}
      @media(max-width:520px){{.trade-stats{{grid-template-columns:repeat(2,1fr)}}.trade-entry{{grid-template-columns:1fr 82px}}.trade-entry strong{{font-size:18px}}.stop-box{{grid-template-columns:1fr auto}}.stop-box em{{grid-column:2}}.targets-title small{{display:none}}.trade-meta{{flex-wrap:wrap}}.closed-row{{grid-template-columns:1fr auto}}.closed-row>div:nth-child(2){{display:none}}}}
    </style>
    <div class="trades-wrap">
      <div class="trades-hero"><div><h1>متابع الصفقات</h1><p>مراقبة الصفقات المفتوحة والنتائج الفعلية بشكل واضح وسريع.</p></div><div class="live-dot"><i></i> بيانات حية</div></div>
      <div class="trade-stats">
        <div class="trade-stat"><small>مفتوحة</small><strong>{len(open_rows)}</strong></div>
        <div class="trade-stat"><small>مغلقة</small><strong>{total}</strong></div>
        <div class="trade-stat"><small>رابحة</small><strong class="green">{wins}</strong></div>
        <div class="trade-stat"><small>خاسرة</small><strong class="red">{losses}</strong></div>
        <div class="trade-stat"><small>نسبة النجاح</small><strong>{winrate:.1f}%</strong></div><div class="trade-stat"><small>اليوم</small><strong class="{'green' if day_pnl>=0 else 'red'}">{day_pnl:+.2f}%</strong></div><div class="trade-stat"><small>الأسبوع</small><strong class="{'green' if week_pnl>=0 else 'red'}">{week_pnl:+.2f}%</strong></div><div class="trade-stat"><small>الشهر</small><strong class="{'green' if month_pnl>=0 else 'red'}">{month_pnl:+.2f}%</strong></div><div class="trade-stat"><small>السنة</small><strong class="{'green' if year_pnl>=0 else 'red'}">{year_pnl:+.2f}%</strong></div>
      </div>
      <div class="section-title"><h2>الصفقات المفتوحة</h2><span>{len(open_rows)} صفقة · مرتبة حسب AI%</span></div>
      <div class="trade-grid">{cards or '<div class="empty-trades">ما فيه صفقات مفتوحة حاليًا.</div>'}</div>
      <div class="section-title"><h2>آخر الصفقات المغلقة</h2><span>آخر 20 صفقة</span></div>
      <div class="closed-list">{history or '<div class="empty-trades">ما فيه صفقات مغلقة حتى الآن.</div>'}</div>
    </div>'''
    return page(req,"متابع الصفقات",body)
@app.get("/register",response_class=HTMLResponse)
def register_form(req:Request):
    err=esc(req.query_params.get("error",""))
    note=f'<div class="card danger" style="margin-bottom:14px">{err}</div>' if err else ""
    return page(req,"تسجيل",f'<div class="card"><h2>إنشاء حساب</h2>{note}<form method="post"><input name="name" placeholder="الاسم" required><input name="email" type="text" placeholder="البريد الإلكتروني" required><input name="password" type="password" placeholder="كلمة المرور — 6 أحرف على الأقل" minlength="6" required><button class="btn primary">إنشاء الحساب</button></form><p class="muted">عندك حساب؟ <a href="/login">تسجيل الدخول</a></p></div>')
@app.post("/register")
def register(req:Request,name:str=Form(""),email:str=Form(""),password:str=Form("")):
    email=email.strip().lower(); name=" ".join(name.split())
    if not name or len(name)<2 or len(name)>60 or not email or len(email)>254 or not password or len(password)<6 or len(password)>128:
        return RedirectResponse("/register?error=تأكد من الاسم والبريد وكلمة المرور (6 أحرف على الأقل)",303)
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        return RedirectResponse("/register?error=البريد الإلكتروني غير صحيح",303)
    c=db()
    try:
        if c.execute("SELECT 1 FROM users WHERE lower(email)=?",(email,)).fetchone():
            return RedirectResponse("/register?error=البريد مستخدم مسبقًا",303)
        if c.execute("SELECT 1 FROM users WHERE lower(name)=?",(name.lower(),)).fetchone():
            return RedirectResponse("/register?error=اسم المستخدم مستخدم مسبقًا",303)
        if name.lower()==ADMIN_USERNAME.lower():
            return RedirectResponse("/register?error=اسم المستخدم محجوز",303)
        c.execute("INSERT INTO users(email,password,name,created_at) VALUES(?,?,?,?)",(email,pwd.hash(password),name,now()))
        c.commit()
    except sqlite3.IntegrityError:
        c.rollback()
        return RedirectResponse("/register?error=البريد أو اسم المستخدم مستخدم مسبقًا",303)
    except sqlite3.OperationalError:
        c.rollback()
        return RedirectResponse("/register?error=قاعدة البيانات مشغولة، حاول مرة ثانية",303)
    return RedirectResponse("/login?created=1",303)
@app.get("/login",response_class=HTMLResponse)
def login_form(req:Request):
    err=esc(req.query_params.get("error",""))
    note='<div class="card" style="margin-bottom:14px;border-color:#16a34a">تم إنشاء الحساب، سجل دخولك الآن.</div>' if req.query_params.get("created")=="1" else ""
    if err:note=f'<div class="card danger" style="margin-bottom:14px">{err}</div>'
    return page(req,"دخول",f'<div class="card"><h2>تسجيل الدخول</h2>{note}<form method="post"><input name="email" type="text" placeholder="البريد أو اسم المستخدم" required><input name="password" type="password" placeholder="كلمة المرور" required><button class="btn primary">دخول</button></form><p class="muted">ما عندك حساب؟ <a href="/register">إنشاء حساب</a></p></div>')
@app.post("/login")
def login(req:Request,email:str=Form(""),password:str=Form("")):
    login_value=email.strip()
    if not login_value or not password or len(login_value)>254 or len(password)>128:
        return RedirectResponse("/login?error=أدخل بيانات الدخول كاملة",303)
    c=db()
    u=c.execute("SELECT * FROM users WHERE active=1 AND (lower(email)=? OR lower(name)=?)",(login_value.lower(),login_value.lower())).fetchone()
    if not u or not pwd.verify(password,u["password"]):
        return RedirectResponse("/login?error=بيانات الدخول غير صحيحة",303)
    req.session.clear()
    req.session["uid"]=u["id"]
    return RedirectResponse("/admin" if u["role"]=="admin" else "/",303)
@app.get("/logout")
def logout(req:Request):req.session.clear();return RedirectResponse("/",303)
@app.get("/support",response_class=HTMLResponse)
def support(req:Request):
    u=require(req)
    if not hasattr(u,"__getitem__"): return u
    rows=db().execute("SELECT * FROM support_tickets WHERE user_id=? ORDER BY id DESC",(u["id"],)).fetchall()
    cards="".join(f'<div class="card"><h3>طلب #{x["id"]} — {("مفتوح" if x["status"]=="open" else "مغلق")}</h3><p>{esc(x["message"])}</p><p class="muted">{esc(x["admin_reply"] or "بانتظار رد الإدارة")}</p></div>' for x in rows)
    body=f'<div class="hero"><h1>الدعم الفني</h1><p>إذا عندك مشكلة أو تبي تتواصل مع الإدارة، ارسل طلبك هنا.</p><form method="post" action="/support"><textarea name="message" required placeholder="اكتب رسالتك للإدارة" style="min-height:140px"></textarea><button class="btn primary">إرسال للإدارة</button></form></div><h2>طلباتك السابقة</h2><div class="grid">{cards or "<div class=card>ما عندك طلبات دعم سابقة.</div>"}</div>'
    return page(req,"الدعم الفني",body)

@app.post("/support")
def support_post(req:Request,message:str=Form("")):
    u=require(req)
    if not hasattr(u,"__getitem__"): return u
    msg=message.strip()
    if not msg:return RedirectResponse("/support",303)
    c=db();c.execute("INSERT INTO support_tickets(user_id,name,email,message,created_at,updated_at) VALUES(?,?,?,?,?,?)",(u["id"],u["name"],u["email"],msg,now(),now()));c.commit()
    return RedirectResponse("/support",303)

@app.get("/account",response_class=HTMLResponse)
def account(req:Request):
    u=require(req)
    if not hasattr(u,"__getitem__"):return u
    c=db(); c.execute("UPDATE subscriptions SET status='expired' WHERE user_id=? AND status='active' AND expires_at IS NOT NULL AND expires_at<=?",(u["id"],now())); c.commit(); subs=c.execute("SELECT * FROM subscriptions WHERE user_id=? ORDER BY id DESC",(u["id"],)).fetchall()
    body=f'<div class="card"><h2>حسابي</h2><p>{esc(u["name"] or u["email"])}</p><p>الحالة: <span class="buy">نشط</span></p><a class="btn" href="/logout">خروج</a></div><h2>الاشتراكات</h2><div class="grid">'+''.join(f'<div class="card">{esc(x["plan"])} — {x["status"]}</div>' for x in subs)+'</div>'
    return page(req,"حسابي",body)

PLAN_PRICES={7:10.0,15:20.0,30:30.0}
@app.get("/subscriptions",response_class=HTMLResponse)
def subscriptions(req:Request):
    plans=[("7 أيام",7,10),("15 يوم",15,20),("30 يوم",30,30)]
    cards="".join(f'<div class="card"><h2>{p[0]}</h2><div class="stat">{p[2]} <small>USDT</small></div><p>الوصول إلى التوصيات والماسح والأسواق</p><a class="btn goldbg" href="/subscribe?days={p[1]}&price={p[2]}">طلب الاشتراك</a></div>' for p in plans)
    return page(req,"الاشتراكات",'<h1>الاشتراكات</h1><div class="grid">'+cards+'</div><p class="muted">الدفع يمر بطلب ومراجعة الإدارة قبل التفعيل.</p>')

@app.get("/subscribe",response_class=HTMLResponse)
def subscribe(req:Request,days:int,price:float):
    u=require(req)
    if not hasattr(u,"__getitem__"):return u
    if days not in PLAN_PRICES or abs(float(price)-PLAN_PRICES[days])>0.001:return RedirectResponse("/subscriptions",303)
    return page(req,"طلب اشتراك",f'<div class="card"><h2>طلب اشتراك {days} يوم</h2><form method="post"><input name="method" placeholder="طريقة الدفع" required><input name="txid" placeholder="رقم العملية" required><input type="hidden" name="days" value="{days}"><input type="hidden" name="price" value="{PLAN_PRICES[days]}"><button class="btn goldbg">إرسال الطلب</button></form></div>')
@app.post("/subscribe")
def subscribe_post(req:Request,days:int=Form(...),price:float=Form(...),method:str=Form(""),txid:str=Form("")):
    u=require(req)
    if not hasattr(u,"__getitem__"):return u
    if days not in PLAN_PRICES or abs(float(price)-PLAN_PRICES[days])>0.001 or not method.strip() or not txid.strip():return RedirectResponse("/subscriptions",303)
    c=db();c.execute("INSERT INTO payments(user_id,plan,amount,method,txid,created_at) VALUES(?,?,?,?,?,?)",(u["id"],f"{days} يوم",PLAN_PRICES[days],method.strip(),txid.strip(),now()));c.commit();return RedirectResponse("/account",303)

@app.get("/admin",response_class=HTMLResponse)
def admin(req:Request):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"):return u
    c=db(); users=c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]; payments=c.execute("SELECT COUNT(*) n FROM payments WHERE status='pending'").fetchone()["n"]; sig=c.execute("SELECT COUNT(*) n FROM signals").fetchone()["n"]
    features=[("accounts","الحسابات والتسجيل"),("trades","الصفقات"),("scanner","الماسح الذكي"),("bot","بوت السبوت"),("spot","السبوت"),("futures","الفيوتشر"),("contracts","العقود"),("american","السوق الأمريكي"),("saudi","السوق السعودي"),("forex","الفوركس والذهب"),("news","الأخبار"),("blog","المدونة"),("subscriptions","الاشتراكات"),("support","الدعم الفني"),("telegram","تيليجرام")]
    feature_cards="".join(f'<div class="card"><div class="section-title"><b>{label}</b><span class="pill {("buy" if feature_enabled(key) else "danger")}">{("مفتوح" if feature_enabled(key) else "مغلق")}</span></div><form method="post" action="/admin/feature/{key}"><button class="btn {("primary" if not feature_enabled(key) else "")}">{("فتح القسم" if not feature_enabled(key) else "إغلاق القسم")}</button></form></div>' for key,label in features)
    body=f'<h1>لوحة الإدارة</h1><div class="grid"><div class="card"><div class="stat">{users}</div>حسابات</div><div class="card"><div class="stat">{payments}</div>طلبات دفع معلقة</div><div class="card"><div class="stat">{sig}</div>توصيات</div></div><div class="card"><h2>التحكم الكامل بالخدمات</h2><p class="muted">تقدر تفتح أو تقفل أي قسم مباشرة من هنا.</p><div class="grid">{feature_cards}</div></div><div class="card"><h2>تشغيل الفحص</h2><form method="post" action="/admin/scan"><button class="btn primary">فحص جميع الأسواق الآن</button></form></div><div class="card"><h2>إضافة رمز للسكانر</h2><form method="post" action="/admin/symbol"><select name="market"><option>spot</option><option>futures</option><option>contracts</option><option>american</option><option>saudi</option><option>forex</option></select><input name="symbol" placeholder="رمز السوق"><button class="btn">إضافة</button></form></div><div class="card"><a class="btn" href="/admin/users">إدارة الحسابات</a> <a class="btn" href="/admin/payments">إدارة المدفوعات</a> <a class="btn" href="/bot">بوت السبوت</a></div>'
    return page(req,"الإدارة",body)
@app.get("/admin/users",response_class=HTMLResponse)
def admin_users(req:Request):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"): return u
    rows=db().execute("SELECT id,name,email,role,active,created_at FROM users ORDER BY id DESC").fetchall()
    cards=[]
    for x in rows:
        state="نشط" if x["active"] else "موقوف"
        action="إيقاف" if x["active"] else "تفعيل"
        role_action="إلغاء المدير" if x["role"]=="admin" else "تعيين مدير"
        cards.append(f'<div class="card"><h3>{esc(x["name"] or x["email"])}</h3><p>{esc(x["email"])}</p><p>الصلاحية: {esc(x["role"])} · الحالة: {state}</p><form method="post" action="/admin/user/{x["id"]}/toggle" style="display:inline"><button class="btn">{action}</button></form> <form method="post" action="/admin/user/{x["id"]}/role" style="display:inline"><button class="btn">{role_action}</button></form></div>')
    return page(req,"إدارة الحسابات",'<h1>إدارة الحسابات</h1><div class="grid">'+''.join(cards)+'</div>')

@app.post("/admin/user/{uid}/toggle")
def admin_user_toggle(req:Request,uid:int):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"): return u
    c=db(); c.execute("UPDATE users SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=? AND id<>?",(uid,u["id"])); c.commit()
    return RedirectResponse("/admin/users",303)

@app.post("/admin/user/{uid}/role")
def admin_user_role(req:Request,uid:int):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"): return u
    c=db(); c.execute("UPDATE users SET role=CASE role WHEN 'admin' THEN 'user' ELSE 'admin' END WHERE id=? AND id<>?",(uid,u["id"])); c.commit()
    return RedirectResponse("/admin/users",303)

@app.post("/admin/feature/{key}")
def admin_feature(req:Request,key:str):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"): return u
    if key not in FEATURE_DEFAULTS: return RedirectResponse("/admin",303)
    set_feature(key,not feature_enabled(key))
    return RedirectResponse("/admin",303)

@app.post("/admin/scan")
def admin_scan(req:Request):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"):return u
    threading.Thread(target=scan_all_markets,daemon=True,name="admin-manual-scan").start()
    return RedirectResponse("/admin",303)
@app.post("/admin/symbol")
def admin_symbol(req:Request,market:str=Form(...),symbol:str=Form(...)):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"):return u
    market=market.strip().lower(); symbol=symbol.strip().upper()
    if market not in ("spot","futures","contracts","american","saudi","forex") or not symbol:return RedirectResponse("/admin",303)
    c=db()
    if not c.execute("SELECT 1 FROM symbols WHERE market=? AND symbol=?",(market,symbol)).fetchone():
        c.execute("INSERT INTO symbols(market,symbol,name) VALUES(?,?,?)",(market,symbol,symbol));c.commit()
    return RedirectResponse("/admin",303)
@app.get("/admin/support",response_class=HTMLResponse)
def admin_support(req:Request):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"): return u
    rows=db().execute("SELECT * FROM support_tickets ORDER BY CASE WHEN status='open' THEN 0 ELSE 1 END, id DESC").fetchall()
    body='<h1>الدعم الفني</h1><div class="grid">'+''.join(f'<div class="card"><h3>#{x["id"]} · {esc(x["name"] or x["email"])}</h3><p class="muted">{esc(x["email"])} · {esc(x["created_at"])}</p><p>{esc(x["message"])}</p><p class="muted">{esc(x["admin_reply"] or "لا يوجد رد بعد")}</p><form method="post" action="/admin/support/{x["id"]}/reply"><textarea name="reply" required placeholder="رد الإدارة"></textarea><button class="btn primary">إرسال الرد</button></form></div>' for x in rows)+'</div>'
    return page(req,"الدعم الفني",body)

@app.post("/admin/support/{tid}/reply")
def admin_support_reply(req:Request,tid:int,reply:str=Form("")):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"): return u
    c=db();c.execute("UPDATE support_tickets SET admin_reply=?,status='closed',updated_at=? WHERE id=?",(reply.strip(),now(),tid));c.commit()
    return RedirectResponse("/admin/support",303)

@app.get("/admin/payments",response_class=HTMLResponse)
def payments(req:Request):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"):return u
    rows=db().execute("SELECT p.*,u.email FROM payments p JOIN users u ON u.id=p.user_id ORDER BY p.id DESC").fetchall()
    body='<div class="card"><h1>المدفوعات</h1><table class="table"><tr><th>المستخدم</th><th>الخطة</th><th>المبلغ</th><th>الحالة</th><th></th></tr>'+''.join(f'<tr><td>{esc(x["email"])}</td><td>{x["plan"]}</td><td>{x["amount"]}</td><td>{x["status"]}</td><td><form method="post" action="/admin/payment/{x["id"]}/approve" style="display:inline"><button class="btn">اعتماد</button></form> <form method="post" action="/admin/payment/{x["id"]}/reject" style="display:inline"><button class="btn">رفض</button></form></td></tr>' for x in rows)+'</table></div>'
    return page(req,"المدفوعات",body)
@app.post("/admin/payment/{pid}/reject")
def reject_payment(req:Request,pid:int):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"):return u
    c=db(); c.execute("UPDATE payments SET status='rejected' WHERE id=? AND status='pending'",(pid,)); c.commit()
    return RedirectResponse("/admin/payments",303)
@app.post("/admin/payment/{pid}/approve")
def approve(req:Request,pid:int):
    u=require(req,"admin")
    if not hasattr(u,"__getitem__"):return u
    c=db();p=c.execute("SELECT * FROM payments WHERE id=? AND status='pending'",(pid,)).fetchone()
    if p:
        c.execute("UPDATE payments SET status='approved' WHERE id=? AND status='pending'",(pid,))
        days=int(str(p["plan"]).split()[0]);created=now();base=datetime.now(timezone.utc)
        active=c.execute("SELECT expires_at FROM subscriptions WHERE user_id=? AND status='active' ORDER BY id DESC LIMIT 1",(p["user_id"],)).fetchone()
        if active and active["expires_at"]:
            try: base=max(base,datetime.fromisoformat(active["expires_at"]))
            except Exception: pass
        expires=(base+__import__("datetime").timedelta(days=days)).isoformat()
        c.execute("INSERT INTO subscriptions(user_id,plan,days,price,status,created_at,expires_at) VALUES(?,?,?,?,?,?,?)",(p["user_id"],p["plan"],days,p["amount"],"active",created,expires));c.commit()
    return RedirectResponse("/admin/payments",303)

@app.get("/news",response_class=HTMLResponse)
def news(req:Request):
    c=db();rows=c.execute("SELECT * FROM news ORDER BY id DESC LIMIT 30").fetchall()
    body='<h1>📰 الأخبار</h1><p class="muted">أخبار محفوظة داخل المنصة وتظهر كصفحات مستقلة.</p><div class="grid">'+''.join(f'<a class="card" href="/news/{x["id"]}"><h3>{esc(x["title"])}</h3><p class="muted">{esc(x["source"])} · {esc(x["published"])}</p></a>' for x in rows)+'</div>'
    return page(req,"الأخبار",body)

@app.get("/news/{nid}",response_class=HTMLResponse)
def news_article(req:Request,nid:int):
    x=db().execute("SELECT * FROM news WHERE id=?",(nid,)).fetchone()
    if not x:return RedirectResponse("/news",303)
    body=f'<article class="card"><h1>{esc(x["title"])}</h1><p class="muted">{esc(x["source"])} · {esc(x["published"])}</p><div style="line-height:2">{esc(x["body"] or "خبر سوقي محفوظ في قاعدة المنصة.").replace(chr(10),"<br>")}</div><a class="btn" href="/news">رجوع للأخبار</a></article>'
    return page(req,"خبر",body)
@app.get("/blog",response_class=HTMLResponse)
def blog(req:Request):
    rows=db().execute("SELECT * FROM posts WHERE status='published' ORDER BY id DESC").fetchall()
    body='<h1>✎ المدونة</h1><div class="grid">'+''.join(f'<a class="card" href="/blog/{esc(x["slug"])}"><h2>{esc(x["title"])}</h2><p class="muted">{esc(x["created_at"])}</p></a>' for x in rows)+'</div>'
    return page(req,"المدونة",body)
@app.get("/blog/{slug}",response_class=HTMLResponse)
def article(req:Request,slug:str):
    x=db().execute("SELECT * FROM posts WHERE slug=? AND status='published'",(slug,)).fetchone()
    if not x:return RedirectResponse("/blog",303)
    return page(req,x["title"],f'<article class="card"><h1>{esc(x["title"])}</h1><div>{esc(x["body"]).replace(chr(10),"<br>")}</div></article>')

def news_loop():
    while True:
        try:
            if not feature_enabled("news"):
                time.sleep(60); continue
            xml=get("https://feeds.bbci.co.uk/arabic/rss.xml");root=ET.fromstring(xml)
            c=db()
            for item in root.findall(".//item")[:20]:
                t=item.findtext("title") or "";u=item.findtext("link") or "";d=item.findtext("pubDate") or "";desc=item.findtext("description") or ""
                if t and not c.execute("SELECT 1 FROM news WHERE url=?",(u,)).fetchone():c.execute("INSERT INTO news(title,url,source,published,body) VALUES(?,?,?,?,?)",(t,u,"BBC عربي",d,desc))
            c.commit()
        except Exception:pass
        time.sleep(900)
def scan_loop():
    while True:
        try:scan_all_markets()
        except Exception:pass
        time.sleep(int(os.getenv("SCAN_SECONDS","900")))

@app.on_event("startup")
def startup():
    db()
    if os.getenv("RUN_NEWS_WORKER","0")=="1":
        threading.Thread(target=news_loop,daemon=True,name="news-worker").start()
    if os.getenv("RUN_SCAN_WORKER","0")=="1":
        threading.Thread(target=_scan_loop,daemon=True,name="scan-worker").start()
@app.get("/robots.txt")
def robots(): return HTMLResponse("User-agent: *\
Allow: /\
Sitemap: /sitemap.xml",media_type="text/plain")
@app.get("/sitemap.xml")
def sitemap(req:Request):
    base=str(req.base_url).rstrip("/"); urls=["/","/trades","/scanner","/market/spot","/market/futures","/market/contracts","/market/american","/market/saudi","/market/forex","/news","/blog","/subscriptions","/login","/register"]
    c=db()
    for x in c.execute("SELECT id FROM news ORDER BY id DESC LIMIT 500").fetchall(): urls.append(f"/news/{x['id']}")
    for x in c.execute("SELECT slug FROM posts WHERE status='published' ORDER BY id DESC LIMIT 500").fetchall(): urls.append("/blog/"+urllib.parse.quote(x["slug"]))
    xml='<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f"<url><loc>{esc(base+u)}</loc></url>" for u in urls)+'</urlset>'
    return HTMLResponse(xml,media_type="application/xml")
@app.get("/health")
def health():
    checks={}
    try:
        c=db(); c.execute("SELECT 1").fetchone(); checks["database"]="ok"
    except Exception: checks["database"]="error"
    checks["telegram"]="on" if feature_enabled("telegram") else "off"
    checks["scanner"]="on" if feature_enabled("scanner") else "off"
    checks["bot"]="on" if feature_enabled("bot") else "off"
    checks["markets"]={k:("on" if feature_enabled(k) else "off") for k in ("spot","futures","contracts","american","saudi","forex")}
    checks["data_cache_entries"]=len(_DATA_CACHE)
    return {"ok":True,"service":"mudarib-smart-pro","time":now(),"database":DB,"checks":checks}
if __name__=="__main__":
    import uvicorn;uvicorn.run(app,host="0.0.0.0",port=int(os.getenv("PORT","8080")))
