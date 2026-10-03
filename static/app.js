const app=document.getElementById("app"),drawer=document.getElementById("drawer"),backdrop=document.getElementById("backdrop"),menuBtn=document.getElementById("menuBtn"),closeMenu=document.getElementById("closeMenu"),themeBtn=document.getElementById("themeBtn"),supportOpen=document.getElementById("supportOpen");
const TFS=["15m","30m","1h","4h","1d","1w","1M"],LABELS={"15m":"15 د","30m":"30 د","1h":"ساعة","4h":"4 ساعات","1d":"يومي","1w":"أسبوعي","1M":"شهري"};
const MARKET={spot:["₿","السبوت","/fast-spot"],futures:["⚡","الفيوتشر","/fast-futures"],contracts:["▣","العقود الأمريكية","/fast-contracts"],us:["US","السوق الأمريكي","/fast-us"],saudi:["SA","السوق السعودي","/fast-saudi"],forex:["FX","الفوركس والذهب","/fast-forex"]};
const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
function openDrawer(){drawer.classList.add("open");backdrop.classList.add("open");document.body.classList.add("drawer-open")}
function closeDrawer(){drawer.classList.remove("open");backdrop.classList.remove("open");document.body.classList.remove("drawer-open")}
menuBtn?.addEventListener("click",e=>{e.preventDefault();openDrawer()});closeMenu?.addEventListener("click",e=>{e.preventDefault();closeDrawer()});backdrop?.addEventListener("click",closeDrawer);
document.querySelectorAll("#drawer a").forEach(a=>a.addEventListener("click",closeDrawer));
function applyTheme(){const light=localStorage.getItem("smart_theme")==="light";document.body.classList.toggle("light",light);if(themeBtn)themeBtn.textContent=light?"☾":"☀"}
themeBtn?.addEventListener("click",()=>{localStorage.setItem("smart_theme",document.body.classList.contains("light")?"dark":"light");applyTheme()});applyTheme();
function home(){app.innerHTML='<section class="hero"><div class="hero-card"><div class="eyebrow">SMART TRADING PRO</div><h1>التداول الذكي <span>PRO</span></h1><p>منصة موحدة لقراءة الأسواق والفرص الحية. كل سوق مستقل، وكل فريم له بياناته وإشارته بدون خلط.</p><div class="actions"><a class="btn primary" href="/fast-spot">₿ ابدأ بالسبوت</a><a class="btn" href="/fast-futures">⚡ الفيوتشر</a></div></div></section>'}
function marketPage(key){const m=MARKET[key]||MARKET.spot;app.innerHTML='<section><div class="market-head"><div><div class="eyebrow">'+m[0]+' '+m[1]+'</div><h1>'+m[1]+'</h1><div class="muted">فحص مستقل للسوق والفريم المختار.</div></div><div class="muted" id="status">جاهز</div></div><div class="tf-row" id="tfRow">'+TFS.map((t,i)=>'<button class="tf '+(i===0?"active":"")+'" data-tf="'+t+'">'+LABELS[t]+'</button>').join("")+'</div><div id="result"><div class="empty loading">جاري جلب بيانات السوق…</div></div><div id="futuresBot"></div></section>';document.querySelectorAll(".tf").forEach(b=>b.onclick=()=>{document.querySelectorAll(".tf").forEach(x=>x.classList.remove("active"));b.classList.add("active");loadMarket(key,b.dataset.tf)});loadMarket(key,"15m");if(key==="futures")loadFuturesBot()}

async function loadFuturesBot(){
  const box=document.getElementById("futuresBot"); if(!box)return;
  try{
    const r=await fetch("/api/futures/bot",{cache:"no-store"}),d=await r.json(),bot=d.bot||{};
    if(bot.status==="open"){
      const entry=Number(bot.entry||0),last=Number(bot.last_price||entry),p=entry>0?((String(bot.side||"BUY").toUpperCase()==="BUY"?(last-entry):(entry-last))/entry*100):0;
      box.innerHTML='<div class="panel futures-bot"><div class="eyebrow">🤖 بوت الفيوتشر</div><h3>صفقة مفتوحة • '+esc(bot.symbol||"—")+' '+(bot.side==="BUY"?"شراء":"بيع")+'</h3><div class="trade-meta"><span class="pill">20x</span><span class="pill">100% من رصيد USDT</span><span class="pill">الربح الحالي: '+p.toFixed(2)+'%</span></div><div class="muted">هذه صفقة حقيقية مفتوحة على Binance بعد تأكيد التنفيذ. تتم متابعتها حتى الإغلاق.</div><div class="actions"><button class="btn primary" id="prepareRealFuturesBot">⚡ تجهيز صفقة حقيقية</button></div></div>';document.getElementById("prepareRealFuturesBot")?.addEventListener("click",async()=>{const tf=document.querySelector(".tf.active")?.dataset.tf||"15m";const btn=document.getElementById("prepareRealFuturesBot");if(btn)btn.disabled=true;try{const r=await fetch("/api/futures/bot/start?timeframe="+encodeURIComponent(tf),{method:"POST",cache:"no-store"}),d=await r.json();if(!r.ok||!d.ok){alert(d.message||"تعذر تجهيز الصفقة للتنفيذ الحقيقي");}else{loadFuturesBot()}}catch(e){alert("تعذر الاتصال بالخادم");}finally{if(document.getElementById("prepareRealFuturesBot"))document.getElementById("prepareRealFuturesBot").disabled=false}});
    }else if(bot.status==="ready"){
      box.innerHTML='<div class="panel futures-bot"><div class="eyebrow">🤖 بوت الفيوتشر</div><h3>⚡ صفقة جاهزة للتأكيد</h3><div class="trade-meta"><span class="pill">'+esc(bot.symbol||"—")+'</span><span class="pill">'+(bot.side==="BUY"?"شراء":"بيع")+'</span><span class="pill">20x</span><span class="pill">100% من USDT</span><span class="pill">AI '+Math.round(Number(bot.ai_pct||0))+'%</span></div><div class="trade-meta"><span class="pill">دخول: '+Number(bot.entry||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</span><span class="pill">TP1: '+Number(bot.tp1||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</span><span class="pill">TP2: '+Number(bot.tp2||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</span><span class="pill">TP3: '+Number(bot.tp3||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</span><span class="pill">SL: '+Number(bot.sl||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</span></div><div class="muted">هذه الصفقة جاهزة للتنفيذ اليدوي. التنفيذ الآلي الحقيقي يتم فقط عند تفعيل AUTO_REAL_FUTURES في Northflank.</div><div class="actions"><button class="btn primary" id="confirmFuturesBot">⚡ تأكيد الصفقة التجريبية</button><button class="btn" id="refreshFuturesBot">إعادة الفحص</button></div></div>';
      document.getElementById("confirmFuturesBot")?.addEventListener("click",()=>{const ok=confirm("هذه تجربة فقط ولن يتم إرسال أي أمر حقيقي إلى Binance.\n\nهل تريد تأكيد الصفقة التجريبية؟");if(!ok)return;const btn=document.getElementById("confirmFuturesBot");if(btn)btn.disabled=true;alert("تم تأكيد الصفقة التجريبية بنجاح — بدون تنفيذ أمر حقيقي.");if(btn)btn.disabled=false;});document.getElementById("refreshFuturesBot")?.addEventListener("click",async()=>{const tf=document.querySelector(".tf.active")?.dataset.tf||"15m";await fetch("/api/futures/bot/start?timeframe="+encodeURIComponent(tf),{method:"POST"});loadFuturesBot()});
    }else{
      box.innerHTML='<div class="panel futures-bot"><div class="eyebrow">🤖 بوت الفيوتشر</div><h3>🤖 بوت الفيوتشر الحقيقي</h3><div class="muted">يفحص السوق تلقائياً ويجهز أعلى إشارة حقيقية مع 20x و100% من رصيد USDT المتاح وTP/SL. التنفيذ يتم فقط بعد تأكيدك.</div><button class="btn primary" id="startFuturesBot">فحص وتجهيز الصفقة</button></div>';
      document.getElementById("startFuturesBot")?.addEventListener("click",async()=>{const tf=document.querySelector(".tf.active")?.dataset.tf||"15m";const btn=box.querySelector("button");btn.disabled=true;const r=await fetch("/api/futures/bot/start?timeframe="+encodeURIComponent(tf),{method:"POST"}),d=await r.json();if(!d.ok)box.innerHTML='<div class="empty">'+esc(d.message||"تعذر تجهيز الصفقة")+'</div>';else loadFuturesBot()});
    }
  }catch(e){box.innerHTML='<div class="empty">بوت الفيوتشر غير متاح حالياً</div>'}
}

setInterval(()=>{if(location.pathname==="/fast-futures")loadFuturesBot()},10000);
async function loadMarket(key,tf){const result=document.getElementById("result"),status=document.getElementById("status");result.innerHTML='<div class="empty loading">جاري الفحص الحقيقي…</div>';status.textContent="يفحص "+LABELS[tf];let lastErr="تعذر جلب البيانات";for(let attempt=0;attempt<2;attempt++){try{const r=await fetch("/api/fast-market?market="+encodeURIComponent(key)+"&timeframe="+encodeURIComponent(tf),{cache:"no-store"});const d=await r.json();if(!r.ok||d.ok===false)throw Error(d.message||"تعذر جلب البيانات");renderMarket(d);status.textContent="مباشر • "+new Date().toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"});return}catch(e){lastErr=e.message;if(attempt===0)await new Promise(x=>setTimeout(x,900))}}result.innerHTML='<div class="empty">لا توجد بيانات حالياً.<br><small>'+esc(lastErr)+'</small><br><button class="btn primary" onclick="loadMarket(\''+esc(key)+'\',\''+esc(tf)+'\')">إعادة المحاولة</button></div>';status.textContent="غير متاح حالياً"}
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
function route(){const p=location.pathname.split("/").filter(Boolean);if(p[0]==="fast-spot")return marketPage("spot");if(p[0]==="fast-futures")return marketPage("futures");if(p[0]==="fast-contracts")return marketPage("contracts");if(p[0]==="fast-us")return marketPage("us");if(p[0]==="fast-saudi")return marketPage("saudi");if(p[0]==="fast-forex")return marketPage("forex");if(p[0]==="login")return loginPage();if(p[0]==="register")return registerPage();if(p[0]==="account")return accountPage();if(p[0]==="blog")return blogPage();if(p[0]==="admin")return adminPage();return home()}
window.addEventListener("pageshow",closeDrawer);route();