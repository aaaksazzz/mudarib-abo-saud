const $=s=>document.querySelector(s);
const MARKET_NAMES={spot:"Binance Spot",futures:"Binance USD-M Futures",coinm:"Binance COIN-M Futures",alpha:"Binance Alpha",saudi:"السوق السعودي",us:"الأسهم الأمريكية",contracts:"العقود الأمريكية",forex:"الفوركس والذهب"};
const PATH=location.pathname.replace(/\/+$/,"")||"/";
const marketMatch=PATH.match(/^\/markets\/([a-z]+)$/);
let market=marketMatch?marketMatch[1]:"spot",busy=false,pending=false,timer=null;
let marketStatuses=new Map();
let analysisTimeframe=new URLSearchParams(location.search).get("timeframe")||"15m";
const VALID_TFS=["15m","1h","4h","1d","1w","1M"];
if(!VALID_TFS.includes(analysisTimeframe))analysisTimeframe="15m";
const timeframeButtons=$("#timeframeButtons");
function strategyLabelFor(tf){
 const labels={"15m":"تأكيد 4 ساعات + يومي","1h":"تأكيد 4 ساعات + يومي","4h":"تأكيد أسبوعي + شهري","1d":"تأكيد أسبوعي + شهري","1w":"تأكيد شهري","1M":"تحليل مستقل"};
 return labels[tf]||"تأكيد متعدد الأطر";
}
function syncTimeframeButtons(){
 if(!timeframeButtons)return;
 timeframeButtons.querySelectorAll("[data-timeframe]").forEach(button=>{
  const active=button.dataset.timeframe===analysisTimeframe;
  button.classList.toggle("active",active);
  button.setAttribute("aria-pressed",active?"true":"false");
 });
 const label=$("#activeStrategy");
 if(label)label.textContent=strategyLabelFor(analysisTimeframe);
}
syncTimeframeButtons();
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
 root.innerHTML=rows.map(x=>'<article class="mover"><div class="mover-head"><b class="mover-symbol">'+safe(x.symbol)+'</b><span class="mover-side">#'+Number(x.fast_mover_rank||0)+' · '+(x.change24h>=0?"صاعد":"هابط")+'</span></div><b class="mover-price">'+fmt(x.price)+'</b><div class="mover-change '+(x.change24h>=0?"up":"down")+'">'+pct(x.change24h)+'</div><small class="mover-volume">سرعة الحركة '+Number(x.fast_mover_score||0)+'/100 · حجم 24س '+compact(x.volume)+'</small></article>').join("");
}
function livePnl(side,entry,current){
 if(!Number.isFinite(Number(entry))||!Number.isFinite(Number(current))||Number(entry)<=0)return null;
 return (Number(current)/Number(entry)-1)*(side==="BUY"?1:-1)*100;
}
function renderSignals(rows,diagnostics={}){
 const root=$("#cards");
 if(!rows||!rows.length){
  const reasons=diagnostics.rejected_by_reason||{};
  const names={insufficient_candles:"شموع غير كافية",provider_error:"تعذر جلب بيانات المصدر",analysis_error:"خطأ في التحليل",no_sweep_or_absorption:"لم يظهر سحب سيولة أو امتصاص ضمن نطاق الحركة القريب",volume_below_threshold:"حجم التداول دون الشرط",candle_not_confirmed:"شمعة الدخول غير مؤكدة",risk_above_4_5pct:"مخاطرة أعلى من الحد",entry_beyond_stop:"السعر تجاوز الوقف",missing_volume:"بيانات الحجم ناقصة",reference_timeframes_not_aligned:"الفريمات المرجعية غير متوافقة",invalid_atr:"مدى الحركة غير صالح",malformed_candles:"بيانات شموع غير سليمة",invalid_ohlc:"بيانات سعر غير سليمة",timeframe_conflict:"تعارض الأطر الزمنية أو عدم تأكيد الساعة"};
  const top=Object.entries(reasons).sort((a,b)=>b[1]-a[1]).slice(0,3);
  root.innerHTML='<article class="scan-diagnostic"><div class="scan-diagnostic-head"><div><span class="kicker">LIVE MARKET SCAN</span><h3>لا توجد صفقة مؤكدة الآن</h3><p>لا نعرض صفقة إلا بعد تحقق شروط الدخول والوقف والأهداف.</p></div><span class="scan-wait">بانتظار فرصة</span></div><div class="scan-metrics"><div><small>الأصول المتاحة</small><b>'+Number(diagnostics.universe_size||0)+'</b></div><div><small>تم فحصها</small><b>'+Number(diagnostics.candidates_scanned||0)+'</b></div><div><small>شموع جاهزة</small><b>'+Number(diagnostics.candles_ready||0)+'</b></div><div><small>فرص مقبولة</small><b>'+Number(diagnostics.accepted_before_top3||0)+'</b></div></div><div class="scan-reasons"><b>أكثر أسباب الاستبعاد</b>'+(top.length?top.map(([k,v])=>'<div><span>'+safe(names[k]||k)+'</span><strong>'+v+'</strong></div>').join(""):'<div><span>لا توجد تفاصيل رفض متاحة بعد</span><strong>—</strong></div>')+'</div></article>';
  return;
 }
 root.innerHTML=rows.map((x,i)=>{
  const side=x.side==="BUY"?1:-1;
  const targetPct=v=>pct(side*(Number(v)/Number(x.entry)-1)*100);
  const stopPct=pct(-Math.abs(Number(x.risk_percent)||Math.abs((x.stop_loss/x.entry-1)*100)));
  const live=Number(x.price),pnl=livePnl(x.side,x.entry,live);
  const rank=i===0?"gold":i===1?"silver":"bronze";
  const flow=x.institutional_flow||{};
  const entryEvidence=x.entry_analysis||{};
  const sweepLabel=entryEvidence.liquidity_sweep==="BULLISH"?"سحب شرائي":entryEvidence.liquidity_sweep==="BEARISH"?"سحب بيعي":"غير مرصود";
  const absorptionLabel=entryEvidence.absorption_proxy==="BULLISH"?"شرائي":entryEvidence.absorption_proxy==="BEARISH"?"بيعي":"غير مرصود";
  return '<article class="trade pro-trade-card"><div class="pro-card-top"><div class="trade-title"><span class="rank '+rank+'">'+(i+1)+'</span><div><b>'+safe(x.symbol)+'</b><small class="card-market-label">'+safe(MARKET_NAMES[market]||market)+' · '+safe(x.timeframe||"15m")+'</small></div></div><div class="card-live-state"><i></i> فرصة جديدة</div></div><div class="pro-signal-strip"><span class="market-direction '+(x.side==="BUY"?"up":"down")+'">'+(x.side==="BUY"?"▲ اتجاه صاعد":"▼ اتجاه هابط")+'</span><span class="tag '+(x.side==="BUY"?"buy":"sell")+'">'+(x.side==="BUY"?"شراء":"بيع")+'</span><span class="quality-chip">جودة الشروط '+Number(x.quality_score||0)+'/100</span></div><div class="pro-live-price"><div><small>السعر الحالي · آخر تحديث</small><b>'+fmt(live)+'</b></div><div class="live-pnl '+(pnl>=0?"up":"down")+'"><small>العائد من الدخول</small><b>'+(pnl===null?"—":(pnl>0?"+":"")+pnl.toFixed(2)+"%")+'</b></div></div><div class="pro-entry-line"><span>الدخول المقترح</span><b>'+fmt(x.entry)+'</b><span>المخاطرة حتى الوقف</span><b class="down">'+stopPct+'</b></div><div class="pro-target-grid"><div class="target-box"><small>TP1 · ربح محتمل</small><b>'+fmt(x.tp1)+'</b><em>'+targetPct(x.tp1)+'</em></div><div class="target-box"><small>TP2 · ربح محتمل</small><b>'+fmt(x.tp2)+'</b><em>'+targetPct(x.tp2)+'</em></div><div class="target-box"><small>TP3 · ربح محتمل</small><b>'+fmt(x.tp3)+'</b><em>'+targetPct(x.tp3)+'</em></div><div class="target-box stop-box"><small>وقف الخسارة</small><b>'+fmt(x.stop_loss)+'</b><em>'+stopPct+'</em></div></div><div class="pro-card-footer"><span>سرعة الحركة <b>'+Number(x.fast_mover_score||0)+'/100</b></span><span>تدفق الأوامر <b>'+safe(flow.status==="supportive"?"مؤيد":flow.status==="opposing"?"معاكس":flow.status==="balanced"?"متوازن":"غير متاح")+'</b></span><span>تغير 24س <b class="'+(x.change24h>=0?"up":"down")+'">'+pct(x.change24h)+'</b></span><span>سحب السيولة <b>'+sweepLabel+'</b></span><span>الامتصاص · استدلال OHLCV <b>'+absorptionLabel+'</b></span></div><div class="pro-card-note">العائد المحتمل محسوب من الدخول إلى الهدف، وليس ضمانًا للربح.</div></article>';
 }).join("");
}
function renderOpen(rows){
 const root=$("#openTrades");$("#openCount").textContent=(rows?.length||0)+" مفتوحة";
 if(!rows||!rows.length){root.innerHTML='<div class="empty">لا توجد صفقات مفتوحة محفوظة لهذا السوق.</div>';return}
 root.innerHTML=rows.map(x=>{
  const pnl=x.live_pnl_percent==null?livePnl(x.side,x.entry,x.current_price):Number(x.live_pnl_percent);
  const current=x.current_price==null?"—":fmt(x.current_price);
  const hits=[x.tp1_hit,x.tp2_hit,x.tp3_hit].filter(Boolean).length;
  const progress=hits===3?100:hits===2?75:hits===1?45:Math.max(0,Math.min(35,pnl==null?0:(pnl>0?pnl*5:0)));
  const state=x.status==="OPEN"?"مفتوحة الآن":x.status==="TP3"?"اكتمل الهدف الثالث":x.status==="SL"?"وصلت للوقف":"منتهية";
  const target=(name,value,hit)=>'<div class="tracked-level '+(hit?"hit":"")+'"><small>'+name+(hit?" ✓":"")+'</small><b>'+fmt(value)+'</b></div>';
  return '<article class="tracked-trade-card"><div class="tracked-head"><div><b>'+safe(x.symbol)+'</b><small>'+safe(MARKET_NAMES[x.market]||x.market)+' · '+(x.side==="BUY"?"شراء":"بيع")+' · '+safe(x.timeframe)+'</small></div><span class="tracked-status '+(x.status==="OPEN"?"active":"closed")+'"><i></i>'+state+'</span></div><div class="tracked-live-grid"><div><small>السعر الحالي</small><b>'+current+'</b></div><div><small>العائد الحي من الدخول</small><b class="'+(pnl>=0?"up":"down")+'">'+(pnl==null?"—":(pnl>0?"+":"")+pnl.toFixed(2)+"%")+'</b></div><div><small>سعر الدخول</small><b>'+fmt(x.entry)+'</b></div></div><div class="tracked-progress"><div><span>الأهداف المحققة</span><b>'+hits+'/3</b></div><i><span style="width:'+progress+'%"></span></i></div><div class="tracked-levels">'+target("TP1",x.tp1,x.tp1_hit)+target("TP2",x.tp2,x.tp2_hit)+target("TP3",x.tp3,x.tp3_hit)+target("وقف الخسارة",x.stop_loss,false)+'</div></article>';
 }).join("");
}
function renderClosed(rows){
 const closed=(rows||[]).filter(x=>x.status!=="OPEN").slice(0,100);
 $("#historyCount").textContent=closed.length+" مغلقة";
 const root=$("#closedTrades");
 if(!closed.length){root.innerHTML='<div class="empty">لا توجد نتائج مغلقة مسجلة بعد.</div>';return}
 root.innerHTML=closed.map(x=>{
  const status=x.status==="TP3"?"وصل TP3":x.status==="EXPIRED"?"انتهت صلاحية 24س":"وقف الخسارة";
  const progress=[x.tp1_hit,x.tp2_hit,x.tp3_hit].filter(v=>Number(v)===1).length;
  const cls=x.status==="TP3"?"tp":x.status==="EXPIRED"?"expired":"sl";
  return '<article class="history-row"><div><b>'+safe(x.symbol)+'</b><small>'+(x.side==="BUY"?"شراء":"بيع")+' · '+safe(MARKET_NAMES[x.market]||x.market)+' · '+safe(x.timeframe||"—")+'</small></div><div><small>الدخول</small><b>'+fmt(x.entry)+'</b></div><div><small>الأهداف التي لُمست</small><b>'+progress+' / 3</b></div><div><small>النتيجة النهائية</small><b class="history-status '+cls+'">'+status+'</b></div><div><small>تاريخ الإغلاق</small><b>'+new Date((x.closed_at||x.updated_at)*1000).toLocaleDateString("ar-SA")+'</b></div></article>';
 }).join("");
}
async function loadHistoryPage(){
 const root=$("#closedTrades");
 if(root)root.innerHTML='<div class="empty">جارٍ تحميل نتائج جميع الأسواق...</div>';
 try{
  const d=await get("/api/trades",12000);
  const rows=d.items||[];
  const closed=rows.filter(x=>x.status!=="OPEN");
  const wins=closed.filter(x=>x.status==="TP3").length;
  const losses=closed.filter(x=>x.status==="SL").length;
  const expired=closed.filter(x=>x.status==="EXPIRED").length;
  const tp1Hits=closed.filter(x=>Number(x.tp1_hit)===1).length;
  const tp2Hits=closed.filter(x=>Number(x.tp2_hit)===1).length;
  $("#historySummary").innerHTML='<article class="result-metric"><small>إجمالي الصفقات المغلقة</small><b>'+closed.length+'</b></article><article class="result-metric"><small>وصلت للهدف الثالث</small><b class="up">'+wins+'</b></article><article class="result-metric"><small>وصلت لوقف الخسارة</small><b class="down">'+losses+'</b></article><article class="result-metric"><small>انتهت صلاحيتها</small><b>'+expired+'</b></article><article class="result-metric"><small>لمست TP1 / TP2</small><b>'+tp1Hits+' / '+tp2Hits+'</b></article><article class="result-metric"><small>نسبة TP3 من TP3 وSL · عينة '+(wins+losses)+'</small><b>'+((wins+losses)?(wins/(wins+losses)*100).toFixed(1)+'%':'—')+'</b></article>';
  renderClosed(rows);
  $("#health").textContent="تم تحديث النتائج";$("#health").className="ok";
 }catch(e){
  if(root)root.innerHTML='<div class="empty">'+safe(e.message)+'</div>';
  $("#health").textContent="تعذر تحميل النتائج";$("#health").className="bad";
 }
}
async function loadMarketStatuses(){
 try{
  const d=await get("/api/markets",8000);
  const states=new Map((d.markets||[]).map(x=>[x.id,x]));
  marketStatuses=states;
  document.querySelectorAll("[data-market]").forEach(b=>{
   const item=states.get(b.dataset.market);if(!item)return;
   const live=item.status==="live"||item.status==="configured_watchlist";
   const small=b.querySelector("small");if(small)small.textContent=live?"مصدر متاح":item.status==="provider_required"?"مزود البيانات غير مربوط":"يتطلب إعداد المصدر";
   b.title=live?"مصدر البيانات متاح":"صفحة السوق مستقلة، لكن مصدر البيانات يحتاج إعدادًا";
   b.classList.toggle("active",b.dataset.market===market);
   const dot=b.querySelector(".tab-state");if(dot)dot.style.display=live?"block":"none";
  });
 }catch(e){$("#health").textContent="تعذر فحص الأسواق";$("#health").className="bad"}
}
function renderGamma(payload){
 const root=$("#gammaCards"),note=$("#gammaNote");
 if(!payload){root.innerHTML='<div class="empty">تحليل السيولة المحلي غير متاح الآن.</div>';return}
 root.innerHTML='<article class="gamma-card"><div class="gamma-card-head"><b>محرك السيولة المحلي</b><span class="gamma-status up">يعمل دون مفاتيح</span></div><div class="gamma-levels"><div><small>نوع التحليل</small><b>OHLCV</b></div><div><small>نسبة الحجم</small><b>Volume Ratio</b></div><div><small>ضغط السعر</small><b>Price Pressure</b></div><div><small>سحب السيولة</small><b>Liquidity Sweep</b></div><div><small>الامتصاص</small><b>Absorption</b></div></div><small class="gamma-time">'+safe(payload.message||"تحليل محلي من بيانات الشموع والحجم العامة؛ ليس Options GEX.")+'</small></article>';
 if(note)note.textContent="محرك التحليل لا يحتاج مفاتيح API. لا يتم احتساب Gamma Exposure أو بيانات الخيارات دون مصدر خيارات موثوق.";
}
async function loadGamma(){
 const button=$("#gammaRefresh"),root=$("#gammaCards");
 if(!button||button.disabled)return;
 button.disabled=true;button.textContent="جارٍ تحديث التحليل...";
 root.innerHTML='<div class="empty">جارٍ تحميل بيانات الشموع العامة وتحليل السيولة...</div>';
 try{const d=await get("/api/analysis/method",12000);renderGamma(d)}
 catch(e){root.innerHTML='<div class="empty">'+safe(e.message)+'</div>'}
 finally{button.disabled=false;button.textContent="تحديث تحليل السيولة"}
}
$("#gammaRefresh")?.addEventListener("click",loadGamma);

const PROVIDER_LABELS={
 configured:"مهيأ",single_source:"مصدر واحد",configured_unverified_runtime:"مهيأ · يحتاج تحقق وقت التشغيل",
 configured_watchlist:"قائمة رموز مهيأة",optional_disabled:"غير مفعّل",symbols_required:"قائمة الرموز مطلوبة",
 provider_required:"مصدر غير مربوط",secret_required:"إعداد مطلوب",unavailable_no_key:"غير متاح"
};
async function loadSystemStatus(){
 const button=$("#systemRefresh"),summary=$("#systemSummary"),root=$("#systemProviders");
 if(button&&button.disabled)return;
 if(button){button.disabled=true;button.textContent="جارٍ الفحص..."}
 try{
  const d=await get("/api/system/status",10000);
  const healthy=d.database==="ok";
  const metrics=[
   ["قاعدة البيانات",healthy?"سليمة":"تحتاج فحص",healthy],
   ["الأسواق المعروفة",(d.markets||[]).length+" أسواق",true],
   ["الصفقات المفتوحة",d.trades?.open??0,true],
   ["عناصر الذاكرة المؤقتة",d.cache_entries??0,true]
  ];
  summary.innerHTML=metrics.map(x=>'<article class="system-metric"><small>'+x[0]+'</small><b class="'+(x[2]?"state-good":"down")+'">'+safe(x[1])+'</b></article>').join("");
  const items=d.markets||[];
  root.innerHTML=items.map(x=>{
   const status=PROVIDER_LABELS[x.status]||x.status||"غير معروف";
   const cls=["configured","configured_watchlist","single_source"].includes(x.status)?"ready":
    x.status==="configured_unverified_runtime"?"check":"missing";
   return '<article class="provider-row"><div class="provider-main"><b>'+safe(x.name)+'</b><small>'+safe(x.provider||"غير محدد")+'</small></div><span class="provider-state '+cls+'">'+safe(status)+'</span><small class="provider-note">'+safe(x.note||"")+'</small><small class="provider-fallback">مسارات احتياط موثقة: '+(x.fallbacks||0)+'</small></article>';
  }).join("")||'<div class="empty">لا توجد مصادر مسجلة.</div>';
  const stamp=d.cache_last_update?new Date(d.cache_last_update*1000).toLocaleTimeString("ar-SA"):"لا توجد بيانات مخزنة";
  $("#systemChecked").textContent="فحص "+new Date(d.timestamp*1000).toLocaleTimeString("ar-SA")+" · آخر تحديث مخزن "+stamp;
  $("#health").textContent=healthy?"متصل":"قاعدة البيانات تحتاج فحص";
  $("#health").className=healthy?"ok":"bad";
 }catch(e){
  summary.innerHTML='<article class="system-metric"><small>حالة الفحص</small><b class="down">تعذر جلب الحالة</b></article>';
  root.innerHTML='<div class="empty">'+safe(e.message)+'</div>';
 }finally{if(button){button.disabled=false;button.textContent="فحص الحالة"}}
}
$("#systemRefresh")?.addEventListener("click",loadSystemStatus);

async function load(){
 if(busy){pending=true;return}
 busy=true;pending=false;
 const refresh=$("#refresh");refresh.disabled=true;refresh.innerHTML="<span>↻</span> جارٍ التحديث";
 $("#health").textContent="جارٍ التحديث";$("#scanState").textContent="يفحص السوق";$("#scanState").className="";
 try{
  const requestedMarket=market;
  const providerState=marketStatuses.get(requestedMarket);
  if(providerState && !["live","configured_watchlist"].includes(providerState.status)){
   $("#direction").textContent="غير متاح";
   $("#direction").className="direction-value neutral";
   ["#up","#down","#flat","#total"].forEach(id=>$(id).textContent="—");
   $("#updated").textContent="—";
   $("#source").textContent="مصدر البيانات غير مربوط";
   $("#sourceShort").textContent="غير متاح";
   $("#scanState").textContent="مصدر البيانات غير مربوط";
   $("#scanState").className="down";
   $("#cards").innerHTML='<article class="scan-diagnostic"><h3>مصدر البيانات غير مربوط</h3><p>هذا السوق لا يملك حالياً مزود بيانات مفعّلاً. لن نعرض أسعاراً أو توصيات غير موثوقة.</p></article>';
   $("#movers").innerHTML='<div class="empty">لا تتوفر بيانات حركة لهذا السوق حالياً.</div>';
   $("#openTrades").innerHTML='<div class="empty">لا توجد بيانات صفقات متاحة لهذا السوق.</div>';
   $("#openCount").textContent="—";
   $("#health").textContent="المصدر غير مربوط";
   $("#health").className="bad";
   return;
  }
  const d=await get("/api/market/"+requestedMarket+"?timeframe="+encodeURIComponent(analysisTimeframe),30000);
  if(requestedMarket!==market){pending=true;return}
  $("#direction").textContent=d.direction_ar;$("#direction").className="direction-value "+(d.direction==="BUY"?"up":d.direction==="SELL"?"down":"neutral");
  $("#up").textContent=d.up;$("#down").textContent=d.down;$("#flat").textContent=d.flat??0;$("#total").textContent=d.total;
  const total=Math.max(1,Number(d.total)||0);
  $("#upBar").style.width=(d.up/total*100)+"%";$("#downBar").style.width=(d.down/total*100)+"%";$("#flatBar").style.width=((d.flat||0)/total*100)+"%";
  $("#updated").textContent=new Date(d.updated*1000).toLocaleTimeString("ar-SA");
  $("#source").textContent="مصدر البيانات: "+d.source+" · "+d.strategy;
  $("#sourceShort").textContent=d.source||"بيانات عامة";
  $("#scanState").textContent="اكتمل";$("#scanState").className="state-good";
  renderMovers(d.movers);renderSignals(d.signals,d.scan_diagnostics||{});renderOpen(d.open_trades);
  syncTimeframeButtons();
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


$("#refresh").addEventListener("click",()=>{if(PATH==="/sections/history")loadHistoryPage();else load()});
timeframeButtons?.addEventListener("click",e=>{
 const button=e.target.closest("[data-timeframe]");
 if(!button)return;
 const next=button.dataset.timeframe;
 if(!VALID_TFS.includes(next)||next===analysisTimeframe)return;
 analysisTimeframe=next;
 syncTimeframeButtons();
 const url=new URL(location.href);url.searchParams.set("timeframe",next);history.replaceState({}, "", url);
 load();
});
async function loadNews(){
 const root=$("#newsFeed");if(!root)return;
 root.innerHTML='<div class="empty">جارٍ جلب آخر العناوين...</div>';
 try{
  const d=await get("/api/news",10000);
  if(!d.items?.length){root.innerHTML='<div class="empty">'+safe(d.error||"لا توجد عناوين متاحة الآن.")+'</div>';return}
  root.innerHTML=d.items.map(x=>'<article class="news-item"><div><small>'+safe(x.source||"مصدر خارجي")+' · '+safe(x.published||"")+'</small><h3><a href="'+safe(x.url)+'" target="_blank" rel="noopener noreferrer">'+safe(x.title)+'</a></h3></div><span class="news-arrow">↗</span></article>').join("");
 }catch(e){root.innerHTML='<div class="empty">'+safe(e.message)+'</div>'}
}
$("#newsRefresh")?.addEventListener("click",loadNews);
function configurePage(){
 const adminAllowed=!$("#adminPanel").hidden;$("#adminPanel").hidden=true;
 const ids=["homeSection","homeOverview","marketSection","directionSection","cryptoGammaSection","systemSection","moversSection","movers","opportunitiesSection","cards","openSection","historySection","blogSection","newsSection"];
 const hideAll=()=>ids.forEach(id=>{const el=$("#"+id);if(el)el.hidden=true});
 const show=(...names)=>names.forEach(id=>{const el=$("#"+id);if(el)el.hidden=false});
 if(PATH==="/"){
  hideAll();show("homeSection","marketSection","homeOverview");
  $("#homeSection h1").innerHTML='منصة <span>الأسواق الذكية</span>';
  $("#homeSection p").textContent="لوحة متابعة مستقلة لاتجاهات الأسواق ومصادر البيانات. التوصيات والصفقات تظهر داخل صفحة كل سوق فقط.";
 }else if(marketMatch){
  if(!MARKET_NAMES[market]){location.replace("/");return}
  hideAll();show("homeSection","directionSection","moversSection","movers","opportunitiesSection","cards","openSection");
  show("cryptoGammaSection");
  $("#homeSection h1").innerHTML='<span>'+MARKET_NAMES[market]+'</span>';
  $("#homeSection p").textContent="صفحة مستقلة؛ بيانات واتجاهات وفرص وسجل هذا السوق فقط.";
 }else if(PATH.startsWith("/sections/")){
  const section=PATH.split("/").pop();
  const map={system:["systemSection"],direction:["directionSection"],movers:["moversSection","movers"],opportunities:["opportunitiesSection","cards"],"open-trades":["openSection"],history:["historySection"]};
  hideAll();show("homeSection",...(map[section]||[]));
  const titles={system:"مركز مراقبة المنصة",direction:"توجه السوق",movers:"الأصول الأكثر حركة",opportunities:"أفضل الفرص الفنية","open-trades":"متابعة الصفقات",history:"سجل النتائج"};
  $("#homeSection h1").innerHTML='<span>'+safe(titles[section]||"القسم")+'</span>';
  $("#homeSection p").textContent="قسم مستقل عن الصفحة الرئيسية.";
 }else if(PATH==="/blog"){
  hideAll();show("homeSection","blogSection");
  $("#homeSection h1").innerHTML='المدونة <span>التعليمية</span>';
  $("#homeSection p").textContent="محتوى تعليمي مستقل عن صفحات الأسواق.";
 }else if(PATH==="/news"){
  hideAll();show("homeSection","newsSection");
  $("#homeSection h1").innerHTML='أخبار <span>الأسواق</span>';
  $("#homeSection p").textContent="آخر العناوين من موجز أخبار خارجي.";
  loadNews();
 }else{hideAll();show("homeSection","marketSection")}
 $("#marketSection").hidden=PATH!=="/";
 $("#refresh").hidden=PATH==="/"||PATH==="/blog"||PATH==="/news"||PATH==="/sections/system";
 if(PATH==="/admin"){
  if(!adminAllowed){location.replace("/");return}
  hideAll();show("homeSection","adminPanel");$("#adminPanel").hidden=false;
  $("#homeSection h1").innerHTML="إدارة <span>المشتركين</span>";
  $("#homeSection p").textContent="إدارة الحسابات والصلاحيات بشكل مستقل.";
 }
 const drawer=$("#siteDrawer");
 if(drawer)drawer.querySelectorAll("a").forEach(a=>a.classList.toggle("active",a.getAttribute("href")===PATH));
}

document.addEventListener("visibilitychange",()=>{
 if(document.hidden||$("#mainContent").hidden)return;
 if(marketMatch||(["direction","movers","opportunities","open-trades"].includes(PATH.split("/").pop())&&PATH.startsWith("/sections/")))load();
 else if(PATH==="/sections/history")loadHistoryPage();
 else if(PATH==="/sections/system")loadSystemStatus();
});
function tick(){ $("#clock").textContent=new Date().toLocaleTimeString("en-GB",{hour12:false}); }
async function showAccess(message, user=null){
 $("#mainContent").hidden=true;
 $("#accessGate").hidden=false;
 $("#topLogout").hidden=true;
 $("#authNotice").textContent=message||"";
 $("#authLogout").hidden=!user;
 $("#authToggle").hidden=!!user;
 $("#authForm").hidden=!!user;
 $("#accessTitle").textContent=user?"الاشتراك غير مفعل":"تسجيل الدخول";
 $("#accessMessage").textContent=user?"حسابك مسجل، لكن لا يوجد اشتراك نشط. تواصل مع الإدارة لتفعيل الوصول إلى الأسواق.":"أنشئ حسابًا أو سجل دخولك. الوصول إلى الأسواق للمشتركين فقط.";
}
async function startAuthorized(user=null){
 $("#accessGate").hidden=true;
 $("#mainContent").hidden=false;
 $("#topLogout").hidden=true;
 $("#adminPanel").hidden=!(user&&user.is_admin);
 $("#drawerAdmin").hidden=!(user&&user.is_admin);
 if(user&&user.is_admin) await loadAdminUsers();
 configurePage();
 if(marketMatch){await loadMarketStatuses();await load();}
 else if(PATH==="/"){await loadMarketStatuses();}
 else if(PATH.startsWith("/sections/") && ["direction","movers","opportunities","open-trades"].includes(PATH.split("/").pop())){await loadMarketStatuses();await load();}
 else if(PATH==="/sections/history"){await loadHistoryPage();}
 else if(PATH==="/sections/system"){await loadSystemStatus();}
}
async function initializeAccess(){
 // Public browsing is enabled. Login is optional and only used for admin tools.
 let user=null;
 try{
  const d=await get("/api/auth/me",5000);
  if(d&&d.configured&&d.user) user=d.user;
 }catch(e){
  console.warn("Optional account status unavailable; continuing in public mode.",e);
 }
 await startAuthorized(user);
}
let creatingAccount=false;
$("#authToggle").addEventListener("click",()=>{
 creatingAccount=!creatingAccount;
 $("#accessTitle").textContent=creatingAccount?"إنشاء حساب جديد":"تسجيل الدخول";
 $("#authSubmit").textContent=creatingAccount?"إنشاء الحساب":"دخول";
 $("#authPassword").autocomplete=creatingAccount?"new-password":"current-password";
 $("#authToggle").textContent=creatingAccount?"لديك حساب؟ تسجيل الدخول":"ليس لديك حساب؟ إنشاء حساب";
 $("#authNotice").textContent="";
});
$("#authForm").addEventListener("submit",async e=>{
 e.preventDefault();
 const button=$("#authSubmit");button.disabled=true;
 $("#authNotice").textContent="جارٍ التحقق...";
 try{
  const response=await fetch(creatingAccount?"/api/auth/register":"/api/auth/login",{
   method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({email:$("#authEmail").value,password:$("#authPassword").value})
  });
  const d=await response.json();
  if(!response.ok)throw Error(d.message||"تعذر إكمال الطلب.");
  if(d.user?.is_admin || d.user?.subscribed) await startAuthorized(d.user);
  else await showAccess("تم إنشاء الحساب بنجاح. الاشتراك يحتاج موافقة الأدمن.",d.user);
 }catch(err){$("#authNotice").textContent=err.message}
 finally{button.disabled=false}
});
async function logout(){
 await fetch("/api/auth/logout",{method:"POST"});
 location.reload();
}
$("#authLogout").addEventListener("click",logout);
$("#topLogout").addEventListener("click",logout);
async function loadAdminUsers(){
 try{
  const d=await get("/api/admin/users",10000);
  const root=$("#adminUsers");
  if(!d.users.length){root.innerHTML='<div class="empty">لا توجد حسابات بعد.</div>';return}
  root.innerHTML=d.users.map(u=>{
   const expiry=u.subscription_expires_at?new Date(u.subscription_expires_at*1000).toLocaleDateString("ar-SA"):"—";
   const status=u.role==="admin"?"أدمن":u.subscribed?"مشترك حتى "+expiry:"غير مشترك";
   const actions=u.role==="admin"?"":'<div class="admin-actions"><button data-admin-action="grant" data-days="30" data-user="'+u.id+'">شهر</button><button data-admin-action="grant" data-days="60" data-user="'+u.id+'">شهرين</button><button data-admin-action="grant" data-days="90" data-user="'+u.id+'">3 أشهر</button><button data-admin-action="grant" data-days="180" data-user="'+u.id+'">6 أشهر</button><button data-admin-action="grant" data-days="365" data-user="'+u.id+'">سنة</button><button class="revoke" data-admin-action="revoke" data-user="'+u.id+'">إلغاء</button></div>';
   return '<article class="admin-user"><div><b>'+safe(u.email)+'</b><small>رقم الحساب: '+u.id+' · '+status+'</small></div>'+actions+'</article>';
  }).join("");
 }catch(e){$("#adminUsers").innerHTML='<div class="empty">'+safe(e.message)+'</div>'}
}
$("#adminRefresh").addEventListener("click",loadAdminUsers);
$("#adminUsers").addEventListener("click",async e=>{
 const b=e.target.closest("[data-admin-action]");if(!b)return;
 b.disabled=true;
 try{
  const response=await fetch("/api/admin/subscription",{
   method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({user_id:Number(b.dataset.user),action:b.dataset.adminAction,days:Number(b.dataset.days||0)})
  });
  const d=await response.json();if(!response.ok)throw Error(d.message||"تعذر تعديل الاشتراك.");
  await loadAdminUsers();
 }catch(err){alert(err.message);b.disabled=false}
});

function closeDrawer(){
 const drawer=$("#siteDrawer"),backdrop=$("#drawerBackdrop"),open=$("#menuOpen");
 drawer.classList.remove("open");drawer.setAttribute("aria-hidden","true");
 backdrop.hidden=true;open.setAttribute("aria-expanded","false");
}
$("#menuOpen").addEventListener("click",()=>{
 const drawer=$("#siteDrawer"),backdrop=$("#drawerBackdrop"),open=$("#menuOpen");
 drawer.classList.add("open");drawer.setAttribute("aria-hidden","false");
 backdrop.hidden=false;open.setAttribute("aria-expanded","true");
});
$("#menuClose").addEventListener("click",closeDrawer);
$("#drawerBackdrop").addEventListener("click",closeDrawer);
$("#siteDrawer").addEventListener("click",e=>{
 const link=e.target.closest("a");if(!link)return;
 closeDrawer();
});

tick();setInterval(tick,1000);
initializeAccess();
timer=setInterval(()=>{if(document.hidden||$("#mainContent").hidden)return;if(marketMatch||(["direction","movers","opportunities","open-trades"].includes(PATH.split("/").pop())&&PATH.startsWith("/sections/")))load();else if(PATH==="/sections/history")loadHistoryPage();else if(PATH==="/sections/system")loadSystemStatus()},30000);
