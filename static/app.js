const P=["home","scanner","tracker","spot","futures","contracts","saudi","us","forex","news","blog","account"],N=["الرئيسية","رادار السيولة","المتابعة","Spot","Futures","العقود","السعودي","الأمريكي","فوركس وذهب","الأخبار","المقالات","الحساب"],I=["⌂","💰","◷","₿","↕","📊","🇸🇦","🇺🇸","💱","📰","✎","◉"],S={p:"home"};
const $=x=>document.querySelector(x),esc=x=>String(x??"").replace(/[&<>"]/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[m])),money=x=>x==null?"—":Number(x).toLocaleString("en-US",{maximumFractionDigits:0}),pct=x=>(Number(x)>0?"+":"")+Number(x||0).toFixed(2)+"%";
const T=["15m","30m","1h","4h","1d","1w","1M"];
function shell(){document.body.innerHTML='<header><button id="m">☰</button><div class="brand"><span>💰</span><div><b>FLOW RADAR</b><small>LIQUIDITY PRO</small></div></div><span class="live">15M+</span></header><aside id="d"><div class="dh"><b>FLOW RADAR PRO</b><button id="x">×</button></div>'+P.map((p,i)=>'<button class="nav" data-p="'+p+'"><i>'+I[i]+"</i>"+N[i]+"</button>").join("")+'</aside><div id="shade"></div><main id="main"></main>';document.querySelectorAll(".nav").forEach(b=>b.onclick=()=>go(b.dataset.p));$("#m").onclick=()=>menu(1);$("#x").onclick=()=>menu(0);$("#shade").onclick=()=>menu(0)}
function menu(v){$("#d").classList.toggle("open",!!v);$("#shade").classList.toggle("show",!!v)} function go(p){S.p=p;menu(0);render()}
async function api(u,opt){const r=await fetch(u,opt);if(!r.ok)throw Error("HTTP "+r.status);return r.json()}
async function addTrack(m,s){try{await api("/api/tracker/"+m+"/"+encodeURIComponent(s),{method:"POST"});alert("تمت الإضافة للمتابعة")}catch(e){alert("تعذر الحفظ")}}
async function delTrack(m,s){await api("/api/tracker/"+m+"/"+encodeURIComponent(s),{method:"DELETE"});render()}

function radarCard(x,market){
 const q=x.timeframes?.["15m"]||x.timeframes?.["1h"]||{},h=x.timeframes?.["1h"]||{},d=x.timeframes?.["1d"]||{};
 const p=Number(q.pressure||0), direction=p>=3?"in":p<=-3?"out":"flat";
 const flowLabel=direction==="in"?"🟢 دخول السيولة":direction==="out"?"🔴 خروج السيولة":"⚪ متوازن";
 const flowClass=direction==="in"?"flowIn":direction==="out"?"flowOut":"flowFlat";
 const t=x.trade;
 const trade=t?'<div class="tradeSignal '+(t.signal==="BUY"?"buy":"sell")+'"><div><b>'+(t.signal==="BUY"?"🟢 شراء":"🔴 بيع")+'</b><small>'+esc(t.flow_label||"سيولة")+' · ثقة '+t.confidence+'%</small></div><div class="tradeLevels"><span>دخول <b>'+Number(t.entry).toLocaleString("en-US",{maximumFractionDigits:8})+'</b></span><span>TP1 <b>'+Number(t.tp1).toLocaleString("en-US",{maximumFractionDigits:8})+'</b></span><span>TP2 <b>'+Number(t.tp2).toLocaleString("en-US",{maximumFractionDigits:8})+'</b></span><span>TP3 <b>'+Number(t.tp3).toLocaleString("en-US",{maximumFractionDigits:8})+'</b></span><span>SL <b>'+Number(t.sl).toLocaleString("en-US",{maximumFractionDigits:8})+'</b></span></div></div>':"";
 return '<article class="radarCard '+flowClass+'"><div class="radarTop"><div><b>'+esc(x.symbol)+'</b><small>'+esc(x.name||"")+" · حجم $"+money(x.volume24h??x.volume)+'</small></div><span class="radarStatus '+(x.first_push?"early":"")+'">'+flowLabel+'</span></div><div class="flowBanner '+flowClass+'"><strong>'+flowLabel+'</strong><span>ضغط 15د '+pct(p)+'</span></div>'+trade+'<div class="radarPrice">'+Number(x.price||0).toLocaleString("en-US",{maximumFractionDigits:8})+' <small>'+pct(x.change24h)+'</small></div><div class="radarRows"><div><span>تدفق 15د</span><b class="'+(p>=0?"in":"out")+'">'+pct(p)+'</b></div><div><span>تسارع السيولة</span><b class="'+(Number(q.acceleration||0)>=0?"in":"out")+'">'+pct(q.acceleration)+'</b></div><div><span>تدفق 1س</span><b class="'+(Number(h.pressure||0)>=0?"in":"out")+'">'+pct(h.pressure)+'</b></div><div><span>تدفق 1ي</span><b class="'+(Number(d.pressure||0)>=0?"in":"out")+'">'+pct(d.pressure)+'</b></div></div><div class="tfline">'+T.map(iv=>{const z=x.timeframes?.[iv];return '<span><i>'+iv+'</i><b class="'+(Number(z?.pressure||0)>=0?"in":"out")+'">'+pct(z?.pressure||0)+'</b></span>'}).join("")+'</div><div class="radarFoot"><strong>قوة '+x.score+'%</strong><button class="track" onclick="addTrack(\''+esc(market)+'\',\''+esc(x.symbol)+'\')">+ متابعة</button></div></article>'}

function radarCards(a,market){return(a||[]).map(x=>radarCard(x,market)).join("")||'<div class="empty">ما فيه صفقات سيولة كافية الآن.</div>'}
function radarHead(){return '<section class="head radarHead"><small>15 MINUTES → MONTH</small><h1>صفقات السيولة المبكرة</h1><p>نبحث عن أول بول: تسارع في السيولة مع ضغط شراء واستمرار على الفريمات الأعلى.</p><div class="tfTabs">'+T.map((x,i)=>'<span class="'+(i===0?"active":"")+'">'+x+'</span>').join("")+'</div></section>'}
async function radar(){const d=await api("/api/radar?limit=20"),a=d.items||[];return radarHead()+'<section class="radarSummary"><div><b>'+a.filter(x=>x.first_push).length+'</b><small>أول بول</small></div><div><b>'+a.filter(x=>x.status==="تجميع").length+'</b><small>تجميع</small></div><div><b>'+a.filter(x=>x.persistent>=3).length+'</b><small>مستمر</small></div><div><b>15د+</b><small>تجدد كل 15د</small></div></section><section class="radarGrid">'+radarCards(a,"spot")+'</section>'}
const MARKET_SECTIONS=[["spot","₿","أبرز السيولة السبوت","/api/radar-market/spot"],["futures","↕","أبرز السيولة الفيوتشر","/api/radar-market/futures"],["contracts","📊","أبرز السيولة العقود","/api/radar-market/contracts"],["saudi","🇸🇦","أبرز السيولة السعودي","/api/radar-market/saudi"],["us","🇺🇸","أبرز السيولة الأمريكي","/api/radar-market/us"],["forex","💱","أبرز السيولة الفوركس","/api/radar-market/forex"]];
async function marketSection(m,icon,title,url){const d=await api("/api/signals/"+m),a=d.items||[];return '<section class="homeMarket"><div class="homeMarketHead"><div><small>LIQUIDITY → AUTO TRADES · 15M</small><h2>'+icon+' '+title+'</h2><p>السيولة القوية تولّد الصفقة تلقائياً: دخول + أهداف + وقف.</p></div><button onclick="go(\'scanner\')">فتح الرادار</button></div><div class="radarGrid">'+radarCards(a.slice(0,6),m)+'</div></section>'}

async function liveFlow(){const d=await api("/api/live-flow?limit=12"),a=d.items||[];return '<section class="liveFlow"><div class="liveFlowHead"><div><small>🐋 LIVE WHALE FLOW</small><h2>السيولة والحيتان — أول بأول</h2><p>تدفق صفقات السوق الحية، مرتبة حسب نشاط الحيتان الآن.</p></div><b>● LIVE</b></div><div class="liveFlowGrid">'+(a.map((x,i)=>'<article class="liveFlowCard"><div><strong>'+(i<3?["👑","🥈","🥉"][i]:"#"+(i+1))+' '+esc(x.symbol)+'</strong><span>🐋 '+x.whales+' حوت</span></div><div class="lfMain"><b>'+money(x.flow)+'</b><em class="'+(x.pressure>=0?"up":"down")+'">'+(x.pressure>=0?"🟢 شراء ":"🔴 بيع ")+pct(Math.abs(x.pressure))+'</em></div><div class="lfRows"><span>شراء <b>'+money(x.buy_flow)+'</b></span><span>بيع <b>'+money(x.sell_flow)+'</b></span><span>حيتان <b>'+money(x.whale_flow)+'</b></span></div></article>').join("")||'<div class="empty">جاري استقبال تدفق السيولة الحي…</div>')+'</div></section>'}
const HOME_FEEDS=[
 ["spot","₿","سبوت — صفقات السيولة","كل ما تدخل سيولة واضحة في عملة تظهر هنا كصفقة."],
 ["futures","↕","فيوتشر — صفقات الحجم","تدفق الحجم والضغط الشرائي/البيعي في عقود Binance."],
 ["contracts","📊","العقود — حركة الحجم","فرص العقود مرتبة من حركة السعر والحجم."],
 ["saudi","🇸🇦","السعودي — دخول الحجم","الأسهم التي يظهر فيها نشاط وحركة حجم واضحة."],
 ["us","🇺🇸","الأمريكي — دخول الحجم","الأسهم الأمريكية التي يظهر فيها نشاط وحركة واضحة."],
 ["forex","💱","فوركس وذهب — حركة السوق","العملات والذهب والنفط عند ظهور حركة واضحة."]
];
let HOME_TIMER=null;
let HOME_ROTATE=0;

function homeFeedCard(x,market){
 const t=x.trade||{}, q=x.timeframes?.["15m"]||x.timeframes?.["1h"]||{};
 const p=Number(q.pressure||t.flow_pressure||0);
 const vol=Number(x.volume24h??x.volume??0);
 const incoming=p>0;
 const title=t.signal==="BUY"?"🟢 شراء — دخلت سيولة":t.signal==="SELL"?"🔴 بيع — ضغط حجمي":incoming?"🟢 دخول سيولة":"🔴 خروج سيولة";
 const conf=t.confidence!=null?Number(t.confidence):Number(x.score||0);
 return '<article class="homeFeedCard '+(incoming?"positive":"negative")+'">'+
   '<div class="homeFeedTop"><div><b>'+esc(x.symbol)+'</b><small>'+esc(x.name||x.source||"حركة السوق")+'</small></div><span>● LIVE</span></div>'+
   '<div class="homeFeedEvent"><strong>'+title+'</strong><small>ضغط 15د '+pct(p)+'</small></div>'+
   (t.signal?'<div class="homeFeedTrade"><div><span>الدخول</span><b>'+Number(t.entry).toLocaleString("en-US",{maximumFractionDigits:8})+'</b></div><div><span>TP1</span><b>'+Number(t.tp1).toLocaleString("en-US",{maximumFractionDigits:8})+'</b></div><div><span>TP2</span><b>'+Number(t.tp2).toLocaleString("en-US",{maximumFractionDigits:8})+'</b></div><div><span>TP3</span><b>'+Number(t.tp3).toLocaleString("en-US",{maximumFractionDigits:8})+'</b></div><div><span>SL</span><b>'+Number(t.sl).toLocaleString("en-US",{maximumFractionDigits:8})+'</b></div></div>':
   '<div class="homeFeedMetrics"><div><span>الحجم</span><b>$'+money(vol)+'</b></div><div><span>تسارع</span><b>'+pct(q.acceleration||x.acceleration)+'</b></div><div><span>القوة</span><b>'+Number(conf||0).toFixed(0)+'%</b></div></div>')+
   '<div class="homeFeedFoot"><span>تحديث '+new Date().toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"})+'</span><button onclick="addTrack(\''+esc(market)+'\',\''+esc(x.symbol)+'\')">+ متابعة</button></div>'+
 '</article>';
}

async function loadHomeFeed(market){
 const d=await api("/api/signals/"+market);
 let a=(d.items||[]).filter(x=>x.trade);
 if(!a.length && market!=="spot") a=d.items||[];
 if(!a.length) return '<div class="homeFeedEmpty">بانتظار دخول سيولة جديدة…</div>';
 // Rotate through the real returned signals so the feed keeps moving without inventing trades.
 const n=Math.min(4,a.length);
 const shift=HOME_ROTATE%a.length;
 a=a.slice(shift).concat(a.slice(0,shift)).slice(0,n);
 return a.map(x=>homeFeedCard(x,market)).join("");
}

async function renderHomeFeeds(){
 if(S.p!=="home")return;
 for(const [market] of HOME_FEEDS){
   const box=document.querySelector('[data-home-feed="'+market+'"]');
   if(!box)continue;
   try{box.innerHTML=await loadHomeFeed(market)}
   catch(e){box.innerHTML='<div class="homeFeedEmpty">جاري استقبال بيانات السوق…</div>'}
 }
 HOME_ROTATE++;
}

function homeFeedSection(market,icon,title,desc){
 return '<section class="homeFeedSection"><div class="homeFeedHead"><div><small>LIVE LIQUIDITY FEED · 15M</small><h2>'+icon+' '+title+'</h2><p>'+desc+'</p></div><button onclick="go(\''+market+'\')">فتح القسم ↗</button></div><div class="homeFeedGrid" data-home-feed="'+market+'"><div class="homeFeedEmpty">جاري التقاط الصفقات…</div></div></section>';
}

async function home(){
 clearInterval(HOME_TIMER);
 HOME_ROTATE=0;
 const sections=HOME_FEEDS.map(x=>homeFeedSection(x[0],x[1],x[2],x[3])).join("");
 const html='<div class="homeTradeCenter">'+
   '<section class="homeTradeHero"><div><small>FLOW RADAR PRO · LIVE TRADE STREAM</small><h1>صفقات السيولة<br><em>تنزل لحظة بلحظة</em></h1><p>ما فيه قوائم أسعار عادية. كل قسم يعرض إشارات مبنية على السيولة والحجم وحركة السوق، ومع دخول فرصة جديدة تتجدد البطاقات تلقائياً.</p></div><div class="homeLiveOrb"><i></i><b>LIVE</b><span>15M FLOW</span></div></section>'+
   '<section class="homeFeedNotice"><span>●</span><b>البث شغال</b><small>صفقة جديدة · دخول سيولة · ارتفاع حجم · متابعة الحيتان</small></section>'+
   sections+
 '</div>';
 setTimeout(()=>{if(S.p==="home"){renderHomeFeeds();HOME_TIMER=setInterval(renderHomeFeeds,20000)}},50);
 return html;
}
async function tracker(){const d=await api("/api/tracker");return '<section class="head"><small>WATCHLIST</small><h1>متابع الصفقات</h1><p>الأصول المحفوظة للمراقبة وتبقى في قاعدة البيانات.</p></section><section class="watchList">'+((d.items||[]).map(x=>'<div class="watchRow"><b>'+esc(x.symbol)+'</b><span>'+esc(x.market)+'</span><span>'+new Date(x.created_at*1000).toLocaleString("ar-SA")+'</span><button onclick="delTrack(\''+esc(x.market)+'\',\''+esc(x.symbol)+'\')">حذف</button></div>').join("")||'<div class="empty">ما حفظت أي أصل للحين.</div>')+'</section>'}
async function liveSpot(){
 const d=await api("/api/signals/spot"),a=d.items||[];
 return '<section class="head"><small>🐋 LIVE LIQUIDITY · AUTO TRADE</small><h1>السبوت — صفقات السيولة</h1><p>كل بطاقة هنا صفقة مولدة من تدفق الحجم والسيولة، ومعها الدخول والأهداف والوقف.</p></section><section class="radarGrid">'+(a.map(x=>radarCard(x,"spot")).join("")||'<div class="empty">جاري انتظار دخول سيولة جديدة…</div>')+'</section><div class="source">المصدر: Binance aggTrade WebSocket — الدخول + TP1 + TP2 + TP3 + وقف.</div>';
}
async function markets(path,title,desc){
 const d=await api("/api/signals/"+S.p),a=d.items||[];
 return '<section class="head"><small>MARKET CENTER · AUTO TRADES</small><h1>'+title+'</h1><p>'+desc+' — السيولة والحجم يولدان صفقات مع دخول + أهداف + وقف.</p></section><section class="radarGrid">'+(a.map(x=>radarCard(x,S.p)).join("")||'<div class="empty">جاري انتظار إشارة حجم جديدة…</div>')+'</section><div class="source">المصدر: '+esc(d.generated_from||d.source||"مزود البيانات")+' — '+esc(d.note||"")+'</div>';
}
async function simple(t,d,url){const x=await api(url);return '<section class="head"><small>MODULE</small><h1>'+t+'</h1><p>'+d+'</p></section><section class="panel"><div class="empty">'+esc(x.message||"القسم جاهز.")+'</div></section>'}
async function render(){const m=$("#main");m.innerHTML='<div class="empty">جاري تحميل البيانات…</div>';try{let h=S.p==="home"?await home():S.p==="scanner"?await radar():S.p==="tracker"?await tracker():S.p==="spot"?await liveSpot():S.p==="futures"?await markets("/api/futures","Futures","عقود Binance USDT-M الحية."):S.p==="contracts"?await markets("/api/contracts","العقود","ES / NQ / YM / RTY / GC / SI / CL / NG — أسعار وحجوم عامة."):S.p==="saudi"?await markets("/api/saudi","السوق السعودي","أسهم سعودية رئيسية عبر مصدر بيانات عام."):S.p==="us"?await markets("/api/us","السوق الأمريكي","أسهم أمريكية رئيسية عبر مصدر بيانات عام."):S.p==="forex"?await markets("/api/forex","فوركس وذهب","عملات رئيسية + الذهب والنفط عبر مصدر بيانات عام."):S.p==="news"?await simple("الأخبار","لا نعرض أخباراً وهمية. اربط مزود أخبار عند الحاجة.","/api/news"):S.p==="blog"?await simple("المقالات","مساحة المقالات والتحليلات.","/api/blog"):await simple("الحساب","الحسابات والصلاحيات تحتاج مزود هوية قبل التفعيل.","/api/auth/me");m.innerHTML=h}catch(e){m.innerHTML='<div class="error">تعذر تحميل البيانات<br><small>'+esc(e.message)+'</small></div>'}}
shell();render()function tradeCard(x,market){
 const t=x.trade||{}, buy=t.signal==="BUY", side=buy?"شراء":"بيع", conf=Math.max(0,Math.min(100,Number(t.confidence||0))), entry=Number(t.entry||0), tp1=Number(t.tp1||0), tp2=Number(t.tp2||0), tp3=Number(t.tp3||0), sl=Number(t.sl||0), w=t.whale_tracking||{}, wp=Number(w.pressure||0), wc=Boolean(w.available), wt=Number(w.trades||0);
 const rr=Math.abs(entry-sl)>0?Math.abs(tp2-entry)/Math.abs(entry-sl):0;
 const fmt=v=>Number(v||0).toLocaleString("en-US",{maximumFractionDigits:8});
 const whaleText=wc?("🐋 حيتان "+(wp>=5?"شراء":wp<=-5?"بيع":"محايد")+" · "+wt+" صفقة كبيرة"):"🐋 متابعة الحيتان: غير متاحة";
 return '<div class="tradeSignal '+(buy?"buy":"sell")+'">'+
 '<div class="tradeHead"><div class="tradeSide"><span class="tradeIcon">'+(buy?"↗":"↘")+'</span><div><b>'+side+'</b><small>'+esc(t.flow_label||"إشارة سيولة")+'</small></div></div><div class="tradeMeta"><strong>'+conf.toFixed(0)+'%</strong><small>ثقة</small></div></div>'+
 '<div class="tradeBar"><i style="width:'+conf+'%"></i></div>'+
 '<div class="tradeInfo"><span>⚡ '+esc(t.signal_tf||"15m")+'</span><span>💧 '+esc(t.liquidity_signal||"سيولة")+'</span><span>📊 حجم '+esc(t.volume_signal||"مراقبة")+'</span><span>'+whaleText+'</span><span>R:R 1:'+rr.toFixed(1)+'</span></div>'+
 '<div class="tradeLevels"><div class="entry"><span>الدخول</span><b>'+fmt(entry)+'</b></div><div><span>هدف 1</span><b>'+fmt(tp1)+'</b></div><div><span>هدف 2</span><b>'+fmt(tp2)+'</b></div><div><span>هدف 3</span><b>'+fmt(tp3)+'</b></div><div class="stop"><span>وقف الخسارة</span><b>'+fmt(sl)+'</b></div></div>'+
 '<div class="tradeFoot"><span>📊 حجم · 💧 سيولة · 🐋 حيتان</span><b>LIVE · '+esc(t.signal_tf||"15M")+'</b></div></div>'
}
function radarCard(x,market){
 const q=x.timeframes?.["15m"]||x.timeframes?.["1h"]||{},h=x.timeframes?.["1h"]||{},d=x.timeframes?.["1d"]||{},p=Number(q.pressure||0),direction=p>=3?"in":p<=-3?"out":"flat";
 const flowLabel=direction==="in"?"🟢 دخول السيولة":direction==="out"?"🔴 خروج السيولة":"⚪ متوازن",flowClass=direction==="in"?"flowIn":direction==="out"?"flowOut":"flowFlat";
 return '<article class="radarCard '+flowClass+'"><div class="radarTop"><div><b>'+esc(x.symbol)+'</b><small>'+esc(x.name||"")+" · حجم $"+money(x.volume24h??x.volume)+'</small></div><span class="radarStatus '+flowClass+'">'+(x.first_push?"⚡ أول بول":flowLabel)+'</span></div><div class="flowBanner '+flowClass+'"><strong>'+flowLabel+'</strong><span>ضغط 15د '+pct(p)+'</span></div><div class="radarPrice">'+Number(x.price||0).toLocaleString("en-US",{maximumFractionDigits:8})+' <small>'+pct(x.change24h)+'</small></div>'+ (x.trade?tradeCard(x,market):"") +'<div class="radarRows"><div><span>تدفق 15د</span><b class="'+(p>=0?"in":"out")+'">'+pct(p)+'</b></div><div><span>تسارع السيولة</span><b class="'+(Number(q.acceleration||0)>=0?"in":"out")+'">'+pct(q.acceleration)+'</b></div><div><span>تدفق 1س</span><b class="'+(Number(h.pressure||0)>=0?"in":"out")+'">'+pct(h.pressure)+'</b></div><div><span>تدفق 1ي</span><b class="'+(Number(d.pressure||0)>=0?"in":"out")+'">'+pct(d.pressure)+'</b></div></div><div class="tfline">'+T.map(iv=>{const z=x.timeframes?.[iv];return '<span><i>'+iv+'</i><b class="'+(Number(z?.pressure||0)>=0?"in":"out")+'">'+pct(z?.pressure||0)+'</b></span>'}).join("")+'</div><div class="radarFoot"><strong>قوة '+Number(x.score||0).toFixed(0)+'%</strong><button class="track" onclick="addTrack(\''+esc(market)+'\',\''+esc(x.symbol)+'\')">+ متابعة</button></div></article>'
}
function radarCards(a,market){return(a||[]).map(x=>radarCard(x,market)).join("")||'<div class="empty">ما فيه صفقة سيولة مطابقة الآن.</div>'}

function radarHead(){return '<section class="head radarHead"><small>15 MINUTES → MONTH</small><h1>صفقات السيولة المبكرة</h1><p>نبحث عن أول بول: تسارع في السيولة مع ضغط شراء واستمرار على الفريمات الأعلى.</p><div class="tfTabs">'+T.map((x,i)=>'<span class="'+(i===0?"active":"")+'">'+x+'</span>').join("")+'</div></section>'}
async function radar(){const d=await api("/api/radar?limit=20"),a=d.items||[];return radarHead()+'<section class="radarSummary"><div><b>'+a.filter(x=>x.first_push).length+'</b><small>أول بول</small></div><div><b>'+a.filter(x=>x.status==="تجميع").length+'</b><small>تجميع</small></div><div><b>'+a.filter(x=>x.persistent>=3).length+'</b><small>مستمر</small></div><div><b>15د+</b><small>تجدد كل 15د</small></div></section><section class="radarGrid">'+radarCards(a,"spot")+'</section>'}
const MARKET_SECTIONS=[["spot","₿","السبوت","/api/signals/spot"],["futures","↕","الفيوتشر","/api/signals/futures"],["contracts","📊","العقود","/api/signals/contracts"],["saudi","🇸🇦","السوق السعودي","/api/signals/saudi"],["us","🇺🇸","السوق الأمريكي","/api/signals/us"],["forex","💱","الفوركس والذهب","/api/signals/forex"]];
async function marketSection(m,icon,title,url){const d=await api(url),a=d.items||[];return '<section class="homeMarket marketSection"><div class="homeMarketHead"><div><small>AUTO LIQUIDITY TRADES · 15M</small><h2>'+icon+" "+title+'</h2><p>السيولة تدخل ← الصفقة تُولد تلقائياً.</p></div><button onclick="go(\'scanner\')">الرادار</button></div><div class="radarGrid">'+radarCards(a.slice(0,6),m)+"</div></section>"}
async function flowDestinations(){const d=await api("/api/flow-destinations?limit=8"),a=d.items||[],b=d.btc_reference||{};const fmt=v=>Number(v||0).toLocaleString("en-US",{maximumFractionDigits:8});return '<section class="flowDest"><div class="flowDestHead"><div><small>LIQUIDITY DESTINATION · LIVE 15M</small><h2>وين تروح السيولة الآن؟</h2><p>₿ البيتكوين مرجع فقط. نبحث عن العملة التي <b>تستقبل السيولة فعلياً</b> مقارنةً به.</p></div><span>BTC ضغط 15د '+pct(b.pressure15m)+'</span></div><div class="destGrid">'+(a.map((x,i)=>{const p=Number(x.price||0),risk=p*.01,entry=p,tp1=p+risk*1.5,tp2=p+risk*2.5,tp3=p+risk*3.5,sl=p-risk;return '<article class="destCard hot"><div><strong>'+(i<3?["👑","🥈","🥉"][i]:("#"+(i+1)))+' '+esc(x.symbol)+'</strong><small>تحول مقابل BTC '+pct(x.relative_to_btc)+'</small></div><b>🟢 دخول سيولة مبكر</b><div class="destMetrics"><span>ضغط 15د <b>'+pct(x.pressure15m)+'</b></span><span>تسارع <b>'+pct(x.acceleration)+'</b></span><span>قوة التحول <b>'+Number(x.score).toFixed(0)+'%</b></span></div><div class="destTrade"><div><span>الدخول</span><b>'+fmt(entry)+'</b></div><div><span>TP1</span><b>'+fmt(tp1)+'</b></div><div><span>TP2</span><b>'+fmt(tp2)+'</b></div><div><span>TP3</span><b>'+fmt(tp3)+'</b></div><div><span>وقف</span><b>'+fmt(sl)+'</b></div></div></article>'}).join("")||'<div class="empty">ما ظهر انتقال سيولة واضح الآن.</div>')+'</div></section>'}
async function home(){
 const blocks=await Promise.all(MARKET_SECTIONS.map(x=>marketSection(x[0],x[1],x[2],x[3]).catch(()=>'<section class="homeMarket"><div class="empty">لا توجد بيانات متاحة الآن.</div></section>')));
 const live=await liveFlow().catch(()=>'<section class="liveFlow"><div class="empty">تعذر استقبال التدفق الحي.</div></section>');
 const flow=await flowDestinations().catch(()=>'<section class="flowDest"><div class="empty">تعذر قراءة حركة السيولة.</div></section>');
 const total=blocks.length;
 return '<div class="homePro">'+
 '<section class="homeHeroPro">'+
   '<div class="heroCopy">'+
     '<div class="eyebrow"><span class="pulseDot"></span> FLOW RADAR PRO <b>LIVE</b></div>'+
     '<h1>مركز السوق<br><em>لحظة بلحظة</em></h1>'+
     '<p>نراقب السيولة والحركة على كل الأسواق، ونحوّل الفرص الواضحة إلى صفقة مرتبة: دخول، أهداف ووقف.</p>'+
     '<div class="heroActions"><button class="heroPrimary" onclick="go(\'scanner\')">افتح رادار الصفقات <span>←</span></button><button class="heroSecondary" onclick="go(\'spot\')">السيولة الآن</button></div>'+
     '<div class="heroMeta"><span>15m</span><span>30m</span><span>1h</span><span>4h</span><span>1D</span><span>1W</span><span>1M</span></div>'+
   '</div>'+
   '<div class="heroVisual">'+
     '<div class="radarCore"><div class="radarSweep"></div><i></i><i></i><i></i><strong>15M</strong><small>LIVE RADAR</small></div>'+
     '<div class="visualBadge top"><b>6</b><span>أسواق</span></div>'+
     '<div class="visualBadge bottom"><b>LIVE</b><span>تحديث مستمر</span></div>'+
   '</div>'+
 '</section>'+
 '<section class="homeStats">'+
   '<div><span>◉</span><b>LIVE</b><small>حالة المحرك</small></div>'+
   '<div><span>15M</span><b>15M+</b><small>فريم الرصد الأساسي</small></div>'+
   '<div><span>↗</span><b>6</b><small>أسواق رئيسية</small></div>'+
   '<div><span>AI</span><b>PRO</b><small>تحليل السيولة</small></div>'+
 '</section>'+
 '<section class="marketHub">'+
   '<div class="hubHead"><div><small>MARKET COMMAND CENTER</small><h2>كل الأسواق في مكان واحد</h2><p>اضغط على أي قسم لفتح الصفقات والتفاصيل.</p></div><button onclick="go(\'scanner\')">عرض الكل ↗</button></div>'+
   '<div class="marketHubGrid">'+
     '<button class="hubTile crypto" onclick="go(\'spot\')"><span>₿</span><div><b>Spot</b><small>السبوت · سيولة العملات</small></div><em>فتح ↗</em></button>'+
     '<button class="hubTile futures" onclick="go(\'futures\')"><span>↕</span><div><b>Futures</b><small>الفيوتشر · USDT-M</small></div><em>فتح ↗</em></button>'+
     '<button class="hubTile contracts" onclick="go(\'contracts\')"><span>◫</span><div><b>العقود</b><small>ES · NQ · GC · CL</small></div><em>فتح ↗</em></button>'+
     '<button class="hubTile saudi" onclick="go(\'saudi\')"><span>🇸🇦</span><div><b>السوق السعودي</b><small>الأسهم · تداول</small></div><em>فتح ↗</em></button>'+
     '<button class="hubTile us" onclick="go(\'us\')"><span>🇺🇸</span><div><b>السوق الأمريكي</b><small>US Stocks · Live</small></div><em>فتح ↗</em></button>'+
     '<button class="hubTile forex" onclick="go(\'forex\')"><span>◈</span><div><b>فوركس وذهب</b><small>عملات · ذهب · نفط</small></div><em>فتح ↗</em></button>'+
   '</div>'+
 '</section>'+
 flow+
 live+
 '<section class="homeMarketsPro"><div class="marketsProHead"><div><small>LIVE TRADE FEED</small><h2>آخر الصفقات حسب السوق</h2><p>بطاقات موحدة بنفس تصميم المنصة، بدون قوائم أسعار عادية.</p></div><span>'+total+' أقسام</span></div>'+
 blocks.join("")+
 '</section>'+
 '<section class="homeFooterCta"><div><small>FLOW RADAR PRO</small><h2>القرار يبدأ من حركة السيولة.</h2><p>ادخل الرادار وشوف الفرص الحالية بالتفصيل.</p></div><button onclick="go(\'scanner\')">ابدأ الآن ←</button></section>'+
 '</div>';
}async function tracker(){const d=await api("/api/tracker");return '<section class="head"><small>WATCHLIST</small><h1>متابع الصفقات</h1><p>الأصول المحفوظة للمراقبة وتبقى في قاعدة البيانات.</p></section><section class="watchList">'+((d.items||[]).map(x=>'<div class="watchRow"><b>'+esc(x.symbol)+'</b><span>'+esc(x.market)+'</span><span>'+new Date(x.created_at*1000).toLocaleString("ar-SA")+'</span><button onclick="delTrack(\''+esc(x.market)+'\',\''+esc(x.symbol)+'\')">حذف</button></div>').join("")||'<div class="empty">ما حفظت أي أصل للحين.</div>')+'</section>'}
async function markets(path,title,desc){const d=await api(path);return '<section class="head"><small>MARKET CENTER</small><h1>'+title+'</h1><p>'+desc+'</p></section><section class="marketGrid">'+((d.items||[]).map(x=>'<div class="market"><div class="mTop"><b>'+esc(x.symbol)+'</b><span>'+esc(x.name||"")+'</span></div><strong>'+Number(x.price||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</strong><em>'+pct(x.change)+'</em><small>الحجم '+money(x.volume24h??x.volume)+'</small><button class="track" onclick="addTrack(\''+esc(S.p)+'\',\''+esc(x.symbol)+'\')">+ متابعة</button></div>').join("")||'<div class="empty">لا توجد بيانات من المصدر الآن.</div>')+'</section><div class="source">المصدر: '+esc(d.source||"مزود البيانات")+' — '+esc(d.note||"")+'</div>'}
async function simple(t,d,url){const x=await api(url);return '<section class="head"><small>MODULE</small><h1>'+t+'</h1><p>'+d+'</p></section><section class="panel"><div class="empty">'+esc(x.message||"القسم جاهز.")+'</div></section>'}
async function render(){const m=$("#main");m.innerHTML='<div class="empty">جاري تحميل البيانات…</div>';try{let h=S.p==="home"?await home():S.p==="scanner"?await radar():S.p==="tracker"?await tracker():S.p==="spot"?await liveSpot():S.p==="futures"?await markets("/api/futures","Futures","عقود Binance USDT-M الحية."):S.p==="contracts"?await markets("/api/contracts","العقود","ES / NQ / YM / RTY / GC / SI / CL / NG — أسعار وحجوم عامة."):S.p==="saudi"?await markets("/api/saudi","السوق السعودي","أسهم سعودية رئيسية عبر مصدر بيانات عام."):S.p==="us"?await markets("/api/us","السوق الأمريكي","أسهم أمريكية رئيسية عبر مصدر بيانات عام."):S.p==="forex"?await markets("/api/forex","فوركس وذهب","عملات رئيسية + الذهب والنفط عبر مصدر بيانات عام."):S.p==="news"?await simple("الأخبار","لا نعرض أخباراً وهمية. اربط مزود أخبار عند الحاجة.","/api/news"):S.p==="blog"?await simple("المقالات","مساحة المقالات والتحليلات.","/api/blog"):await simple("الحساب","الحسابات والصلاحيات تحتاج مزود هوية قبل التفعيل.","/api/auth/me");m.innerHTML=h;if(S.p==="spot")setTimeout(()=>{if(S.p==="spot")render()},10000)}catch(e){m.innerHTML='<div class="error">تعذر تحميل البيانات<br><small>'+esc(e.message)+'</small></div>'}}
shell();render();