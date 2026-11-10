const $=s=>document.querySelector(s);
const names={spot:["Binance Spot","السوق الفوري"],futures:["Binance Futures","العقود الآجلة"],alpha:["Binance Alpha","الأصول الناشئة"],"us-stocks":["الأسهم الأمريكية","الشركات المدرجة"],"us-contracts":["العقود الأمريكية","العقود والأدوات الأمريكية"],saudi:["السوق السعودي","أسهم تداول السعودية"],forex:["Forex & Gold","الفوركس والمعادن"]};
let market="futures",busy=false;
const fmt=v=>v===null||v===undefined||v===""||!Number.isFinite(Number(v))?"—":Number(v).toLocaleString("en-US",{maximumFractionDigits:8});
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function pct(a,b,side){a=Number(a);b=Number(b);return a>0&&b>0?((side==="BUY"?b-a:a-b)/a)*100:null}
function card(x){
 const buy=x.side==="BUY",loss=pct(x.entry,x.stop,x.side),gain=pct(x.entry,x.tp3,x.side);
 const dirs=x.direction_timeframes||{},directionText=["1w","1d","4h"].map(k=>({ "1w":"أسبوعي","1d":"يومي","4h":"4 ساعات"}[k])+": "+({UP:"صاعد",DOWN:"هابط",NEUTRAL:"محايد"}[dirs[k]]||"غير متاح")).join(" · ");
 return '<article class="signal '+(buy?"buy":"sell")+'"><div class="signal-head"><div><span class="tag">'+(buy?"شراء · صاعد":"بيع · هابط")+'</span><h2>'+esc(x.symbol)+'</h2></div><div class="score">'+fmt(x.score)+'<small>قوة الإشارة / 100</small></div></div><div class="meta"><span>فريم الدخول: <b>'+esc(x.entry_timeframe||x.timeframe||"15m")+'</b></span><span>الحالة: <b>مرشح نشط</b></span><span>حجم 24س: <b>'+fmt(x.quote_volume)+'</b></span></div><div class="levels"><div><small>الدخول</small><b>'+fmt(x.entry)+'</b></div><div class="loss"><small>وقف الخسارة</small><b>'+fmt(x.stop)+'</b></div><div class="profit"><small>TP1</small><b>'+fmt(x.tp1)+'</b></div><div class="profit"><small>TP2</small><b>'+fmt(x.tp2)+'</b></div><div class="profit"><small>TP3</small><b>'+fmt(x.tp3)+'</b></div><div><small>العائد/المخاطرة</small><b>'+fmt(x.reward_risk_tp3)+'R</b></div></div><div class="potential"><span class="gain">ربح محتمل: '+(gain===null?"—":"+"+fmt(gain)+"%")+'</span><span class="risk">خسارة محتملة: '+(loss===null?"—":"-"+fmt(Math.abs(loss))+"%")+'</span></div><small class="foot">'+esc(x.pattern||"تحليل حركة السعر")+' · '+esc(directionText)+'</small></article>';
}
function choose(m){
 market=m;
 document.querySelectorAll(".market").forEach(x=>x.classList.toggle("active",x.dataset.market===m));
 $("#marketTitle").textContent=names[m][0];$("#marketDesc").textContent=names[m][1]+" — اتجاه أسبوعي ويومي و4 ساعات، ثم دخول مؤكد على 15 دقيقة.";
 $("#direction").textContent="بانتظار التحليل";$("#checked").textContent="—";$("#opportunities").textContent="—";$("#errors").textContent="—";$("#updated").textContent="—";$("#coverage").textContent="لم يبدأ فحص الأصول بعد.";
 $("#results").innerHTML='<div class="empty"><b>السوق محدد</b><p>ابدأ التحليل لفحص دفعة الأصول التالية.</p></div>';
 const marketPath=location.pathname.startsWith("/market/");
 history.replaceState(null,"",marketPath?("/market/"+m):("/?market="+m));
}
async function scan(){
 if(busy)return;
 busy=true;let buttonLabel="تحليل الدفعة التالية";const b=$("#scan");b.disabled=true;b.textContent="جارٍ التحليل…";
 $("#results").innerHTML='<div class="empty"><b>جارٍ فحص دفعة السوق</b><p>يتم تحليل الأصول والتحقق من الشموع المكتملة.</p></div>';
 try{
  const r=await fetch("/api/intelligence/scan?market="+encodeURIComponent(market),{cache:"no-store"});
  const d=await r.json();
  if(!r.ok||!d.ok)throw Error(d.error||"تعذر إكمال الفحص");
  const checked=Number(d.checked_assets||0),total=Number(d.universe_total||0),offset=Number(d.scan_offset||0),errors=Number(d.analysis_errors||0),found=Number(d.signals_found??(d.signals||[]).length);
  const start=total?(offset%total)+1:0,rawEnd=offset+checked,end=total?Math.min(rawEnd,total):0,wrapped=total&&rawEnd>total,wrapEnd=wrapped?rawEnd%total:0;
  const signals=Array.isArray(d.signals)?d.signals:[];
  const buys=signals.filter(x=>x.side==="BUY").length,sells=signals.filter(x=>x.side==="SELL").length;
  $("#direction").textContent=buys>sells?"ميل إشارات الشراء":sells>buys?"ميل إشارات البيع": "لا يوجد اتجاه مؤكد";
  $("#direction").style.color=buys>sells?"var(--green)":sells>buys?"var(--red)":"var(--text)";
  $("#checked").textContent=fmt(checked)+" / "+fmt(total);
  $("#opportunities").textContent=fmt(found);
  $("#errors").textContent=fmt(errors);
  $("#updated").textContent=new Date(d.updated_at||Date.now()).toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"});
  const complete=total>0&&checked>0&&rawEnd>=total;
  if(d.cached)buttonLabel="النتيجة محفوظة — أعد المحاولة لاحقاً";
  $("#coverage").textContent=(total?("الدفعة "+start+"–"+end+(wrapped?" ثم 1–"+wrapEnd:"")+" من "+total+" · تم فحص "+fmt(checked)+" أصل في هذه الدفعة"):"لا توجد أصول مؤهلة")+(complete?" · اكتملت دورة الفحص الحالية":" · الفحص متناوب؛ النتيجة تخص هذه الدفعة فقط")+(errors?" · تعذر تحليل "+errors+" أصل":"")+(d.cached?" · هذه نتيجة مخزنة خلال آخر دقيقة":"");
  $("#results").innerHTML=signals.length?signals.map(card).join(""):'<div class="empty"><b>لا توجد فرص مؤكدة في هذه الدفعة</b><p>'+(complete?"اكتملت دورة الفحص الحالية دون فرص مكتملة الشروط.":"هذه ليست نتيجة السوق بالكامل؛ افحص مرة أخرى للانتقال إلى الدفعة التالية.")+'</p></div>';
 }catch(e){
  $("#direction").textContent="غير متاح";$("#coverage").textContent="لم يتم اعتماد نتيجة الفحص بسبب خطأ في الطلب.";
  $("#results").innerHTML='<div class="empty"><b>تعذر جلب النتائج</b><p>'+esc(e.message)+'</p></div>';
 }finally{busy=false;b.disabled=false;b.textContent="تحليل الدفعة التالية";}
}
document.querySelectorAll(".market").forEach(b=>b.addEventListener("click",()=>{choose(b.dataset.market);scan()}));
$("#scan").addEventListener("click",scan);
$("#theme").addEventListener("click",()=>document.body.classList.toggle("light"));
const pathMarket=location.pathname.match(/^\/market\/([^/]+)$/)?.[1];
const initial=new URLSearchParams(location.search).get("market")||pathMarket;
choose(names[initial]?initial:"futures");
scan();
$("#date").textContent=new Intl.DateTimeFormat("ar-SA",{dateStyle:"medium"}).format(new Date());
