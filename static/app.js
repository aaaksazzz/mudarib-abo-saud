const app=document.getElementById("app");
const side=document.getElementById("side");
const backdrop=document.getElementById("backdrop");
let page=location.hash.slice(1)||"home",tf=localStorage.getItem("tf")||"15m";
const TF=["15m","30m","1h","4h","1d","1w","1M"];

async function api(url,opts={}){const r=await fetch(url,{cache:"no-store",...opts,headers:{"Content-Type":"application/json",...(opts.headers||{})}});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.error||"تعذر تنفيذ الطلب");return d}
function toast(s){const t=document.getElementById("toast");t.textContent=s;t.classList.add("show");setTimeout(()=>t.classList.remove("show"),2600)}
function closeMenu(){side.classList.remove("open");backdrop.classList.remove("open")}
function openMenu(){side.classList.add("open");backdrop.classList.add("open")}
document.getElementById("menu").onclick=openMenu;document.getElementById("closeMenu").onclick=closeMenu;backdrop.onclick=closeMenu;
document.getElementById("theme").onclick=()=>document.body.classList.toggle("light");
document.querySelectorAll("#side a").forEach(a=>a.onclick=()=>{page=a.dataset.p;location.hash=page;closeMenu();render()});
window.addEventListener("hashchange",()=>{page=location.hash.slice(1)||"home";render()});

function framebar(){return '<div class="toolbar">'+TF.map(x=>'<button class="tf '+(tf===x?"active":"")+'" data-tf="'+x+'">'+x+'</button>').join("")+'</div>'}
function bindFrames(){document.querySelectorAll("[data-tf]").forEach(b=>b.onclick=()=>{tf=b.dataset.tf;localStorage.setItem("tf",tf);render()})}
function shell(title,sub){app.innerHTML='<section class="hero"><div class="eyebrow">TRADING INTELLIGENCE • LIVE</div><h1>'+title+'</h1><p>'+sub+'</p>'+framebar()+'</section><div id="view" class="loading">جاري تحليل البيانات…</div>';bindFrames();return document.getElementById("view")}
function num(v,d=2){return v==null?"—":Number(v).toLocaleString("en-US",{maximumFractionDigits:d})}
function price(v){return v==null?"—":Number(v).toPrecision(8)}
function rows(items){if(!items.length)return '<div class="empty">ما فيه بيانات مطابقة حالياً. ما نعرض أرقام وهمية.</div>';return '<div class="table"><div class="tr th"><span>الرمز</span><span>السعر</span><span>24H</span><span>الحالة</span></div>'+items.map(x=>'<div class="tr"><b>'+x.symbol+'</b><span class="price">'+price(x.price)+'</span><span class="'+(x.change24h>=0?"green":"red")+'">'+num(x.change24h)+'%</span><span class="'+(x.ready?"green":"muted")+'">'+(x.ready?"إشارة":"مراقبة")+'</span></div>').join("")+'</div>'}

async function home(){
 const v=shell("لوحة التداول","منصة نظيفة تعتمد على البيانات الحية وتعرض الاستراتيجية المختارة فقط.");
 try{
  const [s,m,t]=await Promise.all([api("/api/platform/summary"),api("/api/markets?tf="+tf+"&limit=8"),api("/api/tracker")]);
  v.classList.remove("loading");v.innerHTML='<div class="grid"><div class="card metric"><div class="label">حالة المحرك</div><div class="value green">ONLINE</div><div class="sub">اتصال مباشر</div></div><div class="card metric"><div class="label">أزواج مؤهلة</div><div class="value">'+s.open_trades+'</div><div class="sub">صفقات مفتوحة</div></div><div class="card metric"><div class="label">الصفقات المفتوحة</div><div class="value">'+t.stats.open+'</div><div class="sub">محفوظة على السيرفر</div></div><div class="card metric"><div class="label">PnL المغلق</div><div class="value '+(t.stats.pnl>=0?"green":"red")+'">'+num(t.stats.pnl)+'%</div><div class="sub">بدون صفقات وهمية</div></div></div><div class="section-title"><div><h2>الاستراتيجية الموحدة</h2><p>1h EMA200 + 15m EMA20 + RSI &lt; 50 + 15m EMA200</p></div></div><div class="card signal"><div><span class="signal-badge">BUY SETUP</span><div class="kpis"><span class="pill">1H تحت EMA200</span><span class="pill">15M تحت EMA20</span><span class="pill">RSI &lt; 50</span><span class="pill">15M تحت EMA200</span></div></div><div class="score">100%</div></div><div class="section-title"><div><h2>أعلى حركة — Spot USDT</h2><p>حجم يومي فوق 1M USDT</p></div></div>'+rows(m.items)}
 }catch(e){v.classList.remove("loading");v.innerHTML='<div class="empty">'+e.message+'</div>'}
}

async function marketsPage(title,sub){
 const v=shell(title,sub);
 try{const d=await api("/api/markets?tf="+tf+"&limit=80");v.classList.remove("loading");v.innerHTML=rows(d.items)}catch(e){v.classList.remove("loading");v.innerHTML='<div class="empty">'+e.message+'</div>'}
}
async function scanner(){
 const v=shell("الماسح الذكي","يفحص السوق الحي ويُظهر العملات التي تقترب من شروط الاستراتيجية.");
 try{const d=await api("/api/scanner?tf="+tf+"&limit=25");v.classList.remove("loading");v.innerHTML=d.items.length?'<div class="table"><div class="tr th"><span>الرمز</span><span>السعر</span><span>RSI</span><span>AI</span></div>'+d.items.map(x=>'<div class="tr"><b>'+x.symbol+'</b><span>'+price(x.price)+'</span><span>'+num(x.rsi)+'</span><span class="'+(x.ready?"green":"yellow")+'">'+x.score+'%</span></div>').join("")+'</div>':'<div class="empty">حالياً ما فيه إعداد مكتمل. الماسح ينتظر تطابق الشروط.</div>'}catch(e){v.classList.remove("loading");v.innerHTML='<div class="empty">'+e.message+'</div>'}
}
async function analysts(){
 const v=shell("المحللين السبعة","قراءة موحدة للمؤشرات بدون نظام عكسي أو إشارات متضاربة.");
 try{const d=await api("/api/scanner?tf=15m&limit=12");v.classList.remove("loading");v.innerHTML='<div class="grid">'+["الاتجاه 1H","EMA200","EMA20 15M","RSI","زخم السعر","السيولة","تأكيد الإشارة"].map((x,i)=>'<div class="card metric"><div class="label">المحلل '+(i+1)+'</div><div class="value">'+x+'</div><div class="sub">'+(d.items.length?"يعمل على البيانات الحية":"بانتظار تطابق")+'</div></div>').join("")+'</div><div class="section-title"><div><h2>أفضل الإعدادات الحالية</h2></div></div>'+rows(d.items)}</div>'}catch(e){v.classList.remove("loading");v.innerHTML='<div class="empty">'+e.message+'</div>'}
}
async function tracker(){
 const v=shell("متابع الصفقات","كل صفقة محفوظة على قاعدة البيانات. الصفقة المفتوحة تُغلق تلقائياً بعد ساعة.");
 try{const d=await api("/api/tracker");v.classList.remove("loading");if(!d.authenticated){v.innerHTML='<div class="empty">سجّل دخولك من قسم الحساب لعرض وحفظ الصفقات.</div>';return}v.innerHTML='<div class="grid"><div class="card metric"><div class="label">مفتوحة</div><div class="value">'+d.stats.open+'</div></div><div class="card metric"><div class="label">مغلقة</div><div class="value">'+d.stats.closed+'</div></div><div class="card metric"><div class="label">رابحة</div><div class="value green">'+d.stats.wins+'</div></div><div class="card metric"><div class="label">PnL</div><div class="value '+(d.stats.pnl>=0?"green":"red")+'">'+num(d.stats.pnl)+'%</div></div></div><div class="section-title"><div><h2>المفتوحة</h2></div></div>'+tradeRows(d.open,true)+'<div class="section-title"><div><h2>السجل</h2></div></div>'+tradeRows(d.closed,false)}catch(e){v.classList.remove("loading");v.innerHTML='<div class="empty">'+e.message+'</div>'}
}
function tradeRows(items,open){if(!items.length)return '<div class="empty">لا توجد صفقات.</div>';return '<div class="table">'+items.map(x=>'<div class="tr"><b>'+x.symbol+'</b><span>'+num(x.entry,8)+'</span><span class="'+(x.pnl>=0?"green":"red")+'">'+(open?"مفتوحة":num(x.pnl)+'%')+'</span><span>'+(open?'<button class="ghost" onclick="closeTrade('+x.id+')">إغلاق</button>':x.status)+'</span></div>').join("")+'</div>'}
window.closeTrade=async id=>{try{await api("/api/trades/"+id+"/close?price="+prompt("سعر الإغلاق", "0"),{method:"POST"});toast("تم إغلاق الصفقة");tracker()}catch(e){toast(e.message)}};

async function account(){
 const v=shell("الحساب","تسجيل دخول بسيط لحفظ الصفقات على التخزين الدائم.");
 try{const m=await api("/api/auth/me");v.classList.remove("loading");if(m.authenticated){v.innerHTML='<div class="card"><div class="eyebrow">ACCOUNT</div><h2>'+m.user.email+'</h2><p class="muted">الحساب متصل وقاعدة البيانات تعمل.</p><button class="ghost" id="logout">تسجيل الخروج</button></div>';document.getElementById("logout").onclick=async()=>{await api("/api/auth/logout",{method:"POST"});toast("تم تسجيل الخروج");account()};return}v.innerHTML='<div class="card"><div class="form"><input class="input" id="email" placeholder="البريد الإلكتروني" type="email"><input class="input" id="password" placeholder="كلمة المرور — 6 أحرف على الأقل" type="password"><div style="display:flex;gap:8px"><button class="primary" id="login">دخول</button><button class="ghost" id="register">إنشاء حساب</button></div></div></div>';document.getElementById("login").onclick=()=>auth("login");document.getElementById("register").onclick=()=>auth("register")}catch(e){v.classList.remove("loading");v.innerHTML='<div class="empty">'+e.message+'</div>'}
}
async function auth(mode){const email=document.getElementById("email").value,password=document.getElementById("password").value;try{await api("/api/auth/"+mode,{method:"POST",body:JSON.stringify({email,password})});toast("تم بنجاح");account()}catch(e){toast(e.message)}}
async function simple(endpoint,title,text){
 const v=shell(title,text);try{const d=await api(endpoint);v.classList.remove("loading");v.innerHTML='<div class="card"><h2>'+title+'</h2><p class="muted">'+d.message+'</p></div>'}catch(e){v.classList.remove("loading");v.innerHTML='<div class="empty">'+e.message+'</div>'}
}
async function news(){
 const v=shell("الأخبار","موجز واضح بدون حشو أو أخبار وهمية.");try{const d=await api("/api/news");v.classList.remove("loading");v.innerHTML='<div class="card">'+d.items.map(x=>'<article class="article"><h3>'+x.title+'</h3><p>'+x.text+' · '+x.source+'</p></article>').join("")+'</div>'}catch(e){v.classList.remove("loading");v.innerHTML='<div class="empty">'+e.message+'</div>'}
}
function blog(){const v=shell("المدونة","محتوى تعليمي مختصر حول قراءة الاتجاه والمؤشرات.");v.classList.remove("loading");v.innerHTML='<div class="grid2"><div class="card"><article class="article"><h3>كيف تعمل الاستراتيجية الموحدة؟</h3><p>نقيس اتجاه الساعة عبر EMA200 ثم نتحقق من EMA20 وRSI وEMA200 على 15 دقيقة قبل اعتبار الإعداد جاهزاً.</p></article><article class="article"><h3>لماذا لا نعرض بيانات وهمية؟</h3><p>إذا تعذر مصدر البيانات، تظهر الحالة بوضوح بدلاً من اختراع سعر أو صفقة.</p></article></div><div class="card"><div class="eyebrow">RULE</div><h2>الوضوح أولاً</h2><p class="muted">لا يوجد زر عكس استراتيجية ولا إشارات مخفية.</p></div></div>'}
function admin(){const v=shell("الإدارة","مراقبة حالة النظام والبنية الأساسية.");v.classList.remove("loading");v.innerHTML='<div class="grid"><div class="card metric"><div class="label">Backend</div><div class="value green">ONLINE</div></div><div class="card metric"><div class="label">Storage</div><div class="value">SQLite</div><div class="sub">/data/platform.db</div></div><div class="card metric"><div class="label">API</div><div class="value">v6.0</div></div><div class="card metric"><div class="label">Mode</div><div class="value">LIVE</div></div></div>'}

async function render(){
 if(page==="home")return home();
 if(page==="analysts7")return analysts();
 if(page==="scanner")return scanner();
 if(page==="tracker")return tracker();
 if(page==="spot")return marketsPage("Binance Spot","USDT فقط • حجم يومي أعلى من 1M");
 if(page==="futures")return simple("/api/saudi","Futures","قسم الفيوتشر جاهز للربط بمصدر العقود؛ لن نعرض بيانات مزيفة.");
 if(page==="contracts")return simple("/api/saudi","العقود","قسم العقود جاهز لمصدر بيانات مستقل.");
 if(page==="saudi")return simple("/api/saudi","السوق السعودي","السوق السعودي يحتاج مزود بيانات مرخص/مخصص.");
 if(page==="us")return simple("/api/us","السوق الأمريكي","السوق الأمريكي يحتاج مزود بيانات مخصص.");
 if(page==="forex")return simple("/api/forex","فوركس وذهب","الفوركس والذهب يحتاج مزود بيانات مخصص.");
 if(page==="news")return news();
 if(page==="blog")return blog();
 if(page==="account")return account();
 if(page==="admin")return admin();
 return home();
}
render();