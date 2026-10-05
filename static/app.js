const _nativeFetch=window.fetch.bind(window);
window.fetch=async function(input,init={}){
  const opts={...init};
  const controller=new AbortController();
  const timeoutMs=Number(opts.timeoutMs||20000);
  delete opts.timeoutMs;
  if(opts.signal){
    if(opts.signal.aborted) controller.abort();
    else opts.signal.addEventListener("abort",()=>controller.abort(),{once:true});
  }
  opts.signal=controller.signal;
  const timer=setTimeout(()=>controller.abort(),timeoutMs);
  try{return await _nativeFetch(input,opts)}finally{clearTimeout(timer)}
};
const app=document.getElementById("app"),drawer=document.getElementById("drawer"),backdrop=document.getElementById("backdrop"),menuBtn=document.getElementById("menuBtn"),closeMenu=document.getElementById("closeMenu"),themeBtn=document.getElementById("themeBtn"),supportOpen=document.getElementById("supportOpen");
const TFS=["15m","30m","1h","4h","1d","1w","1M"],LABELS={"15m":"15 د","30m":"30 د","1h":"ساعة","4h":"4 ساعات","1d":"يومي","1w":"أسبوعي","1M":"شهري"};
const MARKET={spot:["₿","السبوت","/fast-spot"],futures:["⚡","الفيوتشر","/fast-futures"],contracts:["▣","العقود الأمريكية","/fast-contracts"],us:["US","السوق الأمريكي","/fast-us"],saudi:["SA","السوق السعودي","/fast-saudi"],forex:["FX","الفوركس والذهب","/fast-forex"]};
const esc=s=>String((s!=null?s:"")).replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
function openDrawer(){drawer.classList.add("open");backdrop.classList.add("open");document.body.classList.add("drawer-open")}
function closeDrawer(){drawer.classList.remove("open");backdrop.classList.remove("open");document.body.classList.remove("drawer-open")}
menuBtn&&menuBtn.addEventListener("click",e=>{e.preventDefault();openDrawer()});closeMenu&&closeMenu.addEventListener("click",e=>{e.preventDefault();closeDrawer()});backdrop&&backdrop.addEventListener("click",closeDrawer);
document.querySelectorAll("#drawer a").forEach(a=>a.addEventListener("click",closeDrawer));
function applyTheme(){const light=localStorage.getItem("smart_theme")==="light";document.body.classList.toggle("light",light);if(themeBtn)themeBtn.textContent=light?"☾":"☀"}
themeBtn&&themeBtn.addEventListener("click",()=>{localStorage.setItem("smart_theme",document.body.classList.contains("light")?"dark":"light");applyTheme()});applyTheme();
async function home(){
  if(window.__homeTimer)clearInterval(window.__homeTimer);
  app.innerHTML='<section class="home-page clean-home"><section class="home-welcome"><div class="welcome-copy"><span class="eyebrow">SMART TRADING PRO</span><h1>تابع الأسواق بوضوح، <span>واتخذ قرارك بثقة.</span></h1><p>منصة لمراقبة الأسواق والإشارات والتحليلات في مكان واحد. بدون زحمة وبدون شكل بوتات.</p><div class="actions"><a class="btn primary" href="/fast-spot">استكشف الأسواق</a><a class="btn" href="/strategy-lab">مختبر الاستراتيجيات</a></div></div><div class="welcome-status"><span class="home-live"><i></i> الأسواق مباشرة</span><b>بيانات السوق تتحدث تلقائياً</b><small>اختر السوق والفريم من الصفحات المتخصصة.</small></div></section><section class="home-market-section"><div class="section-head"><div><span class="eyebrow">MARKETS</span><h2>الأسواق</h2></div><span class="muted">اختر سوقك</span></div><div class="home-market-grid">'+Object.entries(MARKET).map(([k,m])=>'<a class="market-quick" href="'+m[2]+'"><span class="mq-icon">'+m[0]+'</span><span><b>'+m[1]+'</b><small>عرض الإشارات والفريمات</small></span><strong>‹</strong></a>').join("")+'</div></section><section class="home-opportunity"><div class="section-head"><div><span class="eyebrow">LIVE MARKET</span><h2>أفضل فرصة حالياً</h2></div><span id="homeUpdated" class="muted">جاري التحديث…</span></div><div id="homeBestSignal" class="home-opportunity-card"><div><small>جاري قراءة الأسواق</small><b>لحظة واحدة…</b><span>نرتب الفرص حسب قوة الإشارة.</span></div><strong>⌁</strong></div></section><section class="home-live-board"><div class="section-head"><div><span class="eyebrow">MARKET RADAR</span><h2>رادار السوق</h2></div><span id="homeCount" class="muted">—</span></div><div id="homeLiveRows" class="trades-list"><div class="empty loading">جاري الفحص…</div></div></section></section>';
  try{
    const [sr,fr]=await Promise.all([
      fetch("/api/fast-market?market=spot&timeframe=15m",{cache:"no-store"}),
      fetch("/api/fast-market?market=futures&timeframe=15m",{cache:"no-store"})
    ]);
    const spot=await sr.json(),fut=await fr.json();
    const rows=[
      ...(Array.isArray(spot.trades)?spot.trades:[]).map(x=>({...x,_market:"السبوت"})),
      ...(Array.isArray(fut.trades)?fut.trades:[]).map(x=>({...x,_market:"الفيوتشر"}))
    ].filter(x=>x.symbol);
    rows.sort((a,b)=>Number(b.ai_pct??b.score??0)-Number(a.ai_pct??a.score??0)||Math.abs(Number(b.change_pct??0))-Math.abs(Number(a.change_pct??0)));
    const best=rows[0];
    const count=rows.length;
    const countEl=document.getElementById("homeCount");
    const updated=document.getElementById("homeUpdated");
    if(countEl)countEl.textContent=count+" إشارة";
    if(updated)updated.textContent="آخر تحديث: "+new Date().toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"});
    if(best){
      const ai=Math.round(Number(best.ai_pct??best.score??0)),ch=Number(best.change_pct??best.change??0),side=String(best.side||"").toUpperCase();
      document.getElementById("homeBestSignal").innerHTML='<div><small>'+esc(best._market)+' • فريم 15 دقيقة</small><b>'+esc(best.symbol)+' · '+(side==="BUY"?"شراء":"بيع")+'</b><span>قوة الإشارة '+ai+'% · التغير '+ch.toFixed(2)+'%</span></div><strong>↗</strong>';
      document.getElementById("homeLiveRows").innerHTML=rows.slice(0,6).map((x,i)=>{const a=Math.round(Number(x.ai_pct??x.score??0)),ch=Number(x.change_pct??x.change??0),s=String(x.side||"").toUpperCase();return '<article class="trade"><div class="trade-top"><div><div class="symbol">#'+(i+1)+' '+esc(x.symbol)+'</div><div class="muted">'+esc(x._market)+' · 15 دقيقة</div></div><span class="side '+(s==="BUY"?"buy":"sell")+'">'+(s==="BUY"?"شراء":"بيع")+' · '+a+'%</span></div><div class="trade-body"><div class="trade-meta"><span class="pill">التغير '+ch.toFixed(2)+'%</span><span class="pill">دخول '+futuresNum(x.entry)+'</span><span class="pill">TP1 '+futuresNum(x.tp1)+'</span><span class="pill">SL '+futuresNum(x.sl)+'</span></div></div></article>';}).join("");
    }else{
      document.getElementById("homeBestSignal").innerHTML='<div><small>الأسواق قيد الفحص</small><b>لا توجد فرصة مطابقة الآن</b><span>سيظهر أفضل تطابق عند اكتمال البيانات.</span></div><strong>—</strong>';
      document.getElementById("homeLiveRows").innerHTML='<div class="empty">'+((spot.scanning||fut.scanning)?"🔎 جاري قراءة الأسواق…":"لا توجد إشارة مطابقة حالياً.")+'</div>';
    }
  }catch(e){
    const el=document.getElementById("homeLiveRows");if(el)el.innerHTML='<div class="empty">⚠️ تعذر تحديث بيانات السوق حالياً.</div>';
  }
  window.__homeTimer=setTimeout(()=>{if(location.pathname==="/")home();},30000);
}
const FRAME_MS={"15m":15*60*1000,"30m":30*60*1000,"1h":60*60*1000,"4h":4*60*60*1000,"1d":24*60*60*1000,"1w":7*24*60*60*1000,"1M":30*24*60*60*1000};
const SIGNAL_CACHE_KEY="smart_signal_cache_v2";
function frameEndMs(tf,candleStart){
  const n=Number(candleStart);
  let start=Number.isFinite(n)&&n>0?(n<1e12?n*1000:n):Date.now();
  if(!n){
    const d=new Date();
    if(tf==="1M") start=Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),1);
    else if(tf==="1w"){const x=new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),d.getUTCDate()));const day=x.getUTCDay();x.setUTCDate(x.getUTCDate()-(day===0?6:day-1));start=x.getTime();}
    else start=Math.floor(start/(FRAME_MS[tf]||FRAME_MS["15m"]))*(FRAME_MS[tf]||FRAME_MS["15m"]);
  }
  if(tf==="1M"){const d=new Date(start);return Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,1);}
  return start+(FRAME_MS[tf]||FRAME_MS["15m"]);
}
function cleanSignalCache(){
  let cache={};try{cache=JSON.parse(localStorage.getItem(SIGNAL_CACHE_KEY)||"{}")}catch(e){}
  const now=Date.now();Object.keys(cache).forEach(k=>{if(!cache[k]||Number(cache[k].expires_at||0)<=now)delete cache[k]});
  localStorage.setItem(SIGNAL_CACHE_KEY,JSON.stringify(cache));return cache;
}
async function loadMarket(key,tf){
  const result=document.getElementById("result"),status=document.getElementById("status");
  if(!result)return;
  const requestId=String(Date.now())+"-"+Math.random().toString(36).slice(2);
  window.__marketRequestId=requestId;
  try{
    const r=await fetch("/api/fast-market?market="+encodeURIComponent(key)+"&timeframe="+encodeURIComponent(tf)+"&_="+Date.now(),{
      cache:"no-store",
      headers:{"Cache-Control":"no-cache","Pragma":"no-cache"}
    });
    if(!r.ok)throw new Error("HTTP "+r.status);
    const d=await r.json();
    if(window.__marketRequestId!==requestId)return;
    if(status)status.textContent=d.scanning?"🔎 تحديث "+(LABELS[tf]||tf):"LIVE • "+(LABELS[tf]||tf);
    renderMarket(d);
    if(d.scanning && (!Array.isArray(d.trades)||d.trades.length===0)){
      setTimeout(()=>loadMarket(key,tf),1500);
    }
  }catch(e){
    if(window.__marketRequestId===requestId)result.innerHTML='<div class="empty">تعذر تحديث السوق حالياً… إعادة المحاولة تلقائياً.</div>';
  }
}
async function loadMarketFrame(key,tf,box){
  if(!box)return;
  try{
    const r=await fetch("/api/fast-market?market="+encodeURIComponent(key)+"&timeframe="+encodeURIComponent(tf),{cache:"no-store"});
    const d=await r.json();
    const rows=Array.isArray(d.trades)?d.trades:[];
    const best=futuresRank(rows)[0];
    const label=LABELS[tf]||tf;
    if(!best){
      box.innerHTML='<div class="frame-head"><div><b>'+label+'</b><small>'+(d.scanning?"🔎 جاري الفحص — القديم انتهى":"لا توجد إشارة مطابقة حالياً")+'</small></div></div>';
      return;
    }
    const side=String(best.side||"").toUpperCase()==="BUY"?"شراء":"بيع";
    const ai=Math.round(Number(best.ai_pct||best.score||0));
    box.innerHTML='<div class="frame-head"><div><b>'+label+'</b><small>أفضل عملة فقط • #1 AI • '+ai+'%</small></div><span class="frame-best">🏆 '+esc(best.symbol||"—")+'</span></div><article class="futures-trade-row featured"><div class="ft-rank">#1</div><div class="ft-symbol"><b>'+esc(best.symbol||"—")+'</b><small>'+label+' • '+side+'</small></div><div class="ft-ai"><small>AI</small><b>'+ai+'%</b></div><div class="ft-change '+(Number(best.change_pct||0)>=0?"profit":"loss")+'">'+Number(best.change_pct||0).toFixed(2)+'%</div><div class="ft-levels"><span>دخول <b>'+futuresNum(best.entry)+'</b></span><span>TP1 <b>'+futuresNum(best.tp1)+'</b></span><span>TP2 <b>'+futuresNum(best.tp2)+'</b></span><span>TP3 <b>'+futuresNum(best.tp3)+'</b></span><span>SL <b>'+futuresNum(best.sl)+'</b></span></div><span class="side '+(String(best.side||"").toUpperCase()==="BUY"?"buy":"sell")+'">'+side+'</span></article>';
  }catch(e){box.innerHTML='<div class="futures-empty-line">⚠️ تعذر تحديث '+(LABELS[tf]||tf)+'</div>';}
}

function marketPage(key){
  const m=MARKET[key]||MARKET.spot;
  app.innerHTML='<section><div class="market-head"><div><div class="eyebrow">'+m[0]+' '+m[1]+'</div><h1>'+m[1]+'</h1><div class="muted">فحص مستقل للسوق والفريم المختار.</div></div><div class="muted" id="status">جاهز</div></div><div class="tf-row" id="tfRow">'+TFS.map((t,i)=>'<button class="tf '+(i===0?"active":"")+'" data-tf="'+t+'">'+LABELS[t]+'</button>').join("")+'</div><div id="result"><div class="empty loading">جاري جلب بيانات السوق…</div></div></section>';
  document.querySelectorAll(".tf").forEach(b=>b.onclick=()=>{document.querySelectorAll(".tf").forEach(x=>x.classList.remove("active"));b.classList.add("active");loadMarket(key,b.dataset.tf)});
  loadMarket(key,"15m");
}

let futuresSelectedTf="15m";
function futuresFmt(v){return Number(v||0).toLocaleString("en-US",{maximumFractionDigits:8})}
function futuresNum(v){return Number(v||0).toLocaleString("en-US",{maximumFractionDigits:8});}
function futuresRank(rows){
  return [...(Array.isArray(rows)?rows:[])].sort((a,b)=>{
    const ai=Number(b.ai_pct||b.score||0)-Number(a.ai_pct||a.score||0);
    if(ai)return ai;
    return Math.abs(Number(b.change_pct||0))-Math.abs(Number(a.change_pct||0));
  });
}
function renderFutures15(rows,scanning){
  const sorted=futuresRank(rows),best=sorted[0];
  if(!best)return '<div class="futures-empty-line">'+(scanning?'🔎 جاري فحص 15 دقيقة…':'لا توجد إشارة 15 دقيقة مطابقة حالياً.')+'</div>';
  const side=String(best.side||"").toUpperCase(),buy=side==="BUY";
  return '<section class="futures-frame-section" data-tf="15m"><div class="frame-head"><div><b>15 دقيقة</b><small>أفضل عملة فقط • #1 AI • '+Math.round(Number(best.ai_pct||best.score||0))+'%</small></div><span class="frame-best">🏆 '+esc(best.symbol||"—")+'</span></div><article class="futures-trade-row featured"><div class="ft-rank">#1</div><div class="ft-symbol"><b>'+esc(best.symbol||"—")+'</b><small>15 دقيقة • '+(buy?"شراء":"بيع")+'</small></div><div class="ft-ai"><small>AI</small><b>'+Math.round(Number(best.ai_pct||best.score||0))+'%</b></div><div class="ft-change '+(Number(best.change_pct||0)>=0?"profit":"loss")+'">'+Number(best.change_pct||0).toFixed(2)+'%</div><div class="ft-levels"><span>دخول <b>'+futuresNum(best.entry)+'</b></span><span>TP1 <b>'+futuresNum(best.tp1)+'</b></span><span>TP2 <b>'+futuresNum(best.tp2)+'</b></span><span>TP3 <b>'+futuresNum(best.tp3)+'</b></span><span>SL <b>'+futuresNum(best.sl)+'</b></span></div><span class="side '+(buy?"buy":"sell")+'">'+(buy?"شراء":"بيع")+'</span></article></section>';
}
async function refreshFuturesPage(){
  const search=document.getElementById("futuresSearch"),frames=document.getElementById("futuresFrames"),live=document.getElementById("futuresLive");
  if(!search||!frames||!live)return;
  try{
    const r=await fetch("/api/fast-market?market=futures&timeframe=15m",{cache:"no-store"});
    const data=await r.json();
    const rows=Array.isArray(data.trades)?data.trades:[];
    const best=futuresRank(rows)[0];
    const botStatus=await fetch("/api/futures/bot",{cache:"no-store"}).then(r=>r.json()).catch(()=>({real_orders:false,bot:{}}));
    const canTrade=Boolean(botStatus.real_orders);
    live.innerHTML=best
      ? '<section class="futures-live-card"><div><small>أفضل إشارة 15 دقيقة • #1 AI</small><h3>'+esc(best.symbol||"—")+' • '+(String(best.side||"").toUpperCase()==="BUY"?"شراء":"بيع")+'</h3><div class="futures-live-levels"><span>AI <b>'+Math.round(Number(best.ai_pct||best.score||0))+'%</b></span><span>دخول <b>'+futuresNum(best.entry)+'</b></span><span>TP1 <b>'+futuresNum(best.tp1)+'</b></span><span>TP2 <b>'+futuresNum(best.tp2)+'</b></span><span>TP3 <b>'+futuresNum(best.tp3)+'</b></span><span>SL <b>'+futuresNum(best.sl)+'</b></span></div></div><button class="btn primary futures-entry-btn" '+(canTrade?"":"disabled")+' onclick="executeFuturesEntry('+JSON.stringify(best).replace(/"/g,"&quot;")+')">'+(canTrade?"دخول حقيقي على Binance":"Binance غير مهيأ")+'</button></section>'
      : '<div class="futures-empty-line">لا توجد إشارة 15 دقيقة جاهزة للدخول حالياً.</div>';
    search.classList.toggle("loading",Boolean(data.scanning));
    search.innerHTML=data.scanning?'<strong>🔎 جاري فحص 15 دقيقة</strong><small>النتيجة تتحدث مع الفريم.</small>':'<strong>✅ 15 دقيقة محدث</strong><small>يتم ترتيب العملات حسب AI وأعلى واحدة هي الوحيدة القابلة للتنفيذ.</small>';
    frames.innerHTML=renderFutures15(rows,Boolean(data.scanning));
  }catch(e){
    search.innerHTML='<strong>⚠️ تعذر تحديث 15 دقيقة</strong><small>'+esc(e.message||"خطأ غير معروف")+'</small>';
    frames.innerHTML='<div class="futures-empty-line">لا توجد بيانات تنفيذ حالياً.</div>';
  }
}
function cacheSignals(market,tf,trades){
  const cache=cleanSignalCache(),now=Date.now(),key=market+"|"+tf;
  const incoming=(Array.isArray(trades)?trades:[]).map(t=>({...t,expires_at:Number(t.expires_at)||frameEndMs(tf,Number(t.candle_start)||now)})).filter(t=>t.expires_at>now);
  const existing=cache[key];
  // ثبّت الإشارة الحالية حتى نهاية الفريم؛ تحديث API لا يلغيها.
  if(existing && Number(existing.expires_at||0)>now && Array.isArray(existing.trade) && existing.trade.length){
    const sameCandle=existing.trade.some(t=>Number(t.expires_at||0)>now);
    if(sameCandle){
      localStorage.setItem(SIGNAL_CACHE_KEY,JSON.stringify(cache));
      return existing.trade.filter(t=>Number(t.expires_at||0)>now);
    }
  }
  if(incoming.length){
    cache[key]={market,timeframe:tf,expires_at:Math.max(...incoming.map(t=>Number(t.expires_at)||0)),trade:incoming};
  }else if(existing && Number(existing.expires_at||0)>now){
    return existing.trade||[];
  }else{
    delete cache[key];
  }
  localStorage.setItem(SIGNAL_CACHE_KEY,JSON.stringify(cache));
  return cache[key]&&cache[key].trade||[];
}
function getCachedSignals(market,tf){
  const cache=cleanSignalCache(),v=cache[market+"|"+tf];
  return v&&Array.isArray(v.trade)?v.trade:[];
}
function renderMarket(d){
  const liveTrades=Array.isArray(d.trades)?d.trades:(d.trade?[d.trade]:[]);
  const market=String(d.market||"");
  const tfKey=String(d.timeframe||"");
  const trades=cacheSignals(market,tfKey,liveTrades);
  const buyOnly=["spot","saudi","us"].includes(market);
  const filtered=buyOnly?trades.filter(t=>String(t.side||"").toUpperCase()==="BUY"):trades;
  if(!filtered.length){
    document.getElementById("result").innerHTML='<div class="empty">لا توجد صفقات مطابقة للشروط في هذا الفريم حالياً.</div>';
    return;
  }
  const tf=LABELS[tfKey]||tfKey||"";
  const ranked=[...filtered].sort((a,b)=>Number((b.ai_pct!=null?b.ai_pct:(b.score!=null?b.score:0)))-Number((a.ai_pct!=null?a.ai_pct:(a.score!=null?a.score:0)))||Math.abs(Number((b.change_pct!=null?b.change_pct:(b.change!=null?b.change:0))))-Math.abs(Number((a.change_pct!=null?a.change_pct:(a.change!=null?a.change:0))))); ranked.forEach((t,i)=>{t.rank=i+1;t._top=i===0;}); const cards=ranked.map((trade,i)=>{
    const side=String(trade.side||"").toUpperCase();
    const label=side==="BUY"?"شراء":side==="SELL"?"بيع":side;
    const ai=Math.round(Number((trade.ai_pct!=null?trade.ai_pct:(trade.score!=null?trade.score:0))));
    const level=(name,val)=>'<div class="level"><small>'+name+'</small><b>'+(val==null?"—":Number(val).toLocaleString("en-US",{maximumFractionDigits:8}))+'</b></div>';
    return '<article class="trade"><div class="trade-top"><div><div class="symbol">'+esc(trade.symbol||"—")+'</div><div class="muted">'+tf+' • AI '+ai+'%</div></div><span class="side '+(side==="BUY"?"buy":"sell")+'">'+label+'</span></div><div class="trade-body"><div class="levels">'+level("الدخول",trade.entry)+level("TP1",trade.tp1)+level("TP2",trade.tp2)+level("TP3",trade.tp3)+level("الوقف",trade.sl)+'</div><div class="trade-meta"><span class="pill">#'+(trade.rank||i+1)+'</span>'+(trade.tracking?'<span class="pill">🔄 '+esc(trade.tracking_status||"متابعة حتى الإغلاق")+'</span>':'')+'<span class="pill">التغير: '+Number((trade.change_pct!=null?trade.change_pct:(trade.change!=null?trade.change:0))).toFixed(2)+'%</span><span class="pill">ربح: '+Number((trade.profit_rate_pct!=null?trade.profit_rate_pct:(trade.profit_pct!=null?trade.profit_pct:0))).toFixed(2)+'%</span><span class="pill">خسارة: '+Number((trade.loss_rate_pct!=null?trade.loss_rate_pct:(trade.loss_pct!=null?trade.loss_pct:0))).toFixed(2)+'%</span>'+(market==="futures"?'<span class="pill">رافعة: '+Number((trade.leverage!=null?trade.leverage:20))+'x</span><span class="pill">هدف: '+Number((trade.target_pct!=null?trade.target_pct:10)).toFixed(0)+'%</span><span class="pill">وقف: '+Number((trade.stop_pct!=null?trade.stop_pct:5)).toFixed(0)+'%</span>':'')+'<span class="pill">'+(trade._top?"👑 الأفضل":"")+'</span><span class="pill">الفريم: '+tf+'</span></div>'+(trade._top&&market==="spot"&&tfKey==="15m"?'<div style="margin-top:12px"><button class="btn primary spot-entry-btn" type="button" data-spot-entry="1">دخول صفقة</button></div>':'')+(trade._top&&market==="futures"&&tfKey==="15m"?'<div style="margin-top:12px"><button class="btn primary futures-entry-btn" type="button" data-futures-entry="1">دخول صفقة حقيقية</button></div>':'')+'</div></article>';
  }).join("");
  document.getElementById("result").innerHTML='<div class="trade-count">الصفقات المطابقة: <b>'+filtered.length+'</b></div><div class="trades-list">'+cards+'</div>';
  if(market==="spot" && tfKey==="15m" && ranked.length){
    const best=ranked[0];
    const btn=document.querySelector(".spot-entry-btn");
    if(btn){btn.onclick=()=>executeSpotEntry(best);btn.setAttribute("aria-label","تنفيذ دخول شراء حقيقي على Binance Spot");}
  }
  if(market==="futures" && tfKey==="15m" && ranked.length){
    const best=ranked[0];
    const btn=document.querySelector(".futures-entry-btn");
    if(btn){
      btn.onclick=()=>executeFuturesEntry(best);
      btn.setAttribute("aria-label","تنفيذ أفضل إشارة AI على Binance Futures");
    }
  }
}
async function spotEntryPreflight(signal){ return executeSpotEntry(signal); }

async function futuresEntryPreflight(signal){ return executeFuturesEntry(signal); }
async function executeSpotEntry(signal){
  const btn=document.querySelector(".spot-entry-btn");
  if(btn){btn.disabled=true;btn.textContent="جاري تنفيذ الأمر الحقيقي…";}
  try{
    const r=await fetch("/api/spot/entry",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(signal||{})});
    const d=await r.json().catch(()=>({}));
    if(!r.ok||!d.ok)throw new Error(d.message||"فشل تنفيذ أمر Binance Spot");
    const t=d.trade||{};
    alert("تم تنفيذ الشراء الحقيقي على Binance Spot\n"+(t.entry?"الدخول: "+futuresNum(t.entry)+"\n":"")+(t.tp_price?"TP1: "+futuresNum(t.tp_price)+"\n":"")+(t.sl_price?"الوقف: "+futuresNum(t.sl_price):""));
    loadMarket("spot","15m");
  }catch(e){
    alert(e.message||"تعذر تنفيذ الأمر الحقيقي");
    if(btn){btn.disabled=false;btn.textContent="دخول صفقة";}
  }
}

async function executeFuturesEntry(signal){
  const btn=document.querySelector(".futures-entry-btn");
  if(btn){btn.disabled=true;btn.textContent="جاري تنفيذ الأمر الحقيقي…";}
  try{
    const r=await fetch("/api/futures/entry",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(signal||{})});
    const d=await r.json().catch(()=>({}));
    if(!r.ok||!d.ok) throw new Error(d.message||"فشل تنفيذ أمر Binance Futures");
    const t=d.trade||{};
    alert("تم تنفيذ الصفقة الحقيقية على Binance Futures\n"+(t.entry?"الدخول: "+futuresNum(t.entry)+"\n":"")+(t.tp_price?"TP1: "+futuresNum(t.tp_price)+"\n":"")+(t.sl_price?"الوقف: "+futuresNum(t.sl_price):""));
    if(location.pathname==="/fast-futures") refreshFuturesPage(); else loadMarket("futures","15m");
  }catch(e){
    alert(e.message||"تعذر تنفيذ الأمر الحقيقي");
    if(btn){btn.disabled=false;btn.textContent="دخول صفقة";}
  }
}
function simplePage(title,body){app.innerHTML='<section class="panel"><div class="eyebrow">SMART TRADING PRO</div><h1>'+title+'</h1>'+body+'</section>'}
function loginPage(){simplePage("تسجيل الدخول",'<form id="loginForm" class="form"><input name="email" type="email" placeholder="البريد الإلكتروني" required><input name="password" type="password" placeholder="كلمة المرور" required><button class="btn primary">دخول</button><div id="formMsg" class="muted"></div></form>');document.getElementById("loginForm").onsubmit=async e=>{e.preventDefault();const r=await fetch("/api/login",{method:"POST",body:new FormData(e.target)}),d=await r.json();document.getElementById("formMsg").textContent=d.message||"تم";if(d.ok)location.href="/account"}}
function registerPage(){simplePage("إنشاء حساب",'<form id="registerForm" class="form"><input name="name" placeholder="الاسم" required><input name="email" type="email" placeholder="البريد الإلكتروني" required><input name="password" type="password" minlength="6" placeholder="كلمة المرور" required><button class="btn primary">إنشاء الحساب</button><div id="formMsg" class="muted"></div></form>');document.getElementById("registerForm").onsubmit=async e=>{e.preventDefault();const r=await fetch("/api/register",{method:"POST",body:new FormData(e.target)}),d=await r.json();document.getElementById("formMsg").textContent=d.message||"تم";if(d.ok)location.href="/account"}}
async function accountPage(){const r=await fetch("/api/me",{cache:"no-store"}),d=await r.json();if(!d.user){simplePage("حسابي",'<div class="empty">يجب تسجيل الدخول أولاً.<br><a class="btn primary" href="/login">تسجيل الدخول</a></div>');return}simplePage("حسابي",'<div class="account"><div class="breadth"><div class="breadth-card"><small>الاسم</small><b>'+esc(d.user.name)+'</b></div><div class="breadth-card"><small>البريد</small><b>'+esc(d.user.email)+'</b></div></div><button id="logout" class="btn">تسجيل الخروج</button></div>');document.getElementById("logout").onclick=async()=>{await fetch("/api/logout",{method:"POST"});location.href="/"}}
function blogPage(){simplePage("المدونة",'<div class="empty">المقالات والتحليلات ستظهر هنا من قاعدة البيانات.</div>')}
function adminLoginPage(){simplePage("دخول الإدارة",'<form id="adminLoginForm" class="form"><input name="username" autocomplete="username" placeholder="اسم مستخدم الإدارة" required><input name="password" type="password" autocomplete="current-password" placeholder="كلمة مرور الإدارة" required><button class="btn primary">دخول الإدارة</button><div id="formMsg" class="muted"></div></form>');document.getElementById("adminLoginForm").onsubmit=async e=>{e.preventDefault();const r=await fetch("/api/admin/login",{method:"POST",body:new FormData(e.target)}),d=await r.json().catch(()=>({}));document.getElementById("formMsg").textContent=d.message||"تم";if(d.ok)location.href="/admin"}
async function adminPage(){const r=await fetch("/api/me",{cache:"no-store"}),d=await r.json().catch(()=>({}));if(!d.user||!d.user.is_admin){location.href="/admin/login";return}simplePage("الإدارة",'<div class="empty">تم تسجيل دخول الإدارة. لوحة التحكم الخاصة بالإدارة هنا.</div>')}
function supportModal(){const box=document.createElement("div");box.className="modal-wrap";box.innerHTML='<div class="modal"><button class="icon-btn modal-close">×</button><h2>تواصل مع الدعم</h2><form id="supportForm" class="form"><input name="name" placeholder="الاسم" required><input name="email" type="email" placeholder="البريد الإلكتروني" required><textarea name="body" placeholder="رسالتك" required></textarea><button class="btn primary">إرسال</button><div id="supportMsg" class="muted"></div></form></div>';document.body.appendChild(box);box.querySelector(".modal-close").onclick=()=>box.remove();box.querySelector("form").onsubmit=async e=>{e.preventDefault();const r=await fetch("/api/support",{method:"POST",body:new FormData(e.target)}),d=await r.json();box.querySelector("#supportMsg").textContent=d.message||"تم";if(d.ok)setTimeout(()=>box.remove(),800)}}
supportOpen&&supportOpen.addEventListener("click",()=>{closeDrawer();supportModal()});
function route(){const p=location.pathname.split("/").filter(Boolean);if(p[0]==="fast-spot")return marketPage("spot");if(p[0]==="fast-futures")return marketPage("futures");if(p[0]==="fast-contracts")return marketPage("contracts");if(p[0]==="fast-us")return marketPage("us");if(p[0]==="fast-saudi")return marketPage("saudi");if(p[0]==="fast-forex")return marketPage("forex");if(p[0]==="login")return loginPage();if(p[0]==="register")return registerPage();if(p[0]==="account")return accountPage();if(p[0]==="blog")return blogPage();if(p[0]==="admin"&&p[1]==="login")return adminLoginPage();if(p[0]==="admin")return adminPage();return home()}
window.addEventListener("pageshow",closeDrawer);route();
