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
 if(p==="home") body=home();
 else if(markets[p]) body=market(p);
 else if(p==="news"||p==="blog") body=articles(p);
 else body='<section class="page-head"><div><span class="eyebrow">SMART CENTER</span><h1>'+ (titles[p]||"التداول الذكي PRO") +'</h1><p>قسم مستقل جاهز للبناء بدون بيانات وهمية.</p></div></section><div class="empty-card"><div class="empty-icon">◆</div><h3>سيتم تفعيل هذا القسم ضمن النسخة الجديدة</h3><p>لن يتم عرض نتائج غير موثوقة.</p></div>';
 app.innerHTML=body;
 nav.classList.remove("open");backdrop.classList.remove("show");
 document.querySelectorAll("aside a").forEach(a=>a.classList.toggle("active",a.dataset.page===p));
 window.scrollTo({top:0,behavior:"smooth"});
}
function home(){
 return '<section class="hero-new"><div class="hero-copy"><span class="eyebrow">MARKET INTELLIGENCE · LIVE</span><h1>كل الأسواق.<br><strong>في واجهة واحدة.</strong></h1><p>تحليل ومتابعة منظمة للسبوت والفيوتشر والعقود والأسواق السعودية والأمريكية والفوركس والذهب.</p><div class="hero-pills"><span>● تحديث مستمر</span><span>AI%</span><span>7 فريمات</span></div></div><div class="hero-orbit"><div class="orbit-ring"></div><div class="orbit-core">◆<small>PRO</small></div></div></section><section class="section-title"><div><span class="eyebrow">MARKETS</span><h2>الأسواق</h2></div><span class="muted">اختر السوق للبدء</span></section><div class="market-grid">'+Object.entries(markets).map(([k,v])=>'<button class="market-card" onclick="page(\''+k+'\')"><span class="market-icon">'+marketIcons[k]+'</span><span><b>'+v+'</b><small>تحليل متعدد الفريمات</small></span><em>←</em></button>').join("")+'</div><section class="quick-grid"><button onclick="page(\'scanner\')" class="quick-card"><span>⌕</span><b>الماسح الذكي</b><small>ابحث عن الفرص المستوفية للشروط</small></button><button onclick="page(\'tracker\')" class="quick-card"><span>◷</span><b>متابع الصفقات</b><small>تابع الصفقات والنتائج المسجلة</small></button><button onclick="page(\'news\')" class="quick-card"><span>📰</span><b>الأخبار</b><small>آخر المحتوى داخل المنصة</small></button></section>';
}
function market(p){
 return '<section class="page-head market-head"><div><span class="eyebrow">'+marketIcons[p]+' MARKET</span><h1>'+markets[p]+'</h1><p>اختر الفريم لعرض النتائج المتوفرة فعلياً.</p></div><div class="status-badge"><i></i> LIVE</div></section><div class="frame-bar">'+frames.map(f=>'<button class="frame" onclick="loadTrades(\''+p+'\',\''+f[0]+'\')">'+f[1]+'</button>').join("")+'</div><div id="results" class="results"><div class="empty-card"><div class="empty-icon">⌁</div><h3>لا توجد صفقات معتمدة حالياً</h3><p>سيظهر هنا التحليل فقط عندما تتوفر بيانات موثوقة.</p></div></div>';
}
async function loadTrades(m,t){
 const r=document.getElementById("results"); if(!r)return;
 r.innerHTML='<div class="loading-card"><span class="loader"></span><b>جاري الفحص</b><small>يتم التحقق من البيانات…</small></div>';
 try{const d=await fetch("/api/trades?market="+encodeURIComponent(m)+"&timeframe="+encodeURIComponent(t)).then(x=>x.json());
 if(!d.items||!d.items.length){r.innerHTML='<div class="empty-card"><div class="empty-icon">⌁</div><h3>لا توجد صفقة مستوفية للشروط</h3><p>الفريم: '+(d.timeframe_name||t)+'</p></div>';return}
 r.innerHTML=d.items.map(x=>'<div class="trade-result">'+JSON.stringify(x)+'</div>').join("");
 }catch(e){r.innerHTML='<div class="empty-card"><h3>تعذر الاتصال بالخادم</h3><p>حاول مرة أخرى.</p></div>'}
}
function articles(p){
 const isNews=p==="news";
 return '<section class="page-head"><div><span class="eyebrow">'+(isNews?"NEWS ROOM":"SMART BLOG")+'</span><h1>'+(isNews?"الأخبار":"المدونة")+'</h1><p>'+(isNews?"محتوى وأخبار السوق داخل المنصة.":"دروس ومنهجيات تداول مكتوبة بشكل مبسط.")+'</p></div></section><div id="articles" class="article-grid"><div class="loading-card"><span class="loader"></span><b>جاري التحميل</b></div></div>';
}
async function loadArticles(p){
 try{const d=await fetch(p==="news"?"/api/news":"/api/blog").then(r=>r.json()),el=document.getElementById("articles");if(!el)return;
 el.innerHTML=d.items.map(x=>'<article class="article-card"><div class="article-meta"><span>'+x.category+'</span><time>'+x.date+'</time></div><h2>'+x.title+'</h2><p>'+x.summary+'</p><button onclick="showArticle('+x.id+',\''+p+'\')">قراءة المقال <b>←</b></button></article>').join("");
 }catch(e){const el=document.getElementById("articles");if(el)el.innerHTML='<div class="empty-card"><h3>تعذر تحميل المحتوى</h3></div>'}
}
async function showArticle(id,p){
 const x=await fetch((p==="news"?"/api/news/":"/api/blog/")+id).then(r=>r.json());
 app.innerHTML='<article class="article-single"><button class="back-btn" onclick="page(\''+p+'\')">→ العودة</button><div class="article-meta"><span>'+x.category+'</span><time>'+x.date+'</time></div><h1>'+x.title+'</h1><p class="article-body">'+x.body+'</p></article>';
 window.scrollTo({top:0,behavior:"smooth"});
}
document.querySelectorAll("aside a").forEach(a=>a.onclick=()=>page(a.dataset.page));
page("home");
loadArticles;
