const $=s=>document.querySelector(s);
const markets={
 futures:{name:"العقود الآجلة",english:"BINANCE USD-M FUTURES",symbol:"₿",desc:"اتجاه سوق العقود الآجلة والصفقات المؤكدة"},
 spot:{name:"السوق الفوري",english:"BINANCE SPOT",symbol:"◈",desc:"اتجاه السوق الفوري والصفقات المؤكدة"},
 alpha:{name:"باينانس ألفا",english:"BINANCE ALPHA",symbol:"✳",desc:"اتجاه أصول Binance Alpha والصفقات المؤكدة"},
 "us-stocks":{name:"الأسهم الأمريكية",english:"UNITED STATES EQUITIES",symbol:"▥",desc:"اتجاه الأسهم الأمريكية والصفقات المؤكدة"},
 "us-contracts":{name:"العقود الأمريكية",english:"US FUTURES & CONTRACTS",symbol:"⌗",desc:"اتجاه العقود الأمريكية والصفقات المؤكدة"},
 saudi:{name:"السوق السعودي",english:"SAUDI EXCHANGE · TASI",symbol:"◉",desc:"اتجاه السوق السعودي والصفقات المؤكدة"},
 forex:{name:"الفوركس والذهب",english:"FOREX & PRECIOUS METALS",symbol:"⇄",desc:"اتجاه الفوركس والذهب والصفقات المؤكدة"}
};
let currentMarket=null,scanBusy=new Set(),refreshTimer=null;
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt=v=>v===null||v===undefined||v===""||!Number.isFinite(Number(v))?"—":Number(v).toLocaleString("en-US",{maximumFractionDigits:8});
const pct=(a,b,side)=>{a=Number(a);b=Number(b);return a>0&&b>0?(side==="BUY"?(b/a-1):(a/b-1))*100:null};
function routeMarket(){const m=location.pathname.match(/^\/market\/([^/]+)\/?$/);return m&&markets[m[1]]?m[1]:null}
async function getJSON(url){const r=await fetch(url,{cache:"no-store",credentials:"same-origin"});let d={};try{d=await r.json()}catch{}if(!r.ok)throw Error(d.error||"تعذر جلب البيانات");return d}
function sideLabel(side,direction){return side==="BUY"?"صاعد":side==="SELL"?"هابط":direction||"غير متاح"}
function marketCard(id){const m=markets[id];return '<a class="market-card" href="/market/'+id+'"><div class="market-card-top"><span class="market-symbol">'+m.symbol+'</span><span class="market-status">فتح القسم</span></div><h3>'+m.name+'</h3><small>'+m.english+'</small><div class="market-direction"><b class="neutral">عرض الصفقات</b><small>اتجاه السوق داخل القسم</small></div></a>'}
function loadHome(){const root=$("#markets");root.innerHTML=Object.keys(markets).map(id=>marketCard(id)).join("")}
async function loadVisitorStats(){
 const total=$("#visitorTotal"),today=$("#visitorToday"),updated=$("#visitorUpdated");
 if(!total||!today)return;
 try{
  const data=await getJSON("/api/visitors/stats");
  total.textContent=fmt(data.total_unique);
  today.textContent=fmt(data.today_unique);
  updated.textContent="آخر تحديث: "+new Date(data.updated_at).toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"});
 }catch(_){
  total.textContent="—";today.textContent="—";
  updated.textContent="تعذر تحميل الإحصائيات حالياً";
 }
}
async function loadSnapshot(m){try{const s=await getJSON("/api/markets/"+m+"/snapshot");if(currentMarket!==m)return;const side=s.side;$("#marketDirection").textContent=sideLabel(side,s.direction);$("#marketDirection").className=side==="BUY"?"up":side==="SELL"?"down":"neutral";$("#snapshotUpdated").textContent=s.updated_at?new Date(s.updated_at).toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"}):"—";$("#snapshotStatus").textContent=s.stale?"قديمة":"متاحة";$("#providerState").textContent=s.stale?"آخر بيانات محفوظة":"بيانات السوق متاحة";$("#directionBasis").textContent=s.direction_basis||"اتجاه السوق العام";const total=Math.max(0,Number(s.total)||0),upCount=Math.max(0,Number(s.up)||0),downCount=Math.max(0,Number(s.down)||0);const up=Math.min(100,Math.max(0,Number(s.up_pct)||0)),down=Math.min(100,Math.max(0,Number(s.down_pct)||0));$("#breadthUp").textContent=fmt(upCount);$("#breadthDown").textContent=fmt(downCount);$("#breadthTotal").textContent=fmt(total)+" أصل";$("#breadthUpPct").textContent=fmt(up)+"%";$("#breadthDownPct").textContent=fmt(down)+"%";$("#breadthUpBar").style.width=up+"%";$("#breadthDownBar").style.width=down+"%";$("#marketBreadth").hidden=!(total>0);}catch(e){if(currentMarket===m){$("#providerState").textContent="مصدر البيانات غير متاح";$("#marketDirection").textContent="غير متاح";$("#snapshotStatus").textContent="متعذرة"}}}
function signalCard(x){const buy=x.side==="BUY",loss=pct(x.entry,x.stop,x.side),gain=pct(x.entry,x.tp3,x.side);return '<article class="signal '+(buy?"buy":"sell")+'"><div class="signal-head"><div><span class="tag">'+(buy?"شراء · صاعد":"بيع · هابط")+'</span><h2>'+esc(x.symbol)+'</h2></div><div class="score">'+fmt(x.score)+'<small>قوة الإشارة / 100</small></div></div><div class="meta"><span>الفريم: <b>'+esc(x.timeframe||"15m")+'</b></span></div><div class="levels"><div><small>الدخول</small><b>'+fmt(x.entry)+'</b></div><div class="loss"><small>وقف الخسارة</small><b>'+fmt(x.stop)+'</b></div><div class="profit"><small>TP1 · القمة/القاع السابق</small><b>'+fmt(x.tp1)+'</b></div><div class="profit"><small>TP2 · امتداد 2R</small><b>'+fmt(x.tp2)+'</b></div><div class="profit"><small>TP3 · امتداد 3R</small><b>'+fmt(x.tp3)+'</b></div><div><small>العائد/المخاطرة</small><b>'+fmt(x.reward_risk)+'R</b></div></div><div class="potential"><span class="gain">ربح محتمل: '+(gain===null?"—":"+"+fmt(gain)+"%")+'</span><span class="risk">مخاطرة: '+(loss===null?"—":fmt(Math.abs(loss))+"%")+'</span></div></article>'}
const FRAME_LIST=[["15m","15 دقيقة"],["1h","ساعة"],["4h","4 ساعات"],["1d","يومي"],["1w","أسبوعي"],["1M","شهري"]];
let selectedFrame="all";
function renderSignals(signals){
 const filters=[["all","كل الفريمات"],...FRAME_LIST];
 $("#timeframeFilters").innerHTML=filters.map(([id,label])=>'<button type="button" class="timeframe-chip '+(selectedFrame===id?"active":"") +'" data-frame="'+id+'">'+label+'</button>').join("");
 const paint=frame=>{
  selectedFrame=frame;
  document.querySelectorAll("[data-frame]").forEach(b=>b.classList.toggle("active",b.dataset.frame===frame));
  const shown=frame==="all"?FRAME_LIST:FRAME_LIST.filter(x=>x[0]===frame);
  $("#results").innerHTML=shown.map(([id,label])=>{
   const rows=signals.filter(x=>x.timeframe===id);
   return '<section class="timeframe-group"><div class="timeframe-group-head"><b>'+label+'</b><small>'+rows.length+' صفقة</small></div>'+(rows.length?rows.map(signalCard).join(""):'<div class="frame-empty">لا توجد صفقة مؤكدة على هذا الفريم حالياً.</div>')+'</section>';
  }).join("");
 };
 document.querySelectorAll("[data-frame]").forEach(b=>b.addEventListener("click",()=>paint(b.dataset.frame)));
 paint(selectedFrame);
}
function showEmpty(message){$("#results").innerHTML='<div class="empty-state"><b>لا توجد صفقات مؤكدة حالياً</b><br>'+esc(message)+'</div>'}
async function runScan(m){if(scanBusy.has(m)||currentMarket!==m)return;scanBusy.add(m);$("#signalCount").textContent="جارٍ الفحص";$("#results").innerHTML='<div class="loading-state">يتم فحص السوق بحثاً عن صفقات مستوفية للشروط…</div>';try{const d=await getJSON("/api/intelligence/scan?market="+encodeURIComponent(m));if(currentMarket!==m)return;const signals=Array.isArray(d.signals)?d.signals:[];$("#signalCount").textContent=fmt(signals.length)+" صفقة";renderSignals(signals);}catch(e){if(currentMarket===m){$("#signalCount").textContent="تعذر الفحص";showEmpty(e.message)}}finally{scanBusy.delete(m)}}
async function openMarket(m){currentMarket=m;selectedFrame="all";$("#homeView").hidden=true;$("#marketView").hidden=false;$("#topTitle").textContent=markets[m].name;$("#marketEnglish").textContent=markets[m].english;$("#marketTitle").textContent=markets[m].name;$("#marketDesc").textContent=markets[m].desc;document.querySelectorAll("[data-market]").forEach(a=>a.classList.toggle("active",a.dataset.market===m));$("#providerState").textContent="جاري التحقق من البيانات";$("#marketDirection").textContent="جارٍ التحميل";$("#snapshotUpdated").textContent="—";$("#snapshotStatus").textContent="—";$("#results").innerHTML='<div class="loading-state">يتم تجهيز السوق…</div>';await loadSnapshot(m);await runScan(m);if(refreshTimer)clearInterval(refreshTimer);refreshTimer=setInterval(async()=>{if(currentMarket===m&&document.visibilityState==="visible"){await loadSnapshot(m);await runScan(m)}},15*60*1000)}
function openHome(){currentMarket=null;if(refreshTimer)clearInterval(refreshTimer);$("#marketView").hidden=true;$("#homeView").hidden=false;$("#topTitle").textContent="مركز الأسواق الذكي";document.querySelectorAll("[data-market]").forEach(a=>a.classList.remove("active"));loadHome();loadVisitorStats()}
function init(){const m=routeMarket();$("#date").textContent=new Intl.DateTimeFormat("ar-SA",{dateStyle:"medium"}).format(new Date());$("#theme").addEventListener("click",()=>document.body.classList.toggle("light"));$("#menuToggle").addEventListener("click",()=>document.body.classList.toggle("menu-open"));$("#scrim").addEventListener("click",()=>document.body.classList.remove("menu-open"));document.querySelectorAll("[data-market]").forEach(a=>a.addEventListener("click",e=>{if(e.metaKey||e.ctrlKey)return;e.preventDefault();history.pushState({},"",a.href);document.body.classList.remove("menu-open");openMarket(a.dataset.market)}));document.querySelector("[data-home]").addEventListener("click",e=>{if(e.metaKey||e.ctrlKey)return;e.preventDefault();history.pushState({},"","/");document.body.classList.remove("menu-open");openHome()});window.addEventListener("popstate",()=>{const next=routeMarket();next?openMarket(next):openHome()});if(m)openMarket(m);else openHome()}
document.addEventListener("DOMContentLoaded",init);