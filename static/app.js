const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
let markets={},currentMarket="spot",currentTf="15m",currentPage="home",currentPeriod="all";
const frames=[["5m","5د"],["15m","15د"],["30m","30د"],["1h","1س"],["4h","4س"],["1d","يومي"],["1w","أسبوعي"],["1M","شهري"]];
const esc=v=>String(v??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[m]));
const fmt=v=>v==null||v===""?"—":Number(v).toLocaleString("en-US",{maximumFractionDigits:8});
async function api(url,opt={},timeoutMs=30000){const c=new AbortController(),t=setTimeout(()=>c.abort(),timeoutMs);try{const r=await fetch(url,{credentials:"include",cache:"no-store",signal:c.signal,...opt});let d={};try{d=await r.json()}catch{}if(!r.ok)throw Error(d.detail||"تعذر الطلب");return d}finally{clearTimeout(t)}}
function setTheme(){document.body.classList.toggle("light",localStorage.getItem("theme")==="light")}
function toggleTheme(){localStorage.setItem("theme",document.body.classList.contains("light")?"dark":"light");setTheme()}
function closeMenu(){document.body.classList.remove("menu-open");$("#drawer")?.classList.remove("open");$("#backdrop")?.classList.remove("show")}
function openMenu(){document.body.classList.add("menu-open");$("#drawer")?.classList.add("open");$("#backdrop")?.classList.add("show")}
function dataList(d){return Array.isArray(d)?d:Array.isArray(d?.items)?d.items:Array.isArray(d?.data)?d.data:Array.isArray(d?.results)?d.results:[]}
function frameButtons(id,selected,onPick){const el=$(id);if(!el)return;el.innerHTML=frames.map(([v,t])=>`<button type="button" class="${v===selected?"active":""}" data-tf="${v}" aria-pressed="${v===selected?"true":"false"}">${t}</button>`).join("");if(el._frameHandler)el.removeEventListener("click",el._frameHandler);el._frameHandler=e=>{const b=e.target.closest("button[data-tf]");if(!b||!el.contains(b))return;e.preventDefault();e.stopPropagation();const tf=b.dataset.tf;el.querySelectorAll("button[data-tf]").forEach(x=>{const active=x.dataset.tf===tf;x.classList.toggle("active",active);x.setAttribute("aria-pressed",active?"true":"false")});onPick(tf)};el.addEventListener("click",el._frameHandler)}
function aiValue(x){const s=x?.signal||x||{};const n=Number(s.ai??x?.ai);return Number.isFinite(n)?n:-1}
function aiTier(ai){if(ai>=90)return["strong","قوية جدًا"];if(ai>=80)return["good","قوية"];if(ai>=70)return["valid","جيدة"];if(ai>=60)return["mid","متوسطة"];return["low","ضعيفة"]}
function sortByAI(items){return [...items].sort((a,b)=>aiValue(b)-aiValue(a))}
function card(x,rank){const s=x.signal||x,side=s.side||"—",buy=side==="شراء",ai=aiValue(x),tier=aiTier(ai),lev=Number(s.leverage??x.leverage??(x.market==="futures"?5:0));const canExecute=["spot","futures"].includes(x.market||"");return `<article class="trade-card ai-${tier[0]}"><div class="trade-top"><div><div class="symbol-row"><div><div class="symbol">${esc(x.symbol)}</div><div class="trade-meta">${esc(x.market||"")} · ${esc(x.timeframe||currentTf)}</div></div><span class="ai-rank">${rank===1?"👑":rank===2?"🥈":rank===3?"🥉":"#"+rank}</span></div></div><span class="side ${buy?"buy":"sell"}">${esc(side)}</span></div><div class="ai-banner"><span>AI ${ai<0?"—":fmt(ai)+"%"}</span><b>${esc(tier[1])}</b></div><div class="trade-values"><div><small>دخول</small><b>${fmt(s.entry)}</b></div><div><small>TP1</small><b>${fmt(s.tp1)}</b></div><div><small>TP2</small><b>${fmt(s.tp2)}</b></div><div><small>TP3</small><b>${fmt(s.tp3)}</b></div><div><small>SL</small><b>${fmt(s.sl)}</b></div><div><small>AI%</small><b class="ai">${ai<0?"—":fmt(ai)+"%"}</b></div></div><div class="trade-footer"><span>${esc(x.status||"فرصة")}</span><span>${(s.reverse_applied===true||Number(s.reverse_applied)===1)?"🔄 عكس الاستراتيجية · 🟢 مفعّل":"🔄 عكس الاستراتيجية · 🔴 غير مفعّل"}</span>${x.market==="futures"&&lev>0?`<span>⚡ ${lev}×</span>`:""}</div>${canExecute?`<button type="button" class="btn primary execute-trade" data-market="${esc(x.market)}" data-symbol="${esc(x.symbol)}" data-side="${esc(side)}" data-tf="${esc(x.timeframe||currentTf)}" data-tp1="${esc(s.tp1)}" data-tp2="${esc(s.tp2)}" data-tp3="${esc(s.tp3)}" data-sl="${esc(s.sl)}">⚡ تنفيذ على Binance</button>`:""}</article>`}
function empty(t){return `<div class="empty-state">⌁<h3>${esc(t)}</h3><p>جرّب فريماً آخر أو أعد الفحص.</p></div>`}
async function stored(m,tf){return dataList(await api(`/api/section/${encodeURIComponent(m)}/trades?timeframe=${encodeURIComponent(tf)}&limit=100`))}
async function scan(m,tf){return dataList(await api(`/api/section/${encodeURIComponent(m)}/scanner?timeframe=${encodeURIComponent(tf)}`))}
async function renderMarket(m,tf){const el=$("#"+m+"List");if(!el)return;el.innerHTML=empty("جاري تحميل الفرص");try{let d=await stored(m,tf);if(!d.length)d=await scan(m,tf);d=sortByAI(d);el.innerHTML=d.length?d.map((x,i)=>card(x,i+1)).join(""):empty("لا توجد إشارة حالياً")}catch(e){console.error(e);el.innerHTML=empty("تعذر جلب البيانات")}}
function setupBinance(){
  const box=$("#binanceBox"),orders=$("#userOrdersBox");
  if(!box)return;
  $("#binanceForm").onsubmit=async e=>{e.preventDefault();const msg=$("#binanceMsg");msg.textContent="جاري التحقق والربط…";try{await api("/api/binance/connect",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({api_key:$("#binanceKey").value,api_secret:$("#binanceSecret").value})});$("#binanceKey").value="";$("#binanceSecret").value="";msg.textContent="تم ربط Binance بنجاح ✅";loadBinanceStatus()}catch(x){msg.textContent=x.message}};
  $("#binanceDisconnect").onclick=async()=>{if(!confirm("فصل حساب Binance من الموقع؟"))return;try{await api("/api/binance/connect",{method:"DELETE"});$("#binanceMsg").textContent="تم فصل Binance";loadBinanceStatus()}catch(x){$("#binanceMsg").textContent=x.message}};
  $("#userOrdersRefresh").onclick=loadUserOrders;
}
async function loadBinanceStatus(){
  const box=$("#binanceBox"),orders=$("#userOrdersBox");if(!box)return;
  try{const me=await api("/api/auth/me");const logged=!!me.authenticated;box.classList.toggle("hidden",!logged);orders.classList.toggle("hidden",!logged);if(!logged)return;
    const s=await api("/api/binance/status");$("#binanceStatus").textContent=s.connected?"● متصل":"غير مربوط";$("#binanceStatus").className=s.connected?"connected":"not-connected";loadUserOrders();
  }catch{}
}
async function loadUserOrders(){
  const el=$("#userOrdersList");if(!el)return;
  try{const d=await api("/api/binance/orders");el.innerHTML=d.length?d.map(o=>`<article class="tracker-card user-order-card"><div class="tracker-card-head"><div><b>${esc(o.symbol)}</b><small>${esc(o.market)} · ${esc(o.timeframe)}</small></div><span class="${o.status==="CLOSED"?"order-closed":"order-open"}">${esc(o.status)}</span></div><div class="tracker-price"><div><small>الدخول</small><b>${fmt(o.entry_price)}</b></div><div><small>السعر</small><b>${fmt(o.price)}</b></div><div><small>PnL</small><b>${fmt(o.pnl)}%</b></div></div><div class="tracker-targets"><span>TP1 <b>${fmt(o.tp1)}</b></span><span>TP2 <b>${fmt(o.tp2)}</b></span><span>TP3 <b>${fmt(o.tp3)}</b></span><span>SL <b>${fmt(o.sl)}</b></span></div><small>${esc(o.side)} · ${o.leverage}× · ${esc(o.created_at||"")}</small>${o.status!=="CLOSED"?`<button type="button" class="btn danger close-user-order" data-order-id="${o.id}">إغلاق الصفقة</button>`:""}</article>`).join(""):empty("لا توجد صفقات Binance خاصة بك");el.querySelectorAll(".close-user-order").forEach(b=>b.onclick=async()=>{if(!confirm("إغلاق الصفقة الآن بسعر السوق؟"))return;try{await api("/api/binance/orders/"+b.dataset.orderId+"/close",{method:"POST"});loadUserOrders()}catch(x){alert(x.message)}})}catch(x){el.innerHTML=empty(x.message)}
}
async function executeTradeButton(b){
  try{
    const me=await api("/api/auth/me");if(!me.authenticated){location.hash="login";setTimeout(()=>{const m=$("#loginMsg");if(m)m.textContent="سجّل الدخول أولاً لتنفيذ الصفقة.";},50);return}
    const st=await api("/api/binance/status");if(!st.connected){location.hash="binance";setTimeout(()=>{const m=$("#binanceMsg");if(m)m.textContent="اربط Binance أولاً لتنفيذ الصفقة.";},50);return}
    const amount=Number(prompt("كم USDT تريد استخدامه؟","10"));if(!Number.isFinite(amount)||amount<=0)return;
    let leverage=1;if(b.dataset.market==="futures"){leverage=Number(prompt("الرافعة؟","5"));if(!Number.isFinite(leverage)||leverage<1)return}
    if(!confirm("تأكيد تنفيذ الصفقة الحقيقية على Binance؟"))return;
    b.disabled=true;b.textContent="جاري التنفيذ…";
    const x=await api("/api/binance/execute",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({market:b.dataset.market,symbol:b.dataset.symbol,side:b.dataset.side,amount,leverage,timeframe:b.dataset.tf,tp1:Number(b.dataset.tp1)||null,tp2:Number(b.dataset.tp2)||null,tp3:Number(b.dataset.tp3)||null,sl:Number(b.dataset.sl)||null})});
    b.textContent="تم التنفيذ ✅";setTimeout(()=>{b.textContent="⚡ تنفيذ على Binance"},1800);location.hash="account";setTimeout(loadUserOrders,250);
  }catch(x){b.disabled=false;b.textContent="⚡ تنفيذ على Binance";alert(x.message)}
}
document.addEventListener("click",e=>{const b=e.target.closest(".execute-trade");if(b){e.preventDefault();executeTradeButton(b)}});

function setupSubscriptions(){document.querySelectorAll(".subscription-btn").forEach(b=>b.onclick=()=>{const plan=b.dataset.plan;location.hash="account";setTimeout(()=>{const msg=document.querySelector("#authMsg");if(msg)msg.textContent="اخترت باقة "+plan+" — سجّل الدخول أو أنشئ حساباً لإكمال الاشتراك.";},50)})}
function setupLeverage(){const box=document.querySelector(".leverage-options");if(!box)return;const out=document.querySelector("#selectedLeverage");box.addEventListener("click",e=>{const b=e.target.closest("[data-leverage]");if(!b)return;box.querySelectorAll("[data-leverage]").forEach(x=>x.classList.remove("active"));b.classList.add("active");if(out)out.textContent=b.dataset.leverage+"×"})}
function setupMarkets(){const map={spot:"#spotFrames",futures:"#futuresFrames",contracts:"#contractsFrames",saudi:"#saudiFrames",us:"#usFrames",forex:"#forexFrames"};Object.entries(map).forEach(([m,id])=>frameButtons(id,currentTf,t=>{currentTf=t;renderMarket(m,t)}))}
function setupTrades(){
  const mbox=$("#tradeMarketTabs");
  if(!mbox)return;
  mbox.innerHTML=Object.entries(markets).map(([k,v])=>`<button type="button" class="${k===currentMarket?"active":""}" data-market-tab="${k}">${esc(v.label)}</button>`).join("");
  if(mbox._marketHandler)mbox.removeEventListener("click",mbox._marketHandler);
  mbox._marketHandler=e=>{
    const b=e.target.closest("button[data-market-tab]");
    if(!b)return;
    e.preventDefault();e.stopPropagation();
    currentMarket=b.dataset.market;
    mbox.querySelectorAll("button[data-market-tab]").forEach(x=>x.classList.toggle("active",x===b));
    loadTrades();
  };
  mbox.addEventListener("click",mbox._marketHandler);
  frameButtons("#tradeFrames",currentTf,t=>{currentTf=t;loadTrades()});
}
async function loadTrades(){const el=$("#tradeList");if(!el)return;el.innerHTML=empty("جاري التحميل");try{let d=await stored(currentMarket,currentTf);if(!d.length)d=await scan(currentMarket,currentTf);d=sortByAI(d);el.innerHTML=d.length?d.map((x,i)=>card(x,i+1)).join(""):empty("لا توجد إشارة حالياً")}catch{el.innerHTML=empty("تعذر جلب الصفقات")}}
let scanRunning=false,scanSeq=0;
function setupScanner(){
  const sel=$("#scanMarket"); if(!sel)return;
  sel.innerHTML=Object.entries(markets).map(([k,v])=>`<option value="${k}">${esc(v.label)}</option>`).join("");
  frameButtons("#scanFrames",currentTf,t=>{currentTf=t;runScan()});
  const btn=$("#scanNow"); if(btn)btn.onclick=runScan;
}
function renderScannerResults(d,stamp){
  const el=$("#scannerList"); if(!el)return;
  d=sortByAI(dataList(d));
  el.innerHTML=d.length?d.map((x,i)=>card(x,i+1)).join(""):`<div class="scan-live-empty"><b>لا توجد فرصة مطابقة الآن</b><small>المحرك يعمل ويعيد الفحص تلقائياً.</small></div>`;
  const old=$("#scanLiveStamp"); if(old)old.textContent=stamp||"آخر تحديث الآن";
}
async function runScan(){
  const el=$("#scannerList"),m=$("#scanMarket")?.value||"spot",tf=currentTf||"15m"; if(!el)return;
  if(scanRunning)return;
  scanRunning=true; const mySeq=++scanSeq;
  const btn=$("#scanNow"); if(btn){btn.disabled=true;btn.textContent="⏳ فحص مباشر…"}
  const started=new Date();
  el.innerHTML=`<div class="scan-live-loading"><span class="scan-pulse"></span><div><b>الفحص المباشر يعمل الآن</b><small>يتم تحديث النتائج من المحرك بدون إيقاف الصفحة.</small></div></div>`;
  try{
    let d=[];
    try{d=await stored(m,tf)}catch{}
    if(mySeq!==scanSeq)return;
    if(d.length){renderScannerResults(d,"النتائج الحالية · "+started.toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"}))}
    const fresh=await scan(m,tf);
    if(mySeq!==scanSeq)return;
    renderScannerResults(fresh,"آخر فحص · "+new Date().toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"}));
  }catch(e){
    console.error("scanner",e);
    if(mySeq===scanSeq){
      try{
        const cached=await stored(m,tf);
        if(cached.length)renderScannerResults(cached,"نتائج محفوظة · المحرك مستمر");
        else el.innerHTML=`<div class="scan-live-empty"><b>تعذر جلب الفحص الآن</b><small>المحرك مستمر — اضغط فحص الآن للمحاولة مرة أخرى.</small></div>`;
      }catch{el.innerHTML=empty("تعذر عرض نتائج الفحص")}
    }
  }finally{
    if(mySeq===scanSeq){scanRunning=false;if(btn){btn.disabled=false;btn.textContent="🔎 فحص الآن"}}
  }
}
let trackerAutoStarted=false,trackerTimer=null;
function setupTracker(){
  const page=$("#tracker"); if(!page)return;
  page.dataset.resultsOnly="0";
  const marketsHtml=Object.entries(markets).map(([k,v])=>'<option value="'+esc(k)+'">'+esc(v.label||k)+'</option>').join("");
  const tfs=frames.map(x=>'<option value="'+x[0]+'" '+(x[0]==="15m"?"selected":"")+'>'+x[1]+'</option>').join("");
  page.innerHTML='<div class="page-head tracker-head"><small>LIVE TRACKER · SERVER SIDE</small><h1>متابع الصفقات</h1><p>المتابع يستمر من السيرفر حتى لو سكرت الموقع أو المتصفح.</p></div>'+
    '<div class="tracker-toolbar"><div class="tracker-filters"><label>السوق<select id="trackerMarket">'+marketsHtml+'</select></label><label>الفريم<select id="trackerTf">'+tfs+'</select></label></div>'+
    '<div class="tracker-actions"><button id="trackerRefresh" class="btn primary" type="button">🔄 تحديث</button><button id="trackerAuto" class="btn ghost" type="button" aria-pressed="true">🟢 تلقائي</button></div></div>'+
    '<div id="trackerStats" class="metrics tracker-metrics"></div>'+
    '<div class="tracker-summary"><div id="trackerStatus" class="tracker-status">🟢 المتابع يعمل من السيرفر</div><div id="trackerUpdated" class="tracker-updated">—</div></div>'+
    '<div class="tracker-sections"><section><div class="section-head"><div><small>OPEN</small><h2>الصفقات المفتوحة</h2></div><span id="trackerOpenCount">0</span></div><div id="trackerOpenList" class="tracker-list"></div></section>'+
    '<section><div class="section-head"><div><small>CLOSED</small><h2>سجل النتائج</h2></div><span id="trackerClosedCount">0</span></div><div id="trackerClosedList" class="tracker-list"></div></section></div>';
  $("#trackerMarket").onchange=loadLiveTracker;
  $("#trackerTf").onchange=loadLiveTracker;
  $("#trackerRefresh").onclick=loadLiveTracker;
  const auto=$("#trackerAuto");
  if(trackerTimer)clearInterval(trackerTimer);
  auto.onclick=()=>{trackerAutoStarted=!trackerAutoStarted;auto.setAttribute("aria-pressed",trackerAutoStarted?"true":"false");auto.textContent=trackerAutoStarted?"🟢 تلقائي":"⏸️ متوقف";if(trackerAutoStarted){loadLiveTracker();trackerTimer=setInterval(()=>{if(location.hash.slice(1)==="tracker")loadLiveTracker()},30000)}else if(trackerTimer){clearInterval(trackerTimer);trackerTimer=null}};
  trackerAutoStarted=true;
  auto.textContent="🟢 تلقائي";
  loadLiveTracker();
  trackerTimer=setInterval(()=>{if(location.hash.slice(1)==="tracker")loadLiveTracker()},30000);
}
function trackerCard(t,i){
  const open=t.status==="open";
  const result=Number(t.pnl||0);
  const rank=i<3?["👑","🥈","🥉"][i]:"#"+(i+1);
  return '<article class="tracker-card '+(open?"is-open":"is-closed")+'"><div class="tracker-card-head"><div><b>'+rank+' '+esc(t.symbol)+'</b><small>'+esc(t.market)+' · '+esc(t.timeframe)+' · '+esc(t.created_at||"")+'</small></div><span class="'+(open?"tracker-open":"tracker-closed")+'">'+(open?"🟢 مفتوحة":"⚪ مغلقة")+'</span></div>'+
    '<div class="tracker-price"><div><small>الدخول</small><b>'+fmt(t.entry)+'</b></div><div><small>السعر/النتيجة</small><b class="'+(result>0?"ai":result<0?"tracker-loss":"")+'">'+(open?"متابعة":" "+fmt(result)+"%")+'</b></div><div><small>AI%</small><b class="ai">'+fmt(t.ai)+'%</b></div></div>'+
    '<div class="tracker-targets"><span>TP1 <b>'+fmt(t.tp1)+'</b></span><span>TP2 <b>'+fmt(t.tp2)+'</b></span><span>TP3 <b>'+fmt(t.tp3)+'</b></span><span>SL <b>'+fmt(t.sl)+'</b></span></div>'+
    '<div class="tracker-card-foot"><span>'+esc(t.side||"—")+'</span><span>'+(t.reverse_applied===true||Number(t.reverse_applied)===1?"🔄 عكس مفعّل":"🔄 عكس غير مفعّل")+'</span></div></article>';
}
async function loadLiveTracker(){
  const openList=$("#trackerOpenList"),closedList=$("#trackerClosedList"),stats=$("#trackerStats"),status=$("#trackerStatus"),updated=$("#trackerUpdated");
  if(!openList)return;
  const m=$("#trackerMarket")?.value||"spot",tf=$("#trackerTf")?.value||"15m";
  try{
    const [d,s]=await Promise.all([
      api("/api/section/"+encodeURIComponent(m)+"/trades?timeframe="+encodeURIComponent(tf)+"&limit=100"),
      api("/api/section/"+encodeURIComponent(m)+"/stats?period=all&timeframe="+encodeURIComponent(tf))
    ]);
    const a=dataList(d), open=a.filter(x=>x.status==="open"), closed=a.filter(x=>x.status!=="open");
    stats.innerHTML=[["مفتوحة",s.open??open.length],["مغلقة",s.closed??closed.length],["فوز",s.wins??"—"],["خسارة",s.losses??"—"],["نجاح",s.win_rate==null?"—":s.win_rate+"%"],["PnL",s.pnl==null?"—":s.pnl+"%"]].map(x=>'<article><small>'+x[0]+'</small><b>'+x[1]+'</b></article>').join("");
    $("#trackerOpenCount").textContent=open.length; $("#trackerClosedCount").textContent=closed.length;
    openList.innerHTML=open.length?open.map((t,i)=>trackerCard(t,i)).join(""):empty("لا توجد صفقات مفتوحة");
    closedList.innerHTML=closed.length?closed.map((t,i)=>trackerCard(t,i)).join(""):empty("لا توجد نتائج مغلقة");
    status.textContent="🟢 المتابع يعمل من السيرفر";
    updated.textContent="آخر تحديث · "+new Date().toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit",second:"2-digit"});
  }catch(e){
    status.textContent="🔴 تعذر تحديث المتابع";
    updated.textContent="حاول التحديث مرة أخرى";
    openList.innerHTML=empty("تعذر جلب الصفقات");
    closedList.innerHTML="";
  }
}
function btNum(v,d=0){const n=Number(v);return Number.isFinite(n)?n:d}
function fmtVol(v){const n=Number(v);if(!Number.isFinite(n)||n<=0)return "—";if(n>=1e9)return (n/1e9).toFixed(2)+"B";if(n>=1e6)return (n/1e6).toFixed(2)+"M";if(n>=1e3)return (n/1e3).toFixed(1)+"K";return fmt(n)}
async function runHistoricalBacktest(){
  if(runHistoricalBacktest.running)return;
  const result=$("#backtestResult"),status=$("#btStatus"),bar=$("#btProgressBar");
  if(!result)return;
  runHistoricalBacktest.running=true;
  const market=$("#btMarket")?.value||"spot",tf=$("#btTf")?.value||"15m",days=$("#btDays")?.value||"30",symbol=($("#btSymbol")?.value||"").trim().toUpperCase();
  if(status)status.textContent="● المحرك يعمل";
  if(bar)bar.style.width="18%";
  result.innerHTML='<div class="bt-running panel"><div class="bt-spinner"></div><h3>جاري تشغيل الاختبار…</h3><p>تحميل البيانات التاريخية ثم تنفيذ Walk-forward شمعة بشمعة. قد يستغرق الاختبار عدة دقائق.</p><small>لا تغلق الصفحة أثناء التشغيل.</small></div>';
  try{
    const q=`/api/backtest?market=${encodeURIComponent(market)}&timeframe=${encodeURIComponent(tf)}&days=${encodeURIComponent(days)}&symbol=${encodeURIComponent(symbol)}`;
    const x=await api(q,{},600000);
    if(bar)bar.style.width="100%";
    const rows=(x.per_symbol||[]).map((z,i)=>{
      const wr=z.win_rate==null?null:btNum(z.win_rate);
      const err=z.error?'<div class="bt-error">⚠ '+esc(z.error)+'</div>':"";
      return `<article class="bt-symbol-card">
        <div class="bt-symbol-head"><div><span class="bt-rank">${i<3?["👑","🥈","🥉"][i]:"#"+(i+1)}</span><b>${esc(z.symbol)}</b></div><strong class="${wr!=null&&wr>=50?"bt-positive":"bt-neutral"}">${wr==null?"—":wr+"%"}</strong></div>
        <div class="bt-mini-grid">
          <div><small>الحجم اليومي</small><b>${fmtVol(z.daily_volume_usdt)}</b></div>
          <div><small>الشموع</small><b>${btNum(z.candles)}</b></div>
          <div><small>الاختبارات</small><b>${btNum(z.trades)}</b></div>
          <div><small>فوز</small><b class="bt-positive">${btNum(z.wins)}</b></div>
          <div><small>خسارة</small><b class="bt-negative">${btNum(z.losses)}</b></div>
          <div><small>صافي R</small><b class="${btNum(z.r)>=0?"bt-positive":"bt-negative"}">${btNum(z.r).toFixed(2)}R</b></div>
        </div>${err}</article>`;
    }).join("");
    const win=btNum(x.wins),loss=btNum(x.losses),trades=btNum(x.trades),wr=x.win_rate==null?null:btNum(x.win_rate),r=btNum(x.r),avg=x.avg_r==null?null:btNum(x.avg_r),pf=x.profit_factor==null?null:btNum(x.profit_factor);
    if(status)status.textContent="✓ اكتمل الاختبار";
    result.innerHTML=`
      <div class="bt-hero panel">
        <div><small>RESULTS · ${esc(tf)} · ${esc(days)} DAYS</small><h2>نتيجة الاختبار</h2><p>${esc(x.method||"Walk-forward historical backtest")}</p></div>
        <span class="bt-live-dot">● مكتمل</span>
      </div>
      <div class="bt-stats">
        <article><small>إجمالي الاختبارات</small><b>${trades}</b></article>
        <article><small>نسبة الفوز</small><b class="${wr!=null&&wr>=50?"bt-positive":"bt-neutral"}">${wr==null?"—":wr+"%"}</b></article>
        <article><small>الفوز</small><b class="bt-positive">${win}</b></article>
        <article><small>الخسارة</small><b class="bt-negative">${loss}</b></article>
        <article><small>صافي R</small><b class="${r>=0?"bt-positive":"bt-negative"}">${r.toFixed(2)}R</b></article>
        <article><small>متوسط R</small><b>${avg==null?"—":avg.toFixed(3)+"R"}</b></article>
        <article><small>Profit Factor</small><b>${pf==null?"—":pf.toFixed(2)}</b></article>
        <article><small>العملات</small><b>${btNum(x.symbols)}</b></article>
      </div>
      <div class="bt-disclosure panel"><b>كيف حُسبت النتيجة؟</b><span>• الإشارة تستخدم الشموع المتاحة حتى لحظة الدخول فقط.</span><span>• لا يوجد Look-ahead أو كتابة نتائج إلى سجل الصفقات.</span><span>• إذا لمس TP وSL في نفس الشمعة تُحسب بشكل محافظ كخسارة.</span><span>• R مبني على مسافة الدخول إلى وقف الخسارة.</span></div>
      <div class="bt-list-head"><h3>تفاصيل الرموز</h3><small>${btNum(x.symbols)} رمز · ${btNum(x.candles)} شمعة</small></div>
      <div class="bt-symbols">${rows||'<div class="empty">لا توجد نتائج تاريخية.</div>'}</div>`;
  }catch(e){
    if(status)status.textContent="⚠ تعذر الاختبار";
    if(bar)bar.style.width="0%";
    result.innerHTML=`<div class="bt-fail panel"><b>⚠ تعذر تشغيل الاختبار</b><p>${esc(e.message||"انتهت مهلة الاتصال أو تعذر جلب البيانات.")}</p><small>إذا كان الاختبار كبيراً جرّب 7 أو 30 يوم أو رمزاً واحداً.</small></div>`;
  }finally{runHistoricalBacktest.running=false}
}
async function loadHome(){try{const x=await api("/api/platform/summary");$("#qOpen").textContent=x.open??"—";$("#qClosed").textContent=x.closed??"—";$("#qWin").textContent=x.win_rate==null?"—":x.win_rate+"%";$("#qTime").textContent=new Date().toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"})}catch{}}
async function loadNews(){const el=$("#newsList");try{const d=dataList(await api("/api/news"));el.innerHTML=d.length?d.map(n=>`<article class="news-card"><small>${esc(n.source||"NEWS")}</small><h3>${esc(n.title)}</h3><p>${esc(n.body||"")}</p><time>${esc(n.created_at||"")}</time></article>`).join(""):empty("لا توجد أخبار")}catch{el.innerHTML=empty("تعذر جلب الأخبار")}}
async function loadMe(){try{const x=await api("/api/auth/me");$("#meState").textContent=x.authenticated?x.user.email+" · "+x.user.role:"غير مسجل";$("#logout").classList.toggle("hidden",!x.authenticated)}catch{}}
function showPage(){const path=location.pathname.replace(/\/+$/,"")||"/";const pathPage=({"/":"home","/spot":"spot","/futures":"futures","/contracts":"contracts","/scanner":"scanner","/saudi":"saudi","/us":"us","/forex":"forex","/trades":"trades","/tracker":"tracker","/news":"news","/blog":"blog","/account":"account","/login":"login","/register":"register","/admin":"admin","/binance":"binance","/subscriptions":"binance-subscriptions"})[path];let p=location.hash.slice(1)||pathPage||"home";if(!document.getElementById(p))p="home";currentPage=p;$$(".page").forEach(x=>x.classList.toggle("active-page",x.id===p));$$("#drawer nav a").forEach(a=>a.classList.toggle("active",a.dataset.section===p));closeMenu();window.scrollTo(0,0);if(p==="home")loadHome();if(p==="trades")loadTrades();if(["spot","futures","contracts","saudi","us","forex"].includes(p))renderMarket(p,currentTf);if(p==="scanner")runScan();if(p==="tracker")setupTracker();if(p==="news")loadNews();if(p==="admin")loadAdmin();if(["account","login","register"].includes(p))loadMe();if(p==="binance")loadBinanceStatus();}
async function loadAdmin(){const panel=$("#adminPanel"),login=$("#adminLogin");const err=$("#adminMsg");try{const me=await api("/api/auth/me");if(!me.authenticated||me.user.role!=="admin"){login.classList.remove("hidden");panel.classList.add("hidden");return}login.classList.add("hidden");panel.classList.remove("hidden");const s=await api("/api/admin/summary");$("#admUsers").textContent=s.users||0;$("#admTrades").textContent=s.trades||0;$("#admOpen").textContent=s.open||0;$("#admClosed").textContent=s.closed||0;const [u,t,n]=await Promise.all([api("/api/admin/users"),api("/api/admin/trades"),api("/api/news")]);$("#atMarket").innerHTML=Object.entries(markets).map(([k,v])=>`<option value="${k}">${esc(v.label)}</option>`).join("");$("#adminUsersList").innerHTML=u.map(x=>`<div class="admin-row"><div><b>${esc(x.email)}</b><small>${esc(x.role)}</small></div><button class="mini-btn" data-role="${x.id}" data-newrole="${x.role==="admin"?"user":"admin"}">تغيير الدور</button><button class="mini-btn danger-mini" data-deluser="${x.id}">حذف</button></div>`).join("");$("#adminTradesList").innerHTML=t.map(x=>`<div class="admin-row"><div><b>${esc(x.symbol)} · ${esc(x.side)}</b><small>${esc(x.market)} · ${esc(x.timeframe)} · ${esc(x.status)}</small></div><button class="mini-btn" data-pub="${x.id}">Telegram</button>${x.status==="open"?`<button class="mini-btn" data-close="${x.id}">إغلاق</button>`:""}<button class="mini-btn danger-mini" data-deltrade="${x.id}">حذف</button></div>`).join("");$("#adminNewsList").innerHTML=n.map(x=>`<div class="admin-row"><div><b>${esc(x.title)}</b></div><button class="mini-btn danger-mini" data-delnews="${x.id}">حذف</button></div>`).join("");adminActions()}catch(e){if(err)err.textContent=e.message||"تعذر تحميل لوحة الإدارة حالياً";panel.classList.remove("hidden");login.classList.add("hidden")}}
function adminActions(){$$("[data-role]").forEach(b=>b.onclick=async()=>{await api("/api/admin/users/"+b.dataset.role+"/role",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({role:b.dataset.newrole})});loadAdmin()});$$("[data-deluser]").forEach(b=>b.onclick=async()=>{if(confirm("حذف المستخدم؟")){await api("/api/admin/users/"+b.dataset.deluser,{method:"DELETE"});loadAdmin()}});$$("[data-pub]").forEach(b=>b.onclick=async()=>{try{const x=await api("/api/admin/publish-trade/"+b.dataset.pub,{method:"POST"});b.textContent=x.ok?"تم":"فشل"}catch(e){b.textContent=e.message}});$$("[data-close]").forEach(b=>b.onclick=async()=>{await api("/api/admin/trades/"+b.dataset.close+"/close",{method:"POST"});loadAdmin()});$$("[data-deltrade]").forEach(b=>b.onclick=async()=>{if(confirm("حذف الصفقة؟")){await api("/api/admin/trades/"+b.dataset.deltrade,{method:"DELETE"});loadAdmin()}});$$("[data-delnews]").forEach(b=>b.onclick=async()=>{if(confirm("حذف الخبر؟")){await api("/api/admin/news/"+b.dataset.delnews,{method:"DELETE"});loadAdmin()}})}
function bindForms(){
  const loginForm=$("#loginForm");
  if(loginForm)loginForm.onsubmit=async e=>{
    e.preventDefault();
    const msg=$("#loginMsg");
    try{
      const x=await api("/api/auth/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email:$("#le").value,password:$("#lp").value})});
      msg.textContent="تم الدخول بنجاح ✅";
      if(x.role==="admin")location.hash="admin";else location.hash="account";
      loadMe();
    }catch(x){msg.textContent=x.message}
  };
  const registerForm=$("#registerForm");
  if(registerForm)registerForm.onsubmit=async e=>{
    e.preventDefault();
    const msg=$("#registerMsg");
    try{
      await api("/api/auth/register",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email:$("#re").value,password:$("#rp").value})});
      msg.textContent="تم إنشاء الحساب بنجاح ✅";
      setTimeout(()=>location.hash="login",350);
    }catch(x){msg.textContent=x.message}
  };
  $("#logout").onclick=async()=>{await api("/api/auth/logout",{method:"POST"});location.hash="login";location.reload()};
  $("#adminLoginForm").onsubmit=async e=>{
    e.preventDefault();
    try{
      await api("/api/auth/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email:$("#ae").value,password:$("#ap").value})});
      $("#adminMsg").textContent="تم دخول الإدارة ✅";
      loadAdmin();
    }catch(x){$("#adminMsg").textContent=x.message}
  };
  $("#adminTradeForm").onsubmit=async e=>{e.preventDefault();try{await api("/api/admin/trades",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({market:$("#atMarket").value,symbol:$("#atSymbol").value,timeframe:$("#atTf").value,side:$("#atSide").value,entry:+$("#atEntry").value,tp1:+$("#atTp1").value,tp2:+$("#atTp2").value,tp3:+$("#atTp3").value,sl:+$("#atSl").value,ai:+$("#atAi").value||0})});$("#tradeAdminMsg").textContent="تمت الإضافة ✅";e.target.reset();loadAdmin()}catch(x){$("#tradeAdminMsg").textContent=x.message}};
  $("#tg").onclick=async()=>{try{const x=await api("/api/admin/telegram-test",{method:"POST"});$("#tgmsg").textContent=x.ok?"تم الإرسال ✅":x.message}catch(x){$("#tgmsg").textContent=x.message}}
}
const defaults={spot:{label:"السبوت"},futures:{label:"الفيوتشر"},contracts:{label:"العقود"},saudi:{label:"السعودي"},us:{label:"الأمريكي"},forex:{label:"فوركس وذهب"}};
async function boot(){setTheme();markets=defaults;try{const x=await api("/api/markets");if(x&&Object.keys(x).length)markets=x}catch{}setupMarkets();setupLeverage();setupSubscriptions();setupBinance();setupTrades();setupScanner();setupTracker();bindForms();await loadMe();showPage()}
document.addEventListener("click",e=>{const el=e.target.closest("button,a");if(!el)return;if(el.id==="menu"){e.preventDefault();openMenu()}else if(el.id==="closeMenu"||el.id==="backdrop"){e.preventDefault();closeMenu()}else if(el.id==="theme"){e.preventDefault();toggleTheme()}},false);
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeMenu()});
window.addEventListener("hashchange",showPage);
window.addEventListener("error",e=>console.error("UI",e.error||e.message));
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot,{once:true});else boot();
setInterval(()=>{if(document.hidden)return;if(currentPage==="home")loadHome();if(currentPage==="news")loadNews();if(["spot","futures","contracts","saudi","us","forex"].includes(currentPage))renderMarket(currentPage,currentTf);if(currentPage==="trades")loadTrades();if(currentPage==="scanner")runScan();},600000);
