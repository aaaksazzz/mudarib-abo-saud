(()=>{
"use strict";
const $=id=>document.getElementById(id);
let busy=false,lastSignals=[];
function toast(message){$("toast").textContent=message;$("toast").classList.add("show");setTimeout(()=>$("toast").classList.remove("show"),2600)}
function fmt(value){return Number(value).toLocaleString("en-US",{maximumFractionDigits:8})}
function money(value){return Number(value).toLocaleString("en-US",{maximumFractionDigits:0})}
function render(items){
 const root=$("signals");
 if(!items.length){root.innerHTML='<div class="empty">ما ظهرت فرص مطابقة الآن. هذا أفضل من عرض دخول غير مكتمل؛ أعد الفحص بعد إغلاق شمعة جديدة.</div>';return}
 root.innerHTML=items.map((s,i)=>'<article class="signal-card"><div class="signal-top"><span class="rank">'+(i===0?"🥇 الأول":i===1?"🥈 الثاني":"🥉 الثالث")+'</span><span class="side '+(s.side==="BUY"?"buy":"sell")+'">'+(s.side==="BUY"?"شراء / LONG":"بيع / SHORT")+'</span></div><div class="symbol">'+s.symbol+'</div><div class="score">قوة الإشارة <b>'+s.score+'%</b></div><div class="price-grid"><div><span>الدخول</span><b>'+fmt(s.entry)+'</b></div><div><span>وقف الخسارة</span><b class="loss">'+fmt(s.stop)+'</b></div><div><span>TP1 · 1.5R</span><b class="profit">'+fmt(s.tp1)+'</b></div><div><span>TP2 · 2R</span><b class="profit">'+fmt(s.tp2)+'</b></div><div><span>TP3 · 3R</span><b class="profit">'+fmt(s.tp3)+'</b></div><div><span>المخاطرة</span><b>'+s.risk_pct+'%</b></div></div><div class="metrics"><span>الحجم <b>'+s.volume_ratio+'×</b></span><span>تداول 24س <b>'+money(s.quote_volume_24h)+' USDT</b></span></div><p class="reason">'+s.reason+'</p><button class="btn copy" data-copy="'+i+'">نسخ مستويات الصفقة</button></article>').join("");
 root.querySelectorAll("[data-copy]").forEach(b=>b.addEventListener("click",async()=>{const s=lastSignals[Number(b.dataset.copy)];const text=s.symbol+" "+s.side+"\nEntry: "+s.entry+"\nSL: "+s.stop+"\nTP1: "+s.tp1+"\nTP2: "+s.tp2+"\nTP3: "+s.tp3+"\nRisk: "+s.risk_pct+"%";try{await navigator.clipboard.writeText(text);toast("تم نسخ مستويات الصفقة")}catch{toast("تعذر النسخ من المتصفح")}}));
}
async function scan(){
 if(busy)return;busy=true;$("scan").disabled=true;$("scan").textContent="جارٍ فحص العقود…";$("scan-status").textContent="يفحص السوق";
 try{
  const response=await fetch("/api/signal-lab/scan",{cache:"no-store"});
  const data=await response.json();if(!response.ok||!data.ok)throw new Error(data.error||"فشل الفحص");
  lastSignals=data.signals||[];$("eligible").textContent=Number(data.universe_eligible||0).toLocaleString("en-US");$("checked").textContent=Number(data.universe_checked||0).toLocaleString("en-US");$("found").textContent=lastSignals.length;$("last-check").textContent=new Date(data.checked_at).toLocaleTimeString("ar-SA");$("scan-status").textContent="اكتمل الفحص";render(lastSignals);
  $("scan-note").textContent="تم فحص أعلى "+data.universe_checked+" عقداً حسب حجم تداول 24 ساعة؛ حد الأهلية 1 مليون USDT.";
 }catch(e){$("scan-status").textContent="تعذر الفحص";$("scan-note").textContent=e.message;toast(e.message)}
 finally{busy=false;$("scan").disabled=false;$("scan").textContent="إعادة فحص السوق"}
}
$("scan").addEventListener("click",scan);
scan();setInterval(scan,5*60*1000);
})();