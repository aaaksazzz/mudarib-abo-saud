const $=s=>document.querySelector(s);
const fmt=n=>Number(n).toLocaleString("en-US",{maximumFractionDigits:8});
const money=n=>fmt(n);
const LEVERAGE=3;
function pct(entry,level,side,isStop=false){
  const move=side==="BUY"?(level-entry)/entry*100:(entry-level)/entry*100;
  const value=isStop?Math.abs(move):move;
  return (isStop?"-":value>=0?"+":"")+value.toFixed(2)+"%";
}
function levelMarkup(label,value,s,kind){
  const isStop=kind==="stop";
  const raw=pct(s.entry,value,s.side,isStop);
  const leveraged=(parseFloat(raw.replace("%",""))*LEVERAGE);
  const lev=(isStop?"-":leveraged>=0?"+":"")+Math.abs(leveraged).toFixed(2)+"%";
  const cls=isStop?"loss":"profit";
  return '<div class="level '+cls+'"><span>'+label+'</span><b>'+money(value)+'</b><small>'+raw+' حركة السعر · '+lev+' تقديري مع رافعة 3x</small></div>';
}
function render(data){
  $("#universe").textContent=data.universe_count??"—";
  $("#scanned").textContent=data.scanned_count??"—";
  $("#signalsCount").textContent=data.signals?.length??0;
  $("#checked").textContent=new Date(data.checked_at*1000).toLocaleTimeString("ar-SA");
  $("#status").textContent=data.note||"اكتمل الفحص";
  const root=$("#signals");
  if(!data.signals?.length){
    root.innerHTML='<div class="empty">ما ظهرت فرصة مكتملة الشروط في هذا الفحص. عدم الدخول أفضل من اختراع صفقة.</div>';
    return;
  }
  root.innerHTML=data.signals.map((s,i)=>
    '<article class="signal"><div class="signal-head"><span class="symbol">'+(i+1)+'. '+s.symbol+'</span><span class="side '+s.side+'">'+(s.side==="BUY"?"شراء":"بيع")+'</span></div>'+
    '<div class="score">قوة التوافق '+s.score+' / 100</div>'+
    '<div class="levels">'+
    levelMarkup("الدخول",s.entry,s,"entry")+
    levelMarkup("وقف الخسارة",s.stop,s,"stop")+
    levelMarkup("الهدف الأول",s.tp1,s,"target")+
    levelMarkup("الهدف الثاني",s.tp2,s,"target")+
    levelMarkup("الهدف الثالث",s.tp3,s,"target")+
    '<div><span>تغير OI</span><b>'+s.oi_change_pct+'%</b></div></div>'+
    '<ul class="reasons"><li>'+s.sweep+'</li>'+s.confirmations.map(x=>'<li>'+x+'</li>').join("")+'</ul>'+
    '<div class="meta">Taker Buy '+s.taker_buy_ratio+'% · ميزان الطلبات '+s.book_imbalance+'% · حجم 24س '+fmt(s.quote_volume)+' USDT</div></article>'
  ).join("");
}
async function scan(){
  const b=$("#scanBtn");
  b.disabled=true;b.textContent="جارٍ فحص العقود...";
  $("#status").textContent="الاتصال ببيانات Binance Futures";
  try{
    const r=await fetch("/smart-flow-lab/api/scan",{cache:"no-store"});
    const data=await r.json();
    if(!r.ok||!data.ok)throw Error(data.error||"فشل الفحص");
    render(data);
  }catch(e){
    $("#status").textContent="تعذر الفحص";
    $("#signals").innerHTML='<div class="empty">'+e.message+'</div>';
  }finally{b.disabled=false;b.textContent="إعادة الفحص";}
}
$("#scanBtn").addEventListener("click",scan);