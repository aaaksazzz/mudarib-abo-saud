const $=s=>document.querySelector(s);
let csrf="",currentUser=null,currentPage="overview",boot={sections:{}},authBusy=false;
const timeframeOptions=[["15m","15 دقيقة"]];
const marketNames={spot:"Binance Spot",futures:"Binance Futures",alpha:"Binance Alpha","us-stocks":"الأسهم الأمريكية","us-contracts":"العقود الأمريكية",saudi:"السوق السعودي",forex:"الفوركس والذهب"};
const pages={overview:"نظرة عامة",...marketNames,plans:"الاشتراكات والدفع",journal:"سجل الصفقات",blog:"المدونة",news:"الأخبار المهمة",admin:"لوحة الإدارة"};
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const money=n=>Number(n).toLocaleString("en-US",{maximumFractionDigits:8});
const pct=(entry,target,side)=>{const v=(target/entry-1)*100*(side==="BUY"?1:-1);return (v>=0?"+":"")+v.toFixed(2)+"%"};
function toast(s){const t=$("#toast");t.textContent=s;t.classList.add("show");setTimeout(()=>t.classList.remove("show"),2800)}
async function api(path,opts={}){const method=(opts.method||"GET").toUpperCase();if(method!=="GET"&&!csrf){const bootResponse=await fetch("/api/bootstrap",{credentials:"same-origin",cache:"no-store"});if(bootResponse.ok){const bootData=await bootResponse.json();csrf=bootData.csrf||csrf;}}const send=()=>{const headers={"Content-Type":"application/json",...(opts.headers||{})};if(method!=="GET"&&csrf)headers["X-CSRF-Token"]=csrf;return fetch(path,{...opts,headers,credentials:"same-origin",cache:"no-store"})};let r=await send(),d={};try{d=await r.json()}catch{}if(r.status===403&&method!=="GET"&&String(d.error||"").toLowerCase().includes("csrf")){const fresh=await fetch("/api/bootstrap",{credentials:"same-origin",cache:"no-store"});if(fresh.ok){const b=await fresh.json();csrf=b.csrf||csrf;r=await send();d={};try{d=await r.json()}catch{}}}if(!r.ok)throw Error(d.error||"تعذر تنفيذ الطلب");return d}
async function init(){const initialPage=pageFromLocation();renderPage(initialPage);const [b,p]=await Promise.allSettled([api("/api/bootstrap"),api("/api/plans")]);if(b.status==="fulfilled"){boot=b.value;csrf=b.value.csrf;currentUser=b.value.user;renderUser()}else{toast("تعذر تحميل بيانات الحساب؛ يمكنك استخدام الصفحة وإعادة المحاولة لاحقاً")}if(p.status==="fulfilled")configureAdminContact(p.value);if(location.pathname==="/login"||location.pathname==="/register"){authModal();if(location.pathname==="/register"&&$("#authSubmit").dataset.mode!=="register")$("#authMode").click()}}
function configureAdminContact(config){const link=$("#adminContact");if(!link)return;if(config.contact_url){link.href=config.contact_url;link.hidden=false}else{link.hidden=true}}
function renderUser(){$("#loginBtn").textContent=currentUser?currentUser.email.split("@")[0]:(document.documentElement.lang==="en"?"Sign in / Register":"دخول / حساب جديد");$("#accountStatus").textContent=currentUser?(currentUser.role==="admin"?"مدير النظام":currentUser.subscribed?"مشترك":"حساب مجاني"):"زائر";$("#adminNav").hidden=!(currentUser&&currentUser.role==="admin")}
function authModal(){const modal=$("#authModal");modal.hidden=false;$("#authEmail").focus()}
function closeAuth(){$("#authModal").hidden=true}
$("#loginBtn").addEventListener("click",()=>currentUser?accountMenu():authModal());
function accountMenu(){if(confirm("هل تريد تسجيل الخروج؟"))api("/api/auth/logout",{method:"POST"}).then(()=>{currentUser=null;csrf="";renderUser();toast("تم تسجيل الخروج");if(currentPage==="admin")openPage("overview")}).catch(e=>toast(e.message))}
$("#authClose").addEventListener("click",closeAuth);
$("#authMode").addEventListener("click",()=>{
 const reg=$("#authSubmit").dataset.mode!=="register";
 const errorBox=$("#authError");if(errorBox){errorBox.hidden=true;errorBox.textContent=""}
 $("#authSubmit").dataset.mode=reg?"register":"login";
 $("#authSubmit").textContent=reg?"إنشاء الحساب":"تسجيل الدخول";
 $("#authMode").textContent=reg?"لديك حساب؟ تسجيل الدخول":"مستخدم جديد؟ إنشاء حساب";
 $("#authPassword").autocomplete=reg?"new-password":"current-password";
 $("#authPassword").minLength=reg?12:0;
 $("#authPassword").placeholder=reg?"12 خانة أو أكثر، حروف وأرقام":"كلمة المرور";
});
$("#authForm").addEventListener("submit",async event=>{
 event.preventDefault();
 if(authBusy||!$("#authForm").reportValidity())return;
 const mode=$("#authSubmit").dataset.mode||"login";
 const submit=$("#authSubmit"),toggle=$("#authMode");
 authBusy=true;submit.disabled=true;toggle.disabled=true;
 submit.textContent=mode==="register"?"جارٍ إنشاء الحساب...":"جارٍ تسجيل الدخول...";
 try{
  const d=await api("/api/auth/"+mode,{method:"POST",body:JSON.stringify({email:$("#authEmail").value.trim(),password:$("#authPassword").value})});
  csrf=d.csrf;currentUser=d.user;renderUser();closeAuth();
  if(location.pathname==="/login"||location.pathname==="/register")history.replaceState({page:"overview"},"","/");
  toast(mode==="login"?"تم تسجيل الدخول":"تم إنشاء الحساب");
  renderPage(currentPage);
 }catch(e){const errorBox=$("#authError");if(errorBox){errorBox.textContent=e.message;errorBox.hidden=false}toast(e.message)}
 finally{
  authBusy=false;submit.disabled=false;toggle.disabled=false;
  submit.textContent=submit.dataset.mode==="register"?"إنشاء الحساب":"تسجيل الدخول";
 }
});
$("#menuToggle").addEventListener("click",()=>{$("#sidebar").classList.toggle("open");$("#scrim").classList.toggle("show")});
$("#scrim").addEventListener("click",()=>{$("#sidebar").classList.remove("open");$("#scrim").classList.remove("show")});
$("#themeToggle").addEventListener("click",()=>{document.body.classList.toggle("light");localStorage.setItem("stp-theme",document.body.classList.contains("light")?"light":"dark")});
const languageLabels={
ar:{overview:"نظرة عامة",spot:"Binance Spot",futures:"Binance Futures",alpha:"Binance Alpha","us-stocks":"الأسهم الأمريكية","us-contracts":"العقود الأمريكية",saudi:"السوق السعودي",forex:"الفوركس والذهب",journal:"سجل الصفقات",blog:"المدونة",news:"الأخبار المهمة",admin:"لوحة الإدارة",workspace:"مساحة العمل",markets:"الأسواق",discover:"اكتشف",systemReady:"واجهة المنصة جاهزة",platform:"المنصة",marketMonitor:"مراقبة الأسواق",login:"دخول / حساب جديد",intelligence:"INTELLIGENCE TERMINAL",overviewTitle:"مركز الأسواق الذكي",overviewSubtitle:"منصة موحدة للأسواق والتحليل والصفقات — بيانات حقيقية دون أرقام مختلقة."},
en:{overview:"Overview",spot:"Binance Spot",futures:"Binance Futures",alpha:"Binance Alpha","us-stocks":"US Stocks","us-contracts":"US Contracts",saudi:"Saudi Market",forex:"Forex & Gold",journal:"Trade Journal",blog:"Blog",news:"Market News",admin:"Admin Console",workspace:"WORKSPACE",markets:"MARKETS",discover:"DISCOVER",systemReady:"Platform interface ready",platform:"Platform",marketMonitor:"Market monitor",login:"Sign in / Register",intelligence:"INTELLIGENCE TERMINAL",overviewTitle:"Market Intelligence Hub",overviewSubtitle:"One platform for markets, analysis and trade ideas — grounded in real data."}
};
function applyLanguage(lang){const en=lang==="en";document.documentElement.lang=lang;document.documentElement.dir=en?"ltr":"rtl";document.body.dir=document.documentElement.dir;localStorage.setItem("stp-language",lang);Object.assign(pages,languageLabels[lang]||languageLabels.en);document.querySelectorAll("[data-page]").forEach(btn=>{const span=btn.querySelector("span:not(.nav-icon)");if(span)span.textContent=pages[btn.dataset.page]||btn.dataset.page});document.querySelectorAll("[data-i18n]").forEach(el=>{const key=el.dataset.i18n;if(languageLabels[lang][key])el.textContent=languageLabels[lang][key]});$("#loginBtn").textContent=currentUser?currentUser.email.split("@")[0]:languageLabels[lang].login;setTitle(currentPage);$("#todayLabel").textContent=new Intl.DateTimeFormat(en?"en-US":"ar-SA",{dateStyle:"medium"}).format(new Date())}
$("#languageSelect").addEventListener("change",e=>{applyLanguage(e.target.value);renderPage(currentPage)});
document.querySelectorAll("[data-page]").forEach(b=>b.addEventListener("click",()=>{if(b.dataset.page==="admin"&&(!currentUser||currentUser.role!=="admin"))return authModal();openPage(b.dataset.page)}));
window.addEventListener("popstate",()=>openPage(pageFromLocation(),{pushHistory:false}));
window.addEventListener("hashchange",()=>openPage(pageFromLocation(),{pushHistory:false}));
function setTitle(page){$("#crumb").textContent=pages[page]||"SMART TRADING PRO";$("#pageTitle").textContent=pages[page]||"SMART TRADING PRO";$("#pageSubtitle").textContent=page==="overview"?"منصة موحدة للأسواق والتحليل والصفقات — بيانات حقيقية دون أرقام مختلقة.":"تحليل مستقل وبيانات خاصة بهذا السوق."}
const validPages=new Set(["overview",...Object.keys(marketNames),"plans","journal","blog","news","admin"]);
const pagePaths={overview:"/",spot:"/market/spot",futures:"/market/futures",alpha:"/market/alpha","us-stocks":"/market/us-stocks","us-contracts":"/market/us-contracts",saudi:"/market/saudi",forex:"/market/forex",plans:"/plans",journal:"/journal",blog:"/blog",news:"/news",admin:"/admin"};
let renderVersion=0,overviewRefreshTimer=null,lastOverviewRefresh=0;
function pageFromHash(){const key=location.hash.replace(/^#\/?/,"").split(/[/?]/)[0];return validPages.has(key)?key:"overview"}
function pageFromLocation(){const path=location.pathname.replace(/\/$/,"")||"/";const route=Object.entries(pagePaths).find(([,url])=>url===path);return route?route[0]:pageFromHash()}
function openPage(page,{pushHistory=true}={}){if(!validPages.has(page))page="overview";if(pushHistory&&pageFromLocation()!==page)history.pushState({page},"",pagePaths[page]||"/");document.querySelectorAll("[data-page]").forEach(b=>{const active=b.dataset.page===page;b.classList.toggle("active",active);if(active)b.setAttribute("aria-current","page");else b.removeAttribute("aria-current")});$("#sidebar").classList.remove("open");$("#scrim").classList.remove("show");renderPage(page)}
function renderPage(page){if(!validPages.has(page))page="overview";if(overviewRefreshTimer){clearInterval(overviewRefreshTimer);overviewRefreshTimer=null}currentPage=page;const version=++renderVersion;setTitle(page);const root=$("#dynamicContent");root.innerHTML='<div class="loading-state">جارٍ تحميل البيانات...</div>';if(page==="overview"){overview(root,version);overviewRefreshTimer=setInterval(()=>{if(currentPage==="overview"&&document.visibilityState==="visible")overview(root,renderVersion)},15*60*1000);return}if(page==="plans")return plansPage(root);if(marketNames[page])return marketPage(root,page,version);if(page==="admin")return adminPage(root);if(page==="journal")return journalPage(root);if(page==="blog"||page==="news")return contentPage(root,page)}
document.addEventListener("visibilitychange",()=>{if(document.visibilityState==="visible"&&currentPage==="overview"&&Date.now()-lastOverviewRefresh>=15*60*1000)overview($("#dynamicContent"),renderVersion)});
function overviewMarketCard(m,s){
 const ready=!!(s&&s.ready!==false&&s.direction&&Number.isFinite(Number(s.total)));
 const direction=ready?s.direction:"غير متاح";
 const tone=direction==="صاعد"?"positive":direction==="هابط"?"negative":"muted-label";
 const breadth=ready?(Number(s.up||0)+" صاعد / "+Number(s.down||0)+" هابط · "+(s.side==="BUY"?"شراء":s.side==="SELL"?"بيع":"متعادل")):"بيانات الاتجاه غير متاحة";
 const status=ready?(s.stale?"آخر نسخة محفوظة · قديمة":s.cache_status==="fresh"?"محفوظة · تتحدث كل 15 دقيقة":"تم التحديث الآن"):(m.provider.configured?"بانتظار بيانات موثوقة":"مصدر البيانات غير مهيأ");
 return '<article class="market-card market-open" role="button" tabindex="0" data-open="'+esc(m.id)+'"><div class="market-card-top"><span class="market-type">'+esc(m.id.toUpperCase())+'</span><span class="status-pending">'+(m.enabled?"مفتوح":"موقوف")+'</span></div><h3>'+esc(marketNames[m.id])+'</h3><p>'+esc(m.provider.configured?m.provider.source:"مصدر البيانات غير مهيأ")+'</p><div class="market-overview-direction"><span>الاتجاه <b class="'+tone+'">'+esc(direction)+'</b></span><small>'+esc(breadth)+'</small></div><div class="market-card-bottom"><span class="empty-status">'+status+'</span><span class="arrow">↙</span></div></article>';
}
async function overview(root,version=renderVersion){
 lastOverviewRefresh=Date.now();
 const marketIds=["spot","futures","alpha","us-stocks","us-contracts","saudi","forex"];
 let markets=marketIds.map(id=>({id,enabled:true,provider:{configured:true,source:""}}));
 const snapshots={};
 const draw=()=>{
  if(version!==renderVersion||currentPage!=="overview")return;
  const grid=$("#overviewMarketGrid");
  if(!grid)return;
  grid.innerHTML=markets.map(m=>overviewMarketCard(m,snapshots[m.id])).join("");
  const values=Object.values(snapshots);
  const failed=marketIds.length-values.length;
  const stale=values.filter(x=>x&&x.stale).length;
  const updated=values.map(x=>Date.parse(x.updated_at)).filter(Number.isFinite);
  const latest=updated.length?new Date(Math.min(...updated)).toLocaleString(document.documentElement.lang==="en"?"en-US":"ar-SA",{dateStyle:"medium",timeStyle:"short"}):"—";
  const note=$("#overviewStatus");
  if(note)note.textContent=failed?"يتم تحديث اتجاهات الأسواق تدريجياً؛ قد تتأخر بعض المصادر.":stale?"بعض الأسواق تعرض آخر بيانات محفوظة.":"بيانات الأسواق محفوظة تلقائيًا وتتحدث كل 15 دقيقة. آخر تحديث: "+latest;
 };
 root.innerHTML='<div class="notice-bar"><span class="notice-symbol">!</span><span id="overviewStatus">يتم تجهيز اتجاهات الأسواق...</span></div><div class="market-grid" id="overviewMarketGrid"></div><p class="market-overview-footnote">الاتجاهات مبنية على اتساع السوق خلال 24 ساعة. البيانات محفوظة وتتحدث تلقائيًا كل 15 دقيقة.</p>';
 root.addEventListener("click",event=>{const card=event.target.closest("[data-open]");if(card&&root.contains(card))openPage(card.dataset.open)});
 root.addEventListener("keydown",event=>{const card=event.target.closest("[data-open]");if(card&&root.contains(card)&&(event.key==="Enter"||event.key===" ")){event.preventDefault();openPage(card.dataset.open)}});
 draw();
 const jobs=[(async()=>{try{const data=await api("/api/markets");if(version!==renderVersion||currentPage!=="overview")return;if(Array.isArray(data.markets)&&data.markets.length)markets=data.markets;draw()}catch(e){const note=$("#overviewStatus");if(note&&version===renderVersion)note.textContent="تعذر تحميل إعدادات بعض الأسواق؛ تظهر البطاقات الأساسية."}})()];
 for(const id of marketIds)jobs.push((async market=>{try{const snapshot=await api("/api/markets/"+market+"/snapshot");if(version!==renderVersion||currentPage!=="overview")return;snapshots[market]=snapshot;draw()}catch(e){const note=$("#overviewStatus");if(note&&version===renderVersion)note.textContent="يتم تحديث بيانات الأسواق تدريجيًا؛ بعض المصادر لم تستجب بعد."}})(id));
 await Promise.allSettled(jobs);
}
async function marketPage(root,market,version=renderVersion){
 try{
  const timeframe="15m";
  const [snap,sig,engine]=await Promise.all([api("/api/markets/"+market+"/snapshot"),api("/api/markets/"+market+"/signals?timeframe="+encodeURIComponent(timeframe)),api("/api/strategy-status").catch(()=>null)]);
  if(version!==renderVersion||currentPage!==market)return;
  const unavailable=snap.ready===false;
  const stale=sig.stale===true;
  const marketClosed=sig.market_closed===true;
  const warning=unavailable?"":marketClosed?'<div class="notice-bar">السوق السعودي مغلق حاليًا؛ تتوقف فرص الدخول على فريم 15 دقيقة خارج جلسة التداول، وتعود مع الجلسة القادمة.</div>':sig.scan_error?'<div class="notice-bar">تعذّر الفحص: '+esc(sig.scan_error)+'</div>':stale&&!sig.updated_at?'<div class="notice-bar">لم يكتمل أول فحص ناجح بعد؛ ننتظر دورة الفحص المجدولة.</div>':stale?'<div class="notice-bar">نتائج الفحص أقدم من 20 دقيقة. ننتظر تحديث الفحص المجدول.</div>':"";
  const signals=sig.signals||[];
  const frameLabel=(timeframeOptions.find(x=>x[0]===timeframe)||[])[1]||timeframe;
  const scanCoverage=sig.scan_universe==null?"نتائج آخر فحص محفوظة":Number(sig.scan_universe)+" أصل في القائمة · تم تحليل "+Number(sig.analysis_completed||0)+" في الدفعة الأخيرة";
  const emptyDetails=(()=>{
   if(marketClosed)return "السوق السعودي يعمل من الأحد إلى الخميس؛ التداول المستمر من 10 صباحًا إلى 3 مساءً بتوقيت الرياض. لا تُنشأ فرص دخول جديدة أثناء الإغلاق.";
   if(!sig.updated_at)return "لم يكتمل فحص ناجح لهذا السوق بعد.";
   if(sig.stale)return "نتائج الفحص قديمة؛ لن نعرض فرصاً قديمة على أنها فرص حالية.";
   const completed=Number(sig.analysis_completed||0),failed=Number(sig.analysis_failed||0);
   const matches=Number(sig.strategy_matches||0),fresh=Number(sig.fresh_matches||0);
   const rejected=Number(sig.direction_rejected||0),staleBars=Number(sig.rejected_stale_candle||0);
   const late=Number(sig.rejected_late_price||0);
   if(completed===0)return "لم تُحلّل أي شموع بنجاح. تحقق من مصدر البيانات لهذا السوق.";
   if(failed>0&&completed<failed)return "بعض طلبات الشموع فشلت؛ راجع اتصال مزود البيانات.";
   if(matches===0)return "اكتمل فحص "+completed+" تحليل، لكن لم تتوافق شروط النماذج على شمعة مغلقة.";
   if(fresh===0)return "ظهرت "+matches+" إعدادات، لكنها استُبعدت بسبب قدم الشمعة أو ابتعاد السعر عن الدخول.";
   if(rejected>0&&Number(sig.accepted_signals||0)===0)return "ظهرت "+fresh+" إعدادات، لكن اتجاه السوق العام ("+(sig.market_bias==="BUY"?"صاعد":sig.market_bias==="SELL"?"هابط":"متعادل")+") لم يؤكد اتجاهها.";
   return "لا توجد فرصة اجتازت جميع شروط التأكيد حالياً.";
  })();
  const tabs='<div class="timeframe-fixed-label">فريم التحليل · 15 دقيقة</div>';
  const engineData=engine||(sig.engine&&sig.fingerprint?{engine:sig.engine,fingerprint:sig.fingerprint}:null);
  const installed=engineData&&engineData.fingerprint==="SMART-FLOW-SMA200-V1-20261107"&&engineData.engine==="SMART FLOW QUANT";
  const legacyLabel=engine&&typeof engine.legacy_removed==="boolean"?(engine.legacy_removed?"القديم مستبدل":"جارٍ إيقاف الصفقات القديمة"):"المحرك مطابق";
  const engineStamp=installed?'<div class="engine-fingerprint"><span class="engine-led"></span><b>بصمة المحرك: '+esc(engineData.fingerprint)+'</b><span>7 أسواق · فريم 15 دقيقة فقط</span><span class="'+(engine&&engine.legacy_removed?"engine-clean":"engine-pending")+'">'+legacyLabel+'</span></div>':'<div class="engine-fingerprint engine-pending">تعذر تأكيد بصمة المحرك من واجهات الخادم الحالية</div>';
  root.innerHTML=warning+'<section class="panel market-summary"><div class="panel-head"><div><span class="section-kicker">'+esc(market.toUpperCase())+'</span><h2>'+esc(marketNames[market])+'</h2></div><span class="status-pending">'+(unavailable?"مصدر غير مربوط":"مصدر عام")+'</span></div><div class="direction-row"><div><small>'+(marketClosed?"اتجاه آخر جلسة · 24 ساعة":"اتجاه السوق · 24 ساعة") +'</small><strong>'+esc(snap.direction||"غير متاح")+(snap.side==="BUY"?" · شراء":snap.side==="SELL"?" · بيع":"") +'</strong></div><div><small>الأصول الصاعدة</small><strong class="positive">'+(snap.up??"—")+'</strong></div><div><small>الأصول الهابطة</small><strong class="negative">'+(snap.down??"—")+'</strong></div><div><small>عدد الأصول</small><strong>'+(snap.total??"—")+'</strong></div></div></section>'+engineStamp+tabs+'<div class="section-head"><div><span class="section-kicker">LIVE OPPORTUNITIES · '+esc(timeframe.toUpperCase())+'</span><h2>الصفقات النشطة · '+esc(frameLabel)+'</h2></div><span class="muted-label">'+esc(scanCoverage)+'</span></div><div class="trade-grid" id="tradeCards"></div><p class="data-footnote">آخر فحص: '+esc(sig.updated_at||snap.updated_at||"لم يبدأ بعد")+' · الفريم: '+esc(frameLabel)+' · التحليل والصفقات على شموع 15 دقيقة فقط.</p>';
  const grid=$("#tradeCards");
  if(grid)grid.innerHTML=signals.length?signals.map((t,i)=>tradeCard(t,i)).join(""):'<div class="panel empty-state"><b>لا توجد فرص مؤكدة على هذا الفريم حالياً</b><p>'+esc(emptyDetails)+'</p><small class="data-footnote">تم تنفيذ '+Number(sig.analysis_completed||0)+' تحليل · فشل '+Number(sig.analysis_failed||0)+' · توافق النماذج '+Number(sig.strategy_matches||0)+' · استبعاد الاتجاه '+Number(sig.direction_rejected||0)+' · شموع قديمة '+Number(sig.rejected_stale_candle||0)+' · دخول متأخر '+Number(sig.rejected_late_price||0)+'</small></div>';
 }catch(e){
  if(version!==renderVersion||currentPage!==market)return;
  root.innerHTML='<div class="panel empty-state"><b>تعذر تحميل بيانات السوق</b><p>'+esc(e.message)+'</p><button class="login-btn" id="retryMarket">إعادة المحاولة</button></div>';
  $("#retryMarket").onclick=()=>openPage(market);
 }
}
function tradeCard(t,index=99){
 const buy=t.side==="BUY";
 const medal=index===0?"🥇":index===1?"🥈":index===2?"🥉":"";
 const states={active:"نشطة",tp1_hit:"تحقق الهدف 1",tp2_hit:"تحقق الهدف 2",tp3_hit:"اكتملت الأهداف",stopped:"ضرب وقف الخسارة",stopped_after_tp1:"وقف بعد الهدف 1",stopped_after_tp2:"وقف بعد الهدف 2",expired:"منتهية",superseded:"استُبدلت"};
 const status=states[t.status]||t.status||"—";
 const pnl=t.result_pct==null?"—":(Number(t.result_pct)>0?"+":"")+Number(t.result_pct).toFixed(2)+"%";
 return '<article class="trade-card"><div class="trade-head"><div>'+(medal?'<span class="medal">'+medal+'</span>':"")+'<span class="trade-symbol">'+esc(t.symbol)+'</span><span class="trade-tag '+(buy?"buy":"sell")+'">'+(buy?"شراء":"بيع")+'</span></div><span class="score-tag">درجة التوافق '+Number(t.score).toFixed(0)+'/100</span></div><div class="trade-entry"><small>سعر الدخول</small><strong>'+money(t.entry)+'</strong></div><div class="targets"><div><small>الهدف 1 · 1R</small><b>'+money(t.tp1)+'</b><i>'+pct(t.entry,t.tp1,t.side)+'</i></div><div><small>الهدف 2 · 2R</small><b>'+money(t.tp2)+'</b><i>'+pct(t.entry,t.tp2,t.side)+'</i></div><div><small>الهدف 3 · 3R</small><b>'+money(t.tp3)+'</b><i>'+pct(t.entry,t.tp3,t.side)+'</i></div></div><div class="stop-row"><span>وقف الخسارة</span><b>'+money(t.stop)+'</b><i class="negative">'+pct(t.entry,t.stop,t.side)+'</i></div><div class="trade-foot"><span>'+esc(t.timeframe||"15m")+' · الفريم · تغير الفترة '+(t.change_pct==null?"—":Number(t.change_pct).toFixed(2)+"%")+'</span><span>التغير السعري من الدخول '+pnl+'</span><span class="status-pending">'+esc(status)+'</span></div></article>'
}
async function plansPage(root){
 try{
  const d=await api("/api/plans");
  const planCards=d.plans.map(p=>'<article class="plan-card"><span class="section-kicker">'+esc(p.name)+'</span><strong>$'+Number(p.total_usd).toFixed(0)+'</strong><small>'+(p.months===1?'شهر واحد':p.months+' أشهر')+'</small><b class="plan-discount">'+(p.discount_pct?'خصم '+p.discount_pct+'%':'السعر الأساسي')+'</b><p>'+(p.months===1?'30 دولار لكل شهر إضافي':p.months===6?'171 دولار بدلاً من 180':'324 دولار بدلاً من 360')+'</p></article>').join("");
  const trc=d.payment_methods.usdt_trc20.address,sol=d.payment_methods.sol.address,binance=d.payment_methods.binance_uid.value;
  root.innerHTML='<section class="panel"><div class="panel-head"><div><span class="section-kicker">MEMBERSHIP</span><h2>باقات الاشتراك</h2></div><span class="status-pending">الأسعار بالدولار</span></div><div class="plan-grid">'+planCards+'</div></section><section class="panel"><div class="panel-head"><h2>طرق الدفع</h2><span class="muted-label">انسخ العنوان وتأكد من الشبكة قبل التحويل</span></div><div class="payment-method"><div><b>USDT · TRC20</b><code>'+esc(trc)+'</code></div><button class="mini-btn" data-copy="'+esc(trc)+'">نسخ</button></div><div class="payment-method"><div><b>Solana · SOL</b><code>'+esc(sol)+'</code></div><button class="mini-btn" data-copy="'+esc(sol)+'">نسخ</button></div><div class="payment-method"><div><b>معرّف حساب Binance</b><code>'+esc(binance)+'</code></div><button class="mini-btn" data-copy="'+esc(binance)+'">نسخ</button></div><p class="data-footnote">بعد التحويل، أرسل إثبات الدفع للإدارة لتفعيل الاشتراك يدوياً. التحويل لا يفعّل الاشتراك تلقائياً.</p>'+(d.contact_url?'<a class="login-btn contact-inline" href="'+esc(d.contact_url)+'" target="_blank" rel="noopener">تواصل مع الإدارة ✓</a>':'<p class="status-pending">قناة التواصل الرسمية تحتاج إعداداً من الإدارة.</p>')+'</section>';
  root.querySelectorAll("[data-copy]").forEach(x=>x.addEventListener("click",async()=>{try{await navigator.clipboard.writeText(x.dataset.copy);toast("تم نسخ بيانات الدفع")}catch(e){toast("تعذر النسخ؛ انسخ العنوان يدوياً")}}));
 }catch(e){root.innerHTML='<div class="panel empty-state">'+esc(e.message)+'</div>'}
}
async function journalPage(root){
 try{
  const d=await api("/api/trades"),s=d.summary||{};
  const active=d.active_trades||[],completed=d.completed_trades||[];
  const rate=s.win_rate==null?"—":Number(s.win_rate).toFixed(1)+"%";
  const marketLabel=m=>marketNames[m]||m||"—";
  const statusLabels={active:"نشطة",tp1_hit:"الهدف الأول تحقق",tp2_hit:"الهدف الثاني تحقق",tp3_hit:"اكتملت الأهداف",stopped:"وقف خسارة",stopped_after_tp1:"وقف بعد الهدف الأول",stopped_after_tp2:"وقف بعد الهدف الثاني"};
  const card=t=>{
   const buy=t.side==="BUY",pnl=t.result_pct==null?"—":(Number(t.result_pct)>0?"+":"")+Number(t.result_pct).toFixed(2)+"%";
   const date=t.created_at?new Date(t.created_at).toLocaleString(document.documentElement.lang==="en"?"en-US":"ar-SA",{dateStyle:"short",timeStyle:"short"}):"—";
   return '<article class="journal-trade"><div class="journal-trade-top"><div><b>'+esc(t.symbol)+'</b><span class="trade-tag '+(buy?"buy":"sell")+'">'+(buy?"شراء":"بيع")+'</span></div><strong class="'+(Number(t.result_pct)>0?"positive":Number(t.result_pct)<0?"negative":"")+'">'+pnl+'</strong></div><div class="journal-trade-meta"><span>'+esc(marketLabel(t.market))+'</span><span>'+esc(t.timeframe||"15m")+'</span><span>'+date+'</span></div><div class="journal-trade-bottom"><span>'+esc(statusLabels[t.status]||t.status||"—")+'</span><span>الدخول '+money(t.entry)+'</span></div></article>';
  };
  root.innerHTML='<section class="journal-summary"><div class="journal-stat"><small>الصفقات النشطة</small><strong>'+Number(s.active||0)+'</strong><span>'+Number(s.buy_active||0)+' شراء · '+Number(s.sell_active||0)+' بيع</span></div><div class="journal-stat"><small>نسبة النجاح</small><strong>'+rate+'</strong><span>من النتائج المكتملة فقط</span></div><div class="journal-stat"><small>ناجحة</small><strong class="positive">'+Number(s.wins||0)+'</strong><span>أهداف أو ربح جزئي</span></div><div class="journal-stat"><small>خاسرة</small><strong class="negative">'+Number(s.losses||0)+'</strong><span>وقف قبل أي هدف</span></div></section>'+
  '<section class="panel journal-section"><div class="panel-head"><div><span class="section-kicker">LIVE FOLLOW-UP</span><h2>الصفقات قيد المتابعة</h2></div><span class="count-pill">'+active.length+'</span></div>'+(active.length?'<div class="journal-list">'+active.map(card).join("")+'</div>':'<div class="empty-state">لا توجد صفقات نشطة حالياً</div>')+'</section>'+
  '<section class="panel journal-section"><div class="panel-head"><div><span class="section-kicker">CLOSED RESULTS</span><h2>النتائج المكتملة</h2></div><span class="count-pill">'+completed.length+'</span></div><p class="data-footnote">نسبة النجاح = الصفقات التي وصلت إلى هدف واحد على الأقل ÷ (الناجحة + الخاسرة). الصفقات المستبدلة والمنتهية دون نتيجة لا تدخل بالحسبة.</p>'+(completed.length?'<div class="journal-list">'+completed.map(card).join("")+'</div>':'<div class="empty-state">لا توجد نتائج مكتملة كافية لحساب الأداء بعد</div>')+'</section>';
 }catch(e){
  root.innerHTML='<div class="panel empty-state"><b>تعذر تحميل سجل الصفقات</b><p>'+esc(e.message)+'</p><button class="login-btn" id="journalRetry">إعادة المحاولة</button></div>';
  $("#journalRetry").onclick=()=>renderPage("journal");
 }
}
async function contentPage(root,kind){
 try{
  const lang=document.documentElement.lang||"ar";
  if(kind==="news"){
   const d=await api("/api/news?lang="+encodeURIComponent(lang));
   const items=d.items||[];
   const sentimentNames={negative:"سلبي · بيع محتمل",positive:"إيجابي · شراء محتمل",neutral:"محايد · بلا اتجاه"};
   root.innerHTML='<section class="panel"><div class="panel-head"><div><span class="section-kicker">IN-APP MARKET INTELLIGENCE</span><h2>أخبار الأسواق واتجاه التأثير</h2></div><span class="status-pending">'+(d.provider||"مصدر الأخبار")+'</span></div>'+(items.length?'<div class="article-grid">'+items.map(a=>'<article class="panel news-card"><div class="panel-head"><span class="section-kicker">'+esc(a.source||"مصدر إخباري")+'</span><span class="trade-tag '+(a.sentiment==="negative"?"sell":a.sentiment==="positive"?"buy":"")+'">'+esc(sentimentNames[a.sentiment]||sentimentNames.neutral)+'</span></div><h3>'+esc(a.title)+'</h3><p class="data-footnote">قراءة آلية للعنوان: '+(a.direction==="SELL"?"يميل إلى ضغط سلبي وقد يدعم البيع":a.direction==="BUY"?"يميل إلى أثر إيجابي وقد يدعم الشراء":"لا يظهر اتجاه واضح")+'</p><small>'+esc(a.published_at||"")+'</small></article>').join("")+'</div>':'<div class="empty-state">لا توجد أخبار متاحة الآن. '+esc(d.error||"أعد المحاولة بعد قليل.")+'</div>')+'</section><p class="data-footnote">تُعرض الأخبار داخل المنصة فقط. تصنيف التأثير آلي ومبني على عنوان الخبر، وليس توصية تداول مؤكدة أو بديلاً عن تحليل السعر.</p>';
   return;
  }
  const d=await api("/api/content/blog?lang="+encodeURIComponent(lang));
  const items=d.items||[];
  root.innerHTML=items.length?'<div class="article-grid">'+items.map(a=>'<article class="panel"><span class="section-kicker">'+esc((a.language||lang).toUpperCase())+' · SMART TRADING PRO</span><h2><a href="/blog/'+encodeURIComponent(a.slug)+'">'+esc(a.title)+'</a></h2><p>'+esc(a.summary)+'</p><small>'+new Date(a.created_at).toLocaleDateString()+'</small></article>').join("")+'</div>':'<div class="panel empty-state"><b>المدونة قيد تجهيز المقالات</b><p>لا توجد مقالات منشورة بهذه اللغة حالياً. ستظهر المقالات بعد اكتمال المحتوى والترجمة والمراجعة.</p></div>';
 }catch(e){root.innerHTML='<div class="panel empty-state"><b>تعذر تحميل المحتوى</b><p>'+esc(e.message)+'</p><button class="login-btn" id="contentRetry">إعادة المحاولة</button></div>';$("#contentRetry").onclick=()=>contentPage(root,kind)}
}
async function adminPage(root){
 if(!currentUser||currentUser.role!=="admin"){
  try{
   const status=await api("/api/system/status");
   root.innerHTML='<section class="panel empty-state"><h2>الدخول إلى لوحة الإدارة</h2><p>سجّل الدخول بحساب المدير المعرّف في إعدادات Northflank.</p><p>'+(status.admin_exists?"يوجد حساب مدير مسجل.":"لا يوجد حساب مدير حتى الآن.")+'</p><p>'+(status.admin_login_configured?"بيانات دخول المدير مهيأة في إعدادات الخدمة.":"يلزم ضبط ADMIN_EMAIL و ADMIN_PASSWORD في إعدادات Northflank.")+'</p><p>'+(status.persistent_secret_configured?"مفتاح الجلسات الدائم مهيأ.":"تحذير: SECRET_KEY الدائم غير مهيأ؛ قد تنتهي الجلسات بعد إعادة التشغيل.")+'</p><button class="login-btn" id="adminLoginNow">تسجيل دخول المدير</button></section>';
   $("#adminLoginNow").onclick=authModal;
  }catch(e){root.innerHTML='<div class="panel empty-state">'+esc(e.message)+'</div>'}
  return;
 }
 try{const [o,u,p,settings]=await Promise.all([api("/api/admin/overview"),api("/api/admin/users"),api("/api/admin/providers"),api("/api/plans")]);root.innerHTML='<section class="panel"><div class="panel-head"><h2>قناة التواصل الرسمية</h2></div><div class="admin-form"><input id="adminContactUrl" type="url" placeholder="رابط واتساب أو تيليجرام يبدأ بـ https://"><button class="login-btn" id="saveAdminContact">حفظ رابط التواصل</button><small>تظهر أيقونة الإدارة للزوار بعد حفظ الرابط.</small></div></section><section class="panel"><div class="panel-head"><h2>منح اشتراك مفتوح</h2><span class="status-pending">بدون تاريخ انتهاء</span></div><div class="admin-form"><input id="lifetimeEmail" type="email" placeholder="البريد الإلكتروني للحساب"><button class="login-btn" id="grantLifetime">منح وصول دائم</button><small>يجب أن يكون الحساب مسجلاً أولاً.</small></div></section><div class="admin-stats"><div class="panel"><small>المستخدمون</small><strong>'+o.users+'</strong></div><div class="panel"><small>الصفقات النشطة</small><strong>'+o.active_trades+'</strong></div><div class="panel"><small>المقالات</small><strong>'+o.articles+'</strong></div></div><section class="panel"><div class="panel-head"><h2>التحكم بالأقسام</h2></div><div class="admin-sections">'+Object.entries(o.sections).map(([k,v])=>'<label><span>'+esc(pages[k]||k)+'</span><input type="checkbox" data-section="'+k+'" '+(v?"checked":"")+'> <b>'+(v?"مفتوح":"مغلق")+'</b></label>').join("")+'</div></section><section class="panel"><div class="panel-head"><h2>إدارة المستخدمين والاشتراكات</h2></div><div class="table-wrap"><table><thead><tr><th>البريد</th><th>الدور</th><th>الحالة</th><th>الاشتراك</th><th>منح اشتراك (أيام)</th></tr></thead><tbody>'+u.users.map(x=>'<tr><td>'+esc(x.email)+'</td><td>'+esc(x.role)+'</td><td>'+ (x.active?"فعال":"موقوف")+' <button class="mini-btn" data-toggle-user="'+x.id+'" data-active="'+(!x.active)+'">'+(x.active?"إيقاف":"تفعيل")+'</button></td><td>'+esc(x.plan||"مجاني")+'<br>'+esc(x.subscription_until||"—")+'</td><td><input type="number" min="1" max="3650" value="30" id="days-'+x.id+'" class="small-input"><button class="mini-btn" data-grant="'+x.id+'">منح</button><button class="mini-btn" data-lifetime="'+x.id+'">مفتوح</button></td></tr>').join("")+'</tbody></table></div></section><section class="panel"><div class="panel-head"><h2>نشر خبر أو مقال</h2></div><div class="admin-form"><select id="contentKind"><option value="blog">مدونة</option><option value="news">خبر</option></select><select id="contentLanguage"><option value="ar">العربية</option><option value="en">English</option><option value="es">Español</option><option value="de">Deutsch</option><option value="id">Bahasa Indonesia</option><option value="pt">Português (Brasil)</option><option value="tr">Türkçe</option><option value="fr">Français</option><option value="hi">हिन्दी</option></select><input id="contentTitle" placeholder="العنوان"><input id="contentMetaTitle" maxlength="70" placeholder="عنوان SEO (70 حرفاً كحد أقصى)"><input id="contentSummary" placeholder="ملخص قصير"><input id="contentMetaDescription" maxlength="170" placeholder="وصف SEO (170 حرفاً كحد أقصى)"><textarea id="contentBody" placeholder="المحتوى"></textarea><label><input type="checkbox" id="contentPublish" checked> نشر مباشرة</label><button class="login-btn" id="publishContent">نشر المحتوى</button></div></section><section class="panel"><h2>حالة مزودي البيانات</h2><div class="status-list">'+Object.entries(p.providers).map(([k,v])=>'<div><span>'+esc(pages[k])+'</span><b class="'+(v.configured?"positive":"status-pending")+'">'+(v.configured?"متصل":"يحتاج إعداد")+'</b></div>').join("")+'</div></section>';
$("#adminContactUrl").value=settings.contact_url||"";
$("#saveAdminContact").onclick=async()=>{try{const url=$("#adminContactUrl").value.trim();await api("/api/admin/contact",{method:"PUT",body:JSON.stringify({url})});toast("تم حفظ رابط التواصل");configureAdminContact({contact_url:url})}catch(e){toast(e.message)}};
$("#grantLifetime").onclick=async()=>{try{const email=$("#lifetimeEmail").value.trim();await api("/api/admin/users/subscription-by-email",{method:"POST",body:JSON.stringify({email,lifetime:true})});toast("تم منح الاشتراك المفتوح");adminPage(root)}catch(e){toast(e.message)}};
root.querySelectorAll("[data-lifetime]").forEach(x=>x.addEventListener("click",async()=>{try{await api("/api/admin/users/"+x.dataset.lifetime+"/subscription",{method:"POST",body:JSON.stringify({lifetime:true})});toast("تم منح الاشتراك المفتوح");adminPage(root)}catch(e){toast(e.message)}}));
root.querySelectorAll("[data-section]").forEach(x=>x.addEventListener("change",async()=>{try{await api("/api/admin/sections/"+x.dataset.section,{method:"PUT",body:JSON.stringify({enabled:x.checked})});toast("تم تحديث صلاحية القسم")}catch(e){x.checked=!x.checked;toast(e.message)}}));
root.querySelectorAll("[data-toggle-user]").forEach(x=>x.addEventListener("click",async()=>{try{await api("/api/admin/users/"+x.dataset.toggleUser,{method:"PATCH",body:JSON.stringify({active:x.dataset.active==="true"})});toast("تم تحديث حالة المستخدم");adminPage(root)}catch(e){toast(e.message)}}));
root.querySelectorAll("[data-grant]").forEach(x=>x.addEventListener("click",async()=>{try{const days=Number($("#days-"+x.dataset.grant).value);await api("/api/admin/users/"+x.dataset.grant+"/subscription",{method:"POST",body:JSON.stringify({days,plan:"pro"})});toast("تم منح الاشتراك");adminPage(root)}catch(e){toast(e.message)}}));
$("#publishContent").onclick=async()=>{try{await api("/api/admin/content",{method:"POST",body:JSON.stringify({kind:$("#contentKind").value,language:$("#contentLanguage").value,title:$("#contentTitle").value,meta_title:$("#contentMetaTitle").value,summary:$("#contentSummary").value,meta_description:$("#contentMetaDescription").value,body:$("#contentBody").value,published:$("#contentPublish").checked})});toast("تم حفظ المحتوى");adminPage(root)}catch(e){toast(e.message)}}
}catch(e){root.innerHTML='<div class="panel empty-state">'+esc(e.message)+'</div>'}}
if(localStorage.getItem("stp-theme")==="light")document.body.classList.add("light");
$("#languageSelect").value=localStorage.getItem("stp-language")||"ar";
applyLanguage($("#languageSelect").value);
init();
const marketRefreshBusy=new Set();
setInterval(async()=>{
 const market=currentPage;
 if(!marketNames[market]||marketRefreshBusy.has(market))return;
 const root=$("#dynamicContent");
 if(!root)return;
 const version=renderVersion;
 marketRefreshBusy.add(market);
 try{await marketPage(root,market,version)}finally{marketRefreshBusy.delete(market)}
},60*1000);
