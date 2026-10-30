const $=s=>document.querySelector(s);
let market="spot",timeframe="15m",busy=false,timer=null;
const names={spot:"Binance Spot",futures:"Binance Futures",alpha:"Binance Alpha",saudi:"السوق السعودي",us:"الأسهم الأمريكية",contracts:"العقود الأمريكية",forex:"الفوركس والذهب"};
const fmt=n=>Number(n).toLocaleString("en-US",{maximumFractionDigits:8});
const safe=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function get(url){const r=await fetch(url,{cache:"no-store"});let j={};try{j=await r.json()}catch{}if(!r.ok)throw Error(j.error||j.message||"تعذر جلب البيانات");return j}
function renderSignals(rows){
 const root=$("#cards");
 if(!rows||!rows.length){root.innerHTML='<div class="empty">لا توجد فرصة اجتازت شروط الاتجاه وتوافق 4 ساعات واليومي حاليًا.</div>';return}
 root.innerHTML=rows.map((x,i)=>'<article class="trade"><div class="trade-head"><b>'+(i+1)+'. '+safe(x.symbol)+'</b><span class="tag '+(x.side==="BUY"?"buy":"sell")+'">'+(x.side==="BUY"?"شراء":"بيع")+'</span></div><div class="entry"><small>الدخول</small><strong>'+fmt(x.entry)+'</strong></div><div class="levels"><div><small>TP1</small><b>'+fmt(x.tp1)+'</b></div><div><small>TP2</small><b>'+fmt(x.tp2)+'</b></div><div><small>TP3</small><b>'+fmt(x.tp3)+'</b></div><div class="stop"><small>وقف الخسارة</small><b>'+fmt(x.stop_loss)+'</b></div></div><div class="meta"><span>المخاطرة للوقف</span><b>'+x.risk_percent+'%</b></div><div class="meta"><span>جودة الشروط</span><b>'+x.quality_score+'/100</b></div><div class="meta"><span>RSI · '+x.timeframe+'</span><b>'+x.rsi+'</b></div></article>').join("");
}
function renderOpen(rows){
 const root=$("#openTrades");
 if(!rows||!rows.length){root.innerHTML='<div class="empty">لا توجد صفقات مفتوحة محفوظة لهذا السوق.</div>';return}
 root.innerHTML=rows.map(x=>'<div class="open-row"><div><b>'+safe(x.symbol)+'</b><small>'+x.timeframe+' · '+(x.side==="BUY"?"شراء":"بيع")+'</small></div><div><small>الدخول</small><b>'+fmt(x.entry)+'</b></div><div><small>الأهداف</small><b>'+(x.tp1_hit?"TP1 ✓":"TP1 —")+' / '+(x.tp2_hit?"TP2 ✓":"TP2 —")+'</b></div><span class="tag">'+x.status+'</span></div>').join("");
}
async function load(){
 if(busy)return;busy=true;$("#health").textContent="● جارٍ التحديث";
 try{
  const d=await get('/api/market/'+market+'?timeframe='+timeframe);
  $("#direction").textContent=d.direction_ar;$("#direction").className=d.direction==="BUY"?"up":d.direction==="SELL"?"down":"neutral";
  $("#up").textContent=d.up;$("#down").textContent=d.down;$("#total").textContent=d.total;
  $("#updated").textContent="آخر تحديث "+new Date(d.updated*1000).toLocaleTimeString("ar-SA");
  $("#source").textContent=d.source+" · "+d.strategy;renderSignals(d.signals);renderOpen(d.open_trades);
  $("#health").textContent="● متصل";$("#health").className="health ok";
 }catch(e){$("#cards").innerHTML='<div class="empty">'+safe(e.message)+'</div>';$("#health").textContent="● غير متصل";$("#health").className="health bad"}
 finally{busy=false}
}
$("#markets").addEventListener("click",e=>{const b=e.target.closest("[data-market]");if(!b||b.disabled)return;market=b.dataset.market;document.querySelectorAll("[data-market]").forEach(x=>x.classList.toggle("active",x===b));load()});
$("#timeframes").addEventListener("click",e=>{const b=e.target.closest("[data-tf]");if(!b)return;timeframe=b.dataset.tf;document.querySelectorAll("[data-tf]").forEach(x=>x.classList.toggle("active",x===b));load()});
$("#refresh").addEventListener("click",load);
document.addEventListener("visibilitychange",()=>{if(!document.hidden)load()});
load();timer=setInterval(()=>{if(!document.hidden)load()},60000);
