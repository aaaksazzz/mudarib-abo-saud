const markets={spot:"السبوت",futures:"الفيوتشر",contracts:"العقود",saudi:"السعودي",us:"الأمريكي",forex:"فوركس وذهب"};
const marketIcons={spot:"₿",futures:"↕",contracts:"◫",saudi:"🇸🇦",us:"🇺🇸",forex:"💱"};
const frames=[["5m","5د"],["15m","15د"],["1h","1س"],["4h","4س"],["1d","يومي"],["1w","أسبوعي"],["1M","شهري"]];
const app=document.getElementById("app"),nav=document.getElementById("nav"),backdrop=document.getElementById("backdrop");
const titles={auto:"التوصيات",analysis:"الاستراتيجية الموحدة",scanner:"الماسح",tracker:"متابع الصفقات",account:"الحساب",admin:"الإدارة"};
let siteConfig={sections:{}};
let currentPage="home";
let reverseStrategy=localStorage.getItem("reverseStrategy")==="1";
function reverseSide(side){return reverseStrategy?(side==="BUY"?"SELL":"BUY"):side;}
function toggleReverse(){reverseStrategy=!reverseStrategy;localStorage.setItem("reverseStrategy",reverseStrategy?"1":"0");page(currentPage);}
document.getElementById("menu").onclick=()=>{nav.classList.toggle("open");backdrop.classList.toggle("show")};
backdrop.onclick=()=>{nav.classList.remove("open");backdrop.classList.remove("show")};
const savedTheme=localStorage.getItem("theme");if(savedTheme==="light")document.body.classList.add("light");
document.getElementById("theme").onclick=()=>{document.body.classList.toggle("light");localStorage.setItem("theme",document.body.classList.contains("light")?"light":"dark")};
function page(p){
 currentPage=p;
 let body="";
 if(p==="home")body=home();
 else if(p==="auto")body=autoPage();
 else if(p==="scanner")body=scannerPage();
 else if(markets[p])body=siteConfig.sections[p]===false?'<section class="page-head"><div><span class="eyebrow">SECTION LOCKED</span><h1>القسم مغلق</h1><p>تم إغلاق هذا القسم من لوحة الإدارة.</p></div></section>':market(p);
 else if(p==="tracker")body=trackerPage();
 else if(p==="news"||p==="blog")body=articles(p);
 else if(p==="account")body=accountPage();
 else if(p==="admin")body=adminPage();
 else if(p==="analysis")body=analysisPage();
 else body='<section class="page-head"><div><span class="eyebrow">SMART CENTER</span><h1>'+ (titles[p]||"التداول الذكي PRO") +'</h1><p>قسم مستقل.</p></div></section><div class="empty-card"><div class="empty-icon">◆</div><h3>سيتم تفعيل هذا القسم ضمن النسخة الجديدة</h3></div>';
 app.innerHTML=body;nav.classList.remove("open");backdrop.classList.remove("show");
 document.querySelectorAll("aside a").forEach(a=>a.classList.toggle("active",a.dataset.page===p));
 window.scrollTo({top:0,behavior:"smooth"});
 if(p==="news"||p==="blog")loadArticles(p);
 if(p==="tracker")loadTracker();
 if(p==="admin")loadAdmin();
 if(p==="account")loadAccount();
 if(p==="analysis")loadAnalysis("spot","5m");
 if(markets[p])loadTrades(p,"5m");
}
function autoPage(){ return market("spot"); }
function home(){
 return '<section class="hero-new"><div class="hero-copy"><span class="eyebrow">MARKET INTELLIGENCE · LIVE</span><h1>كل الأقسام.<br><strong>في واجهة واحدة.</strong></h1><p>الوصول المباشر لكل أسواق وتحليلات ومحتوى المنصة من الصفحة الرئيسية.</p><div class="hero-pills"><span>● تحديث مستمر</span><span>استراتيجية واحدة</span><span>AI% حسب قوة الإشارة</span></div></div><div class="hero-orbit"><div class="orbit-ring"></div><div class="orbit-core">◆<small>PRO</small></div></div></section><section class="section-title"><div><span class="eyebrow">MARKETS</span><h2>الأسواق</h2></div><span class="muted">اضغط على أي سوق للدخول مباشرة</span></section><div class="market-grid">'+Object.entries(markets).map(([k,v])=>'<button type="button" class="market-card" data-page="'+k+'"><span class="market-icon">'+marketIcons[k]+'</span><span><b>'+v+'</b><small>تحليل الاستراتيجية الموحدة</small></span><em>←</em></button>').join("")+'</div><section class="section-title"><div><span class="eyebrow">CENTER</span><h2>أقسام المنصة</h2></div><span class="muted">كل قسم مرتبط مباشرة</span></section><div class="quick-grid"><button type="button" data-page="analysis" class="quick-card"><span>◈</span><b>الاستراتيجية الموحدة</b><small>تحليل موحد لـ7 عناصر</small></button><button type="button" data-page="scanner" class="quick-card"><span>⌕</span><b>الماسح الذكي</b><small>فحص الأسواق والفريمات</small></button><button type="button" data-page="tracker" class="quick-card"><span>◷</span><b>متابع الصفقات</b><small>الصفقات والنتائج</small></button><button type="button" data-page="news" class="quick-card"><span>📰</span><b>الأخبار</b><small>أخبار ومحتوى المنصة</small></button><button type="button" data-page="blog" class="quick-card"><span>✎</span><b>المدونة</b><small>تعلم ومنهجية التداول</small></button><button type="button" data-page="account" class="quick-card"><span>👤</span><b>الحساب</b><small>الدخول وإدارة الحساب</small></button><button type="button" data-page="admin" class="quick-card"><span>⚙</span><b>الإدارة</b><small>إدارة المنصة والنشر</small></button></div>';
}
function market(p){
 return '<section class="page-head market-head"><div><span class="eyebrow">'+marketIcons[p]+' MARKET</span><h1>'+markets[p]+'</h1><p>7 محللين يعملون في الخلفية، ثم تُجمع النتائج في تحليل واحد بدون عرض الشموع أو واجهات محللين منفصلة.</p></div><div class="status-badge"><i></i> LIVE</div></section><div class="frame-bar">'+frames.map(f=>'<button class="frame" onclick="loadTrades(\''+p+'\',\''+f[0]+'\')">'+f[1]+'</button>').join("")+'</div><div id="results" class="results"><div class="empty-card"><div class="empty-icon">⌁</div><h3>اختر الفريم</h3><p>ستظهر كروت الصفقات فقط.</p></div></div>';
}
function scannerPage(){
 return '<section class="page-head market-head"><div><span class="eyebrow">SMART SCANNER · LIVE</span><h1>الماسح الذكي</h1><p>يمسح الأسواق والفريمات بشكل مستقل ويرتب الفرص حسب إجماع الاستراتيجية الموحدة.</p></div><div class="status-badge"><i></i> LIVE</div></section><div class="frame-bar"><button class="frame" onclick="runScanner()">تحديث الماسح</button></div><div id="scanner-results" class="results"><div class="loading-card"><span class="loader"></span><b>جاري تشغيل الماسح</b><small>يفحص الأسواق والفريمات من البيانات الخام</small></div></div>';
}
async function runScanner(){
 const el=document.getElementById("scanner-results");if(!el)return;
 el.innerHTML='<div class="loading-card"><span class="loader"></span><b>جاري فحص الأسواق</b><small>7 محللين يعملون في الخلفية ثم يخرجون بتحليل واحد</small></div>';
 try{
  const d=await fetch("/api/scanner?timeframe=5m",{cache:"no-store"}).then(r=>r.json());
  const items=d.items||[];
  if(!items.length){el.innerHTML='<div class="empty-card"><div class="empty-icon">⌁</div><h3>لا توجد فرص حالياً</h3><p>لا توجد بيانات كافية من الأسواق في هذه اللحظة.</p></div>';return}
  el.innerHTML='<div class="results-note">5د · إجماع 7 محللين ← تحليل واحد</div>'+items.slice(0,50).map((x,i)=>'<article class="trade-card"><div class="trade-top"><div><span class="rank">#'+(i+1)+'</span><b>'+x.asset+'</b><small>'+x.market_name+' · '+x.timeframe_name+' · '+(x.side==="BUY"?"شراء":"بيع")+'</small></div><div class="ai"><strong>'+x.confidence+'%</strong><small>'+((x.analysts_agree||6)+'/7 محللين')+'</small></div></div></article>').join("");
 }catch(e){el.innerHTML='<div class="empty-card"><h3>تعذر تشغيل الماسح</h3><p>حاول تحديث الماسح مرة أخرى.</p></div>'}
}
function analysisPage(){
 return '<section class="page-head market-head"><div><span class="eyebrow">SMART ANALYST · LIVE</span><h1>المحلل الذكي</h1><p>استراتيجية موحدة يقرأون حركة السعر والهيكل والسيولة والاختراقات وإدارة الصفقة بدون مؤشرات.</p></div><div class="status-badge"><i></i> LIVE</div></section><div class="frame-bar market-select">'+Object.keys(markets).map(m=>'<button class="frame" onclick="loadAnalysis(\''+m+'\',currentAnalysisFrame)">'+marketIcons[m]+' '+markets[m]+'</button>').join("")+'</div><div class="frame-bar">'+frames.map(f=>'<button class="frame" onclick="loadAnalysis(currentAnalysisMarket,\''+f[0]+'\')">'+f[1]+'</button>').join("")+'</div><div id="analysis-results" class="results"><div class="empty-card"><div class="empty-icon">◆</div><h3>اختر الفريم</h3><p>سيظهر تحليل الاستراتيجية الموحدة وترتيب إجماعهم.</p></div></div>';
}
let currentAnalysisMarket="spot",currentAnalysisFrame="5m";
async function loadAnalysis(m,t){
 currentAnalysisMarket=m; currentAnalysisFrame=t;
 const r=document.getElementById("analysis-results");if(!r)return;
 r.innerHTML='<div class="loading-card"><span class="loader"></span><b>جاري تحليل '+(frames.find(x=>x[0]===t)||["",t])[1]+'</b><small>استراتيجية موحدة: السعر والهيكل والسيولة والاختراق والمناطق والمخاطر</small></div>';
 try{
  const d=await fetch("/api/analysis?market="+encodeURIComponent(m)+"&timeframe="+encodeURIComponent(t),{cache:"no-store"}).then(x=>x.json());
  if(!d.items?.length){r.innerHTML='<div class="empty-card"><h3>لا توجد بيانات كافية</h3><p>لا توجد إشارة مكتملة حالياً.</p></div>';return}
  r.innerHTML='<div class="results-note">استراتيجية واحدة موحدة تجمع 7 عناصر تحليل في قراءة واحدة</div>'+d.items.map((x,i)=>'<article class="analysis-card"><div class="trade-top"><div><span class="rank">#'+(i+1)+'</span><b>'+x.asset+'</b><small>'+x.timeframe_name+' · '+(x.side==="BUY"?"شراء":"بيع")+'</small></div><div class="ai"><strong>'+x.confidence+'%</strong><small>قوة الاستراتيجية</small></div></div><div class="strategy-line"><span>الاستراتيجية الموحدة</span><b>الاتجاه + الهيكل + السعر + السيولة + الاختراق + المناطق + المخاطر</b></div></article>').join("");
 }catch(e){r.innerHTML='<div class="empty-card"><h3>تعذر الاتصال بالخادم</h3><p>حاول مرة أخرى.</p></div>'}
}
let marketRefreshTimer=null;
function num(v){
 return Number(v).toLocaleString("en-US",{maximumFractionDigits:12});
}
function pctFromEntry(entry,target,kind){
 const e=Number(entry),t=Number(target);
 if(!Number.isFinite(e)||!e||!Number.isFinite(t)) return "";
 const p=((t-e)/e)*100;
 const n=Math.abs(p);
 if(kind==="sl") return (p<=0?"-":"+")+n.toFixed(2)+"%";
 return (p>=0?"+":"-")+n.toFixed(2)+"%";
}
function priceBox(label,value,entry,kind,cls=""){
 const pct=pctFromEntry(entry,value,kind);
 return '<div class="'+cls+'"><small>'+label+(pct?' <em>'+pct+'</em>':'')+'</small><b>'+num(value)+'</b></div>';
}
function tradeCard(x,i){
 const displayedSide=reverseSide(x.side);
 const side=displayedSide==="BUY"?"شراء":"بيع";
 const medal=i===0?"👑":i===1?"🥈":i===2?"🥉":"";
 const sideClass=displayedSide==="BUY"?"buy":"sell";
 const entry=Number(x.entry);
 return '<article class="pro-trade-card '+sideClass+'">'+
 '<div class="pro-trade-head"><div class="pro-rank">'+(medal||((i+1)+' :'))+'</div>'+
 '<div class="pro-symbol"><b>'+esc(x.asset)+'</b><span>'+side+' · '+esc(x.timeframe_name||x.timeframe||"")+'</span></div>'+
 '<div class="pro-ai"><strong>'+Number(x.ai_percent||0)+'%</strong><small>AI</small></div></div>'+
 '<div class="pro-level"><span class="pro-side '+sideClass+'">'+side+'</span>'+
 '<span class="pro-reverse">'+(reverseStrategy?"🔄 عكس مفعّل":"اتجاه أصلي")+'</span>'+
 '<span class="pro-live">● LIVE</span></div>'+
 '<div class="pro-prices">'+
 priceBox("الدخول",x.entry,entry,"entry")+
 priceBox("TP1",x.tp1,entry,"tp")+
 priceBox("TP2",x.tp2,entry,"tp")+
 priceBox("TP3",x.tp3,entry,"tp")+
 priceBox("SL",x.sl,entry,"sl","sl")+
 '</div><div class="pro-foot"><span>AI '+Number(x.ai_percent||0)+'%</span><span>فريم '+esc(x.timeframe_name||x.timeframe||"")+'</span></div></article>';
}

async function loadTrades(m,t){
 if(marketRefreshTimer){clearTimeout(marketRefreshTimer);marketRefreshTimer=null;}
 const r=document.getElementById("results");if(!r)return;
 marketRefreshTimer=setTimeout(()=>{if(currentPage===m)loadTrades(m,t)},60000);
 const label=(frames.find(x=>x[0]===t)||["",t])[1];
 r.innerHTML='<div class="loading-card"><span class="loader"></span><b>جاري تحليل '+label+'</b><small>يتم جلب البيانات الحقيقية ثم ترتيب الفرص</small></div>';
 const controller=new AbortController();
 const timeout=setTimeout(()=>controller.abort(),30000);
 try{
  const resp=await fetch("/api/trades?market="+encodeURIComponent(m)+"&timeframe="+encodeURIComponent(t),{cache:"no-store",signal:controller.signal});
  clearTimeout(timeout);
  let d=null;
  try{d=await resp.json()}catch(_){d={items:[]}}
  if(!resp.ok){
   throw new Error(d?.error||("HTTP "+resp.status));
  }
  if(!d.items?.length){
   const scanning=d?.scanning||false;
   r.innerHTML='<div class="empty-card"><div class="empty-icon">⌁</div><h3>'+(scanning?"جاري فحص السوق":"لا توجد صفقات حالياً")+'</h3><p>'+(scanning?"الفحص مستمر في الخلفية. اضغط تحديث بعد قليل.":"لا توجد إشارة مكتملة من البيانات الحالية.")+'</p><button class="primary-btn" onclick="loadTrades(\''+m+'\',\''+t+'\')">تحديث الآن</button></div>';
   return;
  }
  r.innerHTML='<div class="results-note">مرتبة حسب إجماع الاستراتيجية الموحدة على حركة السوق</div>'+d.items.map(tradeCard).join("");
 }catch(e){
  clearTimeout(timeout);
  const msg=e.name==="AbortError"?"استغرق فحص السوق وقتاً أطول من المتوقع.":"تعذر الاتصال بالخادم حالياً.";
  r.innerHTML='<div class="empty-card"><h3>'+msg+'</h3><p>أعد المحاولة وسيستخدم الموقع البيانات المحفوظة إن وُجدت.</p><button class="primary-btn" onclick="loadTrades(\''+m+'\',\''+t+'\')">إعادة المحاولة</button></div>';
 }
}
function trackerPage(){
 return '<section class="page-head"><div><span class="eyebrow">TRADE TRACKER · LIVE</span><h1>متابع الصفقات</h1><p>يتابع الصفقات التي خرجت فعلياً من محرك التحليل ويحسب نتيجة TP/SL من بيانات السوق.</p></div><div class="status-badge"><i></i> LIVE</div></section><div id="tracker-results" class="results"><div class="loading-card"><span class="loader"></span><b>جاري تحميل المتابع</b></div></div>';
}
let trackerRefreshTimer=null;
async function loadTracker(){
 const el=document.getElementById("tracker-results"); if(!el)return;
 if(trackerRefreshTimer)clearTimeout(trackerRefreshTimer);
 try{
  const d=await fetch("/api/tracker",{cache:"no-store"}).then(r=>r.json());
  const s=d.stats||{}, open=d.open||[], closed=(d.closed||[]).slice().reverse();
  const stat='<div class="hero-pills"><span>🟢 مفتوحة '+open.length+'</span><span>🏆 فوز '+(s.wins||0)+'</span><span>🔴 خسارة '+(s.losses||0)+'</span><span>نسبة الفوز '+(s.win_rate||0)+'%</span><span>💾 محفوظة</span></div>';
  const openHtml=open.map((x,i)=>tradeCard(x,i)).join("");;
  const closedHtml=closed.map((x,i)=>tradeCard(x,i)).join("");;
  el.innerHTML=stat+'<div class="results-note">الصفقات المفتوحة — الحفظ دائم</div>'+(openHtml||'<div class="empty-card"><h3>لا توجد صفقات مفتوحة</h3><p>أي صفقة جديدة ستظهر هنا وتُحفظ تلقائياً.</p></div>')+'<div class="results-note">آخر الصفقات المغلقة — محفوظة في سجل المتابع</div>'+(closedHtml||'<div class="empty-card"><h3>لا توجد نتائج بعد</h3><p>سيتم تسجيل النتائج تلقائياً عند تحقق TP أو SL.</p></div>');
  trackerRefreshTimer=setTimeout(()=>{if(currentPage==="tracker")loadTracker()},15000);
 }catch(e){
  el.innerHTML='<div class="empty-card"><h3>تعذر الاتصال بالخادم</h3><p>حاول مرة أخرى.</p></div>';
  trackerRefreshTimer=setTimeout(()=>{if(currentPage==="tracker")loadTracker()},15000);
 }
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
document.addEventListener("click",e=>{const a=e.target.closest("aside a[data-page]");if(!a)return;e.preventDefault();page(a.dataset.page)});
window.addEventListener("DOMContentLoaded",()=>page("home"));
async function loadSiteConfig(){
 try{
  siteConfig=await fetch("/api/site-config",{cache:"no-store"}).then(r=>r.json());
  document.title=siteConfig.title||"التداول الذكي PRO";
  document.querySelectorAll("aside a[data-page]").forEach(a=>{
   const k=a.dataset.page;
   if(markets[k]) a.style.display=siteConfig.sections?.[k]===false?"none":"flex";
  });
  if(siteConfig.announcement){
   let b=document.getElementById("site-announcement");
   if(!b){b=document.createElement("div");b.id="site-announcement";b.className="site-announcement";document.body.appendChild(b)}
   b.textContent=siteConfig.announcement;
  }
 }catch(e){}
}
loadSiteConfig();
function accountPage(){
 return '<section class="page-head"><div><span class="eyebrow">ACCOUNT CENTER · SECURE</span><h1>الحساب</h1><p>إنشاء حساب وتسجيل الدخول وإدارة جلسة المستخدم من داخل المنصة.</p></div></section><div id="account-results" class="account-grid"><div class="loading-card"><span class="loader"></span><b>جاري تحميل الحساب</b></div></div>';
}
async function loadAccount(){
 const el=document.getElementById("account-results");if(!el)return;
 try{
  const r=await fetch("/api/account/me",{cache:"no-store"});
  if(r.ok){
   const d=await r.json(),u=d.user;
   el.innerHTML='<article class="panel-card"><div class="panel-icon">👤</div><h2>مرحباً '+esc(u.name)+'</h2><p>'+esc(u.email)+'</p><span class="status-pill">مسجل الدخول</span><div class="account-actions"><button class="secondary-btn" onclick="accountLogout()">تسجيل الخروج</button></div></article>'+
   '<article class="panel-card"><div class="panel-icon">◷</div><h2>صفقاتي</h2><p>صفقاتك المسجلة ونتائجها محفوظة في المتابع.</p><button class="primary-btn" onclick="page(\'tracker\')">فتح المتابع</button></article>'+
   '<article class="panel-card"><div class="panel-icon">₿</div><h2>ربط Binance</h2><p>قسم الربط جاهز للطبقة المشفرة الخاصة بمفاتيح المستخدم.</p><span class="status-pill">غير متصل</span></article>';
  }else renderAccountAuth(el);
 }catch(e){el.innerHTML='<div class="empty-card"><h3>تعذر الاتصال بالحساب</h3><p>حاول مرة أخرى.</p></div>'}
}
function renderAccountAuth(el){
 el.innerHTML='<article class="panel-card admin-login"><div class="panel-icon">🔐</div><h2>تسجيل الدخول</h2><div class="admin-form"><input id="acc-email" type="email" placeholder="البريد الإلكتروني" autocomplete="email"><input id="acc-pass" type="password" placeholder="كلمة المرور" autocomplete="current-password"><button class="primary-btn" onclick="accountLogin()">دخول</button><button class="secondary-btn" onclick="showRegister()">إنشاء حساب جديد</button><div id="acc-error" class="muted"></div></div></article>';
}
function showRegister(){
 const el=document.getElementById("account-results");if(!el)return;
 el.innerHTML='<article class="panel-card admin-login"><div class="panel-icon">👤</div><h2>إنشاء حساب</h2><div class="admin-form"><input id="acc-name" placeholder="الاسم" autocomplete="name"><input id="acc-email" type="email" placeholder="البريد الإلكتروني" autocomplete="email"><input id="acc-pass" type="password" placeholder="كلمة المرور - 8 أحرف أو أكثر" autocomplete="new-password"><button class="primary-btn" onclick="accountRegister()">إنشاء الحساب</button><button class="secondary-btn" onclick="loadAccount()">لدي حساب</button><div id="acc-error" class="muted"></div></div></article>';
}
async function accountLogin(){
 const e=document.getElementById("acc-email").value,p=document.getElementById("acc-pass").value;
 const r=await fetch("/api/account/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email:e,password:p})});
 const d=await r.json();if(d.ok)loadAccount();else document.getElementById("acc-error").textContent=d.error||"فشل الدخول";
}
async function accountRegister(){
 const n=document.getElementById("acc-name").value,e=document.getElementById("acc-email").value,p=document.getElementById("acc-pass").value;
 const r=await fetch("/api/account/register",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:n,email:e,password:p})});
 const d=await r.json();if(d.ok)loadAccount();else document.getElementById("acc-error").textContent=d.error||"فشل إنشاء الحساب";
}
async function accountLogout(){await fetch("/api/account/logout",{method:"POST"});loadAccount()}

function adminPage(){
 return '<section class="page-head"><div><span class="eyebrow">ADMIN CONTROL CENTER</span><h1>لوحة الإدارة</h1><p>تحكم كامل بالموقع والأقسام وTelegram.</p></div><div class="status-badge"><i></i> SECURE</div></section><div id="admin-results" class="admin-grid"><div class="loading-card"><span class="loader"></span><b>جاري التحقق</b></div></div>';
}
async function loadAdmin(){
 const el=document.getElementById("admin-results"); if(!el)return;
 try{
  let d=await fetch("/api/admin/overview",{cache:"no-store"});
  if(d.status===401){renderAdminLogin(el);return}
  d=await d.json(); const set=d.settings||{}, sec=d.sections||{};
  el.innerHTML='<article class="panel-card admin-main"><h2>⚙️ التحكم بالموقع</h2><div class="admin-form"><label>اسم الموقع<input id="adm-title" value="'+esc(set.title||"التداول الذكي PRO")+'"></label><label>إعلان أعلى الموقع<input id="adm-ann" value="'+esc(set.announcement||"")+'"></label><label class="switch-row"><span>وضع الصيانة</span><input id="adm-maint" type="checkbox" '+(set.maintenance?"checked":"")+'></label><button class="primary-btn" onclick="saveAdminSettings()">حفظ الإعدادات</button></div></article>'+
  '<article class="panel-card"><h2>🔒 فتح / إغلاق الأقسام</h2><div class="admin-list">'+Object.entries(markets).map(([k,v])=>'<label class="switch-row"><span>'+v+'</span><input class="adm-section" data-k="'+k+'" type="checkbox" '+(set.sections?.[k]!==false?"checked":"")+'></label>').join("")+'</div></article>'+
  '<article class="panel-card"><h2>✈️ Telegram</h2><p>اختبر الربط أو أرسل رسالة مباشرة للقناة.</p><div class="admin-form"><textarea id="tg-text" rows="5" placeholder="نص الرسالة..."></textarea><div class="account-actions"><button class="secondary-btn" onclick="testTelegram()">اختبار Telegram</button><button class="primary-btn" onclick="publishTelegram()">إرسال</button></div><div id="tg-status" class="muted"></div></div></article>'+
  '<article class="panel-card"><h2>🚪 الجلسة</h2><button class="secondary-btn" onclick="adminLogout()">تسجيل الخروج</button></article>';
 }catch(e){el.innerHTML='<div class="empty-card"><h3>تعذر تحميل لوحة الإدارة</h3><p>تحقق من الخادم.</p></div>'}
}
function esc(v){return String(v||"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m]))}
function renderAdminLogin(el){
 el.innerHTML='<article class="panel-card admin-login"><div class="panel-icon">🔐</div><h2>دخول الإدارة</h2><p>اللوحة محمية بجلسة خاصة.</p><div class="admin-form"><input id="adm-user" placeholder="اسم المستخدم" autocomplete="username"><input id="adm-pass" type="password" placeholder="كلمة المرور" autocomplete="current-password"><button class="primary-btn" onclick="adminLogin()">دخول</button><div id="adm-error" class="muted"></div></div></article>';
}
async function adminLogin(){
 const user=document.getElementById("adm-user").value,pass=document.getElementById("adm-pass").value;
 const r=await fetch("/api/admin/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:user,password:pass})});
 const d=await r.json(); if(d.ok)loadAdmin(); else document.getElementById("adm-error").textContent=d.error||"فشل الدخول";
}
async function adminLogout(){await fetch("/api/admin/logout",{method:"POST"});loadAdmin()}
async function saveAdminSettings(){
 const sections={};document.querySelectorAll(".adm-section").forEach(x=>sections[x.dataset.k]=x.checked);
 const d=await fetch("/api/admin/settings",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({title:document.getElementById("adm-title").value,announcement:document.getElementById("adm-ann").value,maintenance:document.getElementById("adm-maint").checked,sections})}).then(r=>r.json());
 alert(d.ok?"تم حفظ الإعدادات":"فشل الحفظ");
}
async function testTelegram(){
 const d=await fetch("/api/admin/telegram/test",{method:"POST"}).then(r=>r.json());
 document.getElementById("tg-status").textContent=d.ok?"تم إرسال اختبار Telegram ✅":(d.error||d.message||"فشل الربط");
}
async function publishTelegram(){
 const d=await fetch("/api/admin/telegram/publish",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:document.getElementById("tg-text").value})}).then(r=>r.json());
 document.getElementById("tg-status").textContent=d.ok?"تم الإرسال إلى Telegram ✅":(d.error||d.message||"فشل الإرسال");
}

