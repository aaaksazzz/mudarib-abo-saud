const $=s=>document.querySelector(s);
let market="spot",timeframe="15m",busy=false,pending=false,timer=null;
const fmt=n=>Number(n).toLocaleString("en-US",{maximumFractionDigits:8});
const compact=n=>{n=Number(n)||0;if(n>=1e9)return (n/1e9).toFixed(2)+"B";if(n>=1e6)return (n/1e6).toFixed(2)+"M";if(n>=1e3)return (n/1e3).toFixed(1)+"K";return fmt(n)};
const pct=n=>(Number(n)>=0?"+":"")+Number(n).toFixed(2)+"%";
const safe=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function get(url,timeout=18000){
 const controller=new AbortController(),id=setTimeout(()=>controller.abort(),timeout);
 try{
  const r=await fetch(url,{cache:"no-store",signal:controller.signal,headers:{"Accept":"application/json"}});
  let j={};try{j=await r.json()}catch{}
  if(!r.ok)throw Error(j.error||j.message||("تعذر جلب البيانات ("+r.status+")"));
  return j;
 }catch(e){if(e.name==="AbortError")throw Error("تأخر مصدر البيانات؛ حاول التحديث بعد قليل.");throw e}
 finally{clearTimeout(id)}
}
function renderMovers(rows){
 const root=$("#movers");
 if(!rows||!rows.length){root.innerHTML='<div class="empty">لا تتوفر حركة أصول كافية للعرض.</div>';return}
 root.innerHTML=rows.map(x=>'<article class="mover"><div class="mover-head"><b class="mover-symbol">'+safe(x.symbol)+'</b><span class="mover-side">'+(x.change24h>=0?"الأعلى صعودًا":"الأعلى هبوطًا")+'</span></div><b class="mover-price">'+fmt(x.price)+'</b><div class="mover-change '+(x.change24h>=0?"up":"down")+'">'+pct(x.change24h)+'</div><small class="mover-volume">حجم 24س '+compact(x.volume)+' USDT</small></article>').join("");
}
function renderSignals(rows){
 const root=$("#cards");
 if(!rows||!rows.length){root.innerHTML='<div class="empty">لا توجد فرصة اجتازت شروط الاتجاه وتوافق 4 ساعات واليومي حاليًا. سيستمر الفحص مع التحديث القادم.</div>';return}
 root.innerHTML=rows.map((x,i)=>{
  const side=x.side==="BUY"?1:-1;
  const tp1=pct(side*(x.tp1/x.entry-1)*100),tp2=pct(side*(x.tp2/x.entry-1)*100),tp3=pct(side*(x.tp3/x.entry-1)*100);
  const rank=i===0?"gold":i===1?"silver":"bronze";
  return '<article class="trade"><div class="trade-head"><div class="trade-title"><span class="rank '+rank+'">'+(i+1)+'</span><b>'+safe(x.symbol)+'</b></div><span class="tag '+(x.side==="BUY"?"buy":"sell")+'">'+(x.side==="BUY"?"شراء":"بيع")+'</span></div><div class="trade-meta-top"><span>الإطار <b>'+safe(x.timeframe)+'</b></span><span>تغير 24س <b class="'+(x.change24h>=0?"up":"down")+'">'+pct(x.change24h)+'</b></span></div><div class="entry"><small>سعر الدخول</small><strong>'+fmt(x.entry)+'</strong></div><div class="levels"><div><small>TP1 · '+tp1+'</small><b>'+fmt(x.tp1)+'</b></div><div><small>TP2 · '+tp2+'</small><b>'+fmt(x.tp2)+'</b></div><div><small>TP3 · '+tp3+'</small><b>'+fmt(x.tp3)+'</b></div><div class="stop"><small>وقف الخسارة</small><b>'+fmt(x.stop_loss)+'</b></div></div><div class="trade-stats"><div class="trade-stat"><small>المخاطرة</small><b>'+x.risk_percent+'%</b></div><div class="trade-stat"><small>جودة الشروط</small><b>'+x.quality_score+'/100</b></div><div class="trade-stat"><small>RSI · حجم</small><b>'+x.rsi+' · '+compact(x.volume)+'</b></div></div></article>';
 }).join("");
}
function renderOpen(rows){
 const root=$("#openTrades");$("#openCount").textContent=(rows?.length||0)+" مفتوحة";
 if(!rows||!rows.length){root.innerHTML='<div class="empty">لا توجد صفقات مفتوحة محفوظة لهذا السوق.</div>';return}
 const target=(name,value,hit)=>'<div class="'+(hit?"hit":"")+'"><small>'+name+(hit?" ✓":"")+'</small><b>'+fmt(value)+'</b></div>';
 root.innerHTML=rows.map(x=>'<article class="open-row"><div><b>'+safe(x.symbol)+'</b><small>'+safe(x.timeframe)+' · '+(x.side==="BUY"?"شراء":"بيع")+'</small></div><div><small>الدخول</small><b>'+fmt(x.entry)+'</b></div>'+target("TP1",x.tp1,x.tp1_hit)+target("TP2",x.tp2,x.tp2_hit)+target("TP3",x.tp3,x.tp3_hit)+'<div class="stop"><small>وقف الخسارة</small><b>'+fmt(x.stop_loss)+'</b></div><span class="tag">مفتوحة</span></article>').join("");
}
function renderClosed(rows){
 const closed=(rows||[]).filter(x=>x.status!=="OPEN").slice(0,12);
 $("#historyCount").textContent=closed.length+" مغلقة";
 const root=$("#closedTrades");
 if(!closed.length){root.innerHTML='<div class="empty">لا توجد نتائج مغلقة مسجلة بعد.</div>';return}
 root.innerHTML=closed.map(x=>'<article class="history-row"><div><b>'+safe(x.symbol)+'</b><small>'+safe(x.timeframe)+' · '+(x.side==="BUY"?"شراء":"بيع")+'</small></div><div><small>الدخول</small><b>'+fmt(x.entry)+'</b></div><div><small>النتيجة</small><b class="history-status '+(x.status==="TP3"?"tp":"sl")+'">'+(x.status==="TP3"?"وصل TP3":"وقف الخسارة")+'</b></div><div><small>تاريخ الإغلاق</small><b>'+new Date((x.closed_at||x.updated_at)*1000).toLocaleDateString("ar-SA")+'</b></div><div><small>الإطار</small><b>'+safe(x.timeframe)+'</b></div></article>').join("");
}
async function loadMarketStatuses(){
 try{
  const d=await get("/api/markets",8000);
  const states=new Map((d.markets||[]).map(x=>[x.id,x]));
  document.querySelectorAll("[data-market]").forEach(b=>{
   const item=states.get(b.dataset.market);if(!item)return;
   const live=item.status==="live";b.disabled=!live;
   const small=b.querySelector("small");if(small)small.textContent=live?(item.provider||"متصل"):"غير متاح";
   b.title=live?"مصدر البيانات متصل":"لا يوجد مصدر بيانات موثوق مربوط حاليًا";
   const dot=b.querySelector(".tab-state");if(dot)dot.style.display=live?"block":"none";
  });
 }catch(e){$("#health").textContent="تعذر فحص الأسواق";$("#health").className="bad"}
}
async function load(){
 if(busy){pending=true;return}
 busy=true;pending=false;
 const refresh=$("#refresh");refresh.disabled=true;refresh.innerHTML="<span>↻</span> جارٍ التحديث";
 $("#health").textContent="جارٍ التحديث";$("#scanState").textContent="يفحص السوق";$("#scanState").className="";
 try{
  const requestedMarket=market,requestedFrame=timeframe;
  const [d,t]=await Promise.all([
   get("/api/market/"+requestedMarket+"?timeframe="+encodeURIComponent(requestedFrame)),
   get("/api/trades?market="+encodeURIComponent(requestedMarket),10000).catch(()=>({items:[]})) 
  ]);
  if(requestedMarket!==market||requestedFrame!==timeframe){pending=true;return}
  $("#direction").textContent=d.direction_ar;$("#direction").className="direction-value "+(d.direction==="BUY"?"up":d.direction==="SELL"?"down":"neutral");
  $("#up").textContent=d.up;$("#down").textContent=d.down;$("#flat").textContent=d.flat??0;$("#total").textContent=d.total;
  const total=Math.max(1,Number(d.total)||0);
  $("#upBar").style.width=(d.up/total*100)+"%";$("#downBar").style.width=(d.down/total*100)+"%";$("#flatBar").style.width=((d.flat||0)/total*100)+"%";
  $("#updated").textContent=new Date(d.updated*1000).toLocaleTimeString("ar-SA");
  $("#source").textContent="مصدر البيانات: "+d.source+" · "+d.strategy;
  $("#sourceShort").textContent=d.source||"بيانات عامة";
  $("#scanState").textContent="اكتمل";$("#scanState").className="state-good";
  renderMovers(d.movers);renderSignals(d.signals);renderOpen(d.open_trades);renderClosed(t.items);
  $("#health").textContent="متصل";$("#health").className="ok";
 }catch(e){
  $("#cards").innerHTML='<div class="empty">'+safe(e.message)+'</div>';
  $("#scanState").textContent="تعذر الفحص";$("#scanState").className="down";
  $("#health").textContent="غير متصل";$("#health").className="bad";
 }finally{
  busy=false;refresh.disabled=false;refresh.innerHTML="<span>↻</span> تحديث البيانات";
  if(pending){pending=false;load()}
 }
}
$("#markets").addEventListener("click",e=>{const b=e.target.closest("[data-market]");if(!b||b.disabled)return;market=b.dataset.market;document.querySelectorAll("[data-market]").forEach(x=>x.classList.toggle("active",x===b));load()});
$("#timeframes").addEventListener("click",e=>{const b=e.target.closest("[data-tf]");if(!b)return;timeframe=b.dataset.tf;document.querySelectorAll("[data-tf]").forEach(x=>x.classList.toggle("active",x===b));load()});
$("#refresh").addEventListener("click",load);
document.addEventListener("visibilitychange",()=>{if(!document.hidden)load()});
function tick(){ $("#clock").textContent=new Date().toLocaleTimeString("en-GB",{hour12:false}); }
tick();setInterval(tick,1000);
loadMarketStatuses().finally(load);
timer=setInterval(()=>{if(!document.hidden)load()},30000);
