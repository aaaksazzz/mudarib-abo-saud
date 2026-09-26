const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
let markets={},currentMarket="spot",currentTf="15m",currentPage="home",currentPeriod="all";
const frames=[["5m","5د"],["15m","15د"],["1h","1س"],["4h","4س"],["1d","يومي"],["1w","أسبوعي"],["1M","شهري"]];
const esc=v=>String(v??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[m]));
async function api(u,o){const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),15000);try{const r=await fetch(u,{credentials:"include",cache:"no-store",signal:ctrl.signal,...(o||{})});let d={};try{d=await r.json()}catch{}if(!r.ok)throw Error(d.detail||"تعذر الطلب");return d}catch(e){if(e.name==="AbortError")throw Error("انتهت مهلة الاتصال");throw e}finally{clearTimeout(timer)}}
function safeClick(el,fn){if(el)el.addEventListener("click",fn)}
function closeMenu(e){if(e?.preventDefault)e.preventDefault();if(e?.stopPropagation)e.stopPropagation();const drawer=$("#drawer"),backdrop=$("#backdrop");drawer?.classList.remove("open");backdrop?.classList.remove("show");document.body.classList.remove("menu-open");$("#menu")?.setAttribute("aria-expanded","false")}
function openMenu(e){if(e){e.preventDefault();e.stopPropagation()}const drawer=$("#drawer"),backdrop=$("#backdrop");if(!drawer||!backdrop)return;drawer.classList.add("open");backdrop.classList.add("show");document.body.classList.add("menu-open");$("#menu")?.setAttribute("aria-expanded","true")}

function setTheme(mode){document.body.classList.toggle("light",mode==="light");try{localStorage.setItem("theme",mode)}catch{}}
function toggleTheme(e){if(e){e.preventDefault();e.stopPropagation()}setTheme(document.body.classList.contains("light")?"dark":"light")}

try{setTheme(localStorage.getItem("theme")==="light"?"light":"dark")}catch{}
function frameButtons(target,selected=currentTf,onPick=()=>{}){const el=$(target);if(!el)return;el.innerHTML=frames.map(([v,t])=>'<button class="'+(v===selected?"active":"")+'" data-tf="'+v+'">'+t+"</button>").join("");$$(target+" button").forEach(b=>b.onclick=()=>onPick(b.dataset.tf))}
function fmt(v){if(v==null||v==="")return"—";return Number(v).toLocaleString("en-US",{maximumFractionDigits:8})}
function tradeCard(x){const s=x.signal||x;return '<article class="trade-card"><div class="trade-top"><div><div class="symbol">'+esc(x.symbol)+'</div><div class="trade-meta">'+esc(x.market||"")+" · "+esc(x.timeframe||currentTf)+'</div></div><span class="side '+(s.side==="شراء"?"buy":"sell")+'">'+esc(s.side||"—")+'</span></div><div class="trade-values"><div class="trade-value"><small>دخول</small><b>'+fmt(s.entry)+'</b></div><div class="trade-value"><small>TP1</small><b>'+fmt(s.tp1)+'</b></div><div class="trade-value"><small>TP2</small><b>'+fmt(s.tp2)+'</b></div><div class="trade-value"><small>TP3</small><b>'+fmt(s.tp3)+'</b></div><div class="trade-value"><small>وقف</small><b>'+fmt(s.sl)+'</b></div><div class="trade-value"><small>AI%</small><b class="ai">'+(s.ai==null?"—":fmt(s.ai)+"%")+"</b></div></div><div class="trade-footer"><span>"+esc(x.status||"فرصة")+'</span><span>⚡ تحديث مباشر</span></div></article>'}
function empty(msg="لا توجد صفقات مطابقة حالياً."){return '<div class="info-banner">'+msg+"</div>"}
async function scannerData(m,tf){return api("/api/section/"+encodeURIComponent(m)+"/scanner?timeframe="+encodeURIComponent(tf))}
async function storedTrades(m,tf){return api("/api/section/"+encodeURIComponent(m)+"/trades?timeframe="+encodeURIComponent(tf)+"&limit=100")}
async function allStored(tf){return api("/api/all-trades?timeframe="+encodeURIComponent(tf)+"&limit=100")}
async function renderMarketPage(m,tf,listId){const list=$(listId);if(!list)return;list.innerHTML=empty("جاري تحميل الصفقات…");try{let d=await storedTrades(m,tf);if(!d.length)d=await scannerData(m,tf);list.innerHTML=d.length?d.map(tradeCard).join(""):empty()}catch{list.innerHTML=empty("تعذر جلب بيانات السوق حالياً.")}}
async function loadStats(period="all"){await loadTracker(period)}
async function loadTracker(period=currentPeriod){const box=$("#historyList");if(!box)return;const market=$("#trackerMarket")?.value||"all";box.innerHTML=empty("جاري تحديث المتابعة…");try{const x=await api("/api/tracker?period="+encodeURIComponent(period)+"&market="+encodeURIComponent(market));const st=x.stats;$("#trTotal").textContent=st.total;$("#open").textContent=st.open;$("#closed").textContent=st.closed;$("#wins").textContent=st.wins;$("#losses").textContent=st.losses;$("#win").textContent=st.win_rate==null?"—":st.win_rate+"%";$("#pnl").textContent=fmt(st.pnl)+"%";$("#livePnl").textContent=fmt(st.live_pnl)+"%";$("#trackerUpdated").textContent=new Date().toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit",second:"2-digit"});currentPeriod=period;$("#periodTabs button").forEach(b=>b.classList.toggle("active",b.dataset.period===period));const items=x.items||[],openItems=items.filter(t=>t.status==="open"),closedItems=items.filter(t=>t.status==="closed");const enrich=t=>'<article class="tracker-card '+(t.status==="open"?"is-open":"is-closed")+'"><div class="tracker-card-head"><div><b>'+esc(t.symbol)+'</b><small>'+esc(t.market)+' · '+esc(t.timeframe)+'</small></div><span class="tracker-state">'+esc(t.state||"مغلقة")+'</span></div><div class="tracker-price"><div><small>الدخول</small><b>'+fmt(t.entry)+'</b></div><div><small>السعر الآن</small><b>'+fmt(t.price)+'</b></div><div><small>PnL</small><b class="'+((t.live_pnl||t.pnl||0)>=0?"profit":"loss")+'">'+fmt(t.live_pnl??t.pnl)+'%</b></div></div><div class="tracker-progress"><div class="progress-head"><span>التقدم إلى TP3</span><b>'+fmt(t.progress)+'%</b></div><div class="progress-track"><i style="width:'+Math.max(0,Math.min(100,Number(t.progress)||0))+'%"></i></div></div><div class="tracker-targets"><span class="'+(t.tp1_hit_at?"hit":"")+'">TP1 <b>'+fmt(t.tp1)+'</b></span><span class="'+(t.tp2_hit_at?"hit":"")+'">TP2 <b>'+fmt(t.tp2)+'</b></span><span class="'+(t.tp3_hit_at?"hit":"")+'">TP3 <b>'+fmt(t.tp3)+'</b></span><span class="'+(t.sl_hit_at?"stop-hit":"")+'">SL <b>'+fmt(t.sl)+'</b></span></div><div class="tracker-meta"><span>AI '+fmt(t.ai)+'%</span><span>دخول: '+esc(t.created_at||"—")+'</span><span>'+(t.closed_at?"إغلاق: "+esc(t.closed_at):"مفتوحة الآن")+'</span></div></article>';$("#openHistory").innerHTML=openItems.length?openItems.map(enrich).join(""):empty("لا توجد صفقات مفتوحة حالياً.");box.innerHTML=closedItems.length?closedItems.slice(0,80).map(enrich).join(""):empty("لا توجد صفقات مغلقة للفترة المحددة.");const best=[...closedItems].sort((a,b)=>(b.pnl||0)-(a.pnl||0))[0];$("#bestTrade").textContent=best?esc(best.symbol)+" "+fmt(best.pnl)+"%":"—";$("#avgAi").textContent=st.avg_ai==null?"—":fmt(st.avg_ai)+"%";$("#bestMarket").textContent=st.best_market||"—";$("#bestTf").textContent=st.best_tf||"—";$("#bestTrade").textContent=st.best_trade?esc(st.best_trade.symbol)+" "+fmt(st.best_trade.pnl)+"%":"—"}catch{box.innerHTML=empty("تعذر تحميل المتابعة حالياً.")}}
async function loadHistory(period="all"){return loadTracker(period)}
async function loadNews(){const el=$("#newsList");if(!el)return;try{const d=await api("/api/news");el.innerHTML=d.length?d.map(x=>'<article class="news-card"><b>'+esc(x.title)+'</b><small>'+esc(x.source)+" · "+esc(x.created_at)+"</small><p>"+esc(x.body)+"</p></article>").join(""):empty("لا توجد أخبار حالياً.")}catch{el.innerHTML=empty("تعذر جلب الأخبار.")}}
async function loadMe(){try{const x=await api("/api/auth/me");if(x.authenticated){$("#meState").textContent=x.user.email+" · "+x.user.role;$("#logout").classList.remove("hidden");if(x.user.role==="admin")loadAdmin()}else{$("#meState").textContent="غير مسجل";$("#logout").classList.add("hidden")}}catch{}}
async function loadAdmin(){try{const x=await api("/api/admin/summary");$("#adminBox").innerHTML='<div class="stats-grid"><div class="stat-card"><small>المستخدمون</small><b>'+x.users+'</b></div><div class="stat-card"><small>الصفقات</small><b>'+x.trades+'</b></div><div class="stat-card"><small>مفتوحة</small><b>'+x.open+'</b></div><div class="stat-card"><small>مغلقة</small><b>'+x.closed+'</b></div></div><button id="tg" class="primary-btn">📨 اختبار Telegram</button><p id="tgmsg" class="notice"></p>';$("#tg").onclick=async()=>{try{const r=await api("/api/admin/telegram-test",{method:"POST"});$("#tgmsg").textContent=r.ok?"تم إرسال الاختبار إلى Telegram ✅":r.message||"Telegram غير مضبوط"}catch(e){$("#tgmsg").textContent=e.message}}}catch{$("#adminBox").innerHTML=empty("سجل دخول المدير لعرض أدوات الإدارة.")}}
async function loadHome(){try{const x=await api("/api/platform/summary");$("#qOpen").textContent=x.open;$("#qClosed").textContent=x.closed;$("#qWin").textContent=x.win_rate==null?"—":x.win_rate+"%";$("#qTime").textContent=new Date().toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"})}catch{$("#qOpen").textContent="—";$("#qClosed").textContent="—";$("#qWin").textContent="—";$("#qTime").textContent="تعذر الاتصال"}}
function setupMarketTabs(){const map={spot:"#spotFrames",futures:"#futuresFrames",contracts:"#contractsFrames",saudi:"#saudiFrames",us:"#usFrames",forex:"#forexFrames"};Object.entries(map).forEach(([m,id])=>frameButtons(id,currentTf,t=>{currentTf=t;renderMarketPage(m,t,"#"+m+"List")}))}
function setupTradeTabs(){const holder=$("#tradeMarketTabs");if(!holder)return;holder.innerHTML=Object.entries(markets).map(([k,v])=>'<button class="'+(k===currentMarket?"active":"")+'" data-market="'+k+'">'+v.label+"</button>").join("");$$("#tradeMarketTabs button").forEach(b=>b.onclick=()=>{currentMarket=b.dataset.market;setupTradeTabs();loadTrades()});frameButtons("#tradeFrames",currentTf,t=>{currentTf=t;loadTrades()})}
async function loadTrades(){const el=$("#tradeList");if(!el)return;el.innerHTML=empty("جاري تحميل الصفقات…");try{let d=await storedTrades(currentMarket,currentTf);if(!d.length)d=await scannerData(currentMarket,currentTf);el.innerHTML=d.length?d.map(tradeCard).join(""):empty("لا توجد صفقات لهذا السوق والفريم.")}catch{el.innerHTML=empty("تعذر جلب الصفقات.")}}
function setupScanner(){const sel=$("#scanMarket");if(!sel)return;sel.innerHTML=Object.entries(markets).map(([k,v])=>'<option value="'+k+'">'+v.label+"</option>").join("");frameButtons("#scanFrames",currentTf,t=>{currentTf=t;runScan()});$("#scanNow").onclick=runScan}
async function runScan(){const el=$("#scannerList");if(!el)return;const m=$("#scanMarket").value;el.innerHTML=empty("جاري الفحص…");try{const d=await scannerData(m,currentTf);el.innerHTML=d.length?d.map(tradeCard).join(""):empty("لا توجد فرصة مطابقة حالياً.")}catch{el.innerHTML=empty("تعذر الفحص حالياً.")}}
function setupTracker(){const sel=$("#trackerMarket");if(sel){sel.innerHTML='<option value="all">كل الأسواق</option>'+Object.entries(markets).map(([k,v])=>'<option value="'+k+'">'+esc(v.label)+'</option>').join("");sel.onchange=()=>loadTracker(currentPeriod)}$("#periodTabs button").forEach(b=>b.onclick=()=>loadTracker(b.dataset.period));safeClick($("#trackerRefresh"),()=>loadTracker(currentPeriod))}
function showPage(){let hash=location.hash.replace("#","")||"home";const valid=["home","trades","spot","futures","contracts","saudi","us","forex","scanner","tracker","news","account","admin"];if(!valid.includes(hash))hash="home";currentPage=hash;$(".page.active-page")?.classList.remove("active-page");$("#"+hash)?.classList.add("active-page");$$("#drawer a").forEach(a=>a.classList.toggle("active",a.dataset.section===hash));window.scrollTo(0,0);if(hash==="home")loadHome();if(hash==="tracker")loadTracker(currentPeriod);if(hash==="spot")renderMarketPage("spot",currentTf,"#spotList");if(hash==="futures")renderMarketPage("futures",currentTf,"#futuresList");if(hash==="contracts")renderMarketPage("contracts",currentTf,"#contractsList");if(hash==="saudi")renderMarketPage("saudi",currentTf,"#saudiList");if(hash==="us")renderMarketPage("us",currentTf,"#usList");if(hash==="forex")renderMarketPage("forex",currentTf,"#forexList");if(hash==="trades")loadTrades();if(hash==="scanner")runScan();if(hash==="news")loadNews();if(hash==="admin")loadAdmin()}
document.addEventListener("click",function(e){const a=e.target.closest("#drawer a[data-section]");if(!a)return;const section=a.dataset.section;if(!document.getElementById(section))return;e.preventDefault();location.hash="#"+section;closeMenu();$("#menu")?.setAttribute("aria-expanded","false")},{capture:true});
window.addEventListener("hashchange",showPage);
safeClick($("#login"),()=>{});$("#login").onsubmit=async e=>{e.preventDefault();try{await api("/api/auth/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email:$("#le").value,password:$("#lp").value})});$("#authMsg").textContent="تم تسجيل الدخول بنجاح ✅";await loadMe()}catch(x){$("#authMsg").textContent=x.message}};
$("#register").onsubmit=async e=>{e.preventDefault();try{await api("/api/auth/register",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email:$("#re").value,password:$("#rp").value})});$("#authMsg").textContent="تم إنشاء الحساب وتسجيل الدخول ✅";await loadMe()}catch(x){$("#authMsg").textContent=x.message}};
$("#logout").onclick=async()=>{await api("/api/auth/logout",{method:"POST"});location.hash="account";location.reload()};
async function boot(){try{markets=await api("/api/markets");setupMarketTabs();setupTradeTabs();setupScanner();setupTracker();await loadMe();showPage()}catch{$("#qTime").textContent="تعذر تشغيل المنصة"}}
/* Keep the interaction layer independent from API boot failures. */
window.addEventListener("error",e=>{console.error("UI error:",e.error||e.message)});
window.addEventListener("unhandledrejection",e=>{console.error("UI promise error:",e.reason)});
setTimeout(()=>boot(),0);
setInterval(()=>{if(currentPage==="home")loadHome();if(currentPage==="tracker")loadTracker(currentPeriod);if(currentPage==="news")loadNews();if(["spot","futures","contracts","saudi","us","forex"].includes(currentPage))renderMarketPage(currentPage,currentTf,"#"+currentPage+"List");if(currentPage==="trades")loadTrades();if(currentPage==="scanner")runScan()},180000);


/* Unified interaction layer — one click path for Android + desktop */
document.addEventListener("click",function(e){
  const t=e.target.closest("#menu,#closeMenu,#backdrop,#theme,#drawer a[data-section]");
  if(!t)return;
  if(t.id==="menu"){
    e.preventDefault();
    openMenu(e);
    return;
  }
  if(t.id==="closeMenu"||t.id==="backdrop"){
    e.preventDefault();
    closeMenu(e);
    return;
  }
  if(t.id==="theme"){
    e.preventDefault();
    toggleTheme(e);
    return;
  }
  const section=t.dataset.section;
  if(section && document.getElementById(section)){
    e.preventDefault();
    location.hash="#"+section;
    closeMenu();
  }
},{capture:true,passive:false});
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeMenu(e)});

try{setTheme(localStorage.getItem("theme")==="light"?"light":"dark")}catch{}
