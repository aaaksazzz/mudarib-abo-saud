const $=s=>document.querySelector(s);
const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
const fmt=n=>Number(n||0).toLocaleString("en-US",{maximumFractionDigits:8});
function tradeCard(x,i=0){
 const side=x.side==="شراء"?"buy":"sell";
 return '<article class="trade-card"><div class="trade-top"><b>'+(i+1)+' · '+esc(x.symbol)+'</b><span class="'+side+'">'+(side==="buy"?"🟢 شراء":"🔴 بيع")+'</span></div><div class="trade-meta"><span>'+esc(x.market)+'</span><span>⏱ '+esc(x.timeframe)+'</span><strong>AI '+fmt(x.confidence)+'%</strong></div><div class="levels"><div><small>دخول</small><b>'+fmt(x.entry)+'</b></div><div><small>هدف 1</small><b>'+fmt(x.tp1)+'</b></div><div><small>هدف 2</small><b>'+fmt(x.tp2)+'</b></div><div><small>هدف 3</small><b>'+fmt(x.tp3)+'</b></div><div><small>وقف</small><b>'+fmt(x.stop)+'</b></div></div></article>';
}
async function json(url){
 const r=await fetch(url,{cache:"no-store",headers:{"Accept":"application/json"}});
 if(!r.ok) throw new Error("HTTP "+r.status);
 return r.json();
}
async function loadTrades(){
 const box=$("#trades"); if(!box)return;
 const p=new URLSearchParams(location.search);
 const market=p.get("market")||"spot", tf=p.get("timeframe")||"15د";
 try{
  const d=await json("/api/trades?market="+encodeURIComponent(market)+"&timeframe="+encodeURIComponent(tf));
  box.innerHTML=d.items?.length?d.items.map(tradeCard).join(""):'<div class="empty">لا توجد صفقات متاحة حالياً لهذا السوق والفريم.</div>';
 }catch(e){box.innerHTML='<div class="empty">تعذر جلب البيانات الآن. أعد المحاولة بعد قليل.</div>';}
}
async function loadScanner(){
 const box=$("#scanner"); if(!box)return;
 try{const d=await json("/api/scanner?timeframe=15د");box.innerHTML=d.items?.length?d.items.map(tradeCard).join(""):'<div class="empty">لا توجد فرص حالياً.</div>';}
 catch(e){box.innerHTML='<div class="empty">تعذر تشغيل الماسح الآن.</div>';}
}
async function loadTracker(){
 const periods=$("#tracker-periods"), summary=$("#tracker-summary"), history=$("#history");
 if(!periods&&!history)return;
 try{
  const d=await json("/api/tracker");
  const order=["اليوم","الأسبوع","1 ساعة","4 ساعات","الشهر","كل السجل"];
  if(periods) periods.innerHTML=order.map(k=>{const x=d.periods[k]||{};return '<div class="tracker-stat"><small>'+k+'</small><b class="'+(x.pnl_pct>=0?'buy':'sell')+'">'+(x.pnl_pct>=0?'+':'')+fmt(x.pnl_pct)+'%</b><span>ربح '+x.wins+' · خسارة '+x.losses+'</span><em>نسبة الفوز '+fmt(x.winrate)+'%</em></div>';}).join("");
  const all=d.periods?.["كل السجل"]||{};
  if(summary) summary.innerHTML='<div><b>'+all.trades+'</b><span>إجمالي الصفقات</span></div><div><b class="buy">'+all.wins+'</b><span>رابحة</span></div><div><b class="sell">'+all.losses+'</b><span>خاسرة</span></div><div><b class="'+(all.pnl_pct>=0?'buy':'sell')+'">'+(all.pnl_pct>=0?'+':'')+fmt(all.pnl_pct)+'%</b><span>صافي الربح</span></div>';
  if(history) history.innerHTML=d.ranking?.length?d.ranking.map(x=>'<article class="trade-card tracker-card"><div class="trade-top"><b>'+x.rank+' · '+esc(x.symbol)+'</b><strong class="'+(x.pnl_pct>=0?'buy':'sell')+'">'+(x.pnl_pct>=0?'+':'')+fmt(x.pnl_pct)+'%</strong></div><div class="trade-meta"><span>'+esc(x.market)+'</span><span>⏱ '+esc(x.timeframe)+'</span><strong>AI '+fmt(x.confidence)+'%</strong></div><div class="tracker-result">'+(x.pnl_pct>0?'🟢 رابحة':x.pnl_pct<0?'🔴 خاسرة':'⚪ تعادل')+'</div></article>').join(""):'<div class="empty">لا توجد صفقات مغلقة حتى الآن.</div>';
 }catch(e){
  if(periods) periods.innerHTML='<div class="empty">تعذر تحميل نتائج المتابعة.</div>';
  if(history) history.innerHTML='<div class="empty">تعذر تحميل سجل الصفقات.</div>';
 }
}
async function loadVisitors(){
 const el=$("#visits"); if(!el)return;
 try{const d=await json("/api/site-visitors");el.textContent=Number(d.visits||0).toLocaleString("en-US");}catch(_){el.textContent="—";}
}
function setup(){
 const menu=$("#menu"),drawer=$("#drawer"),theme=$("#theme");
 const close=()=>{drawer?.classList.remove("open");menu?.setAttribute("aria-expanded","false");};
 menu?.addEventListener("click",e=>{e.preventDefault();e.stopPropagation();const open=!drawer.classList.contains("open");drawer.classList.toggle("open",open);menu.setAttribute("aria-expanded",String(open));});
 drawer?.querySelectorAll("a").forEach(a=>a.addEventListener("click",close));
 theme?.addEventListener("click",()=>{document.body.classList.toggle("light");try{localStorage.setItem("theme",document.body.classList.contains("light")?"light":"dark")}catch(_){}});
 try{if(localStorage.getItem("theme")==="light")document.body.classList.add("light")}catch(_){}
 loadVisitors(); loadTracker(); if($("#scanner")) loadScanner(); if($("#trades")&&!$("#history")) loadTrades();
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",setup,{once:true});else setup();
