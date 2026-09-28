const markets={spot:"السبوت",futures:"الفيوتشر",contracts:"العقود",saudi:"السعودي",us:"الأمريكي",forex:"فوركس وذهب"};
const marketIcons={spot:"₿",futures:"↕",contracts:"◫",saudi:"🇸🇦",us:"🇺🇸",forex:"💱"};
const frames=[["5m","5د"],["15m","15د"],["1h","1س"],["4h","4س"],["1d","يومي"],["1w","أسبوعي"],["1M","شهري"]];
const app=document.getElementById("app"),nav=document.getElementById("nav"),backdrop=document.getElementById("backdrop");
const titles={auto:"التوصيات",analysis:"المحلل الذكي",scanner:"الماسح",tracker:"متابع الصفقات",account:"الحساب",admin:"الإدارة"};
document.getElementById("menu").onclick=()=>{nav.classList.toggle("open");backdrop.classList.toggle("show")};
backdrop.onclick=()=>{nav.classList.remove("open");backdrop.classList.remove("show")};
document.getElementById("theme").onclick=()=>document.body.classList.toggle("light");
function page(p){
 let body="";
 if(p==="home")body=home();
 else if(markets[p])body=market(p);
 else if(p==="tracker")body=trackerPage();
 else if(p==="news"||p==="blog")body=articles(p);
 else body='<section class="page-head"><div><span class="eyebrow">SMART CENTER</span><h1>'+ (titles[p]||"التداول الذكي PRO") +'</h1><p>قسم مستقل.</p></div></section><div class="empty-card"><div class="empty-icon">◆</div><h3>سيتم تفعيل هذا القسم ضمن النسخة الجديدة</h3></div>';
 app.innerHTML=body;nav.classList.remove("open");backdrop.classList.remove("show");
 document.querySelectorAll("aside a").forEach(a=>a.classList.toggle("active",a.dataset.page===p));
 window.scrollTo({top:0,behavior:"smooth"});
 if(p==="news"||p==="blog")loadArticles(p);
 if(p==="tracker")loadTracker();
}
function home(){
 return '<section class="hero-new"><div class="hero-copy"><span class="eyebrow">MARKET INTELLIGENCE · LIVE</span><h1>كل الأسواق.<br><strong>في واجهة واحدة.</strong></h1><p>7 محللين متخصصين يفحصون كل فريم. لا مؤشرات فنية ولا شارتات داخل الصفقات.</p><div class="hero-pills"><span>● تحديث مستمر</span><span>7 محللين</span><span>AI% حسب التوافق</span></div></div><div class="hero-orbit"><div class="orbit-ring"></div><div class="orbit-core">◆<small>PRO</small></div></div></section><section class="section-title"><div><span class="eyebrow">MARKETS</span><h2>الأسواق</h2></div><span class="muted">اختر السوق والفريم</span></section><div class="market-grid">'+Object.entries(markets).map(([k,v])=>'<button class="market-card" onclick="page(\''+k+'\')"><span class="market-icon">'+marketIcons[k]+'</span><span><b>'+v+'</b><small>تحليل 7 محللين</small></span><em>←</em></button>').join("")+'</div><section class="quick-grid"><button onclick="page(\'scanner\')" class="quick-card"><span>⌕</span><b>الماسح الذكي</b><small>فرص مرتبة حسب توافق المحللين</small></button><button onclick="page(\'tracker\')" class="quick-card"><span>◷</span><b>متابع الصفقات</b><small>تابع الصفقات والنتائج</small></button><button onclick="page(\'news\')" class="quick-card"><span>📰</span><b>الأخبار</b><small>المحتوى داخل المنصة</small></button></section>';
}
function market(p){
 return '<section class="page-head market-head"><div><span class="eyebrow">'+marketIcons[p]+' MARKET</span><h1>'+markets[p]+'</h1><p>كل فريم يمر على 7 محللين مستقلين قبل ترتيب الصفقات.</p></div><div class="status-badge"><i></i> LIVE</div></section><div class="frame-bar">'+frames.map(f=>'<button class="frame" onclick="loadTrades(\''+p+'\',\''+f[0]+'\')">'+f[1]+'</button>').join("")+'</div><div id="results" class="results"><div class="empty-card"><div class="empty-icon">⌁</div><h3>اختر الفريم</h3><p>ستظهر كروت الصفقات فقط.</p></div></div>';
}
function num(v){return Number(v).toLocaleString("en-US",{maximumFractionDigits:12})}
function tradeCard(x,i){
 const side=x.side==="BUY"?"شراء":"بيع";
 return '<article class="trade-card"><div class="trade-top"><div><span class="rank">#'+(i+1)+'</span><b>'+x.asset+'</b><small>'+side+' · '+x.timeframe_name+'</small></div><div class="ai"><strong>'+x.ai_percent+'%</strong><small>'+x.analysts_agree+'/7 محللين</small></div></div><div class="trade-grid"><div><span>الدخول</span><b>'+num(x.entry)+'</b></div><div><span>TP1</span><b>'+num(x.tp1)+'</b></div><div><span>TP2</span><b>'+num(x.tp2)+'</b></div><div><span>TP3</span><b>'+num(x.tp3)+'</b></div><div class="stop"><span>SL</span><b>'+num(x.sl)+'</b></div></div></article>';
}
async function loadTrades(m,t){
 const r=document.getElementById("results");if(!r)return;
 r.innerHTML='<div class="loading-card"><span class="loader"></span><b>جاري تحليل '+(frames.find(x=>x[0]===t)||["",t])[1]+'</b><small>7 محللين متخصصين يعملون الآن</small></div>';
 try{
  const d=await fetch("/api/trades?market="+encodeURIComponent(m)+"&timeframe="+encodeURIComponent(t),{cache:"no-store"}).then(x=>x.json());
  if(!d.items?.length){r.innerHTML='<div class="empty-card"><div class="empty-icon">⌁</div><h3>لا توجد صفقات حالياً</h3><p>لم تنتج البيانات توافقاً واضحاً لهذا الفريم.</p></div>';return}
  r.innerHTML='<div class="results-note">مرتبة حسب توافق المحللين السبعة</div>'+d.items.map(tradeCard).join("");
 }catch(e){r.innerHTML='<div class="empty-card"><h3>تعذر الاتصال بالخادم</h3><p>حاول مرة أخرى.</p></div>'}
}
function trackerPage(){
 return '<section class="page-head"><div><span class="eyebrow">TRADE TRACKER · LIVE</span><h1>متابع الصفقات</h1><p>يتابع الصفقات التي خرجت فعلياً من محرك التحليل ويحسب نتيجة TP/SL من بيانات السوق.</p></div><div class="status-badge"><i></i> LIVE</div></section><div id="tracker-results" class="results"><div class="loading-card"><span class="loader"></span><b>جاري تحميل المتابع</b></div></div>';
}
async function loadTracker(){
 const el=document.getElementById("tracker-results"); if(!el)return;
 try{
  const d=await fetch("/api/tracker",{cache:"no-store"}).then(r=>r.json());
  const s=d.stats||{};
  const stat='<div class="hero-pills"><span>مفتوحة '+(d.open||[]).length+'</span><span>فوز '+(s.wins||0)+'</span><span>خسارة '+(s.losses||0)+'</span><span>نسبة الفوز '+(s.win_rate||0)+'%</span></div>';
  const open=(d.open||[]).map((x,i)=>'<article class="trade-card"><div class="trade-top"><div><span class="rank">#'+(i+1)+'</span><b>'+x.asset+'</b><small>'+(x.side==="BUY"?"شراء":"بيع")+' · '+x.timeframe_name+'</small></div><div class="ai"><strong>'+x.ai_percent+'%</strong><small>مفتوحة</small></div></div><div class="trade-grid"><div><span>الدخول</span><b>'+num(x.entry)+'</b></div><div><span>TP1</span><b>'+num(x.tp1)+'</b></div><div><span>TP2</span><b>'+num(x.tp2)+'</b></div><div><span>TP3</span><b>'+num(x.tp3)+'</b></div><div class="stop"><span>SL</span><b>'+num(x.sl)+'</b></div></div></article>').join("");
  const closed=(d.closed||[]).slice().reverse().map((x,i)=>'<article class="trade-card"><div class="trade-top"><div><span class="rank">#'+(i+1)+'</span><b>'+x.asset+'</b><small>'+(x.side==="BUY"?"شراء":"بيع")+' · '+x.timeframe_name+'</small></div><div class="ai"><strong>'+(x.result==="WIN"?"فوز":"خسارة")+'</strong><small>'+x.hit+'</small></div></div><div class="trade-grid"><div><span>الدخول</span><b>'+num(x.entry)+'</b></div><div><span>النتيجة</span><b>'+x.hit+'</b></div><div><span>AI%</span><b>'+x.ai_percent+'%</b></div></div></article>').join("");
  el.innerHTML=stat+'<div class="results-note">الصفقات المفتوحة</div>'+(open||'<div class="empty-card"><h3>لا توجد صفقات مفتوحة</h3><p>سيظهر هنا أي تداول ينتجه المحرك.</p></div>')+'<div class="results-note">آخر الصفقات المغلقة</div>'+(closed||'<div class="empty-card"><h3>لا توجد نتائج بعد</h3><p>لن يتم اختلاق أي نتيجة.</p></div>');
 }catch(e){el.innerHTML='<div class="empty-card"><h3>تعذر الاتصال بالخادم</h3><p>حاول مرة أخرى.</p></div>'}
}
function articles(p){
 const isNews=p==="news";
 return '<section class="page-head"><div><span class="eyebrow">'+(isNews?"NEWS ROOM":"SMART BLOG")+'</span><h1>'+(isNews?"الأخبار":"المدونة")+'</h1><p>محتوى داخل المنصة.</p></div></section><div id="articles" class="article-grid"><div class="loading-card"><span class="loader"></span><b>جاري التحميل</b></div></div>';
}
async function loadArticles(p){
 try{const d=await fetch(p==="news"?"/api/news":"/api/blog").then(r=>r.json()),el=document.getElementById("articles");if(!el)return;
 el.innerHTML=d.items.map(x=>'<article class="article-card"><div class="article-meta"><span>'+x.category+'</span><time>'+x.date+'</time></div><h2>'+x.title+'</h2><p>'+x.summary+'</p><button onclick="showArticle('+x.id+',\''+p+'\')">قراءة المقال <b>←</b></button></article>').join("");
 }catch(e){}
}
async function showArticle(id,p){
 const x=await fetch((p==="news"?"/api/news/":"/api/blog/")+id).then(r=>r.json());
 app.innerHTML='<article class="article-single"><button class="back-btn" onclick="page(\''+p+'\')">→ العودة</button><div class="article-meta"><span>'+x.category+'</span><time>'+x.date+'</time></div><h1>'+x.title+'</h1><p class="article-body">'+x.body+'</p></article>';
 window.scrollTo({top:0,behavior:"smooth"});
}
document.querySelectorAll("aside a").forEach(a=>a.onclick=()=>page(a.dataset.page));
page("home");
