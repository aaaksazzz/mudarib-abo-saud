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
function tradeCard(x){
  const s=x.signal||x;
  return '<article class="trade-card">'+
    '<div class="trade-top"><div><div class="symbol">'+esc(x.symbol)+'</div>'+
    '<div class="trade-meta">'+esc(x.market||"")+' · '+esc(x.timeframe||currentTf)+'</div></div>'+
    '<span class="side '+(s.side==="شراء"?"buy":"sell")+'">'+esc(s.side||"—")+'</span></div>'+
    '<div class="trade-values">'+
    '<div class="trade-value"><small>دخول</small><b>'+fmt(s.entry)+'</b></div>'+
    '<div class="trade-value"><small>TP1</small><b>'+fmt(s.tp1)+'</b></div>'+
    '<div class="trade-value"><small>TP2</small><b>'+fmt(s.tp2)+'</b></div>'+
    '<div class="trade-value"><small>TP3</small><b>'+fmt(s.tp3)+'</b></div>'+
    '<div class="trade-value"><small>وقف</small><b>'+fmt(s.sl)+'</b></div>'+
    '<div class="trade-value"><small>AI%</small><b class="ai">'+(s.ai==null?"—":fmt(s.ai)+"%")+'</b></div>'+
    '</div><div class="trade-footer"><span>'+esc(x.status||"فرصة")+'</span><span>⚡ تحديث مباشر</span></div></article>';
}
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
async function loadAdmin(){
  const loginBox=$("#adminLogin"),panel=$("#adminPanel");
  if(!loginBox||!panel)return;
  try{
    const me=await api("/api/auth/me");
    if(!me.authenticated || !me.user || me.user.role!=="admin"){loginBox.classList.remove("hidden");panel.classList.add("hidden");return}
    loginBox.classList.add("hidden");panel.classList.remove("hidden");
    const s=await api("/api/admin/summary");
    $("#admUsers").textContent=s.users||0;$("#admTrades").textContent=s.trades||0;$("#admOpen").textContent=s.open||0;$("#admClosed").textContent=s.closed||0;
    const [users,trades,news]=await Promise.all([api("/api/admin/users"),api("/api/admin/trades"),api("/api/news")]);
    const ms=$("#atMarket"); if(ms&&!ms.options.length)ms.innerHTML=Object.entries(markets).map(([k,v])=>'<option value="'+k+'">'+esc(v.label)+'</option>').join("");
    const ul=$("#adminUsersList"); if(ul)ul.innerHTML=users.length?users.map(u=>'<div class="admin-row"><div><b>'+esc(u.email)+'</b><small>#'+u.id+' · '+esc(u.role)+'</small></div><div><button class="mini-btn" data-role="'+u.id+'" data-newrole="'+(u.role==="admin"?"user":"admin")+'">'+(u.role==="admin"?"إلغاء المدير":"ترقية مدير")+'</button><button class="mini-btn danger-mini" data-deluser="'+u.id+'">حذف</button></div></div>').join(""):empty("لا يوجد مستخدمون");
    const tl=$("#adminTradesList"); if(tl)tl.innerHTML=trades.length?trades.map(t=>'<div class="admin-row"><div><b>'+esc(t.symbol)+' · '+esc(t.side)+'</b><small>'+esc(t.market)+' · '+esc(t.timeframe)+' · '+esc(t.status)+'</small></div><div><button class="mini-btn" data-pub="'+t.id+'">Telegram</button>'+(t.status==="open"?'<button class="mini-btn" data-close="'+t.id+'">إغلاق</button>':"")+'<button class="mini-btn danger-mini" data-deltrade="'+t.id+'">حذف</button></div></div>').join(""):empty("لا توجد صفقات");
    const nl=$("#adminNewsList"); if(nl)nl.innerHTML=news.length?news.map(n=>'<div class="admin-row"><div><b>'+esc(n.title)+'</b><small>'+esc(n.source||"النظام")+' · '+esc(n.created_at||"")+'</small></div><button class="mini-btn danger-mini" data-delnews="'+n.id+'">حذف</button></div>').join(""):empty("لا توجد أخبار");
    $$("#adminUsersList [data-role]").forEach(btn=>btn.onclick=async()=>{await api("/api/admin/users/"+btn.dataset.role+"/role",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({role:btn.dataset.newrole})});loadAdmin()});
    $$("#adminUsersList [data-deluser]").forEach(btn=>btn.onclick=async()=>{if(confirm("حذف المستخدم؟")){await api("/api/admin/users/"+btn.dataset.deluser,{method:"DELETE"});loadAdmin()}});
    $$("#adminTradesList [data-pub]").forEach(btn=>btn.onclick=async()=>{try{const x=await api("/api/admin/publish-trade/"+btn.dataset.pub,{method:"POST"});btn.textContent=x.ok?"تم الإرسال":"فشل الإرسال"}catch(e){btn.textContent=e.message}});
    $$("#adminTradesList [data-close]").forEach(btn=>btn.onclick=async()=>{await api("/api/admin/trades/"+btn.dataset.close+"/close",{method:"POST"});loadAdmin()});
    $$("#adminTradesList [data-deltrade]").forEach(btn=>btn.onclick=async()=>{if(confirm("حذف الصفقة؟")){await api("/api/admin/trades/"+btn.dataset.deltrade,{method:"DELETE"});loadAdmin()}});
    $$("#adminNewsList [data-delnews]").forEach(btn=>btn.onclick=async()=>{if(confirm("حذف الخبر؟")){await api("/api/admin/news/"+btn.dataset.delnews,{method:"DELETE"});loadAdmin()}});
  }catch(e){loginBox.classList.remove("hidden");panel.classList.add("hidden")}
}
function setupAdmin(){
  const f=$("#adminLoginForm");
  if(f)f.onsubmit=async e=>{e.preventDefault();try{await api("/api/auth/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email:$("#ae").value,password:$("#ap").value})});$("#adminMsg").textContent="تم الدخول، جاري فتح لوحة الإدارة…";await loadAdmin()}catch(x){$("#adminMsg").textContent=x.message}};
  const tf=$("#adminTradeForm");
  if(tf)tf.onsubmit=async e=>{e.preventDefault();try{
    const side=$("#atSide").value;
    const payload={market:$("#atMarket").value,symbol:$("#atSymbol").value,timeframe:$("#atTf").value,side,entry:+$("#atEntry").value,tp1:+$("#atTp1").value,tp2:+$("#atTp2").value,tp3:+$("#atTp3").value,sl:+$("#atSl").value,ai:+$("#atAi").value||0};
    await api("/api/admin/trades",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    $("#tradeAdminMsg").textContent="تمت إضافة الصفقة ✅";tf.reset();$("#atAi").value=0;await loadAdmin();
  }catch(x){$("#tradeAdminMsg").textContent=x.message}};
  const nf=$("#adminNewsForm");
  if(nf)nf.onsubmit=async e=>{e.preventDefault();try{await api("/api/admin/news",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({title:$("#newsTitle").value,source:$("#newsSource").value,body:$("#newsBody").value})});$("#newsTitle").value="";$("#newsBody").value="";await loadAdmin()}catch(x){$("#adminMsg").textContent=x.message}};
  const tg=$("#tg");
  if(tg)tg.onclick=async()=>{try{const x=await api("/api/admin/telegram-test",{method:"POST"});$("#tgmsg").textContent=x.ok?"تم إرسال الاختبار إلى Telegram ✅":x.message||"Telegram غير مضبوط"}catch(e){$("#tgmsg").textContent=e.message}};
}
async function loadHome(){try{const x=await api("/api/platform/summary");$("#qOpen").textContent=x.open;$("#qClosed").textContent=x.closed;$("#qWin").textContent=x.win_rate==null?"—":x.win_rate+"%";$("#qTime").textContent=new Date().toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"})}catch{$("#qOpen").textContent="—";$("#qClosed").textContent="—";$("#qWin").textContent="—";$("#qTime").textContent="تعذر الاتصال"}}
function setupMarketTabs(){const map={spot:"#spotFrames",futures:"#futuresFrames",contracts:"#contractsFrames",saudi:"#saudiFrames",us:"#usFrames",forex:"#forexFrames"};Object.entries(map).forEach(([m,id])=>frameButtons(id,currentTf,t=>{currentTf=t;renderMarketPage(m,t,"#"+m+"List")}))}
function setupTradeTabs(){const holder=$("#tradeMarketTabs");if(!holder)return;holder.innerHTML=Object.entries(markets).map(([k,v])=>'<button class="'+(k===currentMarket?"active":"")+'" data-market="'+k+'">'+v.label+"</button>").join("");$$("#tradeMarketTabs button").forEach(b=>b.onclick=()=>{currentMarket=b.dataset.market;setupTradeTabs();loadTrades()});frameButtons("#tradeFrames",currentTf,t=>{currentTf=t;loadTrades()})}
async function loadTrades(){const el=$("#tradeList");if(!el)return;el.innerHTML=empty("جاري تحميل الصفقات…");try{let d=await storedTrades(currentMarket,currentTf);if(!d.length)d=await scannerData(currentMarket,currentTf);el.innerHTML=d.length?d.map(tradeCard).join(""):empty("لا توجد صفقات لهذا السوق والفريم.")}catch{el.innerHTML=empty("تعذر جلب الصفقات.")}}
function setupScanner(){const sel=$("#scanMarket");if(!sel)return;sel.innerHTML=Object.entries(markets).map(([k,v])=>'<option value="'+k+'">'+v.label+"</option>").join("");frameButtons("#scanFrames",currentTf,t=>{currentTf=t;runScan()});$("#scanNow").onclick=runScan}
async function runScan(){const el=$("#scannerList");if(!el)return;const m=$("#scanMarket").value;el.innerHTML=empty("جاري الفحص…");try{const d=await scannerData(m,currentTf);el.innerHTML=d.length?d.map(tradeCard).join(""):empty("لا توجد فرصة مطابقة حالياً.")}catch{el.innerHTML=empty("تعذر الفحص حالياً.")}}
function setupTracker(){const sel=$("#trackerMarket");if(sel){sel.innerHTML='<option value="all">كل الأسواق</option>'+Object.entries(markets).map(([k,v])=>'<option value="'+k+'">'+esc(v.label)+'</option>').join("");sel.onchange=()=>loadTracker(currentPeriod)}$("#periodTabs button").forEach(b=>b.onclick=()=>loadTracker(b.dataset.period));safeClick($("#trackerRefresh"),()=>loadTracker(currentPeriod))}
function showPage(){let hash=location.hash.replace("#","")||"home";const valid=["home","trades","spot","futures","contracts","saudi","us","forex","scanner","tracker","news","account","admin"];if(!valid.includes(hash))hash="home";currentPage=hash;$(".page.active-page")?.classList.remove("active-page");$("#"+hash)?.classList.add("active-page");$$("#drawer a").forEach(a=>a.classList.toggle("active",a.dataset.section===hash));window.scrollTo(0,0);if(hash==="home")loadHome();if(hash==="tracker")loadTracker(currentPeriod);if(hash==="spot")renderMarketPage("spot",currentTf,"#spotList");if(hash==="futures")renderMarketPage("futures",currentTf,"#futuresList");if(hash==="contracts")renderMarketPage("contracts",currentTf,"#contractsList");if(hash==="saudi")renderMarketPage("saudi",currentTf,"#saudiList");if(hash==="us")renderMarketPage("us",currentTf,"#usList");if(hash==="forex")renderMarketPage("forex",currentTf,"#forexList");if(hash==="trades")loadTrades();if(hash==="scanner")runScan();if(hash==="news")loadNews();if(hash==="admin")loadAdmin()}
window.addEventListener("hashchange",showPage);
const loginForm=$("#login");
if(loginForm) loginForm.onsubmit=async e=>{e.preventDefault();try{await api("/api/auth/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email:$("#le").value,password:$("#lp").value})});$("#authMsg").textContent="تم تسجيل الدخول بنجاح ✅";await loadMe()}catch(x){$("#authMsg").textContent=x.message}};
const registerForm=$("#register");
if(registerForm) registerForm.onsubmit=async e=>{e.preventDefault();try{await api("/api/auth/register",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email:$("#re").value,password:$("#rp").value})});$("#authMsg").textContent="تم إنشاء الحساب وتسجيل الدخول ✅";await loadMe()}catch(x){$("#authMsg").textContent=x.message}};
const logoutBtn=$("#logout");
if(logoutBtn) logoutBtn.onclick=async()=>{await api("/api/auth/logout",{method:"POST"});location.hash="account";location.reload()};
const DEFAULT_MARKETS={
  spot:{label:"سبوت"},futures:{label:"فيوتشر"},contracts:{label:"العقود"},
  saudi:{label:"السعودي"},us:{label:"أمريكي"},forex:{label:"فوركس وذهب"}
};
async function boot(){
  markets={...DEFAULT_MARKETS};
  try{
    const remote=await api("/api/markets");
    if(remote && typeof remote==="object" && Object.keys(remote).length) markets=remote;
  }catch(e){
    console.warn("markets API unavailable; using local market map",e);
  }
  try{setupMarketTabs()}catch(e){console.error("market tabs",e)}
  try{setupTradeTabs()}catch(e){console.error("trade tabs",e)}
  try{setupScanner()}catch(e){console.error("scanner setup",e)}
  try{setupTracker()}catch(e){console.error("tracker setup",e)}
  try{await loadMe()}catch(e){console.error("auth bootstrap",e)}
  try{showPage()}catch(e){console.error("page bootstrap",e)}
}
/* Keep the interaction layer independent from API boot failures. */
window.addEventListener("error",e=>{console.error("UI error:",e.error||e.message)});
window.addEventListener("unhandledrejection",e=>{console.error("UI promise error:",e.reason)});
setTimeout(()=>boot(),0);
setInterval(()=>{if(document.hidden)return;if(currentPage==="home")loadHome();if(currentPage==="news")loadNews();if(["spot","futures","contracts","saudi","us","forex"].includes(currentPage))renderMarketPage(currentPage,currentTf,"#"+currentPage+"List");if(currentPage==="trades")loadTrades();if(currentPage==="scanner")runScan()},600000);
setInterval(()=>{if(!document.hidden&&currentPage==="tracker")loadTracker(currentPeriod)},120000);


/* FINAL TOUCH INTERACTION — mobile-safe pointer + click fallback */
function initTouchUI(){
const menu=$("#menu"), close=$("#closeMenu"), backdrop=$("#backdrop"), theme=$("#theme");
const makeInteractive=el=>{if(!el)return;el.style.pointerEvents="auto";el.style.touchAction="manipulation";el.style.cursor="pointer";};
[menu,close,backdrop,theme].forEach(makeInteractive);
$$("#drawer a, main a, button, select").forEach(makeInteractive);
let lastAction=0;
const runOnce=(fn,e)=>{const now=Date.now();if(now-lastAction<120)return;lastAction=now;fn(e);};
if(menu){menu.onclick=e=>runOnce(openMenu,e);menu.onpointerup=e=>{if(e.pointerType==="touch")runOnce(openMenu,e);};}
if(close){close.onclick=e=>runOnce(closeMenu,e);close.onpointerup=e=>{if(e.pointerType==="touch")runOnce(closeMenu,e);};}
if(backdrop){backdrop.onclick=e=>runOnce(closeMenu,e);backdrop.onpointerup=e=>{if(e.pointerType==="touch")runOnce(closeMenu,e);};}
if(theme){theme.onclick=e=>runOnce(toggleTheme,e);theme.onpointerup=e=>{if(e.pointerType==="touch")runOnce(toggleTheme,e);};}
$('#drawer a[data-section], main a[href^="#"]').forEach(a=>{
const navigate=e=>{const section=a.dataset.section||(a.getAttribute("href")||"").slice(1);if(!section||!document.getElementById(section))return;e.preventDefault();e.stopPropagation();runOnce(()=>{if(location.hash==="#"+section)showPage();else location.hash="#"+section;closeMenu();},e);};
a.onclick=navigate;a.onpointerup=e=>{if(e.pointerType==="touch")navigate(e);};
});
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeMenu(e);});
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",initTouchUI,{once:true});else initTouchUI();
try{setTheme(localStorage.getItem("theme")==="light"?"light":"dark")}catch{}