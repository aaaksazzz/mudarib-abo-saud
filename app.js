import {
initializeApp
} from
"https://www.gstatic.com/firebasejs/12.1.0/firebase-app.js";

import {
getAuth,
GoogleAuthProvider,
signInWithPopup,
signOut,
onAuthStateChanged
} from
"https://www.gstatic.com/firebasejs/12.1.0/firebase-auth.js";

import {
firebaseConfig
} from "./firebase-config.js";


const configured =
!Object.values(firebaseConfig)
.some(v =>
String(v).includes("PUT_YOUR")
);


let auth = null;

if(configured){

const app =
initializeApp(firebaseConfig);

auth =
getAuth(app);

}


const $ =
id => document.getElementById(id);


function toast(message){

const t =
$("toast");

t.textContent =
message;

t.classList.add("show");

setTimeout(
() => t.classList.remove("show"),
2500
);

}



const demoSaudi = [

["2222","أرامكو السعودية","main"],

["1120","مصرف الراجحي","main"],

["2010","سابك","main"],

["1180","الأهلي السعودي","main"],

["7010","stc","main"],

["1211","معادن","main"],

["1150","مصرف الإنماء","main"],

["4030","البحري","main"],

["2050","صافولا","main"],

["7020","اتحاد اتصالات","main"]

];



const demoUS = [

["AAPL","Apple","nasdaq"],

["NVDA","NVIDIA","nasdaq"],

["MSFT","Microsoft","nasdaq"],

["AMZN","Amazon","nasdaq"],

["META","Meta Platforms","nasdaq"],

["TSLA","Tesla","nasdaq"],

["GOOGL","Alphabet","nasdaq"],

["AMD","AMD","nasdaq"],

["JPM","JPMorgan Chase","nyse"],

["XOM","Exxon Mobil","nyse"],

["KO","Coca-Cola","nyse"],

["WMT","Walmart","nyse"]

];



let binanceSymbols = [];

let favorites =
JSON.parse(
localStorage.getItem("favorites") || "[]"
);

let history =
JSON.parse(
localStorage.getItem("history") || "[]"
);

let alerts =
JSON.parse(
localStorage.getItem("alerts") || "[]"
);



function save(){

localStorage.setItem(
"favorites",
JSON.stringify(favorites)
);

localStorage.setItem(
"history",
JSON.stringify(history)
);

localStorage.setItem(
"alerts",
JSON.stringify(alerts)
);

}



function signalFor(symbol){

const n =
[...String(symbol)]
.reduce(
(a,c) =>
a + c.charCodeAt(0),
0
) % 5;

return [
"شراء قوي",
"شراء",
"حيادي",
"بيع",
"بيع قوي"
][n];

}



function priceFor(symbol){

const n =
[...String(symbol)]
.reduce(
(a,c) =>
a + c.charCodeAt(0),
0
);

return (
1 + (n % 9000) / 100
).toFixed(4);

}



function card(
[symbol,name,market]
){

const fav =
favorites.includes(symbol);

const signal =
signalFor(symbol);

const cls =
signal.includes("بيع")
? "red"
: signal === "حيادي"
? "neutral"
: "green";


return `

<div class="market-card">

<div class="market-card-head">

<span class="symbol">
${symbol}
</span>

<span class="${cls}">
${signal}
</span>

</div>

<small>
${name || market || ""}
</small>

<div class="price">
${priceFor(symbol)}
</div>

<div class="card-actions">

<button
class="ghost"
onclick="window.openAnalysis('${symbol}')">

تحليل

</button>

<button
class="ghost"
onclick="window.toggleFav('${symbol}')">

${fav ? "★" : "☆"}

</button>

</div>

</div>

`;

}



function render(
list,
id
){

$(id).innerHTML =
list.map(card).join("")
||
"<div class='panel'>لا توجد نتائج.</div>";

}



function renderSaudi(){

render(
demoSaudi,
"saudiList"
);

$("saudiCount").textContent =
demoSaudi.length;

}



function renderUS(){

render(
demoUS,
"usList"
);

}



async function loadBinance(){

$("binanceStatus").textContent =
"جاري جلب الرموز من Binance...";


try{

const response =
await fetch(
"/api/binance/exchange-info"
);

if(!response.ok)
throw new Error("backend");


const data =
await response.json();


binanceSymbols =
(data.symbols || [])

.filter(
x => x.status === "TRADING"
)

.map(
x => x.symbol
);


}catch(error){

$("binanceStatus").textContent =
"تعذر الاتصال بالخادم. يتم استخدام قائمة تجريبية.";


binanceSymbols = [

"BTCUSDT",

"ETHUSDT",

"BNBUSDT",

"SOLUSDT",

"XRPUSDT",

"DOGEUSDT",

"ADAUSDT",

"TRXUSDT",

"LINKUSDT",

"AVAXUSDT"

];

}


$("binanceCount").textContent =
binanceSymbols.length;


$("binanceStatus").textContent =
`تم تحميل ${binanceSymbols.length} رمز.`;


filterRender(
document.querySelector(
'[data-target="binanceList"]'
)
);


render(
binanceSymbols
.slice(0,9)
.map(
x => [x,x,"Binance"]
),
"homeList"
);

}



function filterRender(input){

if(!input)
return;


const target =
input.dataset.target;

const query =
input.value.toLowerCase();


let list;


if(target === "saudiList"){

list =
demoSaudi;

}

else if(target === "usList"){

list =
demoUS;

}

else{

list =
binanceSymbols.map(
x => [x,x,"Binance"]
);

}


if(target === "binanceList"){

const quote =
$("quoteFilter").value;

if(quote !== "all"){

list =
list.filter(
x => x[0].endsWith(quote)
);

}

}


list =
list.filter(
x =>
x.join(" ")
.toLowerCase()
.includes(query)
);


render(
list,
target
);

}



function openPage(id){

document
.querySelectorAll(".page")
.forEach(
p =>
p.classList.remove("active")
);


$(id).classList.add("active");


document
.querySelectorAll("nav button")
.forEach(
b =>
b.classList.toggle(
"active",
b.dataset.page === id
)
);


window.scrollTo({
top:0,
behavior:"smooth"
});


if(innerWidth < 750){

$("layout")
.classList.add(
"sidebar-hidden"
);

}


if(id === "favorites")
renderFavorites();

if(id === "history")
renderHistory();

if(id === "alerts")
renderAlerts();

}



function analysis(symbol){

symbol =
String(symbol || "")
.trim()
.toUpperCase();


if(!symbol){

toast("اكتب رمز الأصل");

return;

}


const signal =
signalFor(symbol);


const price =
Number(
priceFor(symbol)
);


const entry =
price;


const sl =
price * .98;


const tp1 =
price * 1.02;


const tp2 =
price * 1.04;


const tp3 =
price * 1.06;



history = [

{
symbol,
time:
new Date()
.toLocaleString("ar-SA"),

signal
},

...history.filter(
x => x.symbol !== symbol
)

].slice(0,30);


save();



$("analysisResult").innerHTML = `

<div class="analysis-box">

<div class="panel">

<h2>
${symbol}
</h2>

<div class="chart">

📈

<br>

منطقة الرسم

<br>

اربط مزود شموع حقيقي لإظهار الرسم الحي

</div>


<div class="metrics">

<div class="metric">

EMA 20

<br>

<b>
${(price*.99).toFixed(4)}
</b>

</div>


<div class="metric">

EMA 200

<br>

<b>
${(price*.96).toFixed(4)}
</b>

</div>


<div class="metric">

RSI

<br>

<b>
56.4
</b>

</div>


<div class="metric">

Volume

<br>

<b>
مرتفع
</b>

</div>

</div>

</div>



<div class="panel">

<div class="signal ${
signal.includes("بيع")
? "red"
: signal === "حيادي"
? "neutral"
: "green"
}">

${signal}

</div>


<p>
الفريم:
<b>
${$("tf").value}
</b>
</p>


<p>
دخول:
<b>
${entry.toFixed(4)}
</b>
</p>


<p class="green">
TP1:
${tp1.toFixed(4)}
</p>


<p class="green">
TP2:
${tp2.toFixed(4)}
</p>


<p class="green">
TP3:
${tp3.toFixed(4)}
</p>


<p class="red">
SL:
${sl.toFixed(4)}
</p>


<hr>


<p>
الدعم:
${(price*.97).toFixed(4)}
</p>


<p>
المقاومة:
${(price*1.03).toFixed(4)}
</p>


<p>
MACD:
بانتظار بيانات الشموع الحية
</p>


<p>
Harmonic:
Gartley / Bat / Butterfly / Crab /
Deep Crab / Cypher / Shark / ABCD
</p>


<button
class="primary"
onclick="window.toggleFav('${symbol}')">

⭐ إضافة / إزالة من المفضلة

</button>

</div>

</div>

`;



openPage("analysis");

}



function renderFavorites(){

render(
favorites.map(
x => [x,x,"Favorite"]
),
"favoritesList"
);

}



function renderHistory(){

render(
history.map(
x => [
x.symbol,
x.signal,
x.time
]
),
"historyList"
);

}



function renderAlerts(){

$("alertsList").innerHTML =

alerts.map(
(a,i) => `

<div class="market-card">

<b>
${a.symbol}
</b>

—

${a.condition}

${a.price}

<button
class="ghost"
onclick="window.delAlert(${i})">

حذف

</button>

</div>

`
).join("")

||
"<p>لا توجد تنبيهات.</p>";

}



window.openAnalysis =
symbol => {

$("analysisSymbol").value =
symbol;

analysis(symbol);

};



window.toggleFav =
symbol => {

if(
favorites.includes(symbol)
){

favorites =
favorites.filter(
x => x !== symbol
);

toast("تمت الإزالة من المفضلة");

}else{

favorites.push(symbol);

toast("تمت الإضافة للمفضلة");

}

save();

renderFavorites();

};



window.delAlert =
index => {

alerts.splice(index,1);

save();

renderAlerts();

};



document
.querySelectorAll("nav button")
.forEach(
button => {

button.onclick =
() =>
openPage(
button.dataset.page
);

}
);



document
.querySelectorAll("[data-page-jump]")
.forEach(
button => {

button.onclick =
() =>
openPage(
button.dataset.pageJump
);

}
);



$("menuBtn").onclick =
() =>
$("layout")
.classList.toggle(
"sidebar-hidden"
);



$("heroSearch").onclick =
() =>
openPage("analysis");



$("searchBtn").onclick =
() =>
window.openAnalysis(
$("globalSearch").value
);



$("globalSearch").onkeydown =
event => {

if(event.key === "Enter"){

window.openAnalysis(
event.target.value
);

}

};



$("analyzeBtn").onclick =
() =>
analysis(
$("analysisSymbol").value
);



document
.querySelectorAll(".market-filter")
.forEach(
input => {

input.oninput =
() =>
filterRender(input);

}
);



$("quoteFilter").onchange =
() =>
filterRender(
document.querySelector(
'[data-target="binanceList"]'
)
);



$("refreshBinance").onclick =
loadBinance;



$("runScan").onclick =
() => {

const market =
$("scanMarket").value;


let list;


if(market === "binance"){

list =
binanceSymbols.map(
x => [x,x,"Binance"]
);

}

else if(market === "saudi"){

list =
demoSaudi;

}

else{

list =
demoUS;

}


const filter =
$("scanSignal").value;


if(filter !== "all"){

list =
list.filter(
x =>
signalFor(x[0]) === filter
);

}


render(
list.slice(0,150),
"scanResults"
);

};



$("addAlert").onclick =
() => {

const symbol =
$("alertSymbol")
.value
.trim()
.toUpperCase();


const price =
$("alertPrice").value;


if(!symbol || !price){

toast("أدخل الرمز والسعر");

return;

}


alerts.push({

symbol,

condition:
$("alertCondition").value,

price

});


save();

renderAlerts();

$("alertSymbol").value = "";

$("alertPrice").value = "";

};



$("clearLocal").onclick =
() => {

localStorage.clear();

location.reload();

};



$("accent").oninput =
event => {

document.documentElement
.style
.setProperty(
"--accent",
event.target.value
);

};



$("themeBtn").onclick =
() => {

document.body.classList.toggle(
"light"
);

if(
document.body.classList.contains("light")
){

document.documentElement
.style
.setProperty(
"--bg",
"#f4f7fb"
);

document.documentElement
.style
.setProperty(
"--panel",
"#ffffff"
);

document.documentElement
.style
.setProperty(
"--panel2",
"#edf3f9"
);

document.documentElement
.style
.setProperty(
"--text",
"#102033"
);

document.documentElement
.style
.setProperty(
"--muted",
"#607286"
);

}else{

location.reload();

}

};



$("loginBtn").onclick =
async () => {

if(!configured){

toast(
"أضف بيانات Firebase أولًا"
);

return;

}


try{

await signInWithPopup(
auth,
new GoogleAuthProvider()
);

}catch(error){

toast(
"تعذر تسجيل الدخول"
);

console.error(error);

}

};



$("logoutBtn").onclick =
() => {

if(auth)
signOut(auth);

};



if(auth){

onAuthStateChanged(
auth,
user => {

if(user){

$("userBox").innerHTML =
`👤 <span>
${user.displayName || user.email}
</span>`;

$("loginBtn")
.classList
.add("hidden");

$("logoutBtn")
.classList
.remove("hidden");

}else{

$("userBox").innerHTML =
"👤 <span>زائر</span>";

$("loginBtn")
.classList
.remove("hidden");

$("logoutBtn")
.classList
.add("hidden");

}

}
);

}else{

$("userBox").innerHTML =
"👤 <span>زائر — Firebase غير مضاف</span>";

}



renderSaudi();

renderUS();

renderFavorites();

renderHistory();

renderAlerts();

loadBinance();
