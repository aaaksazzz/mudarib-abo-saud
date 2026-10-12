(function(){
"use strict";
var $=function(s){return document.querySelector(s);};
var routes={home:"/static/index.html",radar:"/static/radar.html?v=20261014-menu-fix",gold:"/static/public-trades.html?market=forex&hours=24",results:"/static/results.html?v=20261014-results-links",news:"/static/news.html?v=20261012-clean-results-v3",blog:"/static/blog.html?v=20261012-clean-results-v3",spot:"/static/public-trades.html?market=spot&hours=24",futures:"/static/public-trades.html?market=futures&hours=24",alpha:"/static/public-trades.html?market=alpha&hours=24",contracts:"/static/public-trades.html?market=contracts&hours=24",us:"/static/public-trades.html?market=us&hours=24",saudi:"/static/public-trades.html?market=saudi&hours=24",forex:"/static/public-trades.html?market=forex&hours=24",signup:"/static/signup.html?v=20261012-clean-results-v3",login:"/static/login.html?v=20261012-clean-results-v3",admin:"/admin",explosion:"/static/explosion.html?v=20261012-direction-fix",flareScanner:"/static/flare-scanner.html?v=20261012-flare-scanner-chart1"};
var page=document.body.getAttribute("data-page")||"home",market=document.body.getAttribute("data-market")||"",loading=false,trackingTimer=null,marketKeys=["spot","futures","alpha","contracts","us","saudi","forex"];
/* رابط الصفقات العامة بجوار الرادار في القائمة على كل الصفحات */
try {
 var publicSide=document.getElementById("sidebar");
 if(publicSide&&!publicSide.querySelector('a[href*="public-trades.html"]')) {
  var publicLink=document.createElement("a");
  publicLink.href="/static/public-trades.html?v=20261013-public-trades";
  publicLink.className="nav-item";
  publicLink.style.textDecoration="none"; publicLink.style.display="block";
  publicLink.textContent="🌐 الصفقات العامة";
  var radarLink=publicSide.querySelector('[data-s="radar"],a[href*="radar.html"]');
  if(radarLink&&radarLink.parentNode)radarLink.parentNode.insertBefore(publicLink,radarLink.nextSibling);
  else {var footer=publicSide.querySelector(".side-footer");if(footer)publicSide.insertBefore(publicLink,footer);else publicSide.appendChild(publicLink);}
 }
} catch(e) {}
/* Keep market shortcuts at the top of every shared sidebar, with services below. */
try {
 var marketSidebar=document.getElementById("sidebar");
 if(marketSidebar){
  var marketNodes=marketKeys.map(function(k){return marketSidebar.querySelector('[data-s="'+k+'"]');}).filter(Boolean);
  if(marketNodes.length){
   var marketHeading=document.createElement("div");marketHeading.className="nav-label";marketHeading.textContent="الأسواق";
   var marketGroup=document.createDocumentFragment();marketGroup.appendChild(marketHeading);
   marketNodes.forEach(function(node){marketGroup.appendChild(node);});
   marketSidebar.insertBefore(marketGroup,marketSidebar.firstChild);
   Array.from(marketSidebar.querySelectorAll(".nav-label")).forEach(function(n){if(n!==marketHeading&&n.textContent.trim()==="الأسواق")n.remove();});
  }
 }
} catch(e) {}
/* إضافة رابط شرارات السوق إلى القائمة في جميع الصفحات */
try{var flareSide=document.getElementById("sidebar");if(flareSide&&!flareSide.querySelector('[data-flare-nav="1"],a[href*="flare-scanner.html"]')){var flareLink=document.createElement("a");flareLink.href="/static/flare-scanner.html?v=20261012-flare-scanner-chart1";flareLink.className="nav-item";flareLink.setAttribute("data-flare-nav","1");flareLink.style.textDecoration="none";flareLink.style.display="block";flareLink.textContent="⚡ شرارات السوق";var flareFooter=flareSide.querySelector(".side-footer");if(flareFooter)flareSide.insertBefore(flareLink,flareFooter);else flareSide.appendChild(flareLink);}}catch(e){}
var timeframes=[["15m","15 دقيقة"],["30m","30 دقيقة"],["1h","ساعة"],["4h","4 ساعات"],["1d","يومي"],["1w","أسبوعي"],["1M","شهري"]];
var selectedTimeframe="15m";
try{var initialTf=new URLSearchParams(window.location.search).get("timeframe");if(timeframes.some(function(x){return x[0]===initialTf;}))selectedTimeframe=initialTf;}catch(e){}
function esc(v){return String(v==null?"":v).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");}

function displaySymbol(x){var s=String((x&&x.symbol)||"").trim().toUpperCase();var m=String((x&&x.market)||market||"").toLowerCase();if((m==="spot"||m==="futures")&&s&&!/USDT$/.test(s)&&/^[A-Z0-9]+$/.test(s)){s=s+"USDT";}return s;}function go(s){if(routes[s]){window.location.href=routes[s];}}
function closeMenu(){var s=$("#sidebar"),o=$("#overlay");if(s)s.classList.remove("open");if(o)o.classList.remove("show");}
function getJSON(url,timeoutMs){var controller=typeof AbortController!=="undefined"?new AbortController():null;var timeout=Number(timeoutMs)||8000;var timer=controller?setTimeout(function(){controller.abort();},timeout):null;return fetch(url,{cache:"no-store",signal:controller?controller.signal:undefined}).then(function(r){if(!r.ok)throw new Error("HTTP "+r.status);return r.json();}).finally(function(){if(timer)clearTimeout(timer);});}
function fmtPrice(v){if(v===null||v===undefined||v==="")return "—";var n=Number(v);if(!Number.isFinite(n))return esc(v);if(n===0)return "0";var a=Math.abs(n),d=a>=1000?2:a>=100?3:a>=1?4:a>=0.01?6:a>=0.0001?8:10;return n.toFixed(d).replace(/\.?0+$/,"");}
function signalScore(x){return Number(x.recommendation_score||x.ai_pct||x.ai||x.analysis_score||0);}
function rankMark(i){return i===0?"👑":i===1?"🥈":i===2?"🥉":"#"+(i+1);}
function card(x,i){
 var sell=String(x.direction||x.side||"").toUpperCase()==="SELL";
 var mark=rankMark(i),tier=i===0?"rank-crown":i===1?"rank-silver":i===2?"rank-bronze":"rank-normal";
 var targets=Array.isArray(x.targets)?x.targets.filter(function(v){return v!==null&&v!==undefined&&v!=="";}).slice(0,3):[];
 if(!targets.length){[x.tp1,x.tp2,x.tp3].forEach(function(v){if(v!==null&&v!==undefined&&v!=="")targets.push(v);});}
 var entry=Number(x.entry),sl=Number(x.sl);
 function pctLabel(price,isStop){
  price=Number(price);
  if(!Number.isFinite(entry)||entry<=0||!Number.isFinite(price)||price<=0)return "";
  var pct=(sell?(entry-price):(price-entry))/entry*100;
  if(isStop)pct=-Math.abs(pct);
  else if(pct<=0)return "";
  if(!Number.isFinite(pct))return "";
  return '<small class="level-percent">'+(pct>0?"+":"")+pct.toFixed(2)+'%</small>';
 }
 var lv='<div class="level"><small>الدخول</small><b>'+fmtPrice(x.entry)+'</b></div>';
 targets.forEach(function(v,n){
  lv+='<div class="level trade-target"><small>TP'+(n+1)+'</small><b>'+fmtPrice(v)+'</b>'+pctLabel(v,false)+'</div>';
 });
 lv+='<div class="level trade-stop"><small>وقف الخسارة</small><b>'+fmtPrice(x.sl)+'</b>'+pctLabel(sl,true)+'</div>';
 var direction=sell?"بيع":"شراء";
 return '<article class="card trade-tracking-card '+tier+'"><div class="card-top"><div><span class="rank trade-rank">'+mark+' '+(i+1)+' · '+esc(x.signal_label||direction)+'</span><div class="symbol">'+esc(displaySymbol(x)||"")+'</div></div><span class="direction '+(sell?"sell":"buy")+'">'+direction+'</span></div><div class="levels">'+lv+'</div></article>';
}
function render(el,rows){if(!el)return;var a=(rows||[]).slice().sort(function(x,y){var d=signalScore(y)-signalScore(x);if(d)return d;var sc=Number(y.source_count||y.alignment||0)-Number(x.source_count||x.alignment||0);if(sc)return sc;return Number(y.detected_at||y.updated_at||0)-Number(x.detected_at||x.updated_at||0);});el.innerHTML=a.length?a.map(card).join(""):'<div class="empty">لا توجد توصيات منشورة خلال آخر 24 ساعة حالياً — جاري إعادة الفحص.</div>';}
function loadMarket(m,tf){
 var el=$("#marketCards"),st=$("#marketStatus");if(!el)return;
 if(m==="alpha"){el.innerHTML='<div class="empty">قسم Binance Alpha مستقل، لكن مصدر إشارات Alpha غير مربوط حاليًا. ما راح نعرض إشارات الفيوتشر على أنها Alpha.</div>';if(st)st.textContent="Binance Alpha · بانتظار ربط مصدر البيانات المستقل";return;}
 selectedTimeframe=tf||selectedTimeframe||"15m";
 var head=$(".page-head"),sw=$("#timeframeSwitch");
 if(head&&!sw){sw=document.createElement("div");sw.id="timeframeSwitch";sw.className="timeframe-switch";head.insertAdjacentElement("afterend",sw);}
 if(sw){sw.innerHTML=timeframes.map(function(t){return '<button type="button" class="timeframe-btn '+(t[0]===selectedTimeframe?'active':'')+'" data-timeframe="'+t[0]+'">'+t[1]+'</button>';}).join("");Array.prototype.forEach.call(sw.querySelectorAll("[data-timeframe]"),function(b){b.addEventListener("click",function(){loadMarket(m,b.getAttribute("data-timeframe"));});});}
 if(st)st.textContent="جاري تحليل "+(timeframes.find(function(t){return t[0]===selectedTimeframe;})||timeframes[0])[1]+"…";
 function fetchMarketOnce(url,done){getJSON(url).then(function(j){j=j||{};done(j);if(j.scan_stats&&j.scan_stats.scanning){setTimeout(function(){fetchMarketOnce(url+"&retry="+Date.now(),done);},8000);}}).catch(function(){if(st)st.textContent="تعذر جلب بيانات هذا السوق حالياً — اضغط تحديث للمحاولة مرة ثانية.";});}
 fetchMarketOnce("/api/opportunities?market="+encodeURIComponent(m)+"&timeframe="+encodeURIComponent(selectedTimeframe)+"&x="+Date.now(),function(j){var rows=j.opportunities||[],s=j.scan_stats||{};render(el,rows);var t=s.updated_at?new Date(s.updated_at*1000).toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"}):"جاري التحديث";if(st)st.textContent=s.scanning?"جاري فحص "+m+" بالخلفية · سيتم تحديث النتائج تلقائياً…":"تحليل "+selectedTimeframe+" · آخر تحديث: "+t;});
}

function loadCoreMarkets(){
 var toolsBox=$("#platformTools"),marketsBox=$("#coreMarkets");
 if(toolsBox){
  var toolsItems=[["◈","الرادار الذكي","radar","فرص الأسواق مرتبة بحسب البيانات المتاحة"],["💎","الصفقات الذهبية","gold","متابعة أقوى الفرص المصنّفة"],["🚀","راصد الانفجار","explosion","رصد الحركة المحتملة مع الأهداف والوقف"],["📊","نتائج الأداء","results","مراجعة نتائج التوصيات السابقة"],["📰","الأخبار","news","متابعة أخبار السوق"],["✍️","المدونة","blog","مقالات التداول وإدارة المخاطر"]];
  toolsBox.innerHTML=toolsItems.map(function(x){return '<article class="core-card tool-card" role="link" tabindex="0" data-s="'+x[2]+'"><div class="core-title"><span>'+x[0]+'</span><b>'+x[1]+'</b></div><div class="core-analysis">'+x[3]+'</div><div class="card-foot">استكشف القسم ←</div></article>';}).join("");
 }
 if(marketsBox){
  var markets=[["₿","سبوت","spot","Binance Spot"],["⚡","فيوتشر","futures","Binance Futures"],["α","Binance Alpha","alpha","فرص Alpha في صفحة مستقلة"],["◉","العقود الأمريكية","contracts","العقود والمؤشرات الأمريكية"],["🇺🇸","الأسهم الأمريكية","us","تحليل الأسهم الأمريكية"],["🇸🇦","السوق السعودي / تاسي","saudi","تحليل السوق السعودي"],["💱","الفوركس","forex","أزواج العملات"],["🥇","الذهب","gold","تحليل الذهب في قسم مستقل"]];
  marketsBox.innerHTML=markets.map(function(x){return '<article class="core-card market-link" role="link" tabindex="0" data-core-market="'+x[2]+'"><div class="core-title"><span>'+x[0]+'</span><b>'+x[1]+'</b></div><div class="core-analysis">'+x[3]+'</div><div class="card-foot">فتح السوق ←</div></article>';}).join("");
  

 }
}
function loadHome(){loadCoreMarkets();}
function fortuneCard(x,i){var d=x.direction==="SELL",score=Number(x.recommendation_score||x.ai_pct||x.ai||x.analysis_score||0),w=Math.max(0,Math.min(100,score)),ts=[x.tp1,x.tp2,x.tp3,x.tp4,x.tp5,x.tp6].filter(function(v){return v!==null&&v!==undefined&&v!=="";});var lv='<div class="level"><small>الدخول</small><b>'+esc(x.entry||"—")+'</b></div>';ts.forEach(function(v,n){lv+='<div class="level"><small>TP'+(n+1)+'</small><b>'+esc(v)+'</b></div>';});lv+='<div class="level"><small>SL</small><b>'+esc(x.sl||"—")+'</b></div>';return '<article class="card fortune-card"><div class="card-top"><div><span class="rank">#'+(i+1)+' · صفقة</span><div class="symbol">'+esc(displaySymbol(x)||"—")+'</div></div><span class="direction '+(d?"sell":"buy")+'">'+(d?"بيع":"شراء")+'</span></div><div class="score"><b>توافق '+Math.round(score)+'%</b><div class="score-bar"><i style="width:'+w+'%"></i></div><span class="rank">'+esc(x.verdict||"صفقة خارجية")+'</span></div><div class="levels">'+lv+'</div><div class="card-foot">🧠 تحليل مباشر للصفقة · '+esc(x.alignment||0)+'% مصادر مستقلة · 🕒 '+esc(x.published||"—")+'</div></article>';}
function loadRadar(tf){
 var box=$("#radarCards");if(!box)return;
 
 selectedTimeframe=tf||selectedTimeframe||"15m";
 var head=$(".page-head"),sw=$("#timeframeSwitch");
 if(head&&!sw){sw=document.createElement("div");sw.id="timeframeSwitch";sw.className="timeframe-switch";head.insertAdjacentElement("afterend",sw);}
 if(sw){sw.innerHTML=timeframes.map(function(t){return '<button type="button" class="timeframe-btn '+(t[0]===selectedTimeframe?"active":"")+'" data-timeframe="'+t[0]+'">'+t[1]+'</button>';}).join("");Array.prototype.forEach.call(sw.querySelectorAll("[data-timeframe]"),function(b){b.addEventListener("click",function(){loadRadar(b.getAttribute("data-timeframe"));});});}
 var markets=[["spot","₿","سبوت"],["futures","⚡","فيوتشر"],["contracts","◉","العقود الأمريكية"],["us","🇺🇸","الأسهم الأمريكية"],["saudi","🇸🇦","السوق السعودي"],["forex","💱","فوركس وذهب"]];
 box.innerHTML='<div class="empty">جاري جمع الإشارات الخارجية من جميع الأسواق على فريم '+esc(selectedTimeframe)+'…</div>';
 Promise.all(markets.map(function(m){return getJSON("/api/opportunities?market="+encodeURIComponent(m[0])+"&timeframe="+encodeURIComponent(selectedTimeframe)+"&x="+Date.now()).then(function(j){return {market:m,rows:(j.opportunities||[]),scan:j.scan_stats||{},error:false};}).catch(function(){return {market:m,rows:[],error:true};});})).then(function(groups){
  var all=[],failed=0,seen={};
  groups.forEach(function(g){if(g.error)failed++;g.rows.forEach(function(x){
   if(x.timeframe&&String(x.timeframe)!==selectedTimeframe)return;
   var symbol=displaySymbol(x),side=String(x.direction||x.side||"").toUpperCase();
   var key=[g.market[0],symbol,side,selectedTimeframe].join("|");
   if(seen[key]){if(Number(x.recommendation_score||x.ai_pct||0)>Number(seen[key].x.recommendation_score||seen[key].x.ai_pct||0))seen[key].x=x;return;}
   var mv=null;["timeframe_change_pct","change_pct","price_change_pct","pct_change","change_percent"].some(function(k){var n=Number(x[k]);if(x[k]!==null&&x[k]!==undefined&&x[k]!==""&&Number.isFinite(n)){mv=n;return true;}return false;});
   var score=Number(x.recommendation_score||x.ai_pct||x.analysis_score||0);
   var source=Number(x.source_count||x.alignment||0);
   var stamp=Number(x.detected_at||x.updated_at||0);if(stamp>1e12)stamp/=1000;
   var age=stamp?Math.max(0,(Date.now()/1000-stamp)/3600):null;
   var method=x.source_name||x.provider_name||x.source||"مصدر خارجي";
   var momentumScore=mv===null?0:Math.min(35,Math.abs(mv)*7); var scorePart=Math.max(0,Math.min(100,score))*.25; var sourcePart=Math.min(10,Math.max(0,source))*1.5; var agePart=age===null?0:age<=1?10:age<=6?7:age<=24?3:-15; var directionPart=0; if(mv!==null){if((mv>0&&side==="BUY")||(mv<0&&side==="SELL"))directionPart=10;else if((mv<0&&side==="BUY")||(mv>0&&side==="SELL"))directionPart=-18;} var quality=Math.max(0,Math.min(100,momentumScore+scorePart+sourcePart+agePart+directionPart));
   var z={x:x,market:g.market,move:mv,score:quality,method:method};all.push(z);seen[key]=z;
  });});
  all.sort(function(a,b){return b.score-a.score;});
  function v(n){return fmtPrice(n);}
  function make(z,i){
   var x=z.x,sell=String(x.direction||x.side||"").toUpperCase()==="SELL";
   var targets=Array.isArray(x.targets)?x.targets:[x.tp1,x.tp2,x.tp3];
   var lv='<div class="level"><small>الدخول</small><b>'+v(x.entry)+'</b></div>';
   targets.slice(0,3).forEach(function(t,j){lv+='<div class="level"><small>TP'+(j+1)+'</small><b>'+v(t)+'</b></div>';});
   lv+='<div class="level"><small>وقف الخسارة</small><b>'+v(x.sl)+'</b></div>';
   var change=z.move===null?'<span>تغيّر الفريم غير متاح</span>':'<b dir="ltr" class="edge-pct '+(z.move>=0?"edge-up":"edge-down")+'">'+(z.move>0?"+":"")+z.move.toFixed(3)+'%</b>';
   return '<article class="card smart-edge-card"><div class="card-top"><div><span class="rank">'+(i===0?"👑 الأفضلية الأولى":i===1?"🥈 الأفضلية الثانية":i===2?"🥉 الأفضلية الثالثة":"#"+(i+1))+' · '+esc(z.market[2])+' · '+esc(selectedTimeframe)+'</span><div class="symbol">'+esc(displaySymbol(x)||"—")+'</div></div><span class="direction '+(sell?"sell":"buy")+'">'+(sell?"بيع":"شراء")+'</span></div><div class="card-foot">مصدر الإشارة: <b>'+esc(z.method)+'</b></div><div class="edge-change"><small>التغيّر على نفس الفريم</small>'+change+'</div><div class="score"><b>درجة ترتيب الفرصة '+Math.round(z.score)+'/100</b><div class="score-bar"><i style="width:'+Math.round(z.score)+'%"></i></div><span class="rank">درجة فرز وليست احتمال ربح</span></div><div class="levels">'+lv+'</div><div class="card-foot">مصادر: '+Number(x.source_count||0)+' · لا تُعرض الصفقة دون بياناتها الفعلية</div></article>';
  }
  box.innerHTML=all.length?'<div class="edge-summary"><div class="edge-stat"><span>الفريم</span><b>'+esc(selectedTimeframe)+'</b></div><div class="edge-stat"><span>الأسواق المستجيبة</span><b>'+(markets.length-failed)+'/6</b></div><div class="edge-stat"><span>الصفقات بعد إزالة التكرار</span><b>'+all.length+'</b></div></div><section class="edge-market-group"><div class="edge-market-title"><h3>🏆 أقوى الإشارات الخارجية بين الأسواق</h3><span>ترتيب موحّد من الأقوى للأقل</span></div><div class="cards">'+all.slice(0,50).map(make).join("")+'</div></section>':'<div class="empty">ما وصلت صفقات حقيقية من المصادر الحالية على هذا الفريم. ما راح نختلق توصيات.</div>';
 }).catch(function(){box.innerHTML='<div class="empty">تعذر جمع الإشارات الخارجية حالياً؛ حاول التحديث لاحقاً.</div>';});
}
function loadGold(tf){
 var edge=$("#smartEdgeCards"),summary=$("#smartEdgeSummary"),updated=$("#smartEdgeUpdated");
 if(!edge)return;
 selectedTimeframe=tf||selectedTimeframe||"15m";
 var head=$(".page-head"),sw=$("#timeframeSwitch");
 if(head&&!sw){sw=document.createElement("div");sw.id="timeframeSwitch";sw.className="timeframe-switch";head.insertAdjacentElement("afterend",sw);}
 if(sw){sw.innerHTML=timeframes.map(function(t){return '<button type="button" class="timeframe-btn '+(t[0]===selectedTimeframe?"active":"")+'" data-timeframe="'+t[0]+'">'+t[1]+'</button>';}).join("");Array.prototype.forEach.call(sw.querySelectorAll("[data-timeframe]"),function(b){b.addEventListener("click",function(){loadGold(b.getAttribute("data-timeframe"));});});}
 var markets=[["spot","₿","سبوت"],["futures","⚡","فيوتشر"],["contracts","◉","العقود الأمريكية"],["us","🇺🇸","الأسهم الأمريكية"],["saudi","🇸🇦","السوق السعودي"],["forex","💱","فوركس وذهب"]];
 edge.innerHTML='<div class="empty">جاري فحص الأسواق الستة على فريم '+esc(selectedTimeframe)+'…</div>';
 if(summary)summary.innerHTML='';
 if(updated)updated.textContent="جاري فحص 6 أسواق…";
 function num(v){var n=Number(v);return v!==null&&v!==undefined&&v!==""&&Number.isFinite(n)?n:null;}
 function stamp(x){var v=num(x.detected_at||x.updated_at||x.timestamp);if(v===null)return null;if(v>1e12)v=v/1000;return v>0?v:null;}
 function movement(x){var keys=["timeframe_change_pct","change_pct","price_change_pct","pct_change","change_percent"];for(var k=0;k<keys.length;k++){var v=num(x[keys[k]]);if(v!==null)return v;}return null;}
 function grade(x,mv){
  var conf=num(x.recommendation_score);if(conf===null)conf=num(x.ai_pct);if(conf===null)conf=num(x.analysis_score);conf=conf===null?0:Math.max(0,Math.min(100,conf));
  var sources=Math.max(0,Math.min(10,num(x.source_count)||0));
  var agree=num(x.external_agreement);if(agree===null)agree=num(x.research_agreement);agree=agree===null?0:Math.max(0,Math.min(100,agree));
  var age=stamp(x),ageH=age===null?null:Math.max(0,(Date.now()/1000-age)/3600);
  var side=String(x.direction||x.side||"").toUpperCase(),match=mv===null?0:((mv>0&&side==="BUY")||(mv<0&&side==="SELL")?10:((mv<0&&side==="BUY")||(mv>0&&side==="SELL")?-18:0));
  var movePts=mv===null?0:Math.min(35,Math.abs(mv)*7);
  var freshness=ageH===null?0:(ageH<=1?10:ageH<=6?7:ageH<=24?3:-15);
  var total=Math.round(Math.max(0,Math.min(100,movePts+conf*.25+sources*1.5+agree*.15+freshness+match)));
  return {total:total,conf:conf,sources:sources,agree:agree,ageH:ageH,match:match};
 }
 Promise.all(markets.map(function(m){return getJSON("/api/opportunities?market="+encodeURIComponent(m[0])+"&timeframe="+encodeURIComponent(selectedTimeframe)+"&x="+Date.now()).then(function(j){return {market:m,rows:(j.opportunities||[]).filter(function(x){return !x.timeframe||String(x.timeframe)===selectedTimeframe;}),scan:j.scan_stats||{}};}).catch(function(){return {market:m,rows:[],error:true};});})).then(function(groups){
  var all=[],total=0,withMove=0,failed=0;
  groups.forEach(function(g){if(g.error)failed++;g.rows.forEach(function(x){var mv=movement(x),q=grade(x,mv);all.push({x:x,move:mv,quality:q,market:g.market});if(mv!==null)withMove++;});total+=g.rows.length;});
  all.sort(function(a,b){return b.quality.total-a.quality.total;});
  function card(z,i){
   var x=z.x,mv=z.move,q=z.quality,down=String(x.direction||x.side||"").toUpperCase()==="SELL",score=q.total,w=score;
   var change=mv===null?'<span class="edge-no-change">بيانات تغيّر الفريم غير متاحة</span>':'<b class="edge-pct '+(mv>=0?"edge-up":"edge-down")+'" dir="ltr">'+(mv>0?"+":"")+mv.toFixed(3)+'%</b>';
   function val(v){return v===null||v===undefined||v===""?"غير محسوب":esc(v);}
   var price=x.current_price||x.live_price||x.price||"—",entry=x.entry||"—";
   var levels='<div class="level"><small>السعر الحالي</small><b>'+val(price)+'</b></div><div class="level"><small>الدخول</small><b>'+val(entry)+'</b></div><div class="level"><small>TP1</small><b>'+val(x.tp1)+'</b></div><div class="level"><small>وقف الخسارة</small><b>'+val(x.sl)+'</b></div>';
   var freshness=q.ageH===null?"حداثة البيانات غير مؤكدة":q.ageH<1?"البيانات خلال آخر ساعة":q.ageH<=24?"عمر البيانات "+Math.round(q.ageH)+" ساعة":"⚠️ البيانات أقدم من 24 ساعة";
   return '<article class="card smart-edge-card"><div class="card-top"><div><span class="rank">'+(i===0?"👑 الأقوى عبر الأسواق":"#"+(i+1))+' · '+esc(z.market[2])+' · '+esc(selectedTimeframe)+'</span><div class="symbol">'+esc(displaySymbol(x)||"—")+'</div></div><span class="direction '+(down?"sell":"buy")+'">'+(down?"بيع":"شراء")+'</span></div><div class="edge-change"><small>تغيّر الفريم</small>'+change+'</div><div class="score"><b>قوة الفرصة '+score+'/100</b><div class="score-bar"><i style="width:'+w+'%"></i></div><span class="rank">تقييم فرز وليس احتمال ربح</span></div><div class="levels">'+levels+'</div><div class="card-foot">المصادر: '+q.sources+' · توافق خارجي: '+q.agree+'% · '+freshness+(q.match<0?' · ⚠️ اتجاه الإشارة يعاكس الحركة':'')+'</div></article>';
  }
  var top=all.slice(0,5);
  var topHtml=top.length?'<section class="edge-market-group"><div class="edge-market-title"><h3>🏆 أقوى الفرص بين جميع الأسواق</h3><span>مرتبة حسب قوة الفرصة</span></div><div class="cards">'+top.map(card).join("")+'</div></section>':'<div class="empty">ما وصلت إشارات قابلة للتقييم من المصادر الحالية.</div>';
  var groupsHtml=groups.map(function(g){
   var rows=all.filter(function(z){return z.market[0]===g.market[0];});
   var body=rows.length?rows.map(function(z,i){return card(z,i+5);}).join(""):'<div class="empty">'+(g.error?"تعذر جلب هذا السوق؛ ما نحسبه كسوق سليم.":"ما فيه إشارات متاحة على الفريم المختار.")+'</div>';
   var st=g.scan||{},scanned=num(st.scanned||st.total_scanned||st.assets_scanned);
   return '<section class="edge-market-group"><div class="edge-market-title"><h3>'+g.market[1]+' '+g.market[2]+'</h3><span>'+rows.length+' إشارة'+(scanned===null?"":" · فُحص "+scanned+" أصل")+'</span></div><div class="cards">'+body+'</div></section>';
  }).join("");
  edge.innerHTML=topHtml+groupsHtml;
  if(summary)summary.innerHTML='<div class="edge-stat"><span>الفريم</span><b>'+esc(selectedTimeframe)+'</b></div><div class="edge-stat"><span>الأسواق المستجيبة</span><b>'+(markets.length-failed)+'/6</b></div><div class="edge-stat"><span>الإشارات المستلمة</span><b>'+total+'</b></div><div class="edge-stat"><span>تغيّر فريم متوفر</span><b>'+withMove+'/'+total+'</b></div>';
  if(updated)updated.textContent="آخر فحص: "+new Date().toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"})+(failed?" · تعذر سوق/أسواق":"");
 }).catch(function(){edge.innerHTML='<div class="empty">تعذر تحديث رادار الأسواق حالياً.</div>';if(updated)updated.textContent="تعذر التحديث";});
}
function loadBlog(){
 var el=$("#blogCards");if(!el)return;
 var articles=[
 ["trading-for-beginners","التداول للمبتدئين: دليل شامل","ابدأ بفهم الأسواق والخطة وإدارة رأس المال."],
 ["technical-analysis-basics","أساسيات التحليل الفني","افهم الاتجاه والدعم والمقاومة وقراءة الرسم."],
 ["risk-management-in-trading","إدارة المخاطر في التداول","خطوات عملية لتحديد حجم الصفقة والمخاطرة."],
 ["stop-loss-explained","وقف الخسارة: كيف تستخدمه؟","تعلم وظيفة وقف الخسارة وحدوده وقت التقلب."],
 ["backtesting-trading-strategy","اختبار الاستراتيجية تاريخياً","كيف تختبر القواعد وتحتسب الرسوم والانزلاق."],
 ["bitcoin-volatility","تقلبات البيتكوين","لماذا يتحرك السعر بسرعة وكيف تقرأ المخاطر."],
 ["crypto-futures-risks","مخاطر عقود العملات الرقمية","الهامش والرافعة والتصفية وإدارة رأس المال."],
 ["crypto-spot-trading","دليل تداول العملات الرقمية سبوت","مبادئ الأوامر والسيولة والرسوم."],
 ["breakout-trading-guide","استراتيجية الاختراق","كيف تقيّم الاختراق وتتحقق من تأكيده."],
 ["forex-risk-basics","أساسيات مخاطر الفوركس","افهم الرافعة والهامش ومخاطر العملات."],
 ["gold-trading-basics","أساسيات تداول الذهب","العوامل المؤثرة على الذهب وإدارة المخاطر."],
 ["risk-reward-ratio","نسبة العائد إلى المخاطرة","طريقة حساب النسبة ولماذا لا تكفي وحدها."],
 ["saudi-stock-market-tasi","دليل السوق السعودي وتاسي","مقدمة عن السوق السعودي ومؤشر تاسي."],
 ["trading-journal","دفتر تداول احترافي","سجل صفقاتك وراجع الأخطاء والنتائج."],
 ["trading-psychology","علم النفس في التداول","تعامل مع الخوف والطمع والاندفاع."],
 ["trading-timeframes","كيف تختار الإطار الزمني؟","الفروق بين الفريمات القصيرة والطويلة."],
 ["trend-following-strategy","استراتيجية تتبع الاتجاه","مبادئ تتبع الاتجاه ومتى تفشل."],
 ["us-stock-market-basics","أساسيات الأسهم الأمريكية","مقدمة عن السوق الأمريكي وجلساته."],
 ["volume-in-trading","حجم التداول وكيف تقرأه","افهم السيولة ونشاط السوق من الحجم."],
 ["support-and-resistance","الدعم والمقاومة","كيف تحدد المناطق السعرية وتتعامل معها."]
 ];
 function renderStatic(){el.innerHTML=articles.map(function(a){return '<article class="card"><span class="eyebrow">مقال تعليمي</span><h3><a href="/static/articles/'+a[0]+'.html">'+esc(a[1])+'</a></h3><p class="card-foot">'+esc(a[2])+'</p><a href="/static/articles/'+a[0]+'.html">اقرأ المقال ←</a></article>';}).join("");}
 getJSON("/api/blog?x="+Date.now()).then(function(j){
  var rows=j.items||[];
  if(rows.length){el.innerHTML=rows.map(function(x){return '<article class="card"><span class="eyebrow">SMART TRADING / BLOG</span><h3><a href="/blog/'+encodeURIComponent(x.slug||"")+'">'+esc(x.title||"مقال")+'</a></h3><p class="card-foot">'+esc(x.text||"")+'</p><a href="/blog/'+encodeURIComponent(x.slug||"")+'">اقرأ المقال ←</a></article>';}).join("");}
  else renderStatic();
 }).catch(renderStatic);
}
function loadNews(){var el=$("#newsCards");if(!el)return;getJSON("/api/news?x="+Date.now()).then(function(j){var rows=j.items||[];el.innerHTML=rows.length?rows.map(function(x){var impacts=x.impacts||[];var marketCards=impacts.map(function(i){var d=i.direction==="بيع",neutral=i.direction==="محايد",cls=neutral?"":(d?"sell":"buy"),icon=neutral?"⚪":(d?"🔴":"🟢");return '<div class="news-market-impact"><div class="card-top"><div><span class="rank">'+icon+' '+esc(i.market_name||"السوق")+' · '+esc(i.impact||"")+'</span><div class="symbol">'+esc(i.symbol||"السوق")+'</div></div><span class="direction '+cls+'">'+esc(i.action||i.direction||"مراقبة")+'</span></div><div class="levels"><div class="level"><small>الاتجاه</small><b>'+esc(i.direction||"محايد")+'</b></div><div class="level"><small>قوة التأثير</small><b>'+esc(i.impact||"—")+'</b></div></div><p class="news-why">💡 '+esc(i.why||"متابعة حركة السعر")+'</p></div>';}).join("");return '<article class="card news-intel"><div class="card-top"><div><span class="rank">📰 خبر يؤثر على '+esc(x.markets_count||impacts.length)+' أسواق</span></div><span class="rank">حديث</span></div><h3>'+esc(x.title||"خبر السوق")+'</h3><p class="news-summary">'+esc(x.summary||"تحليل الخبر حسب كل سوق")+'</p><div class="news-market-list">'+marketCards+'</div><div class="card-foot">تحليل مستقل لكل سوق داخل نفس الخبر · بدون عرض مصادر</div></article>';}).join(""):'<div class="empty">لا توجد أخبار جديدة مؤثرة حالياً.</div>';}).catch(function(){el.innerHTML='<div class="empty">تعذر تحديث تحليل الأخبار حالياً.</div>';});}
function loadResults(){
  var box=$("#resultsCards"),summary=$("#resultsSummary"),markets=$("#resultsMarkets");if(!box)return;
  getJSON("/api/results?x="+Date.now()).then(function(j){
   var s=j.stats||{};
   if(summary)summary.innerHTML='<div class="metric"><span>إجمالي التوصيات</span><b>'+s.total+'</b><small>آخر 24 ساعة</small></div><div class="metric"><span>رابحة</span><b>'+s.wins+'</b><small>وصلت للهدف</small></div><div class="metric"><span>خاسرة</span><b>'+s.losses+'</b><small>وصلت للوقف</small></div><div class="metric"><span>نسبة النجاح</span><b>'+s.win_rate+'%</b><small>من الصفقات المغلقة</small></div>';
   if(markets)markets.innerHTML=Object.keys(j.by_market||{}).map(function(k){var m=j.by_market[k]||{},n={spot:"سبوت",futures:"فيوتشر",contracts:"العقود الأمريكية",us:"الأمريكي",saudi:"السعودي",forex:"فوركس وذهب"}[k]||k;return '<div class="metric"><span>'+n+'</span><b>'+m.win_rate+'%</b><small>'+m.wins+' رابحة · '+m.losses+' خاسرة · '+m.open+' مفتوحة</small></div>';}).join("");
   var rows=j.results||[];
   box.innerHTML=rows.length?rows.map(function(x){var st=x.status==="WIN"?"✅ رابحة":x.status==="LOSS"?"❌ خاسرة":x.status==="EXPIRED"?"⚪ منتهية":"⏳ مفتوحة",cls=x.status==="WIN"?"buy":x.status==="LOSS"?"sell":"";return '<article class="card"><div class="card-top"><div><span class="rank">'+st+'</span><div class="symbol">'+esc(displaySymbol(x))+'</div></div><span class="direction '+cls+'">'+(x.direction==="SELL"?"بيع":"شراء")+'</span></div><div class="levels"><div class="level"><small>الدخول</small><b>'+esc(x.entry||"—")+'</b></div><div class="level"><small>TP1</small><b>'+esc(x.tp1||"—")+'</b></div><div class="level"><small>TP2</small><b>'+esc(x.tp2||"—")+'</b></div><div class="level"><small>TP3</small><b>'+esc(x.tp3||"—")+'</b></div><div class="level"><small>SL</small><b>'+esc(x.sl||"—")+'</b></div><div class="level"><small>النتيجة</small><b>'+st+'</b></div></div><div class="card-foot">'+esc({spot:"سبوت",futures:"فيوتشر",contracts:"العقود",us:"الأمريكي",saudi:"السعودي",forex:"فوركس وذهب",alpha:"Alpha"}[x.market]||x.market)+' · '+new Date(x.created*1000).toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"})+'</div></article>';}).join(""):(j.refreshing?'<div class="empty">⏳ جاري جمع التوصيات وتحديث أسعارها… بتظهر النتائج تلقائيًا عند اكتمال التحديث.</div>':'<div class="empty">ما فيه نتائج مسجلة خلال آخر 24 ساعة حتى الآن.</div>');
   if(j.refreshing)setTimeout(loadResults,8000);
  }).catch(function(){box.innerHTML='<div class="empty">تعذر جلب النتائج حالياً.</div>';});
}
var selectedWhaleMarket="spot";
var selectedWhaleThreshold=10000;
function loadWhales(tf,marketChoice,thresholdChoice){
 var summary=$("#whaleSummary"),markets=$("#whaleMarkets"),box=$("#whaleCards");if(!box)return;
 if(marketChoice)selectedWhaleMarket=marketChoice;
 if(thresholdChoice)selectedWhaleThreshold=Number(thresholdChoice)||10000;
 var names={spot:"سبوت بايننس",futures:"فيوتشر بايننس",contracts:"العقود الأمريكية",us:"الأسهم الأمريكية",saudi:"السوق السعودي / تاسي",forex:"فوركس وذهب"};
 var thresholds=[10000,50000,100000,500000];
 var head=$(".page-head"),mw=$("#whaleMarketSwitch"),tw=$("#whaleThresholdSwitch");
 if(head&&!mw){mw=document.createElement("div");mw.id="whaleMarketSwitch";mw.className="timeframe-switch whale-market-switch";head.insertAdjacentElement("afterend",mw);}
 if(mw){mw.innerHTML=Object.keys(names).map(function(m){return '<button type="button" class="timeframe-btn '+(m===selectedWhaleMarket?'active':'')+'" data-whale-market="'+m+'">'+names[m]+'</button>';}).join("");Array.prototype.forEach.call(mw.querySelectorAll("[data-whale-market]"),function(b){b.addEventListener("click",function(){loadWhales(selectedTimeframe,b.getAttribute("data-whale-market"));});});}
 if(head&&!tw){tw=document.createElement("div");tw.id="whaleThresholdSwitch";tw.className="timeframe-switch whale-threshold-switch";tw.setAttribute("aria-label","فلتر حجم الصفقة");(mw||head).insertAdjacentElement("afterend",tw);}
 if(tw){tw.innerHTML='<span class="whale-filter-label">أقل قيمة للصفقة:</span>'+thresholds.map(function(v){return '<button type="button" class="timeframe-btn '+(v===selectedWhaleThreshold?'active':'')+'" data-whale-threshold="'+v+'">$'+(v/1000)+' ألف</button>';}).join("");Array.prototype.forEach.call(tw.querySelectorAll("[data-whale-threshold]"),function(b){b.addEventListener("click",function(){loadWhales(selectedTimeframe,null,b.getAttribute("data-whale-threshold"));});});}
 var marketName=names[selectedWhaleMarket]||names.spot;
 var thresholdLabel="$"+selectedWhaleThreshold.toLocaleString("en-US");
 if(!["spot","futures"].includes(selectedWhaleMarket)){
  if(summary)summary.innerHTML='<div class="metric"><span>السوق</span><b>'+marketName+'</b><small>المصدر المباشر غير موصول لهذا السوق</small></div>';
  if(markets)markets.innerHTML='<div class="metric"><span>حالة المصدر</span><b>غير موصول</b><small>لن نعرض حركة سعر على أنها صفقات حيتان</small></div>';
  box.innerHTML='<div class="empty">رصد الصفقات الكبيرة المنفذة متاح حاليًا من Binance Spot وFutures فقط. هذا السوق يحتاج مصدر صفقات مستقل.</div>';return;
 }
 if(summary)summary.innerHTML='<div class="metric"><span>المصدر</span><b>Binance مباشر</b><small>صفقات منفذة فعلية</small></div><div class="metric"><span>السوق</span><b>'+marketName+'</b><small>هذا السوق فقط</small></div><div class="metric"><span>حد الصفقة</span><b>'+thresholdLabel+'</b><small>قيمة اسمية للصفقة</small></div>';
 if(markets)markets.innerHTML='<div class="metric"><span>حالة الرصد</span><b>جاري الاتصال</b><small>فحص أعلى 30 زوج USDT بعد استبعاد العملات المستقرة</small></div>';
 box.innerHTML='<div class="empty">جاري جلب الصفقات الكبيرة المنفذة من Binance…</div>';
 getJSON('/api/whale-trades?market='+encodeURIComponent(selectedWhaleMarket)+'&min_notional_usdt='+selectedWhaleThreshold+'&x='+Date.now()).then(function(j){
  var trades=Array.isArray(j.trades)?j.trades:[];
  trades.sort(function(a,b){return Number(b.notional_usdt||0)-Number(a.notional_usdt||0);});
  if(summary)summary.innerHTML='<div class="metric"><span>المصدر</span><b>Binance مباشر</b><small>بيانات صفقات منفذة</small></div><div class="metric"><span>الرموز المفحوصة</span><b>'+Number(j.symbols_scanned||0)+'</b><small>أعلى أزواج USDT تداولًا بعد استبعاد المستقرة</small></div><div class="metric"><span>الصفقات الكبيرة</span><b>'+trades.length+'</b><small>حد أدنى '+thresholdLabel+'</small></div><div class="metric"><span>آخر تحديث</span><b>'+(j.updated_at?new Date(j.updated_at*1000).toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit",second:"2-digit"}):"—")+'</b><small>'+(j.cached?'من ذاكرة مؤقتة قصيرة':'بيانات جديدة')+'</small></div>';
  if(markets)markets.innerHTML='<div class="metric"><span>'+marketName+'</span><b>'+(j.ok?'متصل':'تعذر الاتصال')+'</b><small>'+esc(j.message||'بيانات صفقات عامة')+'</small></div><div class="metric"><span>الترتيب</span><b>الأكبر أولًا</b><small>حسب القيمة الاسمية للصفقة</small></div><div class="metric"><span>تنبيه</span><b>لا تكشف الهوية</b><small>اتجاه taker لا يحدد نية المحفظة</small></div>';
  box.innerHTML=trades.length?trades.map(function(t,i){var buy=t.side==='BUY',time=t.trade_time?new Date(t.trade_time).toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit",second:"2-digit"}):"—";return '<article class="card whale-real-card"><div class="card-top"><div><span class="rank">#'+(i+1)+' · صفقة منفذة</span><div class="symbol">'+esc(t.symbol)+'</div></div><span class="direction '+(buy?'buy':'sell')+'">'+(buy?'شراء من السوق':'بيع للسوق')+'</span></div><div class="levels"><div class="level"><small>القيمة الاسمية</small><b>$'+Number(t.notional_usdt||0).toLocaleString("en-US",{maximumFractionDigits:0})+'</b></div><div class="level"><small>سعر التنفيذ</small><b>'+Number(t.price||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</b></div><div class="level"><small>الكمية</small><b>'+Number(t.quantity||0).toLocaleString("en-US",{maximumFractionDigits:6})+'</b></div><div class="level"><small>وقت التنفيذ</small><b>'+time+'</b></div></div><div class="whale-liquidity" data-liquidity-symbol="'+esc(t.symbol)+'" data-liquidity-side="'+(buy?'BUY':'SELL')+'" data-liquidity-entry="'+Number(t.price||0)+'"><div class="whale-liquidity-head">🎯 أهداف السيولة ووقف الخسارة</div><div class="whale-liquidity-content"><span class="liquidity-loading">جاري حساب مستويات السيولة…</span></div></div><div class="card-foot">صفقة منفذة من Binance · مستويات السيولة تقديرية وليست ضمانًا</div></article>';}).join(''): '<div class="empty">'+esc(j.message||'ما فيه صفقات تجاوزت '+thresholdLabel+' في العينة الحالية.')+'</div>';
  var liquidityCards=Array.prototype.slice.call(box.querySelectorAll("[data-liquidity-symbol]")), liquidityCursor=0;
  function loadNextLiquidity(){
   if(liquidityCursor>=liquidityCards.length)return;
   var el=liquidityCards[liquidityCursor++],content=el.querySelector(".whale-liquidity-content");
   var symbol=el.getAttribute("data-liquidity-symbol"),side=el.getAttribute("data-liquidity-side"),entry=el.getAttribute("data-liquidity-entry");
   getJSON('/api/whale-liquidity?market='+encodeURIComponent(selectedWhaleMarket)+'&symbol='+encodeURIComponent(symbol)+'&side='+side+'&entry='+encodeURIComponent(entry)+'&x='+Date.now()).then(function(l){
    if(!content)return;
    if(!l.available){content.innerHTML='<span class="liquidity-unavailable">'+esc(l.message||'مستويات السيولة غير متاحة الآن')+'</span>';return;}
    var targets=Array.isArray(l.targets)?l.targets:[];
    var targetHtml=targets.map(function(t){return '<div class="liquidity-level"><small>'+esc(t.name)+'</small><b>'+Number(t.price||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</b><em>R/R '+Number(t.risk_reward||0).toFixed(2)+'x</em></div>';}).join('');
    content.innerHTML='<div class="liquidity-entry"><small>الدخول المرجعي</small><b>'+Number(l.entry||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</b></div><div class="liquidity-targets">'+targetHtml+'</div><div class="liquidity-stop"><small>🛑 وقف الخسارة</small><b>'+Number(l.stop_loss||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</b></div><div class="liquidity-note">'+esc(l.note||'مستويات تقديرية')+'</div>';
   }).catch(function(){if(content)content.innerHTML='<span class="liquidity-unavailable">تعذر حساب السيولة لهذه الصفقة.</span>';}).finally(function(){loadNextLiquidity();});
  }
  for(var liquidityWorker=0;liquidityWorker<Math.min(4,liquidityCards.length);liquidityWorker++)loadNextLiquidity();
 }).catch(function(){if(box)box.innerHTML='<div class="empty">تعذر الاتصال ببيانات الصفقات الكبيرة؛ أعد المحاولة بعد قليل.</div>';});
}
function bind(){
 var side=$("#sidebar");
 if(side&&!side.querySelector('[data-s="gold"]')){var goldLink=document.createElement("button");goldLink.className="nav-item";goldLink.type="button";goldLink.setAttribute("data-s","gold");goldLink.innerHTML="<span>💎</span> الصفقات الذهبية";var radarEntry=side.querySelector('[data-s="radar"]');if(radarEntry)radarEntry.insertAdjacentElement("afterend",goldLink);else side.appendChild(goldLink);}
 if(side){var goldNavItem=side.querySelector('[data-s="gold"]');if(goldNavItem)goldNavItem.classList.toggle("active",page==="gold");}

 if(side){
  /* Alpha قسم مستقل ظاهر دائمًا في القائمة */
  if(!side.querySelector('[data-s="alpha"]')){
   var alphaLink=document.createElement("button");
   alphaLink.className="nav-item";
   alphaLink.type="button";
   alphaLink.setAttribute("data-s","alpha");
   alphaLink.innerHTML="<span>α</span> تحليل Binance Alpha";
   var spotEntry=side.querySelector('[data-s="spot"]');
   if(spotEntry&&spotEntry.parentNode)spotEntry.insertAdjacentElement("afterend",alphaLink);
   else side.appendChild(alphaLink);
  }
  side.querySelectorAll('[data-s="alpha"]').forEach(function(b){b.classList.toggle("active",page==="alpha"||new URLSearchParams(window.location.search).get("market")==="alpha");});

  var labels={results:"النتائج",news:"الأخبار",blog:"المدونة"};
  var icons={results:"📊",news:"📰",blog:"✍️"};
  Object.keys(labels).forEach(function(k){
   if(!side.querySelector('[data-s="'+k+'"]')){
    var b=document.createElement("button");
    b.className="nav-item";b.type="button";b.setAttribute("data-s",k);
    b.innerHTML="<span>"+icons[k]+"</span> "+labels[k];
    side.appendChild(b);
   }
  });
  /* Professional sidebar order: home, trading, markets, content, account */
  var footer=side.querySelector(".side-footer");
  var byKey={};
  Array.from(side.querySelectorAll(":scope > .nav-item")).forEach(function(el){
   var k=el.getAttribute("data-s");
   if(k&&!byKey[k])byKey[k]=el;else if(k)el.remove();
  });
  side.querySelectorAll(":scope > .side-title, :scope > .nav-label").forEach(function(el){el.remove();});
  Array.from(side.querySelectorAll(":scope > .nav-item")).forEach(function(el){el.remove();});
  var makeSection=function(title,keys,extraClass){
   var section=document.createElement("div");
   section.className="menu-section"+(extraClass?" "+extraClass:"");
   var heading=document.createElement("div");heading.className="side-title";heading.textContent=title;section.appendChild(heading);
   keys.forEach(function(k){if(byKey[k])section.appendChild(byKey[k]);});
   if(section.querySelector(".nav-item"))side.insertBefore(section,footer||null);
  };
  /* Markets first, then the rest of the platform menu. */
  makeSection("الأسواق",["spot","futures","alpha","contracts","us","saudi","forex"],"menu-markets");
  makeSection("الرئيسية",["home"],"menu-home");
  makeSection("التداول الذكي",["radar","gold","whales"],"menu-trading");
  makeSection("النتائج والمحتوى",["results","news","blog"],"menu-content");
  makeSection("الحساب والإدارة",["signup","login","admin"],"menu-account");
 }
 document.addEventListener("click",function(e){
  var target=e.target;
  if(target&&target.nodeType!==1)target=target.parentElement;
  if(!target)return;
  var nav=target.closest("[data-s]");
  if(nav){var destination=nav.getAttribute("data-s");if(destination){e.preventDefault();closeMenu();go(destination);}return;}
  var marketCard=target.closest("[data-core-market]");
  if(marketCard){var marketDestination=marketCard.getAttribute("data-core-market");if(marketDestination){e.preventDefault();go(marketDestination);}}
 },true);
 document.addEventListener("keydown",function(e){
  if(e.key!=="Enter"&&e.key!==" ")return;
  var el=e.target.closest('[role="link"][data-s], [role="link"][data-core-market]');
  if(!el)return;
  e.preventDefault();
  go(el.getAttribute("data-s")||el.getAttribute("data-core-market"));
 });
 var menu=$("#menu"),overlay=$("#overlay");
 if(menu)menu.addEventListener("click",function(){
  var s=$("#sidebar");if(s)s.classList.add("open");
  if(overlay)overlay.classList.add("show");
 });
 if(overlay)overlay.addEventListener("click",closeMenu);
}
function start(){bind();if(page==="home")loadHome();else if(page==="radar"){loadRadar();if(trackingTimer)clearInterval(trackingTimer);trackingTimer=setInterval(function(){loadRadar(selectedTimeframe);},900000);}else if(page==="gold"){loadGold();if(trackingTimer)clearInterval(trackingTimer);trackingTimer=setInterval(function(){loadGold(selectedTimeframe);},900000);}else if(page==="results"){loadResults();if(trackingTimer)clearInterval(trackingTimer);trackingTimer=setInterval(loadResults,60000);}else if(page==="whales"){loadWhales();if(trackingTimer)clearInterval(trackingTimer);trackingTimer=setInterval(loadWhales,900000);}else if(page==="news"){loadNews();}else if(page==="blog"){loadBlog();}else if(market){loadMarket(market);if(trackingTimer)clearInterval(trackingTimer);trackingTimer=setInterval(function(){loadMarket(market,selectedTimeframe);},900000);}}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start);else start();
})();
/* Global language picker: available on all app-shell pages. */
(function(){if(document.querySelector('script[data-st-language]'))return;var s=document.createElement("script");s.src="/static/language.js";s.defer=true;s.dataset.stLanguage="1";document.head.appendChild(s);})();
