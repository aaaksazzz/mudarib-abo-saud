const app=document.getElementById("app"),drawer=document.getElementById("drawer"),backdrop=document.getElementById("backdrop"),menuBtn=document.getElementById("menuBtn"),closeMenu=document.getElementById("closeMenu"),themeBtn=document.getElementById("themeBtn"),supportOpen=document.getElementById("supportOpen");
const TFS=["15m","30m","1h","4h","1d","1w","1M"],LABELS={"15m":"15 د","30m":"30 د","1h":"ساعة","4h":"4 ساعات","1d":"يومي","1w":"أسبوعي","1M":"شهري"};
const MARKET={spot:["₿","السبوت","/fast-spot"],futures:["⚡","الفيوتشر","/futures-bot"],contracts:["▣","العقود الأمريكية","/fast-contracts"],us:["US","السوق الأمريكي","/fast-us"],saudi:["SA","السوق السعودي","/fast-saudi"],forex:["FX","الفوركس والذهب","/fast-forex"]};
const esc=s=>String((s!=null?s:"")).replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
function openDrawer(){drawer.classList.add("open");backdrop.classList.add("open");document.body.classList.add("drawer-open")}
function closeDrawer(){drawer.classList.remove("open");backdrop.classList.remove("open");document.body.classList.remove("drawer-open")}
menuBtn&&menuBtn.addEventListener("click",e=>{e.preventDefault();openDrawer()});closeMenu&&closeMenu.addEventListener("click",e=>{e.preventDefault();closeDrawer()});backdrop&&backdrop.addEventListener("click",closeDrawer);
document.querySelectorAll("#drawer a").forEach(a=>a.addEventListener("click",closeDrawer));
function applyTheme(){const light=localStorage.getItem("smart_theme")==="light";document.body.classList.toggle("light",light);if(themeBtn)themeBtn.textContent=light?"☾":"☀"}
themeBtn&&themeBtn.addEventListener("click",()=>{localStorage.setItem("smart_theme",document.body.classList.contains("light")?"dark":"light");applyTheme()});applyTheme();
function home(){
  const cards=Object.entries(MARKET).map(([k,m])=>'<a class="market-quick" href="'+m[2]+'" aria-label="فتح '+m[1]+'"><span class="mq-icon">'+m[0]+'</span><span><b>'+m[1]+'</b><small>فحص مستقل • 7 فريمات</small></span><strong>‹</strong></a>').join("");
  app.innerHTML='<section class="home-page"><section class="home-hero"><div class="home-hero-copy"><span class="home-live"><i></i> مباشر الآن</span><div class="eyebrow">SMART TRADING PRO • MARKET INTELLIGENCE</div><h1>قرارك يبدأ من <span>السوق.</span></h1><p>لوحة واحدة لمراقبة أقوى الفرص في السبوت والفيوتشر والأسواق العالمية، مع فريمات مستقلة وإشارات مرتبة بدون زحمة.</p><div class="actions"><a class="btn primary" href="/fast-spot">₿ ابدأ من السبوت</a><a class="btn" href="/futures-bot">⚡ مركز الفيوتشر</a></div><div class="home-kpis"><div><b>07</b><small>فريمات</small></div><div><b>06</b><small>أسواق</small></div><div><b>24/7</b><small>مراقبة</small></div></div></div><div class="home-terminal"><div class="terminal-head"><span>MARKET PULSE</span><b>SIGNAL</b></div><div class="pulse-symbol"><div><small>أفضل مكان للبدء</small><b>الماسح الذكي</b><span>رتّب الفرص حسب قوة الإشارة</span></div><strong>→</strong></div><div class="pulse-grid"><div><small>الفريم الأساسي</small><b>15 دقيقة</b></div><div><small>الإشارات</small><b>شراء / بيع</b></div><div><small>الأهداف</small><b>TP1 • TP2 • TP3</b></div><div><small>الحماية</small><b>وقف واضح</b></div></div><a class="pulse-link" href="/fast-spot">فتح الماسح ←</a></div></section><section class="home-markets"><div class="section-head"><div><span class="eyebrow">MARKET CENTER</span><h2>كل الأسواق في مكان واحد</h2></div><a href="/fast-spot">عرض الماسح ←</a></div><div class="home-market-grid">'+cards+'</div></section><section class="home-how"><div><span>01</span><b>افحص</b><small>اختر السوق والفريم المناسب.</small></div><div><span>02</span><b>رتّب</b><small>الأقوى يظهر أولاً حسب الإشارة.</small></div><div><span>03</span><b>راقب</b><small>الدخول والأهداف والوقف بوضوح.</small></div></section></section>';
  app.querySelector(".home-market-grid").innerHTML=cards;
}
function marketPage(key){
  const m=MARKET[key]||MARKET.spot;
  app.innerHTML='<section><div class="market-head"><div><div class="eyebrow">'+m[0]+' '+m[1]+'</div><h1>'+m[1]+'</h1><div class="muted">فحص مستقل للسوق والفريم المختار.</div></div><div class="muted" id="status">جاهز</div></div><div class="tf-row" id="tfRow">'+TFS.map((t,i)=>'<button class="tf '+(i===0?"active":"")+'" data-tf="'+t+'">'+LABELS[t]+'</button>').join("")+'</div><div id="result"><div class="empty loading">جاري جلب بيانات السوق…</div></div></section>';
  document.querySelectorAll(".tf").forEach(b=>b.onclick=()=>{document.querySelectorAll(".tf").forEach(x=>x.classList.remove("active"));b.classList.add("active");loadMarket(key,b.dataset.tf)});
  loadMarket(key,"15m");
}

let futuresSelectedTf="15m";
function futuresFmt(v){return Number(v||0).toLocaleString("en-US",{maximumFractionDigits:8})}
function futuresCard(x,tf,rank){
  const side=String(x.side||"").toUpperCase(), label=side==="BUY"?"شراء":"بيع";
  const ai=Math.round(Number(x.ai_pct||x.score||0)), ch=Number(x.change_pct||0);
  const level=(n,v)=>'<div class="fut-level"><small>'+n+'</small><b>'+futuresFmt(v)+'</b></div>';
  return '<article class="fut-signal '+(rank===1?"featured":"")+'"><div class="fut-signal-head"><div><span class="rank">#'+rank+'</span><b>'+esc(x.symbol||"—")+'</b><small>'+LABELS[tf]+' • AI '+ai+'%</small></div><span class="side '+(side==="BUY"?"buy":"sell")+'">'+label+'</span></div><div class="fut-levels">'+level("الدخول",x.entry)+level("TP1",x.tp1)+level("TP2",x.tp2)+level("TP3",x.tp3)+level("SL",x.sl)+'</div><div class="fut-meta"><span>تغير <b class="'+(ch>=0?"profit":"loss")+'">'+ch.toFixed(2)+'%</b></span><span>الترتيب <b>#'+rank+'</b></span></div></article>';
}
function futuresFrameSection(tf,rows,scanning){
  const list=Array.isArray(rows)?rows:[];
  const ranked=[...list].sort((a,b)=>Number(b.ai_pct||0)-Number(a.ai_pct||0)||Math.abs(Number(b.change_pct||0))-Math.abs(Number(a.change_pct||0)));
  const body=ranked.length?ranked.slice(0,10).map((x,i)=>futuresCard(x,tf,i+1)).join(""):'<div class="fut-empty">'+(scanning?'🔎 جاري الفحص…':'لا توجد صفقة مطابقة حالياً')+'</div>';
  return '<section class="fut-frame"><div class="fut-frame-head"><div><b>'+LABELS[tf]+'</b><small>'+ranked.length+' فرص • '+(scanning?'فحص مستمر':'محدث الآن')+'</small></div><span>FUTURES</span></div><div class="fut-signals">'+body+'</div></section>';
}
async function futuresPage(){
  app.innerHTML='<section class="futures-new"><div class="futures-topbar"><div><div class="eyebrow">⚡ USDⓈ-M FUTURES</div><h1>مركز إشارات الفيوتشر</h1><p>بيانات Binance حيّة • 7 فريمات • زر دخول ينفذ الصفقة الحقيقية على Binance Futures.</p></div><div class="bot-live real-ready"><i></i><b>REAL ORDERS</b><small>الدخول الحقيقي عند الضغط فقط</small></div></div><div class="futures-strip"><span>● Binance Market Data</span><span>🔎 فحص حي</span><span>📊 ترتيب AI</span><span>🛡️ دخول • أهداف • وقف</span></div><div id="futuresLive"></div><div id="futuresSearch" class="futures-search loading"><strong>🔎 جاري فحص جميع الفريمات</strong><small>يتم ترتيب الإشارات من الأقوى إلى الأضعف.</small></div><div id="futuresFrames"></div></section>';
  await refreshFuturesPage();
}
const FUTURES_TFS=["15m","30m","1h","4h","1d","1w","1M"];
const FUTURES_TF_LABEL={"15m":"15 دقيقة","30m":"30 دقيقة","1h":"ساعة","4h":"4 ساعات","1d":"يومي","1w":"أسبوعي","1M":"شهري"};
function futuresNum(v){return Number(v||0).toLocaleString("en-US",{maximumFractionDigits:8});}
function futuresRank(rows){
  return [...(Array.isArray(rows)?rows:[])].sort((a,b)=>{
    const ai=Number(b.ai_pct||b.score||0)-Number(a.ai_pct||a.score||0);
    if(ai)return ai;
    return Math.abs(Number(b.change_pct||0))-Math.abs(Number(a.change_pct||0));
  });
}
function renderFuturesRows(tf,rows){
  const sorted=futuresRank(rows);
  if(!sorted.length)return '<div class="futures-empty-line">لا توجد صفقة مطابقة حالياً — البوت مستمر بالفحص.</div>';
  return '<div class="futures-trades">'+sorted.map((x,i)=>{
    const side=String(x.side||"").toUpperCase(), buy=side==="BUY";
    const ai=Math.round(Number(x.ai_pct||x.score||0)), ch=Number(x.change_pct||0);
    return '<article class="futures-trade-row"><div class="ft-rank">#'+(i+1)+'</div><div class="ft-symbol"><b>'+esc(x.symbol||"—")+'</b><small>'+FUTURES_TF_LABEL[tf]+' • '+(buy?'شراء':'بيع')+'</small></div><div class="ft-ai"><small>AI</small><b>'+ai+'%</b></div><div class="ft-change '+(ch>=0?'profit':'loss')+'">'+ch.toFixed(2)+'%</div><div class="ft-levels"><span>دخول <b>'+futuresNum(x.entry)+'</b></span><span>TP1 <b>'+futuresNum(x.tp1)+'</b></span><span>TP2 <b>'+futuresNum(x.tp2)+'</b></span><span>TP3 <b>'+futuresNum(x.tp3)+'</b></span><span>SL <b>'+futuresNum(x.sl)+'</b></span></div><span class="side '+(buy?'buy':'sell')+'">'+(buy?'شراء':'بيع')+'</span></article>';
  }).join('')+'</div>';
}
function renderFuturesFrame(tf,rows,scanning){
  const sorted=futuresRank(rows),best=sorted[0];
  const buys=sorted.filter(x=>String(x.side||"").toUpperCase()==="BUY").length;
  const sells=sorted.filter(x=>String(x.side||"").toUpperCase()==="SELL").length;
  const badge=best?'<span class="frame-best">🏆 '+esc(best.symbol||"—")+' • AI '+Math.round(Number(best.ai_pct||best.score||0))+'%</span>':'<span class="frame-no">لا توجد إشارة</span>';
  return '<section class="futures-frame-section"><div class="frame-head"><div><b>'+FUTURES_TF_LABEL[tf]+'</b><small>'+tf+' • '+sorted.length+' صفقات • شراء '+buys+' • بيع '+sells+'</small></div>'+badge+'</div>'+renderFuturesRows(tf,sorted)+'</section>';
}
async function executeFuturesEntry(signal){
  if(!signal||!signal.symbol){return;}
  const side=String(signal.side||"").toUpperCase()==="BUY"?"شراء":"بيع";
  const ok=window.confirm("تنفيذ صفقة حقيقية على Binance Futures؟\n\n"+signal.symbol+" • "+side+"\nدخول: "+futuresNum(signal.entry)+"\nTP: "+futuresNum(signal.tp1)+"\nSL: "+futuresNum(signal.sl));
  if(!ok)return;
  const btn=document.querySelector(".futures-entry-btn");
  if(btn){btn.disabled=true;btn.textContent="جاري تنفيذ الأمر…";}
  try{
    const r=await fetch("/api/futures/entry",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(signal)});
    const d=await r.json();
    if(!r.ok||!d.ok)throw new Error(d.message||"فشل تنفيذ أمر Binance");
    alert("تم تنفيذ الدخول الحقيقي على Binance وتركيب TP/SL.");
    await refreshFuturesPage();
  }catch(e){
    alert(e.message||"تعذر تنفيذ الصفقة");
    if(btn){btn.disabled=false;btn.textContent="دخول حقيقي على Binance";}
  }
}
async function refreshFuturesPage(){
  const search=document.getElementById("futuresSearch"),frames=document.getElementById("futuresFrames"),live=document.getElementById("futuresLive");
  if(!search||!frames||!live)return;
  try{
    const bot={};
    const scans=[];
    for(const tf of FUTURES_TFS){
      try{
        const r=await fetch("/api/fast-market?market=futures&timeframe="+encodeURIComponent(tf),{cache:"no-store"});
        scans.push(await r.json());
      }catch(e){ scans.push({trades:[]}); }
      await new Promise(resolve=>setTimeout(resolve,120));
    }
    const allRows=scans.flatMap(x=>Array.isArray(x.trades)?x.trades:[]);
    const bestOverall=futuresRank(allRows.filter(x=>String(x.timeframe||"") === "15m"))[0];
    const botStatus=await fetch("/api/futures/bot",{cache:"no-store"}).then(r=>r.json()).catch(()=>({real_orders:false,bot:{}}));
    const canTrade=Boolean(botStatus.real_orders);
    const anyScanning=scans.some(x=>Boolean(x.scanning));
    live.innerHTML=bestOverall
      ? '<section class="futures-live-card"><div><small>أفضل إشارة 15 دقيقة</small><h3>'+esc(bestOverall.symbol||"—")+' • '+(String(bestOverall.side||"").toUpperCase()==="BUY"?"شراء":"بيع")+'</h3><div class="futures-live-levels"><span>دخول <b>'+futuresNum(bestOverall.entry)+'</b></span><span>TP1 <b>'+futuresNum(bestOverall.tp1)+'</b></span><span>TP2 <b>'+futuresNum(bestOverall.tp2)+'</b></span><span>TP3 <b>'+futuresNum(bestOverall.tp3)+'</b></span><span>SL <b>'+futuresNum(bestOverall.sl)+'</b></span></div></div><button class="btn primary futures-entry-btn" '+(canTrade?"":"disabled")+' onclick="executeFuturesEntry('+JSON.stringify(bestOverall).replace(/"/g,"&quot;")+')">'+(canTrade?"دخول حقيقي على Binance":"Binance غير مهيأ")+'</button></section>'
      : '<div class="futures-empty-line">لا توجد إشارة 15 دقيقة جاهزة للدخول حالياً.</div>';
    const total=allRows.length;
    search.classList.toggle("loading",anyScanning);
    search.innerHTML=anyScanning?'<strong>🔎 فحص الفريمات السبعة الآن</strong><small>تم العثور على '+total+' فرصة حتى الآن — النتائج تُرتب تلقائياً من الأقوى.</small>':'<strong>✅ مركز السوق محدث</strong><small>'+total+' فرصة • آخر تحديث '+new Date().toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"})+'</small>';
    const top="";
    frames.innerHTML=top+FUTURES_TFS.map((tf,i)=>renderFuturesFrame(tf,Array.isArray(scans[i]&&scans[i].trades)?scans[i].trades:[],Boolean(scans[i]&&scans[i].scanning))).join("");
    
    localStorage.setItem(SIGNAL_CACHE_KEY,JSON.stringify(clean)); return clean;
  }catch(e){localStorage.removeItem(SIGNAL_CACHE_KEY);return {}}
}
function cacheSignals(market,tf,trades){
  const cache=cleanSignalCache(),now=Date.now(),key=market+"|"+tf;
  const valid=(Array.isArray(trades)?trades:[]).map(t=>({...t,expires_at:Number(t.expires_at)||frameEndMs(tf,Number(t.candle_start)||now)})).filter(t=>t.expires_at>now);
  if(valid.length) cache[key]={
    market,timeframe:tf,expires_at:Math.max(...valid.map(t=>Number(t.expires_at)||0)),
    trade:valid
  };
  else delete cache[key];
  localStorage.setItem(SIGNAL_CACHE_KEY,JSON.stringify(cache)); return cache[key]&&cache[key].trade||[];
}
function getCachedSignals(market,tf){
  const cache=cleanSignalCache(),v=cache[market+"|"+tf];
  return v&&Array.isArray(v.trade)?v.trade:[];
}
function renderMarket(d){
  const liveTrades=Array.isArray(d.trades)?d.trades:(d.trade?[d.trade]:[]);
  const market=String(d.market||"");
  const tfKey=String(d.timeframe||"");
  const trades=cacheSignals(market,tfKey,liveTrades);
  const buyOnly=["spot","saudi","us"].includes(market);
  const filtered=buyOnly?trades.filter(t=>String(t.side||"").toUpperCase()==="BUY"):trades;
  if(!filtered.length){
    document.getElementById("result").innerHTML='<div class="empty">لا توجد صفقات مطابقة للشروط في هذا الفريم حالياً.</div>';
    return;
  }
  const tf=LABELS[tfKey]||tfKey||"";
  const ranked=[...filtered].sort((a,b)=>Number((b.ai_pct!=null?b.ai_pct:(b.score!=null?b.score:0)))-Number((a.ai_pct!=null?a.ai_pct:(a.score!=null?a.score:0)))||Math.abs(Number((b.change_pct!=null?b.change_pct:(b.change!=null?b.change:0))))-Math.abs(Number((a.change_pct!=null?a.change_pct:(a.change!=null?a.change:0))))); ranked.forEach((t,i)=>{t.rank=i+1;t._top=i===0;}); const cards=ranked.map((trade,i)=>{
    const side=String(trade.side||"").toUpperCase();
    const label=side==="BUY"?"شراء":side==="SELL"?"بيع":side;
    const ai=Math.round(Number((trade.ai_pct!=null?trade.ai_pct:(trade.score!=null?trade.score:0))));
    const level=(name,val)=>'<div class="level"><small>'+name+'</small><b>'+(val==null?"—":Number(val).toLocaleString("en-US",{maximumFractionDigits:8}))+'</b></div>';
    return '<article class="trade"><div class="trade-top"><div><div class="symbol">'+esc(trade.symbol||"—")+'</div><div class="muted">'+tf+' • AI '+ai+'%</div></div><span class="side '+(side==="BUY"?"buy":"sell")+'">'+label+'</span></div><div class="trade-body"><div class="levels">'+level("الدخول",trade.entry)+level("TP1",trade.tp1)+level("TP2",trade.tp2)+level("TP3",trade.tp3)+level("الوقف",trade.sl)+'</div><div class="trade-meta"><span class="pill">#'+(trade.rank||i+1)+'</span>'+(trade.tracking?'<span class="pill">🔄 '+esc(trade.tracking_status||"متابعة حتى الإغلاق")+'</span>':'')+'<span class="pill">التغير: '+Number((trade.change_pct!=null?trade.change_pct:(trade.change!=null?trade.change:0))).toFixed(2)+'%</span><span class="pill">ربح: '+Number((trade.profit_rate_pct!=null?trade.profit_rate_pct:(trade.profit_pct!=null?trade.profit_pct:0))).toFixed(2)+'%</span><span class="pill">خسارة: '+Number((trade.loss_rate_pct!=null?trade.loss_rate_pct:(trade.loss_pct!=null?trade.loss_pct:0))).toFixed(2)+'%</span>'+(market==="futures"?'<span class="pill">رافعة: '+Number((trade.leverage!=null?trade.leverage:20))+'x</span><span class="pill">هدف: '+Number((trade.target_pct!=null?trade.target_pct:10)).toFixed(0)+'%</span><span class="pill">وقف: '+Number((trade.stop_pct!=null?trade.stop_pct:5)).toFixed(0)+'%</span>':'')+'<span class="pill">'+(trade._top?"👑 الأفضل":"")+'</span><span class="pill">الفريم: '+tf+'</span></div></div></article>';
  }).join("");
  document.getElementById("result").innerHTML='<div class="trade-count">الصفقات المطابقة: <b>'+filtered.length+'</b></div><div class="trades-list">'+cards+'</div>';
}
function simplePage(title,body){app.innerHTML='<section class="panel"><div class="eyebrow">SMART TRADING PRO</div><h1>'+title+'</h1>'+body+'</section>'}
function loginPage(){simplePage("تسجيل الدخول",'<form id="loginForm" class="form"><input name="email" type="email" placeholder="البريد الإلكتروني" required><input name="password" type="password" placeholder="كلمة المرور" required><button class="btn primary">دخول</button><div id="formMsg" class="muted"></div></form>');document.getElementById("loginForm").onsubmit=async e=>{e.preventDefault();const r=await fetch("/api/login",{method:"POST",body:new FormData(e.target)}),d=await r.json();document.getElementById("formMsg").textContent=d.message||"تم";if(d.ok)location.href="/account"}}
function registerPage(){simplePage("إنشاء حساب",'<form id="registerForm" class="form"><input name="name" placeholder="الاسم" required><input name="email" type="email" placeholder="البريد الإلكتروني" required><input name="password" type="password" minlength="6" placeholder="كلمة المرور" required><button class="btn primary">إنشاء الحساب</button><div id="formMsg" class="muted"></div></form>');document.getElementById("registerForm").onsubmit=async e=>{e.preventDefault();const r=await fetch("/api/register",{method:"POST",body:new FormData(e.target)}),d=await r.json();document.getElementById("formMsg").textContent=d.message||"تم";if(d.ok)location.href="/account"}}
async function accountPage(){const r=await fetch("/api/me",{cache:"no-store"}),d=await r.json();if(!d.user){simplePage("حسابي",'<div class="empty">يجب تسجيل الدخول أولاً.<br><a class="btn primary" href="/login">تسجيل الدخول</a></div>');return}simplePage("حسابي",'<div class="account"><div class="breadth"><div class="breadth-card"><small>الاسم</small><b>'+esc(d.user.name)+'</b></div><div class="breadth-card"><small>البريد</small><b>'+esc(d.user.email)+'</b></div></div><button id="logout" class="btn">تسجيل الخروج</button></div>');document.getElementById("logout").onclick=async()=>{await fetch("/api/logout",{method:"POST"});location.href="/"}}
function blogPage(){simplePage("المدونة",'<div class="empty">المقالات والتحليلات ستظهر هنا من قاعدة البيانات.</div>')}
function adminPage(){simplePage("الإدارة",'<div class="empty">لوحة الإدارة مرتبطة بصلاحيات الحساب. سجّل دخولك بحساب الإدارة للوصول إلى وظائف الإدارة.</div>')}
function supportModal(){const box=document.createElement("div");box.className="modal-wrap";box.innerHTML='<div class="modal"><button class="icon-btn modal-close">×</button><h2>تواصل مع الدعم</h2><form id="supportForm" class="form"><input name="name" placeholder="الاسم" required><input name="email" type="email" placeholder="البريد الإلكتروني" required><textarea name="body" placeholder="رسالتك" required></textarea><button class="btn primary">إرسال</button><div id="supportMsg" class="muted"></div></form></div>';document.body.appendChild(box);box.querySelector(".modal-close").onclick=()=>box.remove();box.querySelector("form").onsubmit=async e=>{e.preventDefault();const r=await fetch("/api/support",{method:"POST",body:new FormData(e.target)}),d=await r.json();box.querySelector("#supportMsg").textContent=d.message||"تم";if(d.ok)setTimeout(()=>box.remove(),800)}}
supportOpen&&supportOpen.addEventListener("click",()=>{closeDrawer();supportModal()});
function route(){const p=location.pathname.split("/").filter(Boolean);if(p[0]==="fast-spot")return marketPage("spot");if(p[0]==="futures-bot")return futuresPage();if(p[0]==="fast-contracts")return marketPage("contracts");if(p[0]==="fast-us")return marketPage("us");if(p[0]==="fast-saudi")return marketPage("saudi");if(p[0]==="fast-forex")return marketPage("forex");if(p[0]==="login")return loginPage();if(p[0]==="register")return registerPage();if(p[0]==="account")return accountPage();if(p[0]==="blog")return blogPage();if(p[0]==="admin")return adminPage();return home()}
window.addEventListener("pageshow",closeDrawer);route();
