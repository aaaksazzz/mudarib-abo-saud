(function(){
"use strict";
function $(id){return document.getElementById(id);}
function esc(x){return String(x==null?"":x).replace(/[&<>"']/g,function(m){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m];});}
function num(x){return Number(x||0).toLocaleString("en-US",{maximumFractionDigits:8});}
function updateSiteStatus(){
 var dot=$("siteStatus"),txt=$("siteStatusText"); if(!dot||!txt)return;
 api("/api/status").then(function(d){txt.textContent="متصل · التحليل محدث";dot.classList.add("online");dot.classList.remove("offline");})
 .catch(function(){txt.textContent="الخدمة تعمل بوضع احتياطي";dot.classList.remove("online");dot.classList.add("offline");});
}
function showGlobalToast(message,type){
 var el=$("globalToast"); if(!el){el=document.createElement("div");el.id="globalToast";el.className="global-toast";document.body.appendChild(el);}
 el.textContent=message;el.className="global-toast "+(type||"");
 clearTimeout(window.__toastTimer);window.__toastTimer=setTimeout(function(){el.classList.remove("show");},2600);requestAnimationFrame(function(){el.classList.add("show");});
}
function updateAuthUI(){
 var box=$("authArea"); if(!box)return;
 api("/api/me").then(function(d){
   var u=d.user;
   if(!u){
     box.innerHTML='<a class="top-icon" href="/login" title="تسجيل الدخول">🔐</a><a class="top-icon" href="/register" title="إنشاء حساب">📝</a>';
     return;
   }
   var name=esc(u.name||u.username||"حسابي");
   var admin=d.admin?'<a class="auth-user-link" href="/admin" title="لوحة الإدارة">🛡️</a>':"";
   box.innerHTML='<span class="auth-user" title="'+name+'">👤 '+name+'</span>'+admin+'<button class="top-icon" id="logoutTop" type="button" title="تسجيل الخروج">🚪</button>';
   var out=$("logoutTop"); if(out)out.onclick=async function(){try{await api("/api/auth/logout",{method:"POST"});location.href="/";}catch(e){alert(e.message);}};
 }).catch(function(){});
}
async function api(url,opts){
 opts=opts||{};
 var headers={"Content-Type":"application/json"};
 if(opts.headers){Object.assign(headers,opts.headers);}
 var res=await fetch(url,{cache:"no-store",credentials:"same-origin",method:opts.method||"GET",body:opts.body||undefined,headers:headers});
 var data=await res.json().catch(function(){return {};});
 if(!res.ok||data.ok===false){throw new Error(data.message||"حدث خطأ في الخادم");}
 return data;
}
function sortSignalsByAI(items){
  return (Array.isArray(items)?items:[]).slice().sort((a,b)=>{
    const ca=Number(a?.confidence ?? a?.ai_confidence ?? 0);
    const cb=Number(b?.confidence ?? b?.ai_confidence ?? 0);
    if(cb!==ca)return cb-ca;
    const ra=Number(a?.researchScore ?? 0), rb=Number(b?.researchScore ?? 0);
    if(rb!==ra)return rb-ra;
    const sa=Number(a?.strength ?? 0), sb=Number(b?.strength ?? 0);
    return sb-sa;
  });
}
function strengthBadge(x,rank){
 var medal=rank===1?"👑":rank===2?"🥈":rank===3?"🥉":"";
 return '<span class="rank-badge" title="ترتيب الفرص">'+rank+' : '+medal+'</span>';
}
function card(x,rank){
 var cls=x.direction==="شراء"?"buy":x.direction==="بيع"?"sell":"neutral";
 var optionType=x.market==="contracts"?(x.direction==="شراء"?"📈 CALL":"📉 PUT"):"";
 var typeHtml=optionType?'<span class="signal '+cls+'" style="margin-inline-start:8px">'+optionType+"</span>":"";
 var rankHtml=rank?strengthBadge(x,rank):"";
 return '<article class="trade"><div class="trade-top"><div><div class="symbol">'+rankHtml+' '+esc(x.displayName||x.symbol)+'</div><small>'+esc(x.symbol)+' · '+esc(x.interval)+' · 🤖 AI</small></div><div><b class="signal '+cls+'">'+esc(x.signal)+'</b>'+typeHtml+'</div></div><h3>دخول: '+num(x.entry)+'</h3><div class="levels"><div class="level"><small>TP1</small>'+num(x.tp1)+'</div><div class="level"><small>TP2</small>'+num(x.tp2)+'</div><div class="level"><small>TP3</small>'+num(x.tp3)+'</div><div class="level"><small>SL</small>'+num(x.sl)+'</div></div><div class="meta">'+(rankHtml?rankHtml+' · ':"")+'ثقة AI: '+num(x.confidence)+'% · R:R '+num(x.rr)+'</div></article>';
}
function spotHistoryKey(market,interval){return "mudarib_spot_history_v2_"+market+"_"+interval;}
function readSpotHistory(market,interval){
 try{return JSON.parse(localStorage.getItem(spotHistoryKey(market,interval))||"[]");}catch(e){return [];}
}
function writeSpotHistory(market,interval,items){
 try{localStorage.setItem(spotHistoryKey(market,interval),JSON.stringify(items.slice(-200)));}catch(e){}
}
function mergeMarketSignals(market,interval,fresh){
 var old=readSpotHistory(market,interval),seen={};
 old.forEach(function(x){seen[x.symbol+"|"+x.interval+"|"+x.entry+"|"+x.tp1+"|"+x.tp2+"|"+x.tp3+"|"+x.sl]=true;});
 fresh.forEach(function(x){
  var key=x.symbol+"|"+x.interval+"|"+x.entry+"|"+x.tp1+"|"+x.tp2+"|"+x.tp3+"|"+x.sl;
  if(!seen[key]){old.push(x);seen[key]=true;}
 });
 old=sortSignalsByAI(old);
 writeSpotHistory(market,interval,old);
 return old;
}
function mergeSpotSignals(market,interval,fresh){return mergeMarketSignals(market,interval,fresh);}
async function loadMarket(market,interval,box,replaceLoading){
 if(!box)return;
 if(replaceLoading!==false)box.innerHTML='<div class="empty">🤖 جاري التحقق...</div>';
 try{
  var me=await api("/api/me");
  var paid=(me.paid_markets||[]).indexOf(market)!==-1;
  if(paid && !me.subscription_active && !me.admin){
   box.innerHTML='<div class="empty">🔐 هذا القسم يحتاج اشتراكاً فعالاً.<br><a class="btn" href="/subscription">💳 عرض الباقات والاشتراك</a></div>';
   return;
  }
 }catch(e){}
 if(replaceLoading!==false)box.innerHTML='<div class="empty">🤖 جاري التحليل...</div>';
 try{
  var d=await api("/api/ai/signals?market="+encodeURIComponent(market)+"&interval="+encodeURIComponent(interval)+"&limit=20");
  var all=d.results||[];
  var results=all.filter(function(x){
    var ready=(x.tradeReady===true || x.trade_ready===true);
    return ready && (x.direction==="شراء" || x.direction==="بيع");
  });
  results=sortSignalsByAI(results);
  // Keep a separate history for every market + timeframe so changing timeframe
  // never destroys the previous results.
  results=sortSignalsByAI(mergeMarketSignals(market,interval,results));
  if(!results.length && all.length)results=sortSignalsByAI(all);
  box.innerHTML=results.length?results.map(function(x,i){x._aiRank=i+1;return card(x,i+1);}).join(""):'<div class="empty">لا توجد صفقات قوية حالياً. الفحص الآلي يعمل كل 3 دقائق.</div>';
 }catch(e){
  var saved=readSpotHistory(market,interval);
  if(saved.length){
   var savedSorted=sortSignalsByAI(saved).slice(0,20);
   box.innerHTML=savedSorted.map(function(x,i){x._aiRank=i+1;return card(x,i+1);}).join("");
   return;
  }
  box.innerHTML='<div class="empty">⚠️ '+esc(e.message)+'</div>';
 }
}
function section(){
 var box=$("market"),page=document.body.getAttribute("data-page");
 var map={spot:["crypto","15m"],futures:["futures","15m"],contracts:["contracts","15m"],saudi:["saudi","1D"],usmarket:["usmarket","1D"],forex:["forex","1H"]};
 var cfg=map[page];
 if(!box||!cfg)return;
 var market=cfg[0],def=cfg[1],buttons=document.querySelectorAll("[data-i]");
 buttons.forEach(function(btn){btn.addEventListener("click",function(){buttons.forEach(function(x){x.classList.remove("active");});btn.classList.add("active");loadMarket(market,btn.getAttribute("data-i"),box);});});
 var first=document.querySelector('[data-i="'+def+'"]');
 if(first)first.classList.add("active");
 var refresh=$("refresh");
 if(refresh)refresh.addEventListener("click",function(){var a=document.querySelector("[data-i].active");loadMarket(market,a?a.getAttribute("data-i"):def,box);});
 loadMarket(market,def,box);
 var timerKey="mudaribAuto_"+page;
 if(window[timerKey])clearInterval(window[timerKey]);
 window[timerKey]=setInterval(function(){var a=document.querySelector("[data-i].active");loadMarket(market,a?a.getAttribute("data-i"):def,box,false);},180000);
}
function marketName(m){return {crypto:"🟢 العملات الرقمية",futures:"🔵 كريبتو فيوتشر",contracts:"🇺🇸 العقود الآجلة الأمريكية",saudi:"🇸🇦 السوق السعودي",usmarket:"🇺🇸 السوق الأمريكي",forex:"💱 الفوركس والسلع"}[m]||m;}
function overviewCard(x){
 var total=x.total||0;
 return '<article class="market-card"><div class="market-head"><h3>'+marketName(x.market)+'</h3><span>'+esc(x.interval)+'</span></div><div class="market-counts"><div><b class="up">'+x.up+'</b><small>صاعد</small></div><div><b class="down">'+x.down+'</b><small>هابط</small></div><div><b class="flat">'+x.neutral+'</b><small>محايد</small></div><div><b>'+total+'</b><small>الإجمالي</small></div></div><div class="market-bar"><i style="width:'+((x.up/Math.max(total,1))*100)+'%"></i></div><p class="muted">أقوى إشارة: '+esc(x.top||"لا توجد")+' · ثقة '+num(x.confidence||0)+'%</p><a class="btn" href="'+(x.market==="crypto"?"/spot":x.market==="futures"?"/futures":x.market==="contracts"?"/contracts":x.market==="saudi"?"/saudi":x.market==="usmarket"?"/usmarket":"/forex")+'">عرض السوق بالكامل</a></article>';
}
async function homeOverview(){
 var box=$("marketOverview"); if(!box)return;
 try{
  var d=await api("/api/home/overview");
  box.innerHTML=(d.markets||[]).map(overviewCard).join("")||'<div class="empty">لا توجد بيانات حالياً.</div>';
 }catch(e){box.innerHTML='<div class="empty">⚠️ '+esc(e.message)+'</div>';}
}
function newsTime(x){try{return new Date(x).toLocaleString("ar-SA",{hour:"2-digit",minute:"2-digit",day:"numeric",month:"short"});}catch(e){return x||"";}}
function newsCard(x){
 var slug=String(x.slug||"").trim();
 var href=slug?"/news/"+encodeURIComponent(slug):"/news";
 return '<a class="news-card news-card-native" href="'+href+'"><div class="news-source"><span>📰 '+esc(x.source||"أخبار الأسواق")+'</span><span>'+esc(newsTime(x.published))+'</span></div><div class="news-badge">داخل الموقع</div><h3>'+esc(x.title)+'</h3><p>'+esc(x.description||"")+'</p><div class="news-footer"><span>📌 ملخص السوق</span><span>قراءة الخبر ←</span></div></a>';
}
async function homeNews(){
 var box=$("homeNews");if(!box)return;
 try{
  var d=await api("/api/live-news");
  box.innerHTML=(d.news||[]).map(newsCard).join("")||'<div class="empty">لا توجد أخبار متاحة حالياً.</div>';
  var ticker=$("newsTicker");
  if(ticker){var items=(d.news||[]).slice(0,15);ticker.innerHTML=items.map(function(x){return '<span class="ticker-item">🔴 '+esc(x.title)+'</span>';}).join("　 •　 ")||'<span>لا توجد أخبار حالياً</span>';}
  var u=$("newsUpdated");if(u)u.textContent="● آخر تحديث "+newsTime(d.updatedAt);
 }catch(e){box.innerHTML='<div class="empty">⚠️ تعذر تحديث الأخبار حالياً</div>';}
}
async function homeOpportunities(){
 var box=$("home");if(!box)return;
 box.innerHTML='<div class="empty">🔥 جاري البحث عن أفضل الفرص الآن...</div>';
 try{
  var d=await api("/api/home/opportunities");
  var rows=sortSignalsByAI(d.opportunities||[]);
  box.innerHTML=rows.length?rows.map(function(x,i){x._aiRank=i+1;return card(x,i+1);}).join(""):'<div class="empty">💤 لا توجد فرصة قوية تستوفي الشروط حالياً.</div>';
 }catch(e){box.innerHTML='<div class="empty">⚠️ '+esc(e.message)+'</div>';}
}
function home(){
 var run=function(fn,delay){setTimeout(fn,delay);};
 // Render the page first; expensive market scans start after the UI is visible.
 run(homeOverview,200);
 run(homeNews,400);
 run(homeOpportunities,1200);
 var t=window.mudaribHomeNewsTimer;if(t)clearInterval(t);
 window.mudaribHomeNewsTimer=setInterval(function(){
  run(homeOverview,0);run(homeNews,300);run(homeOpportunities,900);
 },900000); 
}
function scanner(){
 var box=$("scanResults"),head=$("scanHead"),btn=$("scan"),marketButtons=document.querySelectorAll("[data-market]");
 if(!box||!head||!btn)return;
 var market="crypto",allBySymbol={},sortKey="ai",sortDir=-1;
 var intervals=["5m","15m","30m","1H","4H","1D"]; var scanInterval="15m";
 var metrics=[
  ["price","السعر"],["change","التغير %"],["priceVs","السعر مقابل متوسط"],["rsi","RSI"],["stochRsi","Stoch RSI"],["macd","MACD"],
  ["ema20","EMA20"],["ema50","EMA50"],["ema200","EMA200"],["sma20","SMA20"],["sma50","SMA50"],
  ["atr","ATR"],["relVolume","Rel Volume"],["confidence","AI %"]
 ];
 var operators=[">","<",">=","<=","=","بين"];
 var defaultFilters=[];
 var filters=JSON.parse(localStorage.getItem("mudarib_filters")||"null")||defaultFilters;
 var columns=JSON.parse(localStorage.getItem("mudarib_columns")||"null")||[
  {metric:"price",interval:"15m"},{metric:"change",interval:"15m"},{metric:"change",interval:"1H"},
  {metric:"rsi",interval:"15m"},{metric:"rsi",interval:"1H"},{metric:"relVolume",interval:"15m"},{metric:"confidence",interval:"15m"}
 ];
 function esc2(x){return esc(x);}
 function opts(arr,val){return arr.map(function(x){return '<option value="'+esc2(x[0]||x)+'" '+((x[0]||x)===val?'selected':'')+'>'+esc2(x[1]||x)+'</option>';}).join("");}
 function metricOpts(val){return opts(metrics,val);}
 function intervalOpts(val){return opts(intervals,val);}
 function operatorOpts(val){return opts(operators.map(function(x){return [x,x];}),val);}
 function renderFilters(){
  var el=$("filterRows"); if(!el)return;
  var fc=$("filterCount");if(fc)fc.textContent=filters.length+" شروط";
  el.innerHTML=filters.map(function(f,i){
   var extra=f.metric==="priceVs"?'<select data-f="ref">'+opts([["ema20","EMA20"],["ema50","EMA50"],["ema200","EMA200"],["sma20","SMA20"],["sma50","SMA50"],["sma200","SMA200"]],f.ref||"ema200")+'</select>':
    '<input data-f="value" type="number" step="any" value="'+esc2(f.value||"")+'" placeholder="القيمة">';
   return '<div class="filter-row"><span class="filter-index">'+(i+1)+'</span><select data-f="metric">'+metricOpts(f.metric)+'</select><select data-f="interval">'+intervalOpts(f.interval)+'</select><select data-f="op">'+operatorOpts(f.op)+'</select>'+extra+'<button class="remove-filter" data-remove="'+i+'">×</button></div>';
  }).join("");
  el.querySelectorAll("[data-f]").forEach(function(x){x.addEventListener("change",function(){syncFilters();});x.addEventListener("input",function(){syncFilters();});});
  el.querySelectorAll("[data-remove]").forEach(function(b){b.onclick=function(){filters.splice(Number(b.dataset.remove),1);renderFilters();render();};});
 }
 function syncFilters(){
  document.querySelectorAll("#filterRows .filter-row").forEach(function(row,i){
   var m=row.querySelector('[data-f="metric"]'),iv=row.querySelector('[data-f="interval"]'),op=row.querySelector('[data-f="op"]'),v=row.querySelector('[data-f="value"]'),ref=row.querySelector('[data-f="ref"]');
   filters[i]={metric:m.value,interval:iv.value,op:op.value,value:v?v.value:"",ref:ref?ref.value:""};
  });
  localStorage.setItem("mudarib_filters",JSON.stringify(filters));
 }
 function renderColumns(){
  var el=$("columnRows");if(!el)return;
  el.innerHTML=columns.map(function(c,i){
   return '<div class="column-row"><span class="column-index">'+(i+1)+'</span><select data-c="metric">'+metricOpts(c.metric)+'</select><select data-c="interval">'+intervalOpts(c.interval)+'</select><button class="remove-column" data-remove-col="'+i+'">×</button></div>';
  }).join("");
  el.querySelectorAll("[data-c]").forEach(function(x){x.onchange=function(){syncColumns();};});
  el.querySelectorAll("[data-remove-col]").forEach(function(b){b.onclick=function(){columns.splice(Number(b.dataset.removeCol),1);renderColumns();renderHead();render();};});
 }
 function syncColumns(){
  document.querySelectorAll("#columnRows .column-row").forEach(function(row,i){
   columns[i]={metric:row.querySelector('[data-c="metric"]').value,interval:row.querySelector('[data-c="interval"]').value};
  });
  localStorage.setItem("mudarib_columns",JSON.stringify(columns));
  renderHead();render();
 }
 function renderHead(){
  var hs='<tr><th data-sort="symbol"># / الأصل</th>';
  columns.forEach(function(c,i){var label=(metrics.find(function(m){return m[0]===c.metric})||[c.metric,c.metric])[1];hs+='<th data-sort="col'+i+'">'+esc2(label)+' <small>'+esc2(c.interval)+'</small></th>';});
  hs+='<th data-sort="ai">AI</th><th>الإشارة</th><th>جاهزية</th></tr>';head.innerHTML=hs;
  head.querySelectorAll("th[data-sort]").forEach(function(th){th.onclick=function(){var k=th.dataset.sort;if(sortKey===k)sortDir*=-1;else{sortKey=k;sortDir=-1;}render();};});
 }
 function valueFor(x,col){
  if(col.metric==="confidence")return Number(x.confidence||0);
  if(col.metric==="change")return Number(x.change||0);
  if(col.metric==="price")return Number(x.price||0);
  var ind=(x.indicators||{});
  if(col.metric==="priceVs")return Number(x.price||0);
  return ind[col.metric]==null?null:Number(ind[col.metric]);
 }
 function pass(v,op,target,ref){
  if(v==null||Number.isNaN(Number(v)))return false;
  if(op==="=")return Math.abs(Number(v)-Number(target))<0.000001;
  if(op===">")return Number(v)>Number(target);
  if(op==="<")return Number(v)<Number(target);
  if(op===">=")return Number(v)>=Number(target);
  if(op==="<=")return Number(v)<=Number(target);
  if(op==="بين"){var p=String(target).split(",").map(Number);return p.length>1&&Number(v)>=p[0]&&Number(v)<=p[1];}
  return true;
 }
 function filterMatch(x){
  return filters.every(function(f){
   var data=allBySymbol[x.symbol]&&allBySymbol[x.symbol][f.interval]; if(!data)return false;
   if(f.metric==="priceVs"){
    var ind=data.indicators||{}, ref=Number(ind[f.ref||"ema200"]); return pass(Number(data.price||0),f.op,ref);
   }
   var v=valueFor(data,{metric:f.metric,interval:f.interval});
   if(f.ref && data.indicators && data.indicators[f.ref]!=null){
    return pass(v,f.op,Number(data.indicators[f.ref]));
   }
   return pass(v,f.op,Number(f.value));
  });
 }
 function displayValue(v,metric){
  if(v==null||Number.isNaN(Number(v)))return "—";
  var n=Number(v);
  if(metric==="change"||metric==="rsi"||metric==="stochRsi"||metric==="relVolume"||metric==="confidence")return (metric==="change"&&n>0?"+":"")+n.toFixed(2)+(metric==="relVolume"?"x":"%");
  if(Math.abs(n)>=1000)return n.toLocaleString("en-US",{maximumFractionDigits:2});
  return n.toFixed(4).replace(/0+$/,'').replace(/\\.$/,'');
 }
 function render(){
  var q=($("scanSearch")?.value||"").trim().toLowerCase(),min=Number($("scanConfidence")?.value||0),ready=$("scanReady")?.checked,dir=$("scanDirection")?.value||"all";
  var rows=Object.keys(allBySymbol).map(function(sym){var base=allBySymbol[sym]["15m"]||allBySymbol[sym][marketIntervals()[0]]||Object.values(allBySymbol[sym])[0];return base;}).filter(Boolean);
  rows=rows.filter(function(x){var n=((x.displayName||x.symbol)+" "+x.symbol).toLowerCase();return (!q||n.indexOf(q)>=0)&&Number(x.confidence||0)>=min&&(!ready||x.tradeReady)&&(dir==="all"||x.direction===dir);});
  rows.sort(function(a,b){
   function sv(x){if(sortKey==="symbol")return String(x.displayName||x.symbol);if(sortKey==="ai")return Number(x.confidence||0);var idx=Number(sortKey.replace("col",''));return valueFor(allBySymbol[x.symbol][columns[idx].interval],columns[idx]);}
   var av=sv(a),bv=sv(b);if(typeof av==="string")return av.localeCompare(String(bv))*sortDir;return ((Number(av)||0)-(Number(bv)||0))*sortDir;
  });
  if(sortKey==="ai"){
   rows.sort(function(a,b){
    var ca=Number(a.confidence||0), cb=Number(b.confidence||0);
    if(cb!==ca)return cb-ca;
    var ra=Number(a.rr||0), rb=Number(b.rr||0);
    if(rb!==ra)return rb-ra;
    return Number(b.tradeReady)-Number(a.tradeReady);
   });
  }
  $("scanSummary").innerHTML='<b>'+rows.length+'</b> صفقة مطابقة <span>من '+Object.keys(allBySymbol).length+' أصل · '+(dir==="all"?"شراء + بيع":dir)</span>';
  box.innerHTML=rows.length?rows.map(function(x,i){
   var html='<tr><td class="rank">'+(i+1)+'<br><b>'+esc2(x.displayName||x.symbol)+'</b><small>'+esc2(x.symbol)+'</small></td>';
   columns.forEach(function(c){var d=allBySymbol[x.symbol][c.interval];html+='<td>'+displayValue(valueFor(d,c),c.metric)+'</td>';});
   html+='<td><b class="ai-score">AI: '+displayValue(x.confidence,"confidence")+'</b><small>#'+(i+1)+'</small></td><td><span class="signal '+(x.direction==="شراء"?'buy':x.direction==="بيع"?'sell':'neutral')+'">'+esc2(x.signal||x.direction)+'</span></td><td>'+(x.tradeReady?'✅':'—')+'</td></tr>';
   return html;
  }).join(""):'<tr><td colspan="20" class="scan-empty">لا توجد أصول تطابق استراتيجيتك.</td></tr>';

 }
 function openRecommendation(x){
  var m=$("recommendationModal");if(!m)return;
  function set(id,v){var e=$(id);if(e)e.textContent=v==null||v===""?"—":v;}
  set("recMarket",(x.market||"").toUpperCase()+" · "+(x.interval||""));
  set("recName",x.displayName||x.symbol);set("recSymbol",x.symbol);
  set("recAI",Number(x.confidence||0).toFixed(1)+"%");
  set("recSignal",x.signal||x.direction||"حيادي");set("recEntry",x.entry);set("recSL",x.sl);set("recTP1",x.tp1);set("recTP2",x.tp2);set("recTP3",x.tp3);set("recRR",(x.rr||0)+"R");
  set("recReason",x.reason||"تحليل حركة السعر والبيانات التاريخية.");
  set("recUpdated",x.updatedAt?new Date(x.updatedAt).toLocaleString("ar-SA"):"محدث الآن");
  set("recReady",x.tradeReady?"✓ فرصة جاهزة":"مراقبة فقط");
  var bar=$("recBar");if(bar)bar.style.width=Math.max(0,Math.min(100,Number(x.confidence||0)))+"%";
  var mem=x.memory||{};set("recMemory",mem.samples?("🧠 ذاكرة هذا الأصل: "+mem.samples+" حالة · نجاح تاريخي مرجح "+mem.winRate+"%"):"🧠 لا توجد ذاكرة كافية لهذا الأصل — يستخدم تحليل السوق العام.");
  m.hidden=false;document.body.classList.add("rec-open");
 }
 document.querySelectorAll("[data-close-rec]").forEach(function(e){e.onclick=function(){var m=$("recommendationModal");if(m)m.hidden=true;document.body.classList.remove("rec-open");};});

 function marketIntervals(){return intervals;}
 async function run(){
  box.innerHTML='<tr><td class="scan-empty">🤖 جاري تحميل بيانات الفريمات وتحليل '+esc2(market)+'...</td></tr>';
  $("scanStatus").textContent="جاري الفحص...";
  allBySymbol={};
  try{
   var calls=[scanInterval].map(function(iv){return api("/api/ai/signals?market="+encodeURIComponent(market)+"&interval="+encodeURIComponent(iv)+"&limit=100").then(function(d){return {iv:iv,rows:d.results||[]};});});
   var packs=await Promise.all(calls);
   packs.forEach(function(p){p.rows.forEach(function(x){if(!allBySymbol[x.symbol])allBySymbol[x.symbol]={};allBySymbol[x.symbol][p.iv]=x;});});
   render();$("scanStatus").textContent="محدث الآن";
  }catch(e){box.innerHTML='<tr><td class="scan-empty">⚠️ '+esc2(e.message)+'</td></tr>';$("scanStatus").textContent="تعذر التحديث";}
 }
 marketButtons.forEach(function(b){b.onclick=function(){marketButtons.forEach(function(x){x.classList.remove("active");});b.classList.add("active");market=b.dataset.market;run();};}); var intervalPicker=$("scanInterval"); if(intervalPicker){intervalPicker.addEventListener("change",function(){scanInterval=intervalPicker.value;columns=columns.map(function(c){return {metric:c.metric,interval:scanInterval};});renderColumns();renderHead();run();});}
 if($("addFilter"))$("addFilter").onclick=function(){filters.push({metric:"rsi",interval:"15m",op:"<",value:"30"});renderFilters();render();};
 document.querySelectorAll("[data-preset]").forEach(function(b){
  b.onclick=function(){
   var p=b.getAttribute("data-preset");
   var presets={
    oversold:[{metric:"rsi",interval:"15m",op:"<",value:"30"},{metric:"stochRsi",interval:"15m",op:"<",value:"25"}],
    trend:[{metric:"priceVs",interval:"1H",op:">",value:"",ref:"ema200"},{metric:"ema20",interval:"15m",op:">",value:"",ref:"ema50"}],
    volume:[{metric:"relVolume",interval:"15m",op:">",value:"1.5"},{metric:"change",interval:"15m",op:">",value:"0.5"}],
    momentum:[{metric:"rsi",interval:"15m",op:">",value:"50"},{metric:"macd",interval:"15m",op:">",value:"0"}],
    breakout:[{metric:"change",interval:"15m",op:">",value:"1"},{metric:"relVolume",interval:"15m",op:">",value:"1.5"}]
   };
   if(presets[p]){filters=presets[p].map(function(x){return Object.assign({},x);});localStorage.setItem("mudarib_filters",JSON.stringify(filters));renderFilters();render();}
  };
 });
 if($("addColumn"))$("addColumn").onclick=function(){columns.push({metric:"price",interval:"1H"});renderColumns();renderHead();render();};
 if($("clearScreen"))$("clearScreen").onclick=function(){filters=[];localStorage.removeItem("mudarib_filters");renderFilters();render();};
 if($("saveScreen"))$("saveScreen").onclick=function(){var name=prompt("اسم الاستراتيجية؟");if(!name)return;var saved=JSON.parse(localStorage.getItem("mudarib_saved_screens")||"{}");saved[name]={filters:filters,columns:columns};localStorage.setItem("mudarib_saved_screens",JSON.stringify(saved));loadSaved();};
 function loadSaved(){var el=$("savedScreens"),saved=JSON.parse(localStorage.getItem("mudarib_saved_screens")||"{}");if(!el)return;el.innerHTML='<option value="">استراتيجياتي المحفوظة</option>'+Object.keys(saved).map(function(n){return '<option value="'+esc2(n)+'">'+esc2(n)+'</option>';}).join("");el.onchange=function(){var v=el.value;if(!v||!saved[v])return;filters=saved[v].filters||[];columns=saved[v].columns||columns;renderFilters();renderColumns();renderHead();render();};}
 renderFilters();renderColumns();renderHead();loadSaved();btn.onclick=run;run();
 window.mudaribScannerTimer=setInterval(run,180000);
}
function auth(){
 var login=$("login");
 if(login)login.addEventListener("click",async function(){
  try{await api("/api/auth/login",{method:"POST",body:JSON.stringify({email:$("email").value,password:$("password").value})});location.href="/";}
  catch(e){$("msg").textContent=e.message;}
 });
 var register=$("register");
 if(register)register.addEventListener("click",async function(){
  try{await api("/api/auth/register",{method:"POST",body:JSON.stringify({name:$("name").value,email:$("email").value,password:$("password").value})});location.href="/";}
  catch(e){$("msg").textContent=e.message;}
 });
}

async function tradeTracker(){
 var box=$("tradeHistory"),statsBox=$("tradeStats"); if(!box||!statsBox)return;
 var currentFilter="open", currentPeriod="all", data=[], stats={};
 function statCard(title,key){
   var s=stats[key]||{}; var cls=(s.pnl||0)>=0?"positive":"negative";
   return '<div class="trade-stat"><small>'+title+'</small><b class="'+cls+'">'+(s.pnl>=0?"+":"")+num(s.pnl||0)+'%</b><span>🎯 '+s.wins+' نجاح · ❌ '+s.losses+' فشل · 📊 '+s.total+' مغلق</span><strong>نسبة النجاح '+num(s.winRate||0)+'%</strong></div>';
 }
 function rankSort(a,b){
   var ca=Number(a.confidence||a.aiConfidence||a.ai||0),cb=Number(b.confidence||b.aiConfidence||b.ai||0);
   if(cb!==ca)return cb-ca;
   var ra=Number(a.rr||0),rb=Number(b.rr||0);
   if(rb!==ra)return rb-ra;
   return new Date(b.createdAt||0)-new Date(a.createdAt||0);
 }
 function periodRows(source){
   var rows=source.slice();
   if(currentPeriod!=="all"){
     var cutoff=Date.now()-({today:86400000,week:604800000,month:2592000000,year:31536000000}[currentPeriod]||0);
     rows=rows.filter(function(x){return new Date(x.resolvedAt||x.createdAt||0).getTime()>=cutoff;});
   }
   return rows;
 }
 function filterRows(source){
   return source.filter(function(x){
     if(currentFilter==="open")return x.status==="open";
     if(currentFilter==="wins")return x.result==="tp1"||x.result==="tp2"||x.result==="tp3";
     if(currentFilter==="losses")return x.result==="sl";
     return true;
   });
 }
 function renderStats(){
   statsBox.innerHTML=statCard("اليوم","today")+statCard("هذا الأسبوع","week")+statCard("هذا الشهر","month")+statCard("هذه السنة","year")+statCard("إجمالي السجل","all");
 }
 function render(){
   var baseRows=periodRows(data);
   var rows=filterRows(baseRows);
   rows.sort(rankSort);
   box.innerHTML=rows.length?rows.map(function(x,i){
     var status=x.status==="open"?"open":(x.result==="sl"?"loss":(x.result==="ambiguous"?"ambiguous":(x.result==="expired"?"expired":"win")));
     var pnl=Number(x.pnlPercent||0);
     var ai=Number(x.confidence||x.aiConfidence||x.ai||0);
     var result=status==="open"?"🟢 قيد المتابعة":status==="ambiguous"?"⚪ غير محسومة":status==="expired"?"⏱️ انتهى الفريم":status==="win"?"✅ حققت "+String(x.result||"الهدف").toUpperCase():"❌ ضربت الوقف";
     var rank=i+1,medal=rank===1?"👑":rank===2?"🥈":rank===3?"🥉":"";
     var tag=rank<=3?'<em class="ai-rank-tag">'+(rank===1?"الأقوى":rank===2?"الثاني":"الثالث")+'</em>':"";
     return '<article class="tracked-trade '+status+'"><div class="tracked-head"><div><b>'+rank+' : '+medal+' '+esc(x.symbol)+' '+tag+'</b><small>'+esc(x.market)+' · '+esc(x.interval)+' · '+esc(x.direction||"")+" · 🤖 AI "+num(ai)+"% · R:R "+num(x.rr)+'</small></div><span>'+result+'</span></div><div class="tracked-grid"><div><small>الدخول</small><b>'+num(x.entry)+'</b></div><div><small>TP1</small><b>'+num(x.tp1)+'</b></div><div><small>TP2</small><b>'+num(x.tp2)+'</b></div><div><small>TP3</small><b>'+num(x.tp3)+'</b></div><div><small>الوقف</small><b>'+num(x.sl)+'</b></div><div><small>P&amp;L</small><b class="'+(pnl>=0?"positive":"negative")+'">'+(pnl>=0?"+":"")+num(pnl)+'%</b></div></div><div class="tracked-foot"><span>🕒 '+new Date(x.createdAt).toLocaleString("ar-SA")+'</span><span>'+(x.resolvedAt?"إغلاق: "+new Date(x.resolvedAt).toLocaleString("ar-SA"):"آخر متابعة: مباشر")+'</span></div></article>';
   }).join(""):'<div class="empty">لا توجد صفقات محفوظة حالياً.</div>';
 }
 async function load(){
   box.innerHTML='<div class="empty">🤖 جاري تحديث النتائج ومطابقة الأسعار مع الأهداف والوقف...</div>';
   try{
     var d={trades:[],stats:{}};
     try{ d=await api("/api/trades"); }catch(e){ d={trades:[],stats:{}}; }
     data=d.trades||[];
     stats=d.stats||{};
     // إذا كان سجل المتابعة فارغاً أو خدمة السجل غير متاحة، اعرض الإشارات المنشورة الحالية.
     if(!data.length){
       var markets=["crypto","futures","contracts"];
       var packs=await Promise.all(markets.map(function(m){
         return api("/api/ai/signals?market="+encodeURIComponent(m)+"&interval=15m&limit=100")
           .then(function(x){return (x.results||[]).filter(function(s){return (s.direction==="شراء"||s.direction==="بيع")&&Number(s.entry||0)>0;}).map(function(s){
             return Object.assign({},s,{market:m,interval:"15m",status:"open",result:"",createdAt:s.updatedAt||new Date().toISOString(),resolvedAt:"",pnlPercent:0,aiConfidence:Number(s.confidence||0)});
           });}).catch(function(){return [];});
       }));
       data=[].concat.apply([],packs).sort(function(a,b){return Number(b.confidence||0)-Number(a.confidence||0);});
     }
     renderStats();render();
   }
   catch(e){box.innerHTML='<div class="empty">⚠️ '+esc(e.message)+'</div>';}
 }
 document.querySelectorAll("[data-trade-filter]").forEach(function(b){b.onclick=function(){document.querySelectorAll("[data-trade-filter]").forEach(function(x){x.classList.remove("active")});b.classList.add("active");currentFilter=b.dataset.tradeFilter;render();};});
 var period=$("tradePeriod");if(period)period.onchange=function(){currentPeriod=period.value;render();};
 var refresh=$("tradeRefresh");if(refresh)refresh.onclick=load;
 load(); window.mudaribTradeTimer=setInterval(load,60000);
}
async function subscription(){
 if(!$("plans"))return;
 try{
  var d=await api("/api/subscription");
  $("plans").innerHTML=Object.keys(d.plans||{}).map(function(k){var v=d.plans[k];var names={"7d":"7 أيام","30d":"30 يوم","90d":"90 يوم"};return '<button type="button" data-plan="'+esc(k)+'">'+esc(names[k]||k)+" — "+num(v.price)+" USDT</button>";}).join("");
  $("trc").textContent=(d.payment&&d.payment.trc20)||"غير مضبوط";
  $("bin").textContent=(d.payment&&d.payment.binancePay)||"غير مضبوط";
  var selected=null;
  var planBox=$("plans");
  if(planBox){
   planBox.addEventListener("click",function(e){
    var b=e.target.closest ? e.target.closest("[data-plan]") : null;
    if(!b || !planBox.contains(b))return;
    e.preventDefault();
    selected=b.getAttribute("data-plan");
    planBox.querySelectorAll("[data-plan]").forEach(function(x){x.classList.toggle("active",x===b);});
    var m=$("msg");if(m)m.textContent="تم اختيار الباقة: "+b.textContent.trim();
   });
  }
  var send=$("send");
  if(send)send.addEventListener("click",async function(){
   try{
    if(!selected)throw new Error("اختر الباقة أولاً");
    var tx=$("txid");
    if(!tx || !tx.value.trim())throw new Error("أدخل رقم العملية أولاً");
    send.disabled=true;send.textContent="جاري الإرسال...";
    await api("/api/subscription/request",{method:"POST",body:JSON.stringify({plan:selected,txid:tx.value.trim()})});
    $("msg").textContent="تم إرسال طلب الدفع بنجاح";
   }catch(e){$("msg").textContent=e.message;}
   finally{send.disabled=false;send.textContent="إرسال طلب الدفع";}
  });
 }catch(e){$("msg").textContent=e.message;}
}
async function news(){
 var box=$("news");if(!box)return;
 box.innerHTML='<div class="empty">📰 جاري جلب آخر أخبار الأسواق...</div>';
 function cleanText(v){
  var s=String(v==null?"":v);
  s=s.replace(/<[^>]*>/g," ").replace(/&nbsp;/gi," ").replace(/\\s+/g," ").trim();
  return s;
 }
 function timeLabel(v){
  try{return new Date(v).toLocaleString("ar-SA",{day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"});}
  catch(e){return v||"";}
 }
 function categoryLabel(x){
  return x.category||"أخبار الأسواق";
 }
 function card(x,i){
  var title=cleanText(x.title||"خبر السوق");
  var desc=cleanText(x.description||"");
  if(!desc)desc="ملخص سريع للخبر وتأثيره المحتمل على حركة السوق. تابع البيانات والأسعار قبل اتخاذ أي قرار تداول.";
  return '<a class="news-card news-card-native" href="/news/'+encodeURIComponent(x.slug||"")+'">'+
    '<div class="news-source"><span>📰 '+esc(x.source||"مضارب أبو سعود")+'</span><span>'+esc(timeLabel(x.published))+'</span></div>'+
    '<div class="news-badge">'+esc(categoryLabel(x))+'</div>'+
    '<h3>'+esc(title)+'</h3>'+
    '<p>'+esc(desc)+'</p>'+
    '<div class="news-footer"><span>📌 ملخص مضارب أبو سعود</span><span>عرض التفاصيل ←</span></div>'+
  '</a>';
 }
 function openDetail(x){ return; }
 try{
  var d=await api("/api/live-news");
  var items=Array.isArray(d.news)?d.news:[];
  box.innerHTML=items.length?items.map(card).join(""):'<div class="empty">لا توجد أخبار متاحة حالياً. حاول التحديث بعد قليل.</div>';
 }catch(e){
  box.innerHTML='<div class="empty">⚠️ تعذر تحديث الأخبار حالياً. حاول مرة أخرى بعد قليل.</div>';
 }
}

async function loadAdmin(){
 if(!$("stats")||!$("payments")||!$("users"))return;
 try{
  var s=await api("/api/admin/stats"),p=await api("/api/admin/payments"),u=await api("/api/admin/users");
  $("stats").innerHTML='<div>👥 المستخدمون: <b>'+s.users+'</b></div><div>💳 اشتراكات فعالة: <b>'+s.active_subscriptions+'</b></div><div>⏳ طلبات معلقة: <b>'+s.pending_payments+'</b></div>';
  $("payments").innerHTML=(p.payments||[]).map(function(x){var a=x.status==="pending"?' <button type="button" data-approve="'+x.id+'">اعتماد</button> <button type="button" data-reject="'+x.id+'">رفض</button>':"";return '<article class="trade">#'+x.id+" · "+esc(x.username)+" · "+esc(x.plan)+" · "+esc(x.txid)+" · "+esc(x.status)+a+"</article>";}).join("")||'<div class="empty">لا توجد طلبات</div>';
  $("users").innerHTML=(u.users||[]).map(function(x){return '<article class="trade"><b>'+esc(x.name)+'</b><br>'+esc(x.email)+'<br><small>الاشتراك: '+esc(x.subscription_until||"بدون اشتراك")+'</small><br><button type="button" data-extend="'+x.id+'">+30 يوم</button> <button type="button" data-delete="'+x.id+'">حذف</button></article>';}).join("")||'<div class="empty">لا يوجد مستخدمون</div>';
  document.querySelectorAll("[data-approve]").forEach(function(b){b.onclick=function(){adminAction("/api/admin/payments/approve",{id:Number(b.getAttribute("data-approve"))});};});
  document.querySelectorAll("[data-reject]").forEach(function(b){b.onclick=function(){adminAction("/api/admin/payments/reject",{id:Number(b.getAttribute("data-reject"))});};});
  document.querySelectorAll("[data-extend]").forEach(function(b){b.onclick=function(){adminAction("/api/admin/users/extend",{id:Number(b.getAttribute("data-extend")),days:30});};});
  document.querySelectorAll("[data-delete]").forEach(function(b){b.onclick=function(){if(confirm("حذف المستخدم؟"))adminAction("/api/admin/users/delete",{id:Number(b.getAttribute("data-delete"))});};});
 }catch(e){$("msg").textContent=e.message;}
}
async function adminAction(url,body){try{await api(url,{method:"POST",body:JSON.stringify(body)});loadAdmin();}catch(e){alert(e.message);}}
async function adminSession(){
 try{var d=await api("/api/me");if(d.admin){if($("adminLogin"))$("adminLogin").hidden=true;if($("adminPanel"))$("adminPanel").hidden=false;loadAdmin();}}catch(e){}
}
function admin(){
 var telegramTest=$("telegramTest");
 if(telegramTest)telegramTest.addEventListener("click",async function(){
  var out=$("telegramMsg");
  telegramTest.disabled=true;telegramTest.textContent="⏳ جاري الاختبار...";
  if(out)out.textContent="";
  try{
   var d=await api("/api/admin/telegram/test",{method:"POST"});
   if(out)out.textContent="✅ "+(d.message||"تم الإرسال بنجاح");
  }catch(e){if(out)out.textContent="❌ "+e.message;}
  finally{telegramTest.disabled=false;telegramTest.textContent="📲 اختبار تيليجرام";}
 });
 var login=$("alogin");if(!login)return;
 login.addEventListener("click",async function(){
  try{var u=($("au").value||"").trim(),p=$("ap").value||"";if(!u||!p)throw new Error("أدخل اسم المستخدم وكلمة المرور");await api("/api/admin/login",{method:"POST",body:JSON.stringify({username:u,password:p})});$("adminLogin").hidden=true;$("adminPanel").hidden=false;$("msg").textContent="تم تسجيل دخول المشرف";loadAdmin();}
  catch(e){$("msg").textContent=e.message;}
 });
 var logout=$("alogout");
 if(logout)logout.addEventListener("click",async function(){await api("/api/admin/logout",{method:"POST"});location.reload();});
 var add=$("addNews");
 if(add)add.addEventListener("click",async function(){
  try{await api("/api/admin/news",{method:"POST",body:JSON.stringify({title:$("nt").value.trim(),content:$("nc").value.trim(),source:"مضارب أبو سعود"})});$("nt").value="";$("nc").value="";$("msg").textContent="تم نشر الخبر";}
  catch(e){$("msg").textContent=e.message;}
 });
}
document.addEventListener("DOMContentLoaded",function(){
 if(localStorage.getItem("theme")==="light")document.body.classList.add("light");var theme0=$("theme");if(theme0)theme0.textContent=document.body.classList.contains("light")?"☀️":"🌙";updateAuthUI();updateSiteStatus();section();home();scanner();auth();subscription();news();admin();adminSession();tradeTracker();
 var menu=$("menu");if(menu){
  var lastMenuToggle=0;
  function toggleSide(e){
    if(e){e.preventDefault();e.stopPropagation();}
    var now=Date.now();
    if(now-lastMenuToggle<350)return;
    lastMenuToggle=now;
    var side=$("side");if(!side)return;
    var isOpen=side.classList.contains("open");
    side.classList.toggle("open",!isOpen);
    document.body.classList.toggle("side-open",!isOpen);
  }
  // Mobile-safe: pointerup works for touch, pen and mouse without relying
  // on a synthetic click that some mobile browsers can delay/cancel.
  menu.onclick=null;
  menu.onpointerup=toggleSide;
  menu.ontouchend=function(e){toggleSide(e);};
  menu.onkeydown=function(e){
    if(e.key==="Enter" || e.key===" "){toggleSide(e);}
  };
}
var side=$("side");if(side){
  side.querySelectorAll("a").forEach(function(a){
    a.addEventListener("click",function(){
      side.classList.remove("open");
      document.body.classList.remove("side-open");
    });
  });
  document.addEventListener("click",function(e){
    if(side.classList.contains("open") && !side.contains(e.target) && e.target!==menu && !menu.contains(e.target)){
      side.classList.remove("open");
      document.body.classList.remove("side-open");
    }
  });
  document.addEventListener("keydown",function(e){
    if(e.key==="Escape"){
      side.classList.remove("open");
      document.body.classList.remove("side-open");
    }
  });
}
 var theme=$("theme");if(theme)theme.addEventListener("click",function(e){e.preventDefault();document.body.classList.toggle("light");localStorage.setItem("theme",document.body.classList.contains("light")?"light":"dark");theme.textContent=document.body.classList.contains("light")?"☀️":"🌙";});
});
})();