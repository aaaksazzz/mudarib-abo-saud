const $=s=>document.querySelector(s);const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));async function get(u){const r=await fetch(u);if(!r.ok)throw Error("HTTP "+r.status);return r.json()}function fmt(n){return Number(n).toLocaleString("en-US",{maximumFractionDigits:6})}function card(x){const c=x.change>0?"up":x.change<0?"down":"neutral";return '<a class="market-box" href="/coin/'+encodeURIComponent(x.symbol)+'"><div class="market-symbol"><b>'+esc(x.symbol)+'</b><span class="'+c+'">'+(x.change>0?"+":"")+fmt(x.change)+"%</span></div><strong>"+fmt(x.price)+"</strong><small>🎯 عرض الأهداف · حجم 24س · "+fmt(x.volume/1e6)+"M</small></a>"}
function homeTradeCard(x,i){
  const side=x.side==="شراء"?"buy":"sell";
  const market=x.market==="spot"?"🟢 سبوت":x.market==="futures"?"🔴 فيوتشر":x.market==="contracts"?"📑 عقود أمريكية":x.market==="us"?"🇺🇸 أمريكي":x.market==="saudi"?"🇸🇦 سعودي":"💱 فوركس";
  return '<article class="home-trade-card">'+
    '<div class="home-trade-head"><div><b>'+(i<3?["👑","🥈","🥉"][i]+" ":"")+esc(x.symbol)+'</b><small>'+market+' · '+esc(x.timeframe||"15د")+'</small></div><span class="home-ai">🤖 AI '+fmt(x.confidence||0)+'%</span></div>'+
    '<div class="home-trade-side '+side+'">'+esc(x.side)+'</div>'+
    '<div class="home-trade-levels">'+
      '<div><small>الدخول</small><b>'+fmt(x.entry)+'</b></div>'+
      '<div><small>🎯 TP1</small><b>'+fmt(x.tp1)+'</b><em>+'+Math.abs(Number(pctMove(x.entry,x.tp1))).toFixed(2)+'%</em></div>'+
      '<div><small>🎯 TP2</small><b>'+fmt(x.tp2)+'</b><em>+'+Math.abs(Number(pctMove(x.entry,x.tp2))).toFixed(2)+'%</em></div>'+
      '<div><small>🎯 TP3</small><b>'+fmt(x.tp3)+'</b><em>+'+Math.abs(Number(pctMove(x.entry,x.tp3))).toFixed(2)+'%</em></div>'+
      '<div class="home-stop"><small>🛑 وقف</small><b>'+fmt(x.stop)+'</b><em>-'+Math.abs(Number(pctMove(x.entry,x.stop))).toFixed(2)+'%</em></div>'+
    '</div>'+
    '<div class="home-trade-foot"><span>RSI '+fmt(x.rsi||0)+'</span><a href="/trades">متابعة الصفقة ←</a></div>'+
  '</article>';
}
let homeTradeMarket="all";
async function loadHomeTrades(){
  const grid=$("#homeTrades"), status=$("#homeTradeStatus"), filters=$("#homeTradeFilters"), mf=$("#homeMarketFilters");
  if(!grid)return;
  const frames=["15د","30د","1س","4س","يومي","أسبوعي","شهري"];
  const markets=[["all","🌐 الكل"],["spot","🟢 سبوت"],["futures","⚡ فيوتشر"],["contracts","📑 عقود أمريكية"],["us","🇺🇸 أمريكي"],["saudi","🇸🇦 سعودي"],["forex","💱 فوركس"]];
  if(filters && !filters.children.length){
    filters.innerHTML=frames.map((x,i)=>'<button type="button" class="home-filter '+(i===0?"active":"")+'" data-home-tf="'+x+'">'+x+'</button>').join("");
    filters.querySelectorAll("button").forEach(btn=>btn.addEventListener("click",()=>{filters.querySelectorAll("button").forEach(x=>x.classList.remove("active"));btn.classList.add("active");loadHomeTradesFrame(btn.dataset.homeTf);}));
  }
  if(mf && !mf.children.length){
    mf.innerHTML=markets.map((x,i)=>'<button type="button" class="home-market-filter '+(i===0?"active":"")+'" data-home-market="'+x[0]+'">'+x[1]+'</button>').join("");
    mf.querySelectorAll("button").forEach(btn=>btn.addEventListener("click",()=>{mf.querySelectorAll("button").forEach(x=>x.classList.remove("active"));btn.classList.add("active");homeTradeMarket=btn.dataset.homeMarket;loadHomeTradesFrame(filters?.querySelector(".active")?.dataset.homeTf||"30د");}));
  }
  await loadHomeTradesFrame(filters?.querySelector(".active")?.dataset.homeTf||"30د");
}
async function loadHomeTradesFrame(tf){
  const grid=$("#homeTrades"),status=$("#homeTradeStatus");if(!grid)return;
  status.textContent="جاري ترتيب التوصيات...";
  grid.innerHTML='<div class="loading-card">جاري فحص السوق وترتيب الفرص...</div>';
  try{
    const markets=homeTradeMarket==="all"?["spot","futures","contracts","us","saudi","forex"]:[homeTradeMarket];
    const responses=await Promise.all(markets.map(m=>get("/api/trades?market="+m+"&timeframe="+encodeURIComponent(tf))));
    let items=responses.flatMap(d=>(d.items||[]).map(x=>({...x,market:x.market||""})));
    const seen=new Set();
    items=items.filter(x=>{const k=x.id||[x.symbol,x.market,x.timeframe,x.entry].join("|");if(seen.has(k))return false;seen.add(k);return true;});
    items=items.map(x=>{const risk=Math.abs(Number(x.entry)-Number(x.stop));const reward=Math.abs(Number(x.tp2)-Number(x.entry));const rr=risk?reward/risk:0;return {...x,rr,rankScore:(Number(x.confidence)||0)+Math.min(15,rr*5)};});
    items.sort((a,b)=>(b.rankScore||0)-(a.rankScore||0));
    items=items.slice(0,10);
    grid.innerHTML=items.length?items.map(homeTradeCard).join(""):'<div class="loading-card">لا توجد توصيات مؤكدة لهذا الفريم حالياً</div>';
    status.textContent="مباشر · "+items.length+" توصيات مرتبة";
  }catch(e){status.textContent="تعذر التحديث";grid.innerHTML='<div class="loading-card">تعذر تحميل التوصيات حالياً</div>'}
}
async function loadHome(){
  try{
    const d=await get("/api/markets");const items=d.items||[];
    $("#marketCount").textContent=items.length+"+";
    $("#health").textContent="الاتصال يعمل";
    $("#markets").innerHTML=items.slice(0,6).map(card).join("")||'<div class="loading-card">لا توجد بيانات حالياً</div>';
    const pos=items.filter(x=>x.change>0).length,neg=items.filter(x=>x.change<0).length,vol=items.reduce((a,x)=>a+x.volume,0);
    $("#positiveCount").textContent=pos;$("#negativeCount").textContent=neg;$("#volumeCount").textContent=fmt(vol/1e9);
    try{const v=await get("/api/site-visitors");$("#siteVisitors").textContent=fmt(v.visits||0)}catch{}
    loadHomeTrades();
    loadOpportunities();
    loadHomePerformance();
  }catch{
    $("#health").textContent="تعذر الاتصال";
    $("#markets").innerHTML='<div class="loading-card">تعذر تحميل بيانات السوق</div>';
  }
}
async function loadHomePerformance(){
  try{
    const markets=["spot","futures","contracts","us","saudi","forex"];
    const responses=await Promise.all(markets.map(m=>get("/api/trade-tracker?market="+m).catch(()=>({stats:{}}))));
    const s=responses.reduce((a,d)=>{const z=d.stats||{};["open","closed","wins","losses"].forEach(k=>a[k]=(a[k]||0)+(Number(z[k])||0));a.pnl+=(Number(z.pnl_pct)||0);return a},{open:0,closed:0,wins:0,losses:0,pnl:0});
    const rate=s.closed?((s.wins/s.closed)*100):0;
    $("#hpOpen").textContent=s.open;$("#hpClosed").textContent=s.closed;$("#hpWin").textContent=s.wins;$("#hpLoss").textContent=s.losses;$("#hpRate").textContent=rate.toFixed(1)+"%";$("#hpPnl").textContent=(s.pnl>=0?"+":"")+s.pnl.toFixed(2)+"%";
  }catch{}
}
async function loadOpportunities(){try{const d=await get("/api/opportunities");const items=(d.items||[]).slice(0,8);$("#opportunities").innerHTML=items.length?items.map(x=>'<a class="opportunity-card" href="/scanner"><div class="opp-head"><b>'+esc(x.symbol)+'</b><span class="'+(x.signal==="شراء"?"buy":x.signal.includes("ارتداد")?"watch":"neutral")+'">'+esc(x.signal)+'</span></div><strong>'+fmt(x.price)+'</strong><div class="opp-bottom"><span class="'+(x.change>=0?"up":"down")+'">'+(x.change>0?"+":"")+fmt(x.change)+'%</span><small>ثقة '+fmt(x.confidence)+'%</small></div></a>').join(""):'<div class="loading-card">لا توجد فرص مؤكدة حالياً</div>'}catch{$("#opportunities").innerHTML='<div class="loading-card">تعذر تحليل الفرص حالياً</div>'}}async function loadMarkets(){try{const d=await get("/api/markets");$("#marketTable").innerHTML=d.items.map(x=>'<a class="row" href="/coin/'+encodeURIComponent(x.symbol)+'"><b>'+esc(x.symbol)+'</b><span>'+fmt(x.price)+'</span><span class="'+(x.change>=0?"up":"down")+'">'+fmt(x.change)+"%</span><span>🎯 الأهداف</span></a>").join("")}catch{$("#marketTable").innerHTML='<div class="card">تعذر تحميل البيانات</div>'}}
function pctMove(entry,price){const e=Number(entry),p=Number(price);if(!Number.isFinite(e)||!e)return "0.00";return (((p-e)/e)*100).toFixed(2)}
function tradePct(entry,price,label){const v=pctMove(entry,price);return (Number(v)>0?"+":"")+v+"% "+label}
async function loadMarketTrades(tf="30د"){
  const box=$("#marketTrades"), status=$("#marketTradeStatus"), tabs=$("#marketTimeframes");
  if(!box)return;
  const p=location.pathname;
  const market=p==="/spot"?"spot":p==="/futures"?"futures":p==="/contracts"?"contracts":p==="/us"?"us":p==="/saudi"?"saudi":p==="/forex"?"forex":"";
  const marketNames={spot:"سبوت",futures:"فيوتشر",contracts:"العقود الأمريكية",us:"السوق الأمريكي",saudi:"السوق السعودي",forex:"الفوركس والسلع"};
  if(!market)return;
  document.querySelectorAll(".market-name").forEach(x=>x.textContent=marketNames[market]||"");
  if(status)status.textContent="جاري تحليل "+tf+"...";
  box.innerHTML='<div class="loading-card">جاري استخراج صفقات '+tf+'...</div>';
  try{
    const d=await get("/api/market-trades/"+market+"?timeframe="+encodeURIComponent(tf));
    const items=d.items||[];
    box.innerHTML=items.length?items.map((x,i)=>'<article class="trade-card"><div class="trade-top"><b>'+(i<3?["👑","🥈","🥉"][i]+" ":"")+esc(x.symbol)+'</b><span>'+esc(x.timeframe)+'</span></div><div class="trade-meta-row"><span class="mini-badge ai-mini">🤖 AI '+fmt(x.confidence)+'%</span><span class="mini-badge">حركة '+fmt(x.movement)+'%</span><span class="mini-badge">RSI '+fmt(x.rsi)+'</span>'+(x.market==="futures"&&x.max_leverage?'<span class="mini-badge leverage-badge">⚡ رافعة '+fmt(x.max_leverage)+'x</span>':"")+'</div>'+(x.market==="contracts"?'<div class="trade-meta-row"><span class="mini-badge">📌 '+esc(x.contract_type||"")+"</span><span class="mini-badge">Strike "+fmt(x.strike)+"</span><span class="mini-badge">انتهاء "+esc(x.expiration||"")+"</span><span class="mini-badge">OI "+fmt(x.open_interest||0)+"</span></div>":"")+'<div class="trade-side '+(x.side==="شراء"?"buy":"sell")+'">'+esc(x.side)+'</div><div class="trade-line"><span>الدخول</span><b>'+fmt(x.entry)+'</b></div><div class="trade-line"><span>🎯 الهدف 1 <small class="trade-pct">('+tradePct(x.entry,x.tp1,"ربح")+')</small></span><b>'+fmt(x.tp1)+'</b></div><div class="trade-line"><span>🎯 الهدف 2 <small class="trade-pct">('+tradePct(x.entry,x.tp2,"ربح")+')</small></span><b>'+fmt(x.tp2)+'</b></div><div class="trade-line"><span>🎯 الهدف 3 <small class="trade-pct">('+tradePct(x.entry,x.tp3,"ربح")+')</small></span><b>'+fmt(x.tp3)+'</b></div><div class="trade-line stop-line"><span>🛑 وقف الخسارة <small class="trade-pct">(-'+Math.abs(Number(pctMove(x.entry,x.stop))).toFixed(2)+'% خسارة)</small></span><b>'+fmt(x.stop)+'</b></div></article>').join(""):'<div class="card empty">لا توجد صفقات مؤكدة لهذا الفريم حالياً.</div>';
    if(status)status.textContent="تم التحديث · "+items.length+" صفقة";
  }catch(e){
    if(status)status.textContent="تعذر التحليل";
    box.innerHTML='<div class="card empty">تعذر تحميل صفقات هذا الفريم حالياً.</div>';
  }
}
function setupMarketTimeframes(){
  const tabs=$("#marketTimeframes"); if(!tabs)return;
  const frames=["15د","30د","1س","4س","يومي","أسبوعي","شهري"];
  tabs.innerHTML=frames.map((x,i)=>'<button type="button" class="trade-tab '+(i===1?"active":"")+'" data-market-tf="'+x+'">'+x+'</button>').join("");
  tabs.querySelectorAll("button").forEach(b=>b.addEventListener("click",()=>{
    tabs.querySelectorAll("button").forEach(x=>x.classList.remove("active"));
    b.classList.add("active"); loadMarketTrades(b.dataset.marketTf);
  }));
  loadMarketTrades("15د");
}

async function auth(form,url,msg){form?.addEventListener("submit",async e=>{e.preventDefault();const b=form.querySelector("button");b.disabled=true;$(msg).textContent="جارٍ التحقق...";try{const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams(new FormData(form))});const d=await r.json();if(!r.ok)throw Error(d.error||"تعذر التنفيذ");location.href="/"}catch(e){$(msg).textContent=e.message}finally{b.disabled=false}})}const TRADE_MARKETS=[["all","🌐 الكل"],["spot","🟢 سبوت"],["futures","🔴 فيوتشر"],["contracts","📑 عقود أمريكية"],["us","🇺🇸 أمريكي"],["saudi","🇸🇦 سعودي"],["forex","💱 فوركس/سلع"]];

function copyTrade(x){
  const txt="📌 "+x.symbol+" · "+(x.market||"spot")+" · "+x.timeframe+"\n"+
    "📊 الاتجاه: "+x.side+"\n"+
    "💰 الدخول: "+fmt(x.entry)+"\n"+
    "🎯 TP1: "+fmt(x.tp1)+" ("+tradePct(x.entry,x.tp1,"ربح")+")\n"+
    "🎯 TP2: "+fmt(x.tp2)+" ("+tradePct(x.entry,x.tp2,"ربح")+")\n"+
    "🎯 TP3: "+fmt(x.tp3)+" ("+tradePct(x.entry,x.tp3,"ربح")+")\n"+
    "🛑 الوقف: "+fmt(x.stop)+" (-"+Math.abs(Number(pctMove(x.entry,x.stop))).toFixed(2)+"% خسارة)\n"+
    "🤖 AI: "+fmt(x.confidence||0)+"%";
  const done=()=>{const b=document.querySelector('[data-copy-id="'+x.id+'"]');if(b){b.textContent="✓ تم النسخ";setTimeout(()=>b.textContent="📋 نسخ التوصية",1500);}};
  if(navigator.clipboard?.writeText) navigator.clipboard.writeText(txt).then(done).catch(()=>fallbackCopy(txt,done)); else fallbackCopy(txt,done);
}
function fallbackCopy(txt,done){const t=document.createElement("textarea");t.value=txt;t.style.position="fixed";t.style.opacity="0";document.body.appendChild(t);t.select();try{document.execCommand("copy");done();}catch(e){}t.remove();}
function trackerCard(x,i){
  const status=x.status==="closed"?"مغلقة":"مفتوحة";
  const state=x.status==="closed"?(x.pnl_pct>0?"ربح":"خسارة"):(x.reached_tp3?"الهدف 3":x.reached_tp2?"الهدف 2":x.reached_tp1?"الهدف 1":"مفتوحة");
  return '<article class="trade-card tracker-card">'+
    '<div class="trade-top"><b>'+(i<3?["👑","🥈","🥉"][i]+" ":"")+esc(x.symbol)+'</b><span>'+esc(x.market||"spot")+' · '+esc(x.timeframe)+'</span></div>'+
    '<div class="trade-meta-row"><span class="mini-badge ai-mini">🤖 AI '+fmt(x.confidence||0)+'%</span><span class="mini-badge">'+esc(state)+'</span><span class="mini-badge">'+esc(status)+'</span></div>'+
    '<div class="trade-side '+(x.side==="شراء"?"buy":"sell")+'">'+esc(x.side)+'</div>'+
    '<div class="trade-line"><span>الدخول</span><b>'+fmt(x.entry)+'</b></div>'+
    '<div class="trade-line"><span>🎯 الهدف 1 <small class="trade-pct">('+tradePct(x.entry,x.tp1,"ربح")+')</small></span><b>'+fmt(x.tp1)+'</b></div>'+
    '<div class="trade-line"><span>🎯 الهدف 2 <small class="trade-pct">('+tradePct(x.entry,x.tp2,"ربح")+')</small></span><b>'+fmt(x.tp2)+'</b></div>'+
    '<div class="trade-line"><span>🎯 الهدف 3 <small class="trade-pct">('+tradePct(x.entry,x.tp3,"ربح")+')</small></span><b>'+fmt(x.tp3)+'</b></div>'+
    '<div class="trade-line stop-line"><span>🛑 وقف الخسارة <small class="trade-pct">(-'+Math.abs(Number(pctMove(x.entry,x.stop))).toFixed(2)+'% خسارة)</small></span><b>'+fmt(x.stop)+'</b></div>'+
    (x.status==="closed"?'<div class="trade-result '+(x.pnl_pct>0?"profit":"loss")+'">'+(x.pnl_pct>0?"🟢 ربح ":"🔴 خسارة ")+fmt(x.pnl_pct)+'%</div>':'<div class="trade-result live">🟡 الصفقة مفتوحة</div>')+
    '<button type="button" class="copy-trade-btn" data-copy-id="'+esc(String(x.id||""))+'" onclick="copyTrade('+JSON.stringify(x).replace(/</g,"\\u003c")+')">📋 نسخ التوصية</button>'+
    '</article>';
}
async function loadTrades(tf="",market="all"){
  const status=$("#tradeStatus"),grid=$("#tradesGrid"),statsBox=$("#tradeStats");
  if(!grid)return;
  status.textContent="جاري تحديث متابع الصفقات...";
  grid.innerHTML='<div class="loading-card">جاري تحميل الصفقات وتحديث حالتها...</div>';
  try{
    const markets=market==="all"?["spot","futures","contracts","us","saudi","forex"]:[market];
    const responses=await Promise.all(markets.map(m=>get("/api/trades?market="+m+(tf?"&timeframe="+encodeURIComponent(tf):""))));
    let items=responses.flatMap(d=>d.items||[]);
    const seen=new Set();
    items=items.filter(x=>{const k=x.id||[x.symbol,x.market,x.timeframe,x.entry].join("|");if(seen.has(k))return false;seen.add(k);return true;});
    items.sort((a,b)=>(b.confidence||0)-(a.confidence||0));
    const stats=responses.reduce((a,d)=>{const z=d.stats||{};["total","open","closed","wins","losses"].forEach(k=>a[k]=(a[k]||0)+(Number(z[k])||0));a.pnl_pct=(a.pnl_pct||0)+(Number(z.pnl_pct)||0);return a;},{total:0,open:0,closed:0,wins:0,losses:0,pnl_pct:0});
    stats.win_rate=stats.closed?Math.round(stats.wins/stats.closed*1000)/10:0;
    const profitItems=items.filter(x=>x.status==="closed"&&Number(x.pnl_pct)>0);
    const lossItems=items.filter(x=>x.status==="closed"&&Number(x.pnl_pct)<=0);
    const profitPct=profitItems.reduce((a,x)=>a+Number(x.pnl_pct||0),0);
    const lossPct=Math.abs(lossItems.reduce((a,x)=>a+Number(x.pnl_pct||0),0));
    if(statsBox){
      const p=stats.periods||{};
      const periodCard=(label,key)=>{const z=p[key]||{trades:0,wins:0,losses:0,profit_pct:0,loss_pct:0,pnl_pct:0};
        return '<div class="trade-period"><strong>'+label+'</strong><span>🟢 '+z.wins+' رابحة · 🔴 '+z.losses+' خاسرة</span><span>💰 +'+fmt(z.profit_pct)+'% · 📉 -'+fmt(z.loss_pct)+'%</span><b>صافي '+(Number(z.pnl_pct)>=0?'+':'')+fmt(z.pnl_pct)+'%</b></div>';};
      statsBox.innerHTML=
        '<div><b>'+stats.wins+'</b><small>🟢 رابحة</small></div>'+
        '<div><b>'+stats.losses+'</b><small>🔴 خاسرة</small></div>'+
        '<div><b>'+fmt(profitPct)+'%</b><small>💰 إجمالي الربح</small></div>'+
        '<div><b>'+fmt(lossPct)+'%</b><small>📉 إجمالي الخسارة</small></div>'+
        '<div><b>'+fmt(stats.win_rate)+'%</b><small>📊 نسبة النجاح</small></div>'+
        '<div><b>'+fmt(stats.pnl_pct)+'%</b><small>📈 صافي P/L</small></div>'+
        periodCard('آخر ساعة','hour')+
        periodCard('آخر 24 ساعة','day')+
        periodCard('آخر 7 أيام','week')+
        periodCard('آخر سنة','year');
    }
    grid.innerHTML=items.length?items.map(trackerCard).join(""):'<div class="card empty">لا توجد صفقات مسجلة حالياً.</div>';
    status.textContent="تم التحديث · "+items.length+" صفقة · آخر تحديث "+new Date().toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"});
  }catch(e){
    status.textContent="تعذر تحديث المتابعة";
    grid.innerHTML='<div class="card empty">تعذر تحميل الصفقات حالياً. حاول التحديث بعد قليل.</div>';
  }
}
function setupTrades(){
  const tabs=$("#tradeTabs"), markets=$("#tradeMarkets"); if(!tabs)return;
  const frames=["15د","30د","1س","4س","يومي","أسبوعي","شهري"];
  tabs.innerHTML=frames.map((x,i)=>'<button type="button" class="trade-tab '+(i===0?"active":"")+'" data-tf="'+x+'">'+x+'</button>').join("");
  if(markets){
    markets.innerHTML=TRADE_MARKETS.map((m,i)=>'<button type="button" class="trade-tab '+(i===0?"active":"")+'" data-market="'+m[0]+'">'+m[1]+'</button>').join("");
    markets.querySelectorAll("button").forEach(b=>b.addEventListener("click",()=>{
      markets.querySelectorAll("button").forEach(x=>x.classList.remove("active"));b.classList.add("active");
      const tf=document.querySelector("#tradeTabs .active")?.dataset.tf||"15د";
      loadTrades(tf,b.dataset.market);
    }));
  }
  tabs.querySelectorAll("button").forEach(b=>b.addEventListener("click",()=>{
    tabs.querySelectorAll("button").forEach(x=>x.classList.remove("active"));b.classList.add("active");
    const market=markets?.querySelector(".active")?.dataset.market||"all";
    loadTrades(b.dataset.tf,market);
  }));
  loadTrades("15د","all");
  setInterval(()=>{
    const tf=tabs.querySelector(".active")?.dataset.tf||"15د", market=markets?.querySelector(".active")?.dataset.market||"all";
    loadTrades(tf,market);
  },180000);
}
async function loadNews(){
  const box=$("#newsList"); if(!box)return;
  box.innerHTML='<div class="loading-card">جاري جلب الأخبار...</div>';
  try{
    const d=await get("/api/news"); const items=Array.isArray(d)?d:(d.items||[]);
    if(!items.length){box.innerHTML='<div class="loading-card">لا توجد أخبار حالياً</div>';return;}
    box.innerHTML=items.map(x=>'<article class="news-card"><small>'+esc(x.source||"موجز المضارب")+' · '+esc(x.time||"الآن")+'</small><h3>'+esc(x.title||"خبر جديد")+'</h3><p>'+esc(x.summary||"آخر مستجدات الأسواق والتحركات المالية.")+'</p></article>').join("");
  }catch(e){box.innerHTML='<div class="loading-card">تعذر جلب الأخبار حالياً — حاول التحديث مرة أخرى.</div>';}
}
async function loadScanner(tf="15د"){
  const grid=$("#scannerGrid"); if(!grid)return;
  const filter=$("#filter");
  grid.innerHTML='<div class="loading-card">جاري فحص الأسواق واستخراج الصفقات...</div>';
  try{
    const markets=["spot","futures","contracts","us","saudi","forex"];
    const responses=await Promise.all(markets.map(m=>get("/api/trades?market="+m+"&timeframe="+encodeURIComponent(tf)).catch(()=>({items:[]}))));
    let items=responses.flatMap(d=>d.items||[]);
    const seen=new Set();
    items=items.filter(x=>{const k=x.id||[x.symbol,x.market,x.timeframe,x.entry].join("|");if(seen.has(k))return false;seen.add(k);return true;});
    const q=(filter?.value||"").trim().toUpperCase();
    if(q)items=items.filter(x=>String(x.symbol).toUpperCase().includes(q));
    items=items.map(x=>{const risk=Math.abs(Number(x.entry)-Number(x.stop));const reward=Math.abs(Number(x.tp2)-Number(x.entry));const rr=risk?reward/risk:0;return {...x,rr,rankScore:(Number(x.confidence)||0)+Math.min(15,rr*5)};});
    items.sort((a,b)=>(b.rankScore||0)-(a.rankScore||0));
    items=items.slice(0,70);
    grid.innerHTML=items.length?items.map((x,i)=>'<article class="trade-card scanner-trade-card"><div class="trade-top"><b>'+(i<3?["👑","🥈","🥉"][i]+" ":"")+esc(x.symbol)+'</b><span>'+esc(x.market||"")+" · "+esc(x.timeframe||tf)+'</span></div><div class="trade-meta-row"><span class="mini-badge ai-mini">🤖 AI '+fmt(x.confidence||0)+'%</span><span class="mini-badge">RSI '+fmt(x.rsi||0)+'</span><span class="mini-badge">R:R '+fmt(x.rr||0)+'</span></div><div class="trade-side '+(x.side==="شراء"?"buy":"sell")+'">'+esc(x.side)+'</div><div class="trade-line"><span>الدخول</span><b>'+fmt(x.entry)+'</b></div><div class="trade-line"><span>🎯 الهدف 1</span><b>'+fmt(x.tp1)+'</b></div><div class="trade-line"><span>🎯 الهدف 2</span><b>'+fmt(x.tp2)+'</b></div><div class="trade-line"><span>🎯 الهدف 3</span><b>'+fmt(x.tp3)+'</b></div><div class="trade-line stop-line"><span>🛑 وقف الخسارة</span><b>'+fmt(x.stop)+'</b></div></article>').join(""):'<div class="loading-card">لا توجد صفقات مؤكدة لهذا الفريم حالياً</div>';
  }catch(e){grid.innerHTML='<div class="loading-card">تعذر تشغيل الماسح حالياً</div>'}
}
function setupBreakingNews(){
  if(document.querySelector(".breaking-bar"))return;
  const header=document.querySelector("header"); if(!header || location.pathname!=="/")return;
  const bar=document.createElement("div"); bar.className="breaking-bar";
  bar.innerHTML='<div class="breaking-label">🔴 عاجل</div><div class="breaking-track"><div class="breaking-content">جاري جلب آخر أخبار الأسواق...</div></div>';
  header.insertAdjacentElement("afterend",bar);
  get("/api/news").then(d=>{
    const items=Array.isArray(d)?d:(d.items||[]);
    const titles=items.slice(0,12).map(x=>String(x.title||"خبر جديد").trim()).filter(Boolean);
    bar.querySelector(".breaking-content").textContent=titles.length?titles.join("   •   "):"آخر أخبار الأسواق والتحركات المالية أولاً بأول";
  }).catch(()=>{bar.querySelector(".breaking-content").textContent="آخر أخبار الأسواق والتحركات المالية أولاً بأول";});
}
function setup(){setupBreakingNews();const menu=$("#menu"),drawer=$("#drawer"),backdrop=$("#drawerBackdrop");
function closeDrawer(e){if(e)e.stopPropagation();drawer?.classList.remove("open");drawer?.setAttribute("aria-hidden","true");menu?.setAttribute("aria-expanded","false")}
function toggleDrawer(e){if(e){e.preventDefault();e.stopPropagation()}if(!drawer||!menu)return;const open=!drawer.classList.contains("open");drawer.classList.toggle("open",open);drawer.setAttribute("aria-hidden",String(!open));menu.setAttribute("aria-expanded",String(open))}
if(menu){let handled=0;const tap=e=>{const now=Date.now();if(now-handled<450)return;handled=now;toggleDrawer(e)};menu.addEventListener("pointerup",tap,{passive:false});menu.addEventListener("click",tap)}
backdrop?.addEventListener("click",closeDrawer);
drawer?.querySelectorAll("a").forEach(a=>a.addEventListener("click",closeDrawer));
$("#theme")?.addEventListener("click",()=>{document.body.classList.toggle("light");localStorage.theme=document.body.classList.contains("light")?"light":"dark"});if(localStorage.theme==="light")document.body.classList.add("light");if($("#opportunities"))loadHome();setupTrades();if($("#marketTrades")){setupMarketTimeframes();loadMarketTrades("30د");}if($("#coinTargets"))loadCoin();if($("#newsList"))loadNews();if($("#scannerGrid")){loadScanner();$("#refresh")?.addEventListener("click",()=>loadScanner(document.querySelector(".scanner-tf.active")?.dataset.tf||"15د"));$("#filter")?.addEventListener("input",()=>loadScanner(document.querySelector(".scanner-tf.active")?.dataset.tf||"15د"));document.querySelectorAll(".scanner-tf").forEach(b=>b.addEventListener("click",()=>{document.querySelectorAll(".scanner-tf").forEach(x=>x.classList.remove("active"));b.classList.add("active");loadScanner(b.dataset.tf)}));}auth($("#loginForm"),"/api/login","#loginMsg");auth($("#registerForm"),"/api/register","#registerMsg")}document.addEventListener("DOMContentLoaded",setup);
async function loadCoin(){
  const title=$("#coinTitle"), summary=$("#coinSummary"), grid=$("#coinTargets"), status=$("#coinStatus");
  if(!grid)return;
  const symbol=decodeURIComponent(location.pathname.split("/").pop()||"").toUpperCase();
  try{
    const d=await get("/api/coin/"+encodeURIComponent(symbol));
    title.textContent=d.asset.symbol;
    summary.innerHTML='<div class="coin-summary-main"><div><small>السعر الحالي</small><strong class="coin-price">'+fmt(d.asset.price)+'</strong></div><div class="coin-change '+(d.asset.change>=0?"up":"down")+'">'+(d.asset.change>0?"+":"")+fmt(d.asset.change)+'%</div></div><div class="coin-summary-meta"><span>📊 حجم 24س</span><b>'+fmt(d.asset.volume/1e6)+'M</b><span>📌 الرمز</span><b>'+esc(d.asset.symbol)+'</b></div>';
    grid.innerHTML=d.signals?.length?d.signals.map(x=>'<article class="coin-signal-card"><div class="coin-signal-head"><div><b>'+esc(x.timeframe)+'</b><small>الفريم</small></div><span class="coin-ai">🤖 AI '+fmt(x.confidence)+'%</span></div><div class="coin-signal-side '+(x.side==="شراء"?"buy":"sell")+'">'+esc(x.side)+'</div><div class="coin-levels"><div><small>الدخول</small><b>'+fmt(x.entry)+'</b></div><div><small>🎯 الهدف</small><b>'+fmt(x.target)+'</b></div><div><small>🛑 الوقف</small><b>'+fmt(x.stop)+'</b></div></div><div class="coin-signal-foot"><span>RSI '+fmt(x.rsi)+'</span><span>إشارة تحليلية</span></div></article>').join(""):'<div class="card empty">لا توجد إشارة مؤكدة حالياً، لكن بيانات العملة متاحة.</div>';
    status.textContent="تم التحليل · "+(d.signals?.length||0)+" فريم";
  }catch(e){title.textContent=symbol;summary.innerHTML='<div class="loading-card">تعذر تحميل بيانات العملة</div>';grid.innerHTML='<div class="card empty">تأكد من الرمز وحاول مرة ثانية.</div>'}
}
async function setupAssetSearch(){
  const input=$("#assetSearch"), btn=$("#assetSearchBtn"), clear=$("#assetSearchClear"), box=$("#assetSearchResults");
  if(!input||!box)return;
  let timer;
  function render(items,q){
    if(!q){box.innerHTML="";box.classList.remove("show");return}
    box.innerHTML=items.length?items.slice(0,12).map(x=>{
      const label=x.market==="spot"?"🟢 سبوت":x.market==="futures"?"🔴 فيوتشر":x.market==="us"?"🇺🇸 أمريكي":x.market==="saudi"?"🇸🇦 سعودي":"💱 فوركس و سلع";
      return '<a class="search-result-item" href="/asset/'+encodeURIComponent(x.market)+'/'+encodeURIComponent(x.symbol)+'"><span class="search-result-icon">'+label.split(" ")[0]+'</span><span class="search-result-main"><b>'+esc(x.symbol)+'</b><small>'+esc(x.name||"")+'</small></span><em>'+esc(label)+'</em></a>';
    }).join(""):'<div class="search-empty">ما لقيت أصل بهذا الاسم</div>';
    box.classList.add("show");
  }
  async function search(){
    const q=input.value.trim();
    if(!q){render([],q);return}
    box.innerHTML='<div class="search-empty">جاري البحث…</div>';box.classList.add("show");
    try{
      const d=await get("/api/asset-search?q="+encodeURIComponent(q));
      render(d.items||[],q);
    }catch{box.innerHTML='<div class="search-empty">تعذر البحث حالياً — جرّب مرة ثانية</div>';box.classList.add("show")}
  }
  input.addEventListener("input",()=>{clearTimeout(timer);timer=setTimeout(search,180)});
  btn?.addEventListener("click",search);
  clear?.addEventListener("click",()=>{input.value="";render([],"");input.focus()});
  input.addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();search()}});
  document.addEventListener("click",e=>{if(!e.target.closest(".asset-search"))box.classList.remove("show")});
}
