const $=s=>document.querySelector(s);let market="spot",timeframe="15m",busy=false;
async function request(url){const r=await fetch(url,{cache:"no-store"});const j=await r.json();if(!r.ok)throw new Error(j.error||"تعذر جلب البيانات");return j}
function money(n){return Number(n).toLocaleString("en-US",{maximumFractionDigits:8})}
function render(data){
  $("#direction").textContent=data.direction||"غير متاح";
  $("#up").textContent=data.up??"—";$("#down").textContent=data.down??"—";$("#total").textContent=data.total??"—";
  $("#updated").textContent=data.updated?new Date(data.updated*1000).toLocaleTimeString("ar-SA"):"—";
  const cards=$("#cards");
  if(!data.signals?.length){cards.innerHTML='<div class="empty">لا توجد صفقة مطابقة لاتجاه السوق وشروط التحليل في هذا الإطار.</div>';return}
  cards.innerHTML=data.signals.map((x,i)=>'<article class="trade"><div class="trade-head"><b>'+(i+1)+'. '+x.symbol+'</b><span class="tag '+(x.side==="BUY"?"buy":"sell")+'">'+(x.side==="BUY"?"شراء":"بيع")+'</span></div><div class="price">'+money(x.entry)+'</div><div class="meta"><span>سعر الدخول</span><b>'+money(x.entry)+'</b></div><div class="levels"><div><small>هدف 1</small><b>'+money(x.tp1)+'</b></div><div><small>هدف 2</small><b>'+money(x.tp2)+'</b></div><div><small>هدف 3</small><b>'+money(x.tp3)+'</b></div><div class="stop"><small>وقف الخسارة</small><b>'+money(x.stop_loss)+'</b></div></div><div class="meta"><span>المخاطرة إلى الوقف</span><b>'+x.risk_percent+'%</b></div><div class="meta"><span>التوافق الفني</span><b>'+x.strength+'%</b></div><div class="meta"><span>الإطار</span><b>'+x.timeframe+'</b></div></article>').join("");
}
async function load(){
  if(busy)return;busy=true;$("#cards").innerHTML='<div class="empty">يتم تحديث بيانات السوق...</div>';
  try{const d=await request('/api/market/'+market+'?timeframe='+timeframe);render(d);$("#health").textContent="● متصل";$("#health").style.color="var(--green)"}
  catch(e){$("#cards").innerHTML='<div class="empty">'+e.message+'</div>';$("#health").textContent="● تعذر الاتصال";$("#health").style.color="var(--red)"}
  finally{busy=false}
}
$("#markets").addEventListener("click",e=>{const b=e.target.closest("[data-market]");if(!b)return;market=b.dataset.market;document.querySelectorAll("[data-market]").forEach(x=>x.classList.toggle("active",x===b));load()});
$("#timeframes").addEventListener("click",e=>{const b=e.target.closest("[data-tf]");if(!b)return;timeframe=b.dataset.tf;document.querySelectorAll("[data-tf]").forEach(x=>x.classList.toggle("active",x===b));load()});
$("#refresh").addEventListener("click",load);load();setInterval(()=>{if(!document.hidden)load()},60000);document.addEventListener("visibilitychange",()=>{if(!document.hidden)load()});
