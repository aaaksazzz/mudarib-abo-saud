const app=document.getElementById("app"),drawer=document.getElementById("drawer"),backdrop=document.getElementById("backdrop"),menuBtn=document.getElementById("menuBtn"),closeMenu=document.getElementById("closeMenu"),themeBtn=document.getElementById("themeBtn"),supportOpen=document.getElementById("supportOpen");
const TFS=["15m","30m","1h","4h","1d","1w","1M"],LABELS={"15m":"15 د","30m":"30 د","1h":"ساعة","4h":"4 ساعات","1d":"يومي","1w":"أسبوعي","1M":"شهري"};
const MARKET={spot:["₿","السبوت","/fast-spot"],futures:["⚡","الفيوتشر","/futures-bot"],contracts:["▣","العقود الأمريكية","/fast-contracts"],us:["US","السوق الأمريكي","/fast-us"],saudi:["SA","السوق السعودي","/fast-saudi"],forex:["FX","الفوركس والذهب","/fast-forex"]};
const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
function openDrawer(){drawer.classList.add("open");backdrop.classList.add("open");document.body.classList.add("drawer-open")}
function closeDrawer(){drawer.classList.remove("open");backdrop.classList.remove("open");document.body.classList.remove("drawer-open")}
menuBtn?.addEventListener("click",e=>{e.preventDefault();openDrawer()});closeMenu?.addEventListener("click",e=>{e.preventDefault();closeDrawer()});backdrop?.addEventListener("click",closeDrawer);
document.querySelectorAll("#drawer a").forEach(a=>a.addEventListener("click",closeDrawer));
function applyTheme(){const light=localStorage.getItem("smart_theme")==="light";document.body.classList.toggle("light",light);if(themeBtn)themeBtn.textContent=light?"☾":"☀"}
themeBtn?.addEventListener("click",()=>{localStorage.setItem("smart_theme",document.body.classList.contains("light")?"dark":"light");applyTheme()});applyTheme();
function home(){app.innerHTML='<section class="hero"><div class="hero-card"><div class="eyebrow">SMART TRADING PRO</div><h1>التداول الذكي <span>PRO</span></h1><p>منصة موحدة لقراءة الأسواق والفرص الحية. كل سوق مستقل، وكل فريم له بياناته وإشارته بدون خلط.</p><div class="actions"><a class="btn primary" href="/fast-spot">₿ ابدأ بالسبوت</a><a class="btn" href="/futures-bot">⚡ الفيوتشر</a></div></div></section>'}
function marketPage(key){
  const m=MARKET[key]||MARKET.spot;
  app.innerHTML='<section><div class="market-head"><div><div class="eyebrow">'+m[0]+' '+m[1]+'</div><h1>'+m[1]+'</h1><div class="muted">فحص مستقل للسوق والفريم المختار.</div></div><div class="muted" id="status">جاهز</div></div><div class="tf-row" id="tfRow">'+TFS.map((t,i)=>'<button class="tf '+(i===0?"active":"")+'" data-tf="'+t+'">'+LABELS[t]+'</button>').join("")+'</div><div id="result"><div class="empty loading">جاري جلب بيانات السوق…</div></div></section>';
  document.querySelectorAll(".tf").forEach(b=>b.onclick=()=>{document.querySelectorAll(".tf").forEach(x=>x.classList.remove("active"));b.classList.add("active");loadMarket(key,b.dataset.tf)});
  loadMarket(key,"15m");
}

async function futuresPage(){
  app.innerHTML='<section class="futures-new"><div class="futures-topbar"><div><div class="eyebrow">⚡ USDⓈ-M FUTURES</div><h1>بوت الفيوتشر الحقيقي</h1><p>تنفيذ آلي 24/7 على Binance — صفقة واحدة فقط، فحص مستمر، وحماية على منصة Binance.</p></div><div class="bot-live"><i></i><b>REAL</b><small>يعمل 24/7</small></div></div><div class="futures-strip"><span>● اتصال Binance</span><span>⚙️ تنفيذ آلي</span><span>🛡️ حماية مباشرة</span><span>⏱️ فريم التنفيذ 15د</span></div><div id="futuresSearch" class="futures-search loading"><strong>🔎 جاري فحص السوق</strong><small>يتم البحث عن أفضل فرصة مباشرة.</small></div><div id="futuresDashboard"></div></section>';
  await refreshFuturesPage();
}
async function refreshFuturesPage(){
  const search=document.getElementById("futuresSearch"),dash=document.getElementById("futuresDashboard");
  if(!search||!dash)return;
  try{
    const [sr,br]=await Promise.all([
      fetch("/api/fast-market?market=futures&timeframe=15m",{cache:"no-store"}),
      fetch("/api/futures/bot",{cache:"no-store"})
    ]);
    const scan=await sr.json(),bd=await br.json(),bot=bd.bot||{};
    const scanning=Boolean(scan.scanning);
    search.classList.toggle("loading",scanning);
    search.innerHTML=scanning
      ? '<strong>🔎 جاري فحص السوق</strong><small>الفحص مستمر بالخلفية — ستظهر أفضل فرصة مباشرة.</small>'
      : '<strong>✅ تم تحديث السوق</strong><small>آخر تحديث '+new Date().toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"})+'</small>';
    const side=String(bot.side||"").toUpperCase(),status=String(bot.status||"idle");
    const profit=Number(bot.profit_pct||0);
    let action=bot.halted?'<button class="btn primary" id="restartFutures">إعادة تشغيل البوت</button>':"";
    const position=status==="open"
      ? '<div class="futures-card live-card"><div class="card-title"><span>🟢 صفقة حقيقية مفتوحة</span><em>LIVE</em></div><div class="symbol-row"><b>'+esc(bot.symbol||"—")+'</b><span class="side '+(side==="BUY"?"buy":"sell")+'">'+(side==="BUY"?"شراء":"بيع")+'</span></div><div class="kpi-grid"><div><small>الدخول</small><b>'+Number(bot.entry||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</b></div><div><small>السعر الآن</small><b>'+Number(bot.last_price||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</b></div><div><small>النتيجة</small><b class="'+(profit>=0?"profit":"loss")+'">'+profit.toFixed(2)+'%</b></div><div><small>الرافعة</small><b>'+Number(bot.leverage||20)+'x</b></div></div><div class="levels-row"><span>TP1 '+Number(bot.tp1||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</span><span>TP2 '+Number(bot.tp2||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</span><span>TP3 '+Number(bot.tp3||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</span><span>SL '+Number(bot.sl||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</span></div></div>'
      : '<div class="futures-card bot-card"><div class="card-title"><span>🤖 حالة البوت</span><em class="'+(bot.halted?"danger":"ready")+'">'+(bot.halted?"HALTED":"READY")+'</em></div><div class="bot-state">'+(bot.halted?"متوقف للحماية":"يبحث عن فرصة مطابقة")+'</div><p>التنفيذ الحقيقي يتم تلقائياً من الخادم عند ظهور إشارة مؤهلة، بدون تأكيد يدوي.</p>'+action+'</div>';
    const rows=Array.isArray(scan.trades)?scan.trades:[];
    let candidate=rows.length?(()=>{const x=rows[0],sd=String(x.side||"").toUpperCase();return '<div class="futures-card candidate-card"><div class="card-title"><span>🎯 أفضل إشارة الآن</span><em>15M</em></div><div class="symbol-row"><b>'+esc(x.symbol||"—")+'</b><span class="side '+(sd==="BUY"?"buy":"sell")+'">'+(sd==="BUY"?"شراء":"بيع")+'</span></div><div class="kpi-grid"><div><small>AI</small><b>'+Math.round(Number(x.ai_pct||0))+'%</b></div><div><small>التغير</small><b class="'+(Number(x.change_pct||0)>=0?"profit":"loss")+'">'+Number(x.change_pct||0).toFixed(2)+'%</b></div><div><small>الفريم</small><b>15 د</b></div><div><small>الحالة</small><b>مباشر</b></div></div><div class="levels-row"><span>دخول '+Number(x.entry||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</span><span>TP1 '+Number(x.tp1||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</span><span>TP2 '+Number(x.tp2||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</span><span>SL '+Number(x.sl||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</span></div></div>'})()
      : '<div class="futures-card empty-card"><div class="empty-icon">⌁</div><b>ما فيه إشارة مطابقة حالياً</b><p>البوت مستمر يفحص السوق تلقائياً، وإذا تحققت الشروط تظهر الفرصة هنا.</p></div>';
    dash.innerHTML='<div class="futures-grid">'+position+candidate+'</div><div class="futures-rules"><div class="rules-head"><b>حالة البوت</b><span>REAL</span></div><div class="rules-note">التنفيذ والحماية آليان على Binance • فريم المتابعة 15 دقيقة • مركز واحد فقط</div></div>';    document.getElementById("restartFutures")?.addEventListener("click",async()=>{const btn=document.getElementById("restartFutures");btn.disabled=true;btn.textContent="جاري التشغيل…";await fetch("/api/futures/bot/start?timeframe=15m",{method:"POST",cache:"no-store"});refreshFuturesPage()});
  }catch(e){
    dash.innerHTML='<div class="futures-card empty-card"><b>تعذر قراءة حالة البوت</b><p>المحرك يستمر على الخادم إذا كان مفعلاً. حاول تحديث الصفحة بعد لحظات.</p></div>';
  }
}
setInterval(()=>{if(location.pathname==="/futures-bot")refreshFuturesPage()},7000);
async function loadMarket(key,tf){
  const token=++marketLoadToken;
  const result=document.getElementById("result"),status=document.getElementById("status");
  result.innerHTML='<div class="empty loading">🔎 جاري البحث في السوق…<br><small>يتم فحص العملات والبيانات الحية، لا تغلق الصفحة.</small></div>';
  status.textContent="جاري البحث • "+LABELS[tf];
  let lastErr="تعذر جلب البيانات";
  for(let attempt=0;attempt<2;attempt++){
    try{
      const r=await fetch("/api/fast-market?market="+encodeURIComponent(key)+"&timeframe="+encodeURIComponent(tf),{cache:"no-store"});
      const d=await r.json();
      if(token!==marketLoadToken)return;
      if(!r.ok||d.ok===false)throw Error(d.message||"تعذر جلب البيانات");
      const scanning=Boolean(d.scanning);
      const hasRows=Array.isArray(d.trades)&&d.trades.length>0;
      renderMarket(d);
      if(scanning){
        status.textContent="🔎 جاري البحث • "+LABELS[tf];
        if(!hasRows){
          result.innerHTML='<div class="empty loading">🔎 جاري البحث في السوق…<br><small>الفحص مستمر في الخلفية وسيتم عرض الصفقات فور العثور عليها.</small></div>';
        }
        setTimeout(()=>{if(token===marketLoadToken)loadMarket(key,tf)},1800);
      }else{
        status.textContent="مباشر • "+new Date().toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"});
      }
      return;
    }catch(e){
      lastErr=e.message;
      if(attempt===0)await new Promise(x=>setTimeout(x,900));
    }
  }
  if(token!==marketLoadToken)return;
  result.innerHTML='<div class="empty">تعذر إكمال البحث حالياً.<br><small>'+esc(lastErr)+'</small><br><button class="btn primary" onclick="loadMarket(\''+esc(key)+'\',\''+esc(tf)+'\')">إعادة البحث</button></div>';
  status.textContent="تعذر إكمال البحث";
}
const SIGNAL_CACHE_KEY="smart_signal_cache_v3";
function frameMs(tf){return {"15m":900000,"30m":1800000,"1h":3600000,"4h":14400000,"1d":86400000,"1w":604800000}[tf]||0}
function frameEndMs(tf,stamp){
  const t=Number(stamp||Date.now()),d=new Date(t);
  if(tf==="1M") return new Date(d.getFullYear(),d.getMonth()+1,1).getTime();
  if(tf==="1w"){const x=new Date(d);const day=x.getDay();x.setDate(x.getDate()+(7-day));x.setHours(0,0,0,0);return x.getTime()}
  if(tf==="1d"){const x=new Date(d);x.setDate(x.getDate()+1);x.setHours(0,0,0,0);return x.getTime()}
  const ms=frameMs(tf); return ms?Math.floor(t/ms)*ms+ms:Date.now();
}
function cleanSignalCache(){
  try{
    const cache=JSON.parse(localStorage.getItem(SIGNAL_CACHE_KEY)||"{}"),now=Date.now(),clean={};
    Object.entries(cache).forEach(([k,v])=>{
      if(v&&Number(v.expires_at)>now&&Array.isArray(v.trade)) clean[k]=v;
    });
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
  localStorage.setItem(SIGNAL_CACHE_KEY,JSON.stringify(cache)); return cache[key]?.trade||[];
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
  const ranked=[...filtered].sort((a,b)=>Number(b.ai_pct??b.score??0)-Number(a.ai_pct??a.score??0)||Math.abs(Number(b.change_pct??b.change??0))-Math.abs(Number(a.change_pct??a.change??0))); ranked.forEach((t,i)=>{t.rank=i+1;t._top=i===0;}); const cards=ranked.map((trade,i)=>{
    const side=String(trade.side||"").toUpperCase();
    const label=side==="BUY"?"شراء":side==="SELL"?"بيع":side;
    const ai=Math.round(Number(trade.ai_pct??trade.score??0));
    const level=(name,val)=>'<div class="level"><small>'+name+'</small><b>'+(val==null?"—":Number(val).toLocaleString("en-US",{maximumFractionDigits:8}))+'</b></div>';
    return '<article class="trade"><div class="trade-top"><div><div class="symbol">'+esc(trade.symbol||"—")+'</div><div class="muted">'+tf+' • AI '+ai+'%</div></div><span class="side '+(side==="BUY"?"buy":"sell")+'">'+label+'</span></div><div class="trade-body"><div class="levels">'+level("الدخول",trade.entry)+level("TP1",trade.tp1)+level("TP2",trade.tp2)+level("TP3",trade.tp3)+level("الوقف",trade.sl)+'</div><div class="trade-meta"><span class="pill">#'+(trade.rank||i+1)+'</span>'+(trade.tracking?'<span class="pill">🔄 '+esc(trade.tracking_status||"متابعة حتى الإغلاق")+'</span>':'')+'<span class="pill">التغير: '+Number(trade.change_pct??trade.change??0).toFixed(2)+'%</span><span class="pill">ربح: '+Number(trade.profit_rate_pct??trade.profit_pct??0).toFixed(2)+'%</span><span class="pill">خسارة: '+Number(trade.loss_rate_pct??trade.loss_pct??0).toFixed(2)+'%</span>'+(market==="futures"?'<span class="pill">رافعة: '+Number(trade.leverage??20)+'x</span><span class="pill">هدف: '+Number(trade.target_pct??10).toFixed(0)+'%</span><span class="pill">وقف: '+Number(trade.stop_pct??5).toFixed(0)+'%</span>':'')+'<span class="pill">'+(trade._top?"👑 الأفضل":"")+'</span><span class="pill">الفريم: '+tf+'</span></div></div></article>';
  }).join("");
  document.getElementById("result").innerHTML='<div class="trade-count">الصفقات المطابقة: <b>'+filtered.length+'</b></div><div class="trades-list">'+cards+'</div>';if(market==="futures")loadFuturesBot();
}
function simplePage(title,body){app.innerHTML='<section class="panel"><div class="eyebrow">SMART TRADING PRO</div><h1>'+title+'</h1>'+body+'</section>'}
function loginPage(){simplePage("تسجيل الدخول",'<form id="loginForm" class="form"><input name="email" type="email" placeholder="البريد الإلكتروني" required><input name="password" type="password" placeholder="كلمة المرور" required><button class="btn primary">دخول</button><div id="formMsg" class="muted"></div></form>');document.getElementById("loginForm").onsubmit=async e=>{e.preventDefault();const r=await fetch("/api/login",{method:"POST",body:new FormData(e.target)}),d=await r.json();document.getElementById("formMsg").textContent=d.message||"تم";if(d.ok)location.href="/account"}}
function registerPage(){simplePage("إنشاء حساب",'<form id="registerForm" class="form"><input name="name" placeholder="الاسم" required><input name="email" type="email" placeholder="البريد الإلكتروني" required><input name="password" type="password" minlength="6" placeholder="كلمة المرور" required><button class="btn primary">إنشاء الحساب</button><div id="formMsg" class="muted"></div></form>');document.getElementById("registerForm").onsubmit=async e=>{e.preventDefault();const r=await fetch("/api/register",{method:"POST",body:new FormData(e.target)}),d=await r.json();document.getElementById("formMsg").textContent=d.message||"تم";if(d.ok)location.href="/account"}}
async function accountPage(){const r=await fetch("/api/me",{cache:"no-store"}),d=await r.json();if(!d.user){simplePage("حسابي",'<div class="empty">يجب تسجيل الدخول أولاً.<br><a class="btn primary" href="/login">تسجيل الدخول</a></div>');return}simplePage("حسابي",'<div class="account"><div class="breadth"><div class="breadth-card"><small>الاسم</small><b>'+esc(d.user.name)+'</b></div><div class="breadth-card"><small>البريد</small><b>'+esc(d.user.email)+'</b></div></div><button id="logout" class="btn">تسجيل الخروج</button></div>');document.getElementById("logout").onclick=async()=>{await fetch("/api/logout",{method:"POST"});location.href="/"}}
function blogPage(){simplePage("المدونة",'<div class="empty">المقالات والتحليلات ستظهر هنا من قاعدة البيانات.</div>')}
function adminPage(){simplePage("الإدارة",'<div class="empty">لوحة الإدارة مرتبطة بصلاحيات الحساب. سجّل دخولك بحساب الإدارة للوصول إلى وظائف الإدارة.</div>')}
function supportModal(){const box=document.createElement("div");box.className="modal-wrap";box.innerHTML='<div class="modal"><button class="icon-btn modal-close">×</button><h2>تواصل مع الدعم</h2><form id="supportForm" class="form"><input name="name" placeholder="الاسم" required><input name="email" type="email" placeholder="البريد الإلكتروني" required><textarea name="body" placeholder="رسالتك" required></textarea><button class="btn primary">إرسال</button><div id="supportMsg" class="muted"></div></form></div>';document.body.appendChild(box);box.querySelector(".modal-close").onclick=()=>box.remove();box.querySelector("form").onsubmit=async e=>{e.preventDefault();const r=await fetch("/api/support",{method:"POST",body:new FormData(e.target)}),d=await r.json();box.querySelector("#supportMsg").textContent=d.message||"تم";if(d.ok)setTimeout(()=>box.remove(),800)}}
supportOpen?.addEventListener("click",()=>{closeDrawer();supportModal()});
function route(){const p=location.pathname.split("/").filter(Boolean);if(p[0]==="fast-spot")return marketPage("spot");if(p[0]==="futures-bot")return futuresPage();if(p[0]==="fast-contracts")return marketPage("contracts");if(p[0]==="fast-us")return marketPage("us");if(p[0]==="fast-saudi")return marketPage("saudi");if(p[0]==="fast-forex")return marketPage("forex");if(p[0]==="login")return loginPage();if(p[0]==="register")return registerPage();if(p[0]==="account")return accountPage();if(p[0]==="blog")return blogPage();if(p[0]==="admin")return adminPage();return home()}
window.addEventListener("pageshow",closeDrawer);route();