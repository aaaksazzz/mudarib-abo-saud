(() => {
"use strict";

/* =========================================================
HELPERS
========================================================= */

const $ = (id) => document.getElementById(id);

const qs = (selector) => document.querySelector(selector);

const qsa = (selector) => [...document.querySelectorAll(selector)];

/* =========================================================
STATE
========================================================= */

const state = {
market: "crypto",
scannerMarket: "crypto",

interval: "15m",

results: [],
signals: [],

loading: false,
lastUpdated: null,

sortField: "change",
sortDesc: true,

signalFilter: null,
search: "",

recent: JSON.parse(
  localStorage.getItem("mudarib_recent") || "[]"
),

chart: null,

requestId: 0

};

/* =========================================================
API ROUTES
========================================================= */

const MARKET_API = {
crypto: "/api/okx/scan",
saudi: "/api/saudi/scan",
usmarket: "/api/usmarket/signals",
forex: "/api/forex/signals",
futures: "/api/futures/scan"
};

const MARKET_NAMES = {
crypto: "العملات الرقمية",
saudi: "السوق السعودي",
usmarket: "السوق الأمريكي",
forex: "الفوركس",
futures: "الفيوتشر"
};

/* =========================================================
INTERVALS
========================================================= */

const MARKET_INTERVALS = {
crypto: ["5m", "15m", "1h", "4h", "1d"],
saudi: ["5m", "15m", "1h", "4h", "1d"],
usmarket: ["5m", "15m", "1h", "4h", "1d"],
forex: ["5m", "15m", "1h", "4h", "1d"],
futures: ["5m", "15m", "1h", "4h", "1d"]
};

function normalizeInterval(interval) {

const value =
  String(interval || "")
    .trim()
    .toLowerCase();

const aliases = {
  "1m": "1m",
  "5m": "5m",
  "15m": "15m",
  "30m": "30m",
  "1h": "1h",
  "4h": "4h",
  "1d": "1d",
  "1day": "1d",
  "day": "1d"
};

return aliases[value] || "15m";

}

/* =========================================================
HTML ESCAPE
========================================================= */

function escapeHTML(value) {

return String(value ?? "")
  .replace(/&/g, "&amp;")
  .replace(/</g, "&lt;")
  .replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;")
  .replace(/'/g, "&#039;");

}

/* =========================================================
SAFE NUMBER
========================================================= */

function number(value, digits = 4) {

const n = Number(value);

if (!Number.isFinite(n)) {
  return "—";
}

if (Math.abs(n) >= 1e12) {
  return `${(n / 1e12).toFixed(2)}T`;
}

if (Math.abs(n) >= 1e9) {
  return `${(n / 1e9).toFixed(2)}B`;
}

if (Math.abs(n) >= 1e6) {
  return `${(n / 1e6).toFixed(2)}M`;
}

if (Math.abs(n) >= 1e3) {
  return n.toLocaleString("en-US", {
    maximumFractionDigits: 2
  });
}

if (Math.abs(n) < 0.001 && n !== 0) {
  return n.toLocaleString("en-US", {
    maximumFractionDigits: 8
  });
}

if (Math.abs(n) < 1 && n !== 0) {
  return n.toLocaleString("en-US", {
    maximumFractionDigits: 6
  });
}

return n.toLocaleString("en-US", {
  maximumFractionDigits: digits
});

}

function percent(value) {

const n = Number(value);

if (!Number.isFinite(n)) {
  return "—";
}

return `${n.toFixed(2)}%`;

}

function volume(value) {

const n = Number(value);

if (!Number.isFinite(n)) {
  return "—";
}

if (n >= 1e12) {
  return `${(n / 1e12).toFixed(2)}T`;
}

if (n >= 1e9) {
  return `${(n / 1e9).toFixed(2)}B`;
}

if (n >= 1e6) {
  return `${(n / 1e6).toFixed(2)}M`;
}

if (n >= 1e3) {
  return `${(n / 1e3).toFixed(1)}K`;
}

return number(n, 0);

}

function timeText(value) {

if (!value) {
  return "الآن";
}

const date = new Date(value);

if (Number.isNaN(date.getTime())) {
  return "الآن";
}

return date.toLocaleTimeString("ar-SA", {
  hour: "2-digit",
  minute: "2-digit"
});

}

/* =========================================================
SAFE OBJECT
========================================================= */

function safeItem(item) {

if (
  !item ||
  typeof item !== "object" ||
  Array.isArray(item)
) {
  return {};
}

return item;

}

/* =========================================================
DATA HELPERS
========================================================= */

function getSymbol(item) {

const x = safeItem(item);

return (
  x.symbol ??
  x.ticker ??
  x.code ??
  x.name ??
  "—"
);

}

function getName(item) {

const x = safeItem(item);

return (
  x.name ??
  x.symbol ??
  x.ticker ??
  x.code ??
  "—"
);

}

function getPrice(item) {

const x = safeItem(item);

const values = [
  x.price,
  x.close,
  x.last,
  x.currentPrice,
  x.entry
];

for (const value of values) {

  const n = Number(value);

  if (Number.isFinite(n)) {
    return n;
  }
}

return null;

}

function getEntry(item) {

const x = safeItem(item);

const values = [
  x.entry,
  x.price,
  x.close,
  x.last
];

for (const value of values) {

  const n = Number(value);

  if (Number.isFinite(n)) {
    return n;
  }
}

return null;

}

function getTP1(item) {

const x = safeItem(item);

const values = [
  x.tp1,
  x.takeProfit,
  x.target,
  x.tp
];

for (const value of values) {

  const n = Number(value);

  if (Number.isFinite(n)) {
    return n;
  }
}

return null;

}

function getTP2(item) {

const x = safeItem(item);

const values = [
  x.tp2,
  x.tp1,
  x.takeProfit,
  x.target,
  x.tp
];

for (const value of values) {

  const n = Number(value);

  if (Number.isFinite(n)) {
    return n;
  }
}

return null;

}

function getTP3(item) {

const x = safeItem(item);

const values = [
  x.tp3,
  x.tp2,
  x.tp1,
  x.takeProfit,
  x.target,
  x.tp
];

for (const value of values) {

  const n = Number(value);

  if (Number.isFinite(n)) {
    return n;
  }
}

return null;

}

function getSL(item) {

const x = safeItem(item);

const values = [
  x.sl,
  x.stopLoss,
  x.stop,
  x.stop_price
];

for (const value of values) {

  const n = Number(value);

  if (Number.isFinite(n)) {
    return n;
  }
}

return null;

}

function getSignal(item) {

const x = safeItem(item);

return String(
  x.signal ??
  x.direction ??
  x.action ??
  "حيادي"
);

}

function getScore(item) {

const x = safeItem(item);

let score =
  Number(x.score);

if (!Number.isFinite(score)) {

  score =
    Number(x.score10) * 10;
}

if (!Number.isFinite(score)) {

  score =
    Number(x.strength);
}

if (!Number.isFinite(score)) {

  score =
    Number(x.signal_strength);
}

if (!Number.isFinite(score)) {
  score = 0;
}

return Math.max(
  0,
  Math.min(100, score)
);

}

function getChange(item) {

const x = safeItem(item);

const value =
  x.change ??
  x.change24h ??
  x.changePercent ??
  x.percentChange ??
  x.pctChange ??
  0;

const n = Number(value);

return Number.isFinite(n)
  ? n
  : 0;

}

function getVolume(item) {

const x = safeItem(item);

const value =
  x.volume ??
  x.volume24h ??
  x.volCcy24h ??
  x.volume_usdt ??
  x.quoteVolume ??
  0;

const n = Number(value);

return Number.isFinite(n)
  ? n
  : 0;

}

function getRSI(item) {

const x = safeItem(item);

const n =
  Number(
    x.rsi ??
    x.RSI
  );

return Number.isFinite(n)
  ? n
  : null;

}

/* =========================================================
SIGNAL
========================================================= */

function isBuy(item) {

const s =
  getSignal(item).toUpperCase();

return (
  s.includes("شراء") ||
  s.includes("BUY") ||
  s.includes("LONG")
);

}

function isSell(item) {

const s =
  getSignal(item).toUpperCase();

return (
  s.includes("بيع") ||
  s.includes("SELL") ||
  s.includes("SHORT")
);

}

function isSignal(item) {

return (
  isBuy(item) ||
  isSell(item)
);

}

function signalClass(signal) {

const s =
  String(signal || "")
    .toUpperCase();

if (
  s.includes("شراء") ||
  s.includes("BUY") ||
  s.includes("LONG")
) {
  return "signal-buy";
}

if (
  s.includes("بيع") ||
  s.includes("SELL") ||
  s.includes("SHORT")
) {
  return "signal-sell";
}

return "signal-neutral";

}

function signalIcon(signal) {

const s =
  String(signal || "")
    .toUpperCase();

if (
  s.includes("شراء") ||
  s.includes("BUY") ||
  s.includes("LONG")
) {
  return "🟢";
}

if (
  s.includes("بيع") ||
  s.includes("SELL") ||
  s.includes("SHORT")
) {
  return "🔴";
}

return "⚪";

}

/* =========================================================
API
========================================================= */

async function api(url, options = {}) {

const response =
  await fetch(
    url,
    {
      cache: "no-store",
      credentials: "same-origin",
      ...options,

      headers: {
        Accept: "application/json",
        ...(options.headers || {})
      }
    }
  );


let data = null;


try {

  data =
    await response.json();

} catch {

  throw new Error(
    `استجابة غير صالحة من السيرفر (${response.status})`
  );
}


if (!response.ok) {

  throw new Error(
    data?.error ||
    data?.message ||
    `خطأ ${response.status}`
  );
}


if (
  data &&
  typeof data === "object" &&
  data.ok === false
) {

  throw new Error(
    data.error ||
    data.message ||
    "تعذر تنفيذ الطلب"
  );
}


return data;

}

/* =========================================================
STATUS
========================================================= */

function setStatus(text) {

const el =
  $("systemStatus");

if (el) {
  el.textContent = text;
}

}

/* =========================================================
NORMALIZE API
========================================================= */

function normalizeResults(data) {

if (!data) {
  return [];
}


if (Array.isArray(data)) {

  return data
    .filter(
      item =>
        item &&
        typeof item === "object"
    );
}


if (
  Array.isArray(data.results)
) {

  return data.results
    .filter(
      item =>
        item &&
        typeof item === "object"
    );
}


if (
  Array.isArray(data.signals)
) {

  return data.signals
    .filter(
      item =>
        item &&
        typeof item === "object"
    );
}


if (
  Array.isArray(data.data)
) {

  return data.data
    .filter(
      item =>
        item &&
        typeof item === "object"
    );
}


if (
  Array.isArray(data.items)
) {

  return data.items
    .filter(
      item =>
        item &&
        typeof item === "object"
    );
}


return [];

}

/* =========================================================
ONLY TRADES
========================================================= */

function onlyTrades(items) {

if (!Array.isArray(items)) {
  return [];
}

return items.filter(
  item =>
    item &&
    typeof item === "object" &&
    isSignal(item)
);

}

/* =========================================================
INTERVAL UI
========================================================= */

function setActiveInterval(containerSelector, interval) {

qsa(
  `${containerSelector} [data-interval]`
).forEach(
  button => {

    button.classList.toggle(
      "active",
      normalizeInterval(
        button.dataset.interval
      ) ===
      normalizeInterval(interval)
    );
  }
);

}

function getActiveInterval(containerSelector) {

const button =
  qs(
    `${containerSelector} [data-interval].active`
  );

return normalizeInterval(
  button?.dataset?.interval ||
  state.interval
);

}

/* =========================================================
NAVIGATION
========================================================= */

function openSection(id) {

qsa(".section").forEach(
  section => {

    section.classList.toggle(
      "active",
      section.id === id
    );
  }
);


qsa(
  ".nav-item[data-section]"
).forEach(
  button => {

    button.classList.toggle(
      "active",
      button.dataset.section === id
    );
  }
);


const title =
  $("pageTitle");


const titles = {

  dashboard: "الرئيسية",

  scanner: "ماسح الفرص",

  recent: "صفقات السبوت",

  futures: "صفقات الفيوتشر",

  saudi: "صفقات السوق السعودي",

  usmarket: "صفقات السوق الأمريكي",

  forex: "صفقات الفوركس",

  news: "الأخبار"
};


if (title) {

  title.textContent =
    titles[id] ||
    "مضارب أبو سعود";
}


localStorage.setItem(
  "mudarib_last_section",
  id
);


if (id === "dashboard") {
  loadCryptoDashboard();
}

if (id === "scanner") {
  loadScanner();
}

if (id === "recent") {
  renderRecent();
}

if (id === "futures") {
  loadFutures();
}

if (id === "saudi") {
  loadSaudi();
}

if (id === "usmarket") {
  loadUSMarket();
}

if (id === "forex") {
  loadForex();
}

if (id === "news") {
  loadNews();
}

}

function setupNavigation() {

qsa(
  ".nav-item[data-section]"
).forEach(
  button => {

    button.addEventListener(
      "click",
      () => {

        openSection(
          button.dataset.section
        );


        if (
          window.innerWidth <= 800
        ) {

          $("sidebar")?.classList.remove(
            "open"
          );
        }
      }
    );
  }
);


$("menuBtn")?.addEventListener(
  "click",
  () => {

    $("sidebar")?.classList.toggle(
      "open"
    );
  }
);

}

/* =========================================================
THEME
========================================================= */

function setupTheme() {

const saved =
  localStorage.getItem(
    "mudarib_theme"
  );


if (saved === "dark") {

  document.body.classList.add(
    "dark"
  );
}


updateThemeButton();


$("themeBtn")?.addEventListener(
  "click",
  () => {

    document.body.classList.toggle(
      "dark"
    );


    localStorage.setItem(
      "mudarib_theme",
      document.body.classList.contains(
        "dark"
      )
        ? "dark"
        : "light"
    );


    updateThemeButton();
  }
);

}

function updateThemeButton() {

const btn =
  $("themeBtn");

if (!btn) {
  return;
}


btn.textContent =
  document.body.classList.contains(
    "dark"
  )
    ? "☀️ الوضع النهاري"
    : "🌙 الوضع الليلي";

}

/* =========================================================
CARD
========================================================= */

function renderCard(item) {

const x =
  safeItem(item);


const symbol =
  escapeHTML(
    getSymbol(x)
  );


const signal =
  getSignal(x);


const cls =
  signalClass(signal);


const price =
  getPrice(x);


const entry =
  getEntry(x);


const tp1 =
  getTP1(x);


const sl =
  getSL(x);


const score =
  getScore(x);


const change =
  getChange(x);


const rsi =
  getRSI(x);


return `
  <div class="signal-card ${cls}">

    <div class="signal-card-header">

      <div class="signal-symbol">

        ${signalIcon(signal)}

        <strong>
          ${symbol}
        </strong>

      </div>

      <span class="signal-badge ${cls}">
        ${escapeHTML(signal)}
      </span>

    </div>


    <div class="signal-price">
      ${number(price)}
    </div>


    <div class="signal-grid">

      <div class="signal-item">
        <span>الدخول</span>
        <strong>
          ${number(entry)}
        </strong>
      </div>


      <div class="signal-item">
        <span>الهدف</span>
        <strong>
          ${number(tp1)}
        </strong>
      </div>


      <div class="signal-item">
        <span>وقف</span>
        <strong>
          ${number(sl)}
        </strong>
      </div>


      <div class="signal-item">
        <span>القوة</span>
        <strong>
          ${number(score, 1)}
        </strong>
      </div>


      <div class="signal-item">
        <span>RSI</span>
        <strong>
          ${
            rsi === null
              ? "—"
              : number(rsi, 1)
          }
        </strong>
      </div>


      <div class="signal-item">
        <span>التغير</span>
        <strong>
          ${percent(change)}
        </strong>
      </div>

    </div>


    <div class="signal-footer">

      <span>
        صفقة مباشرة
      </span>

      <span>
        ${timeText(
          x.updatedAt ??
          x.updated_at ??
          x.timestamp
        )}
      </span>

    </div>

  </div>
`;

}

function renderCards(
containerId,
items,
empty = "لا توجد صفقات حالياً."
) {

const box =
  $(containerId);


if (!box) {
  return;
}


const safeItems =
  Array.isArray(items)
    ? items.filter(
        item =>
          item &&
          typeof item === "object"
      )
    : [];


if (!safeItems.length) {

  box.innerHTML =
    `
      <div class="empty-state">
        ${escapeHTML(empty)}
      </div>
    `;

  return;
}


box.innerHTML =
  safeItems
    .map(renderCard)
    .join("");

}

/* =========================================================
GENERIC MARKET REQUEST
========================================================= */

function buildMarketURL(
market,
interval,
extra = ""
) {

const endpoint =
  MARKET_API[market];


if (!endpoint) {
  return null;
}


const params =
  new URLSearchParams();


params.set(
  "interval",
  normalizeInterval(interval)
);


if (extra) {

  const extraParams =
    new URLSearchParams(extra);


  extraParams.forEach(
    (value, key) => {

      params.set(
        key,
        value
      );
    }
  );
}


return `${endpoint}?${params.toString()}`;

}

async function fetchMarket(
market,
interval,
extra = ""
) {

const url =
  buildMarketURL(
    market,
    interval,
    extra
  );


if (!url) {

  throw new Error(
    "السوق غير مدعوم"
  );
}


console.log(
  "MARKET REQUEST:",
  market,
  normalizeInterval(interval),
  url
);


const data =
  await api(url);


return {
  data,
  results:
    normalizeResults(data)
};

}

/* =========================================================
SCANNER
========================================================= */

function getScannerMarket() {

return (
  $("scannerMarket")?.value ||
  state.scannerMarket ||
  "crypto"
);

}

async function loadScanner() {

if (state.loading) {
  return;
}


const market =
  getScannerMarket();


state.scannerMarket =
  market;


const interval =
  getActiveInterval(
    "#intervalChips"
  );


state.interval =
  interval;


state.loading = true;


const requestId =
  ++state.requestId;


const btn =
  $("scanBtn");


const status =
  $("scannerStatus");


if (btn) {

  btn.disabled = true;

  btn.textContent =
    "⏳ جاري جلب الصفقات";
}


if (status) {

  status.textContent =
    `⏳ جاري جلب صفقات ${MARKET_NAMES[market]} — ${interval}...`;
}


try {

  const result =
    await fetchMarket(
      market,
      interval,
      market === "futures"
        ? "limit=40"
        : ""
    );


  if (
    requestId !==
    state.requestId
  ) {
    return;
  }


  state.results =
    onlyTrades(
      result.results
    );


  state.signals =
    [...state.results];


  state.lastUpdated =
    Date.now();


  addRecent(
    state.results
  );


  renderScanner();


  if (status) {

    status.textContent =
      `🟢 ${MARKET_NAMES[market]} • ` +
      `${interval} • ` +
      `${state.results.length} صفقة مباشرة`;
  }


  setStatus(
    `● ${MARKET_NAMES[market]} — ${interval}`
  );

} catch (error) {

  console.error(
    "Scanner:",
    error
  );


  if (
    requestId !==
    state.requestId
  ) {
    return;
  }


  state.results = [];
  state.signals = [];


  renderScanner();


  if (status) {

    status.textContent =
      `❌ ${error.message}`;
  }


  setStatus(
    "● تعذر تحميل الصفقات"
  );

} finally {

  if (
    requestId ===
    state.requestId
  ) {

    state.loading = false;


    if (btn) {

      btn.disabled = false;

      btn.textContent =
        "🔄 تحديث";
    }
  }
}

}

function getFilteredScanner() {

let items =
  [...state.results];


const search =
  state.search
    .trim()
    .toLowerCase();


if (search) {

  items =
    items.filter(
      item =>
        String(
          getSymbol(item)
        )
          .toLowerCase()
          .includes(search) ||

        String(
          getName(item)
        )
          .toLowerCase()
          .includes(search)
    );
}


if (state.signalFilter) {

  items =
    items.filter(
      item =>
        getSignal(item) ===
        state.signalFilter
    );
}


items.sort(
  (a, b) => {

    let av = 0;
    let bv = 0;


    switch (
      state.sortField
    ) {

      case "score":

        av =
          getScore(a);

        bv =
          getScore(b);

        break;


      case "price":

        av =
          Number(
            getPrice(a)
          ) || 0;

        bv =
          Number(
            getPrice(b)
          ) || 0;

        break;


      case "volume":

        av =
          getVolume(a);

        bv =
          getVolume(b);

        break;


      case "symbol":

        return state.sortDesc

          ? String(
              getSymbol(b)
            ).localeCompare(
              String(
                getSymbol(a)
              )
            )

          : String(
              getSymbol(a)
            ).localeCompare(
              String(
                getSymbol(b)
              )
            );


      case "signal":

        return state.sortDesc

          ? String(
              getSignal(b)
            ).localeCompare(
              String(
                getSignal(a)
              )
            )

          : String(
              getSignal(a)
            ).localeCompare(
              String(
                getSignal(b)
              )
            );


      case "change":

      default:

        av =
          getChange(a);

        bv =
          getChange(b);

        break;
    }


    return state.sortDesc
      ? bv - av
      : av - bv;
  }
);


return items;

}

function renderScanner() {

const body =
  $("scannerBody");


if (!body) {
  return;
}


const items =
  getFilteredScanner();


if (!items.length) {

  body.innerHTML =
    `
      <tr>
        <td colspan="7">
          لا توجد صفقات مباشرة حالياً.
        </td>
      </tr>
    `;

  return;
}


body.innerHTML =
  items
    .map(
      item => {

        const x =
          safeItem(item);


        const signal =
          getSignal(x);


        const cls =
          signalClass(signal);


        return `
          <tr>

            <td>
              <strong>
                ${signalIcon(signal)}
                ${escapeHTML(
                  getSymbol(x)
                )}
              </strong>
            </td>


            <td>
              ${number(
                getPrice(x)
              )}
            </td>


            <td>
              <span class="${cls}">
                ${percent(
                  getChange(x)
                )}
              </span>
            </td>


            <td>
              <span
                class="signal-badge ${cls}"
              >
                ${escapeHTML(
                  signal
                )}
              </span>
            </td>


            <td>
              ${number(
                getScore(x),
                1
              )}
            </td>


            <td>
              ${volume(
                getVolume(x)
              )}
            </td>


            <td>
              صفقة مباشرة
            </td>

          </tr>
        `;
      }
    )
    .join("");

}

function setupScanner() {

const market =
  $("scannerMarket");


if (market) {

  market.value =
    state.scannerMarket;


  market.addEventListener(
    "change",
    () => {

      state.scannerMarket =
        market.value;


      state.signalFilter =
        null;


      state.search =
        "";


      if ($("scannerSearch")) {

        $("scannerSearch").value =
          "";
      }


      qsa(
        ".signal-chips [data-signal]"
      ).forEach(
        button => {

          button.classList.remove(
            "active"
          );
        }
      );


      loadScanner();
    }
  );
}


qsa(
  "#intervalChips [data-interval]"
).forEach(
  button => {

    button.addEventListener(
      "click",
      () => {

        const interval =
          normalizeInterval(
            button.dataset.interval
          );


        state.interval =
          interval;


        setActiveInterval(
          "#intervalChips",
          interval
        );


        loadScanner();
      }
    );
  }
);


qsa(
  ".signal-chips [data-signal]"
).forEach(
  button => {

    button.addEventListener(
      "click",
      () => {

        const signal =
          button.dataset.signal;


        if (
          state.signalFilter ===
          signal
        ) {

          state.signalFilter =
            null;


          button.classList.remove(
            "active"
          );

        } else {

          state.signalFilter =
            signal;


          qsa(
            ".signal-chips [data-signal]"
          ).forEach(
            b => {

              b.classList.toggle(
                "active",
                b === button
              );
            }
          );
        }


        renderScanner();
      }
    );
  }
);


$("scannerSearch")
  ?.addEventListener(
    "input",
    event => {

      state.search =
        event.target.value;


      renderScanner();
    }
  );


$("sortField")
  ?.addEventListener(
    "change",
    event => {

      state.sortField =
        event.target.value;


      renderScanner();
    }
  );


$("sortDir")
  ?.addEventListener(
    "click",
    () => {

      state.sortDesc =
        !state.sortDesc;


      $("sortDir").textContent =
        state.sortDesc
          ? "↓ تنازلي"
          : "↑ تصاعدي";


      renderScanner();
    }
  );


$("scanBtn")
  ?.addEventListener(
    "click",
    loadScanner
  );

}

/* =========================================================
DASHBOARD
========================================================= */

async function loadCryptoDashboard() {

try {

  const interval =
    normalizeInterval(
      state.interval
    );


  const result =
    await fetchMarket(
      "crypto",
      interval
    );


  const results =
    result.results;


  const signals =
    onlyTrades(results);


  state.results =
    results;


  state.signals =
    signals;


  updateDashboard(
    results
  );


  if (results.length) {

    const strongest =
      [...results]
        .sort(
          (a, b) =>
            getScore(b) -
            getScore(a)
        )[0];


    if (strongest) {

      updateDashboardDetails(
        strongest
      );
    }
  }


  setStatus(
    `● العملات الرقمية — ${interval} — OKX`
  );

} catch (error) {

  console.error(
    "Dashboard:",
    error
  );


  setStatus(
    `● تعذر تحديث الرئيسية — ${error.message}`
  );
}

}

function updateDashboard(results) {

const items =
  Array.isArray(results)
    ? results.filter(
        item =>
          item &&
          typeof item === "object"
      )
    : [];


const best =
  onlyTrades(items)
    .sort(
      (a, b) =>
        getScore(b) -
        getScore(a)
    )
    .slice(0, 6);


const first =
  best.length
    ? safeItem(best[0])
    : null;


if ($("dashSymbol")) {

  $("dashSymbol").textContent =
    first
      ? getSymbol(first)
      : "—";
}


if ($("dashPrice")) {

  $("dashPrice").textContent =
    first
      ? number(
          getPrice(first)
        )
      : "—";
}


if ($("dashChange")) {

  $("dashChange").textContent =
    first
      ? percent(
          getChange(first)
        )
      : "—";
}


if ($("dashSignal")) {

  $("dashSignal").textContent =
    first
      ? getSignal(first)
      : "—";
}

}

function updateDashboardDetails(item) {

const x =
  safeItem(item);


if (!Object.keys(x).length) {
  return;
}


const signal =
  getSignal(x);


if ($("bigSignal")) {

  $("bigSignal").textContent =
    `${signalIcon(signal)} ${signal}`;
}


if ($("scoreText")) {

  $("scoreText").textContent =
    `${number(
      getScore(x),
      1
    )}/100`;
}


if ($("scoreBar")) {

  $("scoreBar").style.width =
    `${getScore(x)}%`;
}


if ($("entry")) {

  $("entry").textContent =
    number(
      getEntry(x)
    );
}


if ($("tp1")) {

  $("tp1").textContent =
    number(
      getTP1(x)
    );
}


if ($("tp2")) {

  $("tp2").textContent =
    number(
      getTP2(x)
    );
}


if ($("tp3")) {

  $("tp3").textContent =
    number(
      getTP3(x)
    );
}


if ($("sl")) {

  $("sl").textContent =
    number(
      getSL(x)
    );
}


if ($("rsi")) {

  const rsi =
    getRSI(x);


  $("rsi").textContent =
    rsi === null
      ? "—"
      : number(
          rsi,
          1
        );
}


if ($("ema20")) {

  $("ema20").textContent =
    number(
      x.ema20
    );
}


if ($("ema50")) {

  $("ema50").textContent =
    number(
      x.ema50
    );
}


if ($("ema200")) {

  $("ema200").textContent =
    number(
      x.ema200
    );
}


if ($("analysisMeta")) {

  $("analysisMeta").textContent =
    `${state.interval} • صفقة مباشرة`;
}


const reasons =
  $("reasons");


if (reasons) {

  const list =
    Array.isArray(
      x.reasons
    )
      ? x.reasons
      : [];


  reasons.innerHTML =
    list.length

      ? list
          .map(
            reason =>
              `<li>${escapeHTML(
                reason
              )}</li>`
          )
          .join("")

      : "";
}

}

/* =========================================================
DASHBOARD INTERVALS
========================================================= */

function setupDashboardIntervals() {

qsa(
  "#dashIntervals [data-interval]"
).forEach(
  button => {

    button.addEventListener(
      "click",
      () => {

        const interval =
          normalizeInterval(
            button.dataset.interval
          );


        state.interval =
          interval;


        setActiveInterval(
          "#dashIntervals",
          interval
        );


        loadCryptoDashboard();
      }
    );
  }
);

}

/* =========================================================
SAUDI
========================================================= */

async function loadSaudi() {

const box =
  $("saudiList");


if (!box) {
  return;
}


const interval =
  getActiveInterval(
    "#saudiIntervals"
  );


box.innerHTML =
  `
    <div class="empty-state">
      ⏳ جاري جلب صفقات السوق السعودي — ${escapeHTML(interval)}...
    </div>
  `;


try {

  const result =
    await fetchMarket(
      "saudi",
      interval
    );


  let results =
    onlyTrades(
      result.results
    );


  results =
    applySearch(
      results,
      "saudiSearch"
    );


  renderCards(
    "saudiList",
    results,
    "لا توجد صفقات سعودية حالياً."
  );


  addRecent(results);


  setStatus(
    `● السعودي — ${interval} — ${results.length} صفقة`
  );

} catch (error) {

  console.error(
    "Saudi:",
    error
  );


  box.innerHTML =
    `
      <div class="empty-state">
        ❌ ${escapeHTML(
          error.message
        )}
      </div>
    `;


  setStatus(
    "● تعذر تحميل صفقات السعودي"
  );
}

}

/* =========================================================
US MARKET
========================================================= */

async function loadUSMarket() {

const box =
  $("usMarketList");


if (!box) {
  return;
}


const interval =
  getActiveInterval(
    "#usIntervals"
  );


box.innerHTML =
  `
    <div class="empty-state">
      ⏳ جاري جلب صفقات السوق الأمريكي — ${escapeHTML(interval)}...
    </div>
  `;


try {

  const result =
    await fetchMarket(
      "usmarket",
      interval
    );


  let results =
    onlyTrades(
      result.results
    );


  results =
    applySearch(
      results,
      "usSearch"
    );


  renderCards(
    "usMarketList",
    results,
    "لا توجد صفقات أمريكية حالياً."
  );


  addRecent(results);


  setStatus(
    `● الأمريكي — ${interval} — ${results.length} صفقة`
  );

} catch (error) {

  console.error(
    "US:",
    error
  );


  box.innerHTML =
    `
      <div class="empty-state">
        ❌ ${escapeHTML(
          error.message
        )}
      </div>
    `;


  setStatus(
    "● تعذر تحميل صفقات الأمريكي"
  );
}

}

/* =========================================================
FOREX
========================================================= */

async function loadForex() {

const box =
  $("forexList");


if (!box) {
  return;
}


const interval =
  getActiveInterval(
    "#forexIntervals"
  );


box.innerHTML =
  `
    <div class="empty-state">
      ⏳ جاري جلب صفقات الفوركس — ${escapeHTML(interval)}...
    </div>
  `;


try {

  const result =
    await fetchMarket(
      "forex",
      interval
    );


  let results =
    onlyTrades(
      result.results
    );


  results =
    applySearch(
      results,
      "forexSearch"
    );


  renderCards(
    "forexList",
    results,
    "لا توجد صفقات فوركس حالياً."
  );


  addRecent(results);


  setStatus(
    `● الفوركس — ${interval} — ${results.length} صفقة`
  );

} catch (error) {

  console.error(
    "Forex:",
    error
  );


  box.innerHTML =
    `
      <div class="empty-state">
        ❌ ${escapeHTML(
          error.message
        )}
      </div>
    `;


  setStatus(
    "● تعذر تحميل صفقات الفوركس"
  );
}

}

function applySearch(
results,
inputId
) {

const value =
  $(inputId)?.value
    ?.trim()
    ?.toLowerCase();


if (!value) {
  return results;
}


return results.filter(
  item => {

    const x =
      safeItem(item);


    return (
      String(
        getSymbol(x)
      )
        .toLowerCase()
        .includes(value) ||

      String(
        getName(x)
      )
        .toLowerCase()
        .includes(value)
    );
  }
);

}

/* =========================================================
MARKET INTERVALS
========================================================= */

function setupMarketIntervals() {

$("refreshSaudi")
  ?.addEventListener(
    "click",
    loadSaudi
  );


$("refreshUSMarket")
  ?.addEventListener(
    "click",
    loadUSMarket
  );


$("refreshForex")
  ?.addEventListener(
    "click",
    loadForex
  );


$("saudiSearch")
  ?.addEventListener(
    "input",
    () => {

      loadSaudi();
    }
  );


$("usSearch")
  ?.addEventListener(
    "input",
    () => {

      loadUSMarket();
    }
  );


$("forexSearch")
  ?.addEventListener(
    "input",
    () => {

      loadForex();
    }
  );


qsa(
  "#saudiIntervals [data-interval]"
).forEach(
  button => {

    button.addEventListener(
      "click",
      () => {

        const interval =
          normalizeInterval(
            button.dataset.interval
          );


        setActiveInterval(
          "#saudiIntervals",
          interval
        );


        loadSaudi();
      }
    );
  }
);


qsa(
  "#usIntervals [data-interval]"
).forEach(
  button => {

    button.addEventListener(
      "click",
      () => {

        const interval =
          normalizeInterval(
            button.dataset.interval
          );


        setActiveInterval(
          "#usIntervals",
          interval
        );


        loadUSMarket();
      }
    );
  }
);


qsa(
  "#forexIntervals [data-interval]"
).forEach(
  button => {

    button.addEventListener(
      "click",
      () => {

        const interval =
          normalizeInterval(
            button.dataset.interval
          );


        setActiveInterval(
          "#forexIntervals",
          interval
        );


        loadForex();
      }
    );
  }
);

}

/* =========================================================
FUTURES
========================================================= */

async function loadFutures() {

const box =
  $("futuresList");


if (!box) {
  return;
}


const interval =
  state.interval ||
  "15m";


box.innerHTML =
  `
    <div class="empty-state">
      ⏳ جاري جلب صفقات الفيوتشر — ${escapeHTML(interval)}...
    </div>
  `;


try {

  const result =
    await fetchMarket(
      "futures",
      interval,
      "limit=40"
    );


  const results =
    onlyTrades(
      result.results
    );


  renderCards(
    "futuresList",
    results,
    "لا توجد صفقات فيوتشر حالياً."
  );


  addRecent(results);


  setStatus(
    `● الفيوتشر — ${interval} — ${results.length} صفقة`
  );

} catch (error) {

  console.error(
    "Futures:",
    error
  );


  box.innerHTML =
    `
      <div class="empty-state">
        ❌ ${escapeHTML(
          error.message
        )}
      </div>
    `;


  setStatus(
    "● تعذر تحميل صفقات الفيوتشر"
  );
}

}

$("refreshFutures")
?.addEventListener(
"click",
loadFutures
);

/* =========================================================
RECENT
========================================================= */

function saveRecent() {

try {

  localStorage.setItem(
    "mudarib_recent",
    JSON.stringify(
      state.recent
    )
  );

} catch (error) {

  console.warn(
    "Recent storage:",
    error
  );
}

}

function addRecent(items) {

const trades =
  onlyTrades(items);


if (!trades.length) {
  return;
}


const combined = [
  ...trades,
  ...state.recent
];


const seen =
  new Set();


state.recent =
  combined
    .filter(
      item => {

        if (
          !item ||
          typeof item !== "object"
        ) {
          return false;
        }


        const key =
          `${getSymbol(item)}|${getSignal(item)}`;


        if (
          seen.has(key)
        ) {
          return false;
        }


        seen.add(key);

        return true;
      }
    )
    .slice(0, 50);


saveRecent();

}

function renderRecent() {

const box =
  $("recentList");


if (!box) {
  return;
}


const trades =
  state.recent
    .filter(
      item =>
        item &&
        typeof item === "object" &&
        isSignal(item)
    );


if (!trades.length) {

  box.innerHTML =
    `
      <div class="empty-state">
        لا توجد صفقات محفوظة حالياً.
      </div>
    `;

  return;
}


box.innerHTML =
  trades
    .map(renderCard)
    .join("");

}

$("clearRecent")
?.addEventListener(
"click",
() => {

    state.recent = [];

    localStorage.removeItem(
      "mudarib_recent"
    );

    renderRecent();
  }
);

/* =========================================================
NEWS
========================================================= */

async function loadNews() {

const box =
  $("newsList");


if (!box) {
  return;
}


box.innerHTML =
  `
    <div class="empty-state">
      ⏳ جاري تحميل الأخبار...
    </div>
  `;


try {

  const data =
    await api(
      "/api/news"
    );


  const news =
    Array.isArray(
      data?.news
    )
      ? data.news

      : Array.isArray(
          data
        )
        ? data

        : [];


  if (!news.length) {

    box.innerHTML =
      `
        <div class="empty-state">
          لا توجد أخبار حالياً.
        </div>
      `;

    return;
  }


  box.innerHTML =
    news
      .filter(
        item =>
          item &&
          typeof item === "object"
      )
      .map(
        item => {

          const title =
            item.title ??
            item.name ??
            "خبر";


          const source =
            item.source ??
            "";


          const link =
            item.url ??
            item.link ??
            "#";


          return `
            <article class="news-card">

              <h3>
                ${escapeHTML(title)}
              </h3>

              <small>
                ${escapeHTML(source)}
              </small>

              ${
                link !== "#"

                  ? `
                    <a
                      href="${escapeHTML(link)}"
                      target="_blank"
                      rel="noopener"
                    >
                      قراءة الخبر
                    </a>
                  `

                  : ""
              }

            </article>
          `;
        }
      )
      .join("");

} catch (error) {

  console.error(
    "News:",
    error
  );


  box.innerHTML =
    `
      <div class="empty-state">
        ❌ ${escapeHTML(
          error.message
        )}
      </div>
    `;
}

}

$("newsBtn")
?.addEventListener(
"click",
loadNews
);

/* =========================================================
HEALTH
========================================================= */

async function checkHealth() {

try {

  const data =
    await api(
      "/health"
    );


  setStatus(
    data?.ok === false
      ? "● السيرفر متصل"
      : "● السيرفر متصل"
  );

} catch {

  setStatus(
    "● تعذر الاتصال بالسيرفر"
  );
}

}

/* =========================================================
AUTO REFRESH
========================================================= */

function setupAutoRefresh() {

setInterval(
  () => {

    const active =
      qs(
        ".section.active"
      )?.id;


    if (
      active ===
      "dashboard"
    ) {

      loadCryptoDashboard();

    } else if (
      active ===
      "scanner"
    ) {

      loadScanner();

    } else if (
      active ===
      "saudi"
    ) {

      loadSaudi();

    } else if (
      active ===
      "usmarket"
    ) {

      loadUSMarket();

    } else if (
      active ===
      "forex"
    ) {

      loadForex();

    } else if (
      active ===
      "futures"
    ) {

      loadFutures();

    } else if (
      active ===
      "news"
    ) {

      loadNews();
    }

  },
  60000
);


setInterval(
  checkHealth,
  60000
);

}

/* =========================================================
INITIAL INTERVALS
========================================================= */

function setupInitialIntervals() {

setActiveInterval(
  "#dashIntervals",
  state.interval
);


setActiveInterval(
  "#intervalChips",
  state.interval
);


setActiveInterval(
  "#saudiIntervals",
  "1d"
);


setActiveInterval(
  "#usIntervals",
  "1d"
);


setActiveInterval(
  "#forexIntervals",
  "1h"
);

}

/* =========================================================
INIT
========================================================= */

async function init() {

console.log(
  "مضارب أبو سعود — SAFE DIRECT TRADES MODE"
);


setupNavigation();

setupTheme();

setupScanner();

setupDashboardIntervals();

setupMarketIntervals();


setupInitialIntervals();


await checkHealth();


await loadCryptoDashboard();


renderRecent();


setupAutoRefresh();


const active =
  localStorage.getItem(
    "mudarib_last_section"
  );


if (
  active &&
  [
    "dashboard",
    "scanner",
    "recent",
    "futures",
    "saudi",
    "usmarket",
    "forex",
    "news"
  ].includes(active)
) {

  openSection(active);
}

}

/* =========================================================
GLOBAL
========================================================= */

window.loadScanner =
loadScanner;

window.loadSaudi =
loadSaudi;

window.loadUSMarket =
loadUSMarket;

window.loadForex =
loadForex;

window.loadFutures =
loadFutures;

window.loadNews =
loadNews;

window.loadCryptoDashboard =
loadCryptoDashboard;

/* =========================================================
START
========================================================= */

if (
document.readyState ===
"loading"
) {

document.addEventListener(
  "DOMContentLoaded",
  init
);

} else {

init();

}

})();
