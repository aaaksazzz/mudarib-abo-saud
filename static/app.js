(function(){
"use strict";
var $=function(s){return document.querySelector(s);};
var routes={home:"/static/home.html?v=20261008-core",radar:"/static/radar.html?v=20261008-core",gold:"/static/gold.html?v=20261008-core",results:"/static/results.html?v=20261008-core",news:"/static/news.html?v=20261008-core",blog:"/static/blog.html?v=20261008-core",spot:"/static/spot.html?v=20261008-core",futures:"/static/futures.html?v=20261008-core",contracts:"/static/contracts.html?v=20261008-core",us:"/static/us.html?v=20261008-core",saudi:"/static/saudi.html?v=20261008-core",forex:"/static/forex.html?v=20261008-core",signup:"/static/signup.html?v=20261008-core",login:"/static/login.html?v=20261008-core",admin:"/static/admin.html?v=20261008-core"};
var page=document.body.getAttribute("data-page")||"home",market=document.body.getAttribute("data-market")||"",loading=false;
function esc(v){return String(v==null?"":v).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");}

function displaySymbol(x){var s=String((x&&x.symbol)||"").trim().toUpperCase();var m=String((x&&x.market)||market||"").toLowerCase();if((m==="spot"||m==="futures")&&s&&!/USDT$/.test(s)&&/^[A-Z0-9]+$/.test(s)){s=s+"USDT";}return s;}function go(s){if(routes[s]){window.location.href=routes[s];}}
function closeMenu(){var s=$("#sidebar"),o=$("#overlay");if(s)s.classList.remove("open");if(o)o.classList.remove("show");}
function getJSON(url){return fetch(url,{cache:"no-store"}).then(function(r){if(!r.ok)throw new Error("HTTP "+r.status);return r.json();});}
function card(x,i){
 var sell=x.direction==="SELL",score=Number(x.recommendation_score||x.ai||0),w=Math.max(0,Math.min(100,score));
 var stamp=Number(x.detected_at||x.updated_at||0),age=stamp?Math.max(0,Math.floor((Date.now()/1000-stamp)/60)):null;
 var targets=Array.isArray(x.targets)?x.targets.filter(function(v){return v!==null&&v!==undefined&&v!=="";}):[];
 if(!targets.length){[x.tp1,x.tp2,x.tp3,x.tp4,x.tp5,x.tp6].forEach(function(v){if(v!==null&&v!==undefined&&v!=="")targets.push(v);});}
 var pcts=Array.isArray(x.target_profit_pcts)?x.target_profit_pcts:[];
 var hit=Array.isArray(x.hit_targets)?x.hit_targets:[];
 var outcome=x.outcome||"OPEN";
 var profit=Number(x.profit_pct);
 var live=x.outcome_live===true;
 var lv='<div class="level"><small>الدخول</small><b>'+esc(x.entry||"—")+'</b></div>';
 targets.forEach(function(v,n){
   var done=hit.indexOf(n+1)>=0, pct=pcts[n]!=null?pcts[n]:null;
   lv+='<div class="level trade-target '+(done?"hit":"")+'"><small>TP'+(n+1)+' '+(done?"💡":"")+'</small><b>'+esc(v)+'</b>'+(pct!==null?'<em>'+ (pct>0?"+":"")+pct+'%</em>':"")+'</div>';
 });
 lv+='<div class="level '+(outcome==="SL"?"hit-stop":"")+'"><small>SL '+(outcome==="SL"?"🔴":"")+'</small><b>'+esc(x.sl||"—")+'</b></div>';
 var resultText=live?(outcome==="SL"?"وقف الضرب 🔴":outcome==="OPEN"?"مفتوحة 🟡":outcome+" تحقق 🟢"):"بانتظار السعر";
 var profitText=live&&!isNaN(profit)?(profit>=0?"+":"")+profit.toFixed(2)+"%":"—";
 return '<article class="card"><div class="card-top"><div><span class="rank">#'+(x.rank||i+1)+' · فرصة</span><div class="symbol">'+esc(displaySymbol(x)||"")+'</div></div><span class="direction '+(sell?"sell":"buy")+'">'+(sell?"بيع":"شراء")+'</span></div><div class="score"><b>توافق المصادر '+profitText+'</b><div class="score-bar"><i style="width:'+w+'%"></i></div><span class="rank">'+resultText+'</span></div><div class="levels">'+lv+'</div><div class="card-foot">🎯 كل هدف يضيء عند تحققه · '+(x.source_count||0)+' مصادر · '+(age===null?"وقت التحديث غير متاح":age<1?"محدث الآن":"محدث قبل "+age+" د")+'</div></article>';
}
function render(el,rows){if(!el)return;var a=(rows||[]).slice().sort(function(x,y){return Number(y.recommendation_score||y.ai||0)-Number(x.recommendation_score||x.ai||0);});el.innerHTML=a.length?a.map(card).join(""):'<div class="empty">لا توجد فرص مؤكدة حالياً — جاري إعادة الفحص.</div>';}
function loadMarket(m){
 var el=$("#marketCards"),st=$("#marketStatus");if(!el)return;
 function fetchMarketOnce(url,done){getJSON(url).then(function(j){done(j||{});if((j.scan_stats&&j.scan_stats.scanning)&&!(j.opportunities||[]).length){setTimeout(function(){getJSON(url+"&retry=1").then(function(x){done(x||{});}).catch(function(){});},8000);}}).catch(function(){if(st)st.textContent="تعذر جلب بيانات هذا السوق حالياً.";});}
fetchMarketOnce("/api/opportunities?market="+encodeURIComponent(m)+"&x="+Date.now(),function(j){var rows=j.opportunities||[],s=j.scan_stats||{};render(el,rows);var t=s.updated_at?new Date(s.updated_at*1000).toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"}):"جاري الفحص";if(st)st.textContent=(s.valid_15m!==undefined?"تم تحليل "+(s.analyzed||0)+" · آخر تحديث: "+t:"جاري تحديث البيانات…");});
}
function loadCoreMarkets(){
 var box=$("#coreMarkets");if(!box)return;
 var items=[
  ["saudi","🇸🇦","السعودي / تاسي"],["spot","₿","الكريبتو سبوت"],["futures","⚡","الفيوتشر"],["us","🇺🇸","الأسهم الأمريكية"],["contracts","◉","العقود"],["forex","🥇","فوركس وذهب"]
 ];
 box.innerHTML=items.map(function(x){return '<article class="core-card" data-core-market="'+x[0]+'"><div class="core-title"><span>'+x[1]+'</span><b>'+x[2]+'</b></div><div class="core-analysis">جاري البحث عن صفقات منشورة...</div></article>';}).join("");
 getJSON("/api/radar?x="+Date.now()).then(function(j){
  var rows=j.opportunities||[];
  box.querySelectorAll("[data-core-market]").forEach(function(el){
   var m=el.getAttribute("data-core-market"),x=rows.find(function(r){return String(r.market||"").toLowerCase()===m;});
   var a=el.querySelector(".core-analysis");
   if(x)a.textContent=(x.direction==="SELL"?"بيع":"شراء")+" · "+esc(displaySymbol(x)||"—")+" · "+(x.source_count||0)+" مصدر";
   else if(a)a.textContent="لا توجد صفقة منشورة مكتملة حالياً — البحث مستمر";
  });
 }).catch(function(){
  box.querySelectorAll(".core-analysis").forEach(function(a){a.textContent="البحث مستمر عن صفقات منشورة";});
 });
}
function loadMarketSectors(){
 var box=$("#marketSectors");if(!box)return;
 var items=[
  ["🇸🇦","السعودي / تاسي"],["🇺🇸","الأسهم الأمريكية"],["💻","التقنية"],["🏦","البنوك والمالي"],["🏭","الصناعة"],["🏥","الصحة"],["🛒","الاستهلاك والتجزئة"],["⚡","الطاقة والمرافق"],["🏗️","العقار والإنشاءات"],["₿","الكريبتو"],["🥇","الذهب والمعادن"],["🛢️","النفط والطاقة"],["💵","الفوركس"],["📈","المؤشرات"],["🌍","الاقتصاد العالمي"]
 ];
 box.innerHTML=items.map(function(x){return '<article class="core-card"><div class="core-title"><span>'+x[0]+'</span><b>'+x[1]+'</b></div><div class="core-analysis">جمع المعلومات والتحليل مستمر...</div></article>';}).join("");
 getJSON("/api/fast-market?market=spot&timeframe=15m&x="+Date.now()).then(function(j){
  var n=(j.scan_stats&&j.scan_stats.analyzed)||0;
  box.querySelectorAll(".core-analysis").forEach(function(el){el.textContent="بيانات السوق: "+n+" أصل محلل · التحليل الخارجي قيد التحديث";});
 }).catch(function(){});
}
function loadHome(){loadCoreMarkets();var el=$("#homeCards"),rb=$("#homeResults");if(loading)return;loading=true;Promise.all([getJSON("/api/radar?x="+Date.now()),getJSON("/api/results?x="+Date.now())]).then(function(v){var j=v[0]||{},r=v[1]||{},rows=j.opportunities||[];render(el,rows.slice(0,8));if($("#count"))$("#count").textContent=rows.length;if($("#sources"))$("#sources").textContent=(j.opportunities||[]).reduce(function(n,x){return n+Number(x.source_count||0);},0);if($("#updated"))$("#updated").textContent=new Date().toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"});var rs=r.results||[];if(rb)rb.innerHTML=rs.length?rs.slice(0,6).map(function(x){var st=x.status==="WIN"?"✅ رابحة":x.status==="LOSS"?"❌ خاسرة":x.status==="EXPIRED"?"⚪ منتهية":"⏳ مفتوحة";return '<article class="card"><div class="card-top"><div><span class="rank">'+st+'</span><div class="symbol">'+esc(displaySymbol(x)||"—")+'</div></div><span class="direction '+(x.direction==="SELL"?"sell":"buy")+'">'+(x.direction==="SELL"?"بيع":"شراء")+'</span></div><div class="levels"><div class="level"><small>الدخول</small><b>'+esc(x.entry||"—")+'</b></div><div class="level"><small>TP1</small><b>'+esc(x.tp1||"—")+'</b></div><div class="level"><small>SL</small><b>'+esc(x.sl||"—")+'</b></div></div><div class="card-foot">نتيجة التوصية · '+esc(x.updated||x.created||"—")+'</div></article>';}).join(""):'<div class="empty">لا توجد نتائج حديثة حالياً.</div>';}).catch(function(){render(el,[]);if(rb)rb.innerHTML='<div class="empty">لا توجد نتائج حديثة حالياً.</div>';}).finally(function(){loading=false;});}
function fortuneCard(x,i){var d=x.direction==="SELL",score=Number(x.ai||x.analysis_score||0),w=Math.max(0,Math.min(100,score)),ts=[x.tp1,x.tp2,x.tp3,x.tp4,x.tp5,x.tp6].filter(function(v){return v!==null&&v!==undefined&&v!=="";});var lv='<div class="level"><small>الدخول</small><b>'+esc(x.entry||"—")+'</b></div>';ts.forEach(function(v,n){lv+='<div class="level"><small>TP'+(n+1)+'</small><b>'+esc(v)+'</b></div>';});lv+='<div class="level"><small>SL</small><b>'+esc(x.sl||"—")+'</b></div>';return '<article class="card fortune-card"><div class="card-top"><div><span class="rank">#'+(i+1)+' · صفقة</span><div class="symbol">'+esc(displaySymbol(x)||"—")+'</div></div><span class="direction '+(d?"sell":"buy")+'">'+(d?"بيع":"شراء")+'</span></div><div class="score"><b>توافق '+Math.round(score)+'%</b><div class="score-bar"><i style="width:'+w+'%"></i></div><span class="rank">'+esc(x.verdict||"تحليل مباشر")+'</span></div><div class="levels">'+lv+'</div><div class="card-foot">🧠 تحليل مباشر للصفقة · '+esc(x.alignment||0)+'% مصادر مستقلة · 🕒 '+esc(x.published||"—")+'</div></article>';}
function loadGold(){var el=$("#fortuneCards");if(!el)return;getJSON("/api/gold-signals?x="+Date.now()).then(function(j){var p=j.signals||[];el.innerHTML=p.length?p.map(fortuneCard).join(""):'<div class="empty">لا توجد صفقة ذهب مؤكدة حالياً.</div>';}).catch(function(){el.innerHTML='<div class="empty">تعذر تحديث صفقات الذهب حالياً.</div>';});}
function loadBlog(){var el=$("#blogCards");if(!el)return;getJSON("/api/blog?x="+Date.now()).then(function(j){var rows=j.items||[];el.innerHTML=rows.length?rows.map(function(x){return '<article class="card"><span class="eyebrow">SMART TRADING</span><h3>'+esc(x.title||"مقال")+'</h3><p class="card-foot">'+esc(x.text||"")+'</p></article>';}).join(""):'<div class="empty">لا توجد مقالات حالياً.</div>';}).catch(function(){el.innerHTML='<div class="empty">جاري تحديث المدونة…</div>';});}
function loadNews(){var el=$("#newsCards");if(!el)return;getJSON("/api/news?x="+Date.now()).then(function(j){var rows=j.items||[];el.innerHTML=rows.length?rows.map(function(x){var impacts=x.impacts||[];var marketCards=impacts.map(function(i){var d=i.direction==="بيع",neutral=i.direction==="محايد",cls=neutral?"":(d?"sell":"buy"),icon=neutral?"⚪":(d?"🔴":"🟢");return '<div class="news-market-impact"><div class="card-top"><div><span class="rank">'+icon+' '+esc(i.market_name||"السوق")+' · '+esc(i.impact||"")+'</span><div class="symbol">'+esc(i.symbol||"السوق")+'</div></div><span class="direction '+cls+'">'+esc(i.action||i.direction||"مراقبة")+'</span></div><div class="levels"><div class="level"><small>الاتجاه</small><b>'+esc(i.direction||"محايد")+'</b></div><div class="level"><small>قوة التأثير</small><b>'+esc(i.impact||"—")+'</b></div></div><p class="news-why">💡 '+esc(i.why||"متابعة حركة السعر")+'</p></div>';}).join("");return '<article class="card news-intel"><div class="card-top"><div><span class="rank">📰 خبر يؤثر على '+esc(x.markets_count||impacts.length)+' أسواق</span></div><span class="rank">حديث</span></div><h3>'+esc(x.title||"خبر السوق")+'</h3><p class="news-summary">'+esc(x.summary||"تحليل الخبر حسب كل سوق")+'</p><div class="news-market-list">'+marketCards+'</div><div class="card-foot">تحليل مستقل لكل سوق داخل نفس الخبر · بدون عرض مصادر</div></article>';}).join(""):'<div class="empty">لا توجد أخبار جديدة مؤثرة حالياً.</div>';}).catch(function(){el.innerHTML='<div class="empty">تعذر تحديث تحليل الأخبار حالياً.</div>';});}
function loadResults(){
 var box=$("#resultsCards"),summary=$("#resultsSummary"),markets=$("#resultsMarkets");if(!box)return;
 getJSON("/api/results?x="+Date.now()).then(function(j){
  var s=j.stats||{};
  if(summary)summary.innerHTML='<div class="metric"><span>إجمالي التوصيات</span><b>'+s.total+'</b><small>آخر 24 ساعة</small></div><div class="metric"><span>رابحة</span><b>'+s.wins+'</b><small>وصلت للهدف</small></div><div class="metric"><span>خاسرة</span><b>'+s.losses+'</b><small>وصلت للوقف</small></div><div class="metric"><span>نسبة النجاح</span><b>'+s.win_rate+'%</b><small>من الصفقات المغلقة</small></div>';
  if(markets)markets.innerHTML=Object.keys(j.by_market||{}).map(function(k){var m=j.by_market[k]||{},n={spot:"سبوت",futures:"فيوتشر",contracts:"العقود",us:"الأمريكي",saudi:"السعودي",forex:"فوركس وذهب"}[k]||k;return '<div class="metric"><span>'+n+'</span><b>'+m.win_rate+'%</b><small>'+m.wins+' رابحة · '+m.losses+' خاسرة · '+m.open+' مفتوحة</small></div>';}).join("");
  var rows=j.results||[];
  box.innerHTML=rows.length?rows.map(function(x){var st=x.status==="WIN"?"✅ رابحة":x.status==="LOSS"?"❌ خاسرة":x.status==="EXPIRED"?"⚪ منتهية":"⏳ مفتوحة",cls=x.status==="WIN"?"buy":x.status==="LOSS"?"sell":"";return '<article class="card"><div class="card-top"><div><span class="rank">'+st+'</span><div class="symbol">'+esc(displaySymbol(x))+'</div></div><span class="direction '+cls+'">'+(x.direction==="SELL"?"بيع":"شراء")+'</span></div><div class="levels"><div class="level"><small>الدخول</small><b>'+esc(x.entry||"—")+'</b></div><div class="level"><small>TP1</small><b>'+esc(x.tp1||"—")+'</b></div><div class="level"><small>TP2</small><b>'+esc(x.tp2||"—")+'</b></div><div class="level"><small>TP3</small><b>'+esc(x.tp3||"—")+'</b></div><div class="level"><small>SL</small><b>'+esc(x.sl||"—")+'</b></div><div class="level"><small>النتيجة</small><b>'+st+'</b></div></div><div class="card-foot">'+esc({spot:"سبوت",futures:"فيوتشر",contracts:"العقود",us:"الأمريكي",saudi:"السعودي",forex:"فوركس وذهب"}[x.market]||x.market)+' · '+new Date(x.created*1000).toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"})+'</div></article>';}).join(""):'<div class="empty">لا توجد نتائج مسجلة حتى الآن.</div>';
 }).catch(function(){box.innerHTML='<div class="empty">تعذر جلب النتائج حالياً.</div>';});
}
function bind(){var side=$("#sidebar");if(side){var labels={results:"📊 النتائج",news:"📰 الأخبار",blog:"✍️ المدونة"};var have={};Array.prototype.forEach.call(side.querySelectorAll("[data-s]"),function(b){have[b.getAttribute("data-s")]=true;});Object.keys(labels).forEach(function(k){if(!have[k]){var b=document.createElement("button");b.className="nav-item";b.type="button";b.setAttribute("data-s",k);b.innerHTML="<span>"+(k==="results"?"📊":k==="news"?"📰":"✍️")+"</span> "+labels[k].replace(/^[^\s]+\s*/,"");side.appendChild(b);}});
 // Keep one fixed, logical menu order. Do not insert new sections at the top.
 var order=["home","radar","gold","results","news","blog","spot","futures","contracts","us","saudi","forex","signup","login","admin"];
 order.forEach(function(k){var bs=side.querySelectorAll('[data-s="'+k+'"]');if(bs.length){side.appendChild(bs[0]);for(var j=1;j<bs.length;j++)bs[j].remove();}});}
Array.prototype.forEach.call(document.querySelectorAll("[data-s]"),function(b){b.addEventListener("click",function(e){e.preventDefault();go(b.getAttribute("data-s"));});});var menu=$("#menu"),overlay=$("#overlay");if(menu)menu.addEventListener("click",function(){var s=$("#sidebar");if(s)s.classList.add("open");if(overlay)overlay.classList.add("show");});if(overlay)overlay.addEventListener("click",closeMenu);}
function start(){bind();if(page==="home")loadHome();else if(page==="radar"){var lr=function(){getJSON("/api/radar?x="+Date.now()).then(function(j){render($("#radarCards"),j.opportunities||[]);});};lr();}else if(page==="gold"){loadGold();}else if(page==="results"){loadResults();}else if(page==="news"){loadNews();}else if(page==="blog"){loadBlog();}else if(market){loadMarket(market);}}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start);else start();
})();