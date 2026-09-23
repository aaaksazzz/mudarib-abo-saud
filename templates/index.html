"use strict";

/* =========================================================
   مضارب أبو سعود
   app.js
   متوافق مع server.py + index.html
========================================================= */

const $ = (id) => document.getElementById(id);

const state = {
  market: "crypto",
  interval: "15m",
  symbol: "BTCUSDT",

  results: [],
  recent: [],

  signalFilter: "",
  search: "",

  sortField: "change",
  sortDesc: true,

  busy: false,
  chart: null,

  futuresInterval: "15m",
  saudiInterval: "1d",
  usInterval: "1d",
  forexInterval: "1h",

  currentDashboard: null
};


/* =========================================================
   API
========================================================= */

const MARKET_API = {
  crypto: "/api/okx/scan",
  saudi: "/api/saudi/scan",
  usmarket: "/api/usmarket/signals",
  forex: "/api/forex/signals",
  futures: "/api/futures/scan"
};


/* =========================================================
   HELPERS
========================================================= */

function safeNumber(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}


function fmtNumber(value, digits = 4) {
  const n = Number(value);

  if (!Number.isFinite(n)) {
    return "—";
  }

  return n.toLocaleString("en-US", {
    maximumFractionDigits: digits
  });
}


function fmtPrice(value) {
  const n = Number(value);

  if (!Number.isFinite(n)) {
    return "—";
  }

  if (Math.abs(n) >= 1000) {
    return n.toLocaleString("en-US", {
      maximumFractionDigits: 2
    });
  }

  if (Math.abs(n) >= 1) {
    return n.toLocaleString("en-US", {
      maximumFractionDigits: 6
    });
  }

  return n.toLocaleString("en-US", {
    maximumFractionDigits: 8
  });
}


function fmtPercent(value) {
  const n = Number(value);

  if (!Number.isFinite(n)) {
    return "—";
  }

  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}


function escapeHTML(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}


function getPrice(item) {
  if (!item) return null;

  return (
    item.price ??
    item.close ??
    item.last ??
    item.entry ??
    item.c ??
    null
  );
}


function getChange(item) {
  if (!item) return 0;

  return safeNumber(
    item.change ??
    item.change24h ??
    item.percent ??
    item.pct ??
    item.change_percent ??
    0
  );
}


function getScore(item) {
  if (!item) return 0;

  return safeNumber(
    item.score ??
    item.score10 ??
    item.strength ??
    0
  );
}


function getSignal(item) {
  if (!item) return "حيادي";

  return (
    item.signal ??
    item.direction ??
    item.status ??
    "حيادي"
  );
}


function getSymbol(item) {
  if (!item) return "—";

  return (
    item.symbol ??
    item.instId ??
    item.ticker ??
    item.code ??
    "—"
  );
}


function getVolume(item) {
  if (!item) return 0;

  return safeNumber(
    item.volume ??
    item.quoteVolume ??
    item.vol ??
    item.amount ??
    0
  );
}


function signalClass(signal) {

  signal = String(signal || "");

  if (signal.includes("شراء قوي")) {
    return "strong-buy";
  }

  if (signal.includes("شراء")) {
    return "buy";
  }

  if (signal.includes("بيع قوي")) {
    return "strong-sell";
  }

  if (signal.includes("بيع")) {
    return "sell";
  }

  return "neutral";
}


function signalEmoji(signal) {

  const s = String(signal || "");

  if (s.includes("شراء قوي")) return "🟢";
  if (s.includes("شراء")) return "🟩";
  if (s.includes("بيع قوي")) return "🔴";
  if (s.includes("بيع")) return "🟥";

  return "⚪";
}


/* =========================================================
   FETCH
========================================================= */

async function apiFetch(url, options = {}) {

  const response = await fetch(url, {
    cache: "no-store",
    ...options
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  const data = await response.json();

  if (data === null || data === undefined) {
    throw new Error("استجابة فارغة");
  }

  return data;
}


/* =========================================================
   NORMALIZE
========================================================= */

function normalizeResults(data) {

  if (!data) {
    return [];
  }

  let list = [];

  if (Array.isArray(data)) {
    list = data;
  } else if (Array.isArray(data.results)) {
    list = data.results;
  } else if (Array.isArray(data.data)) {
    list = data.data;
  } else if (Array.isArray(data.items)) {
    list = data.items;
  } else if (Array.isArray(data.symbols)) {
    list = data.symbols;
  } else if (Array.isArray(data.signals)) {
    list = data.signals;
  }

  return list.filter(Boolean);
}


/* =========================================================
   STATUS
========================================================= */

function setStatus(text, type = "") {

  const el = $("systemStatus");

  if (!el) return;

  el.textContent = text;

  el.classList.remove(
    "online",
    "offline",
    "loading",
    "error"
  );

  if (type) {
    el.classList.add(type);
  }
}


function setScannerStatus(text) {

  const el = $("scannerStatus");

  if (el) {
    el.textContent = text;
  }
}


/* =========================================================
   NAVIGATION
========================================================= */

function openSection(section) {

  document
    .querySelectorAll(".section")
    .forEach((el) => {
      el.classList.remove("active");
    });

  const target = $(section);

  if (target) {
    target.classList.add("active");
  }

  document
    .querySelectorAll(".nav-item")
    .forEach((el) => {
      el.classList.toggle(
        "active",
        el.dataset.section === section
      );
    });

  const titles = {
    dashboard: "الرئيسية",
    scanner: "ماسح الفرص",
    recent: "صفقات السبوت",
    futures: "صفقات الفيوتشر",
    saudi: "السوق السعودي",
    usmarket: "السوق الأمريكي",
    forex: "الفوركس",
    news: "الأخبار"
  };

  if ($("pageTitle")) {
    $("pageTitle").textContent =
      titles[section] || "مضارب أبو سعود";
  }

  window.scrollTo({
    top: 0,
    behavior: "smooth"
  });

  if (section === "dashboard") {
    loadDashboard();
  }

  if (section === "scanner") {
    if (!state.results.length) {
      fetchScanner();
    }
  }

  if (section === "recent") {
    renderRecent();
  }

  if (section === "futures") {
    fetchFutures();
  }

  if (section === "saudi") {
    fetchSaudi();
  }

  if (section === "usmarket") {
    fetchUSMarket();
  }

  if (section === "forex") {
    fetchForex();
  }

  if (section === "news") {
    fetchNews();
  }
}


/* =========================================================
   MENU
========================================================= */

function setupNavigation() {

  document
    .querySelectorAll(".nav-item")
    .forEach((button) => {

      button.addEventListener("click", () => {

        const section = button.dataset.section;

        if (!section) return;

        openSection(section);

        const sidebar = $("sidebar");

        if (sidebar) {
          sidebar.classList.remove("open");
        }
      });

    });


  const menuBtn = $("menuBtn");

  if (menuBtn) {

    menuBtn.addEventListener("click", () => {

      const sidebar = $("sidebar");

      if (sidebar) {
        sidebar.classList.toggle("open");
      }

    });

  }
}


/* =========================================================
   THEME
========================================================= */

function setupTheme() {

  const btn = $("themeBtn");

  if (!btn) return;

  const saved =
    localStorage.getItem("mudarib_theme");

  if (saved === "light") {
    document.body.classList.add("light");
    btn.textContent = "☀️ الوضع النهاري";
  }

  btn.addEventListener("click", () => {

    document.body.classList.toggle("light");

    const light =
      document.body.classList.contains("light");

    localStorage.setItem(
      "mudarib_theme",
      light ? "light" : "dark"
    );

    btn.textContent =
      light
        ? "☀️ الوضع النهاري"
        : "🌙 الوضع الليلي";
  });
}


/* =========================================================
   INTERVAL CHIPS
========================================================= */

function setupIntervalButtons() {

  const groups = [
    ["dashIntervals", (v) => {
      state.interval = v;
      loadDashboard();
    }],

    ["intervalChips", (v) => {
      state.interval = v;
      fetchScanner();
    }],

    ["futuresIntervals", (v) => {
      state.futuresInterval = v;
      fetchFutures();
    }],

    ["saudiIntervals", (v) => {
      state.saudiInterval = v;
      fetchSaudi();
    }],

    ["usIntervals", (v) => {
      state.usInterval = v;
      fetchUSMarket();
    }],

    ["forexIntervals", (v) => {
      state.forexInterval = v;
      fetchForex();
    }]
  ];


  groups.forEach(([id, callback]) => {

    const container = $(id);

    if (!container) return;

    container
      .querySelectorAll("[data-interval]")
      .forEach((button) => {

        button.addEventListener("click", () => {

          container
            .querySelectorAll("[data-interval]")
            .forEach((b) => {
              b.classList.remove("active");
            });

          button.classList.add("active");

          const value =
            button.dataset.interval;

          callback(value);
        });

      });

  });
}


/* =========================================================
   DASHBOARD
========================================================= */

async function loadDashboard(symbol = state.symbol) {

  const cleanSymbol =
    symbol || "BTCUSDT";

  state.symbol = cleanSymbol;

  setStatus("جاري التحليل...", "loading");

  try {

    const url =
      `/api/okx/analysis?symbol=${encodeURIComponent(cleanSymbol)}&interval=${encodeURIComponent(state.interval)}`;

    const data = await apiFetch(url);

    state.currentDashboard = data;

    renderDashboard(data);

    setStatus("متصل", "online");

  } catch (error) {

    console.error("Dashboard:", error);

    setStatus("تعذر الاتصال", "error");

    showDashboardError();

  }
}


function renderDashboard(data) {

  if (!data) {
    showDashboardError();
    return;
  }

  const symbol =
    data.symbol ??
    data.instId ??
    state.symbol;

  const price =
    getPrice(data);

  const change =
    getChange(data);

  const signal =
    getSignal(data);

  const score =
    safeNumber(data.score, 0);


  if ($("dashSymbol")) {
    $("dashSymbol").textContent =
      symbol;
  }

  if ($("dashPrice")) {
    $("dashPrice").textContent =
      fmtPrice(price);
  }

  if ($("dashChange")) {
    $("dashChange").textContent =
      fmtPercent(change);

    $("dashChange").className =
      change > 0
        ? "positive"
        : change < 0
          ? "negative"
          : "";
  }

  if ($("dashSignal")) {
    $("dashSignal").textContent =
      `${signalEmoji(signal)} ${signal}`;
  }

  if ($("bigSignal")) {

    $("bigSignal").textContent =
      `${signalEmoji(signal)} ${signal}`;

    $("bigSignal").className =
      `signal-big ${signalClass(signal)}`;
  }


  const score10 =
    data.score10 !== undefined
      ? safeNumber(data.score10)
      : Math.max(
          0,
          Math.min(10, score / 10)
        );


  if ($("scoreText")) {
    $("scoreText").textContent =
      `${score10.toFixed(1)} / 10`;
  }


  if ($("scoreBar")) {

    const percent =
      Math.max(
        0,
        Math.min(
          100,
          score10 * 10
        )
      );

    $("scoreBar").style.width =
      `${percent}%`;
  }


  const entry =
    data.entry ??
    data.price ??
    price;

  const tp1 =
    data.tp1 ??
    data.target ??
    data.tp ??
    null;

  const tp2 =
    data.tp2 ??
    null;

  const tp3 =
    data.tp3 ??
    null;

  const sl =
    data.sl ??
    data.stop_loss ??
    data.stop ??
    null;


  if ($("entry")) {
    $("entry").textContent =
      fmtPrice(entry);
  }

  if ($("tp1")) {
    $("tp1").textContent =
      fmtPrice(tp1);
  }

  if ($("tp2")) {
    $("tp2").textContent =
      fmtPrice(tp2);
  }

  if ($("tp3")) {
    $("tp3").textContent =
      fmtPrice(tp3);
  }

  if ($("sl")) {
    $("sl").textContent =
      fmtPrice(sl);
  }


  const rsi =
    data.rsi ??
    data.indicators?.rsi;

  const ema20 =
    data.ema20 ??
    data.indicators?.ema20;

  const ema50 =
    data.ema50 ??
    data.indicators?.ema50;

  const ema200 =
    data.ema200 ??
    data.indicators?.ema200;


  if ($("rsi")) {
    $("rsi").textContent =
      fmtNumber(rsi, 2);
  }

  if ($("ema20")) {
    $("ema20").textContent =
      fmtPrice(ema20);
  }

  if ($("ema50")) {
    $("ema50").textContent =
      fmtPrice(ema50);
  }

  if ($("ema200")) {
    $("ema200").textContent =
      fmtPrice(ema200);
  }


  renderReasons(
    data.reasons ??
    data.reason ??
    data.analysis ??
    []
  );


  if ($("analysisMeta")) {

    const source =
      data.source ??
      "OKX";

    $("analysisMeta").textContent =
      `${source} — ${state.interval}`;
  }


  const candles =
    data.candles ??
    data.klines ??
    data.data ??
    [];

  renderChart(candles);
}


function showDashboardError() {

  if ($("dashPrice")) {
    $("dashPrice").textContent = "—";
  }

  if ($("dashSignal")) {
    $("dashSignal").textContent = "⚪ غير متاح";
  }

  if ($("bigSignal")) {
    $("bigSignal").textContent =
      "⚪ البيانات غير متاحة";
  }
}


/* =========================================================
   REASONS
========================================================= */

function renderReasons(reasons) {

  const el = $("reasons");

  if (!el) return;

  el.innerHTML = "";

  if (!reasons) {
    return;
  }

  if (!Array.isArray(reasons)) {
    reasons = [reasons];
  }

  reasons
    .filter(Boolean)
    .slice(0, 10)
    .forEach((reason) => {

      const li =
        document.createElement("li");

      if (typeof reason === "object") {

        li.textContent =
          reason.text ??
          reason.reason ??
          JSON.stringify(reason);

      } else {

        li.textContent =
          String(reason);
      }

      el.appendChild(li);
    });
}


/* =========================================================
   CHART
========================================================= */

function renderChart(candles) {

  const canvas = $("priceChart");

  if (!canvas) return;

  if (!Array.isArray(candles)) {
    return;
  }

  if (!candles.length) {
    return;
  }


  const parsed = candles
    .map((c) => {

      if (Array.isArray(c)) {

        return {
          time: c[0],
          close: safeNumber(c[4])
        };

      }

      return {
        time:
          c.time ??
          c.timestamp ??
          c.ts ??
          c.t ??
          Date.now(),

        close:
          safeNumber(
            c.close ??
            c.c ??
            c.price
          )
      };

    })
    .filter(
      (x) =>
        Number.isFinite(x.close)
    )
    .slice(-150);


  if (!parsed.length) {
    return;
  }


  const labels =
    parsed.map((x) => {

      const date =
        new Date(
          Number(x.time)
        );

      if (
        !Number.isNaN(
          date.getTime()
        )
      ) {

        return date.toLocaleTimeString(
          "ar-SA",
          {
            hour: "2-digit",
            minute: "2-digit"
          }
        );
      }

      return "";
    });


  const values =
    parsed.map(
      (x) => x.close
    );


  if (state.chart) {

    try {
      state.chart.destroy();
    } catch (_) {}

    state.chart = null;
  }


  if (
    typeof Chart === "undefined"
  ) {
    return;
  }


  state.chart =
    new Chart(canvas, {

      type: "line",

      data: {

        labels,

        datasets: [

          {
            label: state.symbol,

            data: values,

            borderWidth: 2,

            pointRadius: 0,

            tension: 0.25,

            fill: false
          }

        ]
      },


      options: {

        responsive: true,

        maintainAspectRatio: false,

        interaction: {
          intersect: false,
          mode: "index"
        },

        plugins: {

          legend: {
            display: false
          }

        },

        scales: {

          x: {
            display: true,
            ticks: {
              maxTicksLimit: 8
            }
          },

          y: {
            display: true
          }

        }
      }

    });
}


/* =========================================================
   SCANNER
========================================================= */

async function fetchScanner() {

  if (state.busy) {
    return;
  }

  state.busy = true;

  setScannerStatus(
    "جاري فحص السوق..."
  );

  const body = $("scannerBody");

  if (body) {
    body.innerHTML = `
      <tr>
        <td colspan="7">
          جاري الفحص...
        </td>
      </tr>
    `;
  }


  try {

    const api =
      MARKET_API[state.market] ||
      MARKET_API.crypto;

    let url =
      `${api}?interval=${encodeURIComponent(state.interval)}`;

    if (
      state.market === "crypto" ||
      state.market === "futures"
    ) {

      url += "&limit=40";
    }


    const data =
      await apiFetch(url);

    state.results =
      normalizeResults(data);


    setScannerStatus(
      `تم العثور على ${state.results.length} فرصة`
    );

    renderScanner();

  } catch (error) {

    console.error("Scanner:", error);

    setScannerStatus(
      "تعذر تحميل بيانات السوق"
    );

    if (body) {

      body.innerHTML = `
        <tr>
          <td colspan="7">
            ⚠️ تعذر تحميل البيانات
          </td>
        </tr>
      `;
    }

  } finally {

    state.busy = false;
  }
}


/* =========================================================
   SCANNER RENDER
========================================================= */

function renderScanner() {

  const body =
    $("scannerBody");

  if (!body) return;

  let list =
    [...state.results];


  const search =
    String(
      state.search || ""
    ).trim().toLowerCase();


  if (search) {

    list =
      list.filter((item) => {

        const symbol =
          getSymbol(item)
            .toLowerCase();

        return symbol.includes(search);
      });
  }


  if (state.signalFilter) {

    list =
      list.filter((item) => {

        const signal =
          getSignal(item);

        return signal ===
          state.signalFilter;
      });
  }


  list.sort((a, b) => {

    let av;
    let bv;


    switch (state.sortField) {

      case "price":
        av = safeNumber(
          getPrice(a)
        );
        bv = safeNumber(
          getPrice(b)
        );
        break;


      case "score":
        av = getScore(a);
        bv = getScore(b);
        break;


      case "volume":
        av = getVolume(a);
        bv = getVolume(b);
        break;


      case "symbol":
        av = getSymbol(a);
        bv = getSymbol(b);

        return state.sortDesc
          ? String(bv).localeCompare(
              String(av)
            )
          : String(av).localeCompare(
              String(bv)
            );


      case "signal":
        av = getSignal(a);
        bv = getSignal(b);

        return state.sortDesc
          ? String(bv).localeCompare(
              String(av)
            )
          : String(av).localeCompare(
              String(bv)
            );


      case "change":

      default:
        av = getChange(a);
        bv = getChange(b);
        break;
    }


    return state.sortDesc
      ? bv - av
      : av - bv;
  });


  if (!list.length) {

    body.innerHTML = `
      <tr>
        <td colspan="7">
          لا توجد نتائج
        </td>
      </tr>
    `;

    return;
  }


  body.innerHTML =
    list.map((item) => {

      const symbol =
        getSymbol(item);

      const price =
        getPrice(item);

      const change =
        getChange(item);

      const signal =
        getSignal(item);

      const score =
        getScore(item);

      const volume =
        getVolume(item);


      return `
        <tr
          class="scanner-row"
          data-symbol="${escapeHTML(symbol)}"
        >

          <td>
            <button
              class="symbol-btn"
              data-symbol="${escapeHTML(symbol)}"
            >
              ${escapeHTML(symbol)}
            </button>
          </td>

          <td>
            ${fmtPrice(price)}
          </td>

          <td class="${change >= 0 ? "positive" : "negative"}">
            ${fmtPercent(change)}
          </td>

          <td>
            <span class="signal ${signalClass(signal)}">
              ${signalEmoji(signal)}
              ${escapeHTML(signal)}
            </span>
          </td>

          <td>
            ${fmtScore(score)}
          </td>

          <td>
            ${fmtVolume(volume)}
          </td>

          <td>
            ${escapeHTML(state.interval)}
          </td>

        </tr>
      `;

    }).join("");


  body
    .querySelectorAll(".symbol-btn")
    .forEach((button) => {

      button.addEventListener(
        "click",
        () => {

          const symbol =
            button.dataset.symbol;

          if (!symbol) return;

          state.symbol =
            symbol;

          openSection("dashboard");

          loadDashboard(symbol);

        }
      );

    });
}


function fmtScore(score) {

  const n =
    safeNumber(score);

  if (n <= 10) {
    return `${n.toFixed(1)}/10`;
  }

  return `${n.toFixed(0)}`;
}


function fmtVolume(value) {

  const n =
    safeNumber(value);

  if (!n) {
    return "—";
  }

  if (n >= 1e9) {
    return `${(n / 1e9).toFixed(2)}B`;
  }

  if (n >= 1e6) {
    return `${(n / 1e6).toFixed(2)}M`;
  }

  if (n >= 1e3) {
    return `${(n / 1e3).toFixed(2)}K`;
  }

  return fmtNumber(n, 2);
}


/* =========================================================
   SCANNER CONTROLS
========================================================= */

function setupScanner() {

  const market =
    $("scannerMarket");

  if (market) {

    market.value =
      state.market;

    market.addEventListener(
      "change",
      () => {

        state.market =
          market.value ||
          "crypto";

        state.results = [];

        fetchScanner();
      }
    );
  }


  const scanBtn =
    $("scanBtn");

  if (scanBtn) {

    scanBtn.addEventListener(
      "click",
      fetchScanner
    );
  }


  const search =
    $("scannerSearch");

  if (search) {

    search.addEventListener(
      "input",
      () => {

        state.search =
          search.value || "";

        renderScanner();
      }
    );
  }


  document
    .querySelectorAll(
      ".signal-chips [data-signal]"
    )
    .forEach((button) => {

      button.addEventListener(
        "click",
        () => {

          const active =
            button.classList.contains(
              "active"
            );


          document
            .querySelectorAll(
              ".signal-chips [data-signal]"
            )
            .forEach((b) => {
              b.classList.remove(
                "active"
              );
            });


          if (active) {

            state.signalFilter = "";

          } else {

            button.classList.add(
              "active"
            );

            state.signalFilter =
              button.dataset.signal ||
              "";
          }


          renderScanner();
        }
      );

    });


  const sortField =
    $("sortField");

  if (sortField) {

    sortField.value =
      state.sortField;

    sortField.addEventListener(
      "change",
      () => {

        state.sortField =
          sortField.value ||
          "change";

        renderScanner();
      }
    );
  }


  const sortDir =
    $("sortDir");

  if (sortDir) {

    sortDir.addEventListener(
      "click",
      () => {

        state.sortDesc =
          !state.sortDesc;

        sortDir.textContent =
          state.sortDesc
            ? "↓ تنازلي"
            : "↑ تصاعدي";

        renderScanner();
      }
    );
  }
}


/* =========================================================
   FUTURES
========================================================= */

async function fetchFutures() {

  const container =
    $("futuresList");

  if (container) {

    container.innerHTML = `
      <div class="loading-card">
        جاري تحميل الفيوتشر...
      </div>
    `;
  }


  try {

    const url =
      `/api/futures/scan?interval=${encodeURIComponent(state.futuresInterval)}&limit=40`;

    const data =
      await apiFetch(url);

    const list =
      normalizeResults(data);


    if ($("futuresStatus")) {

      $("futuresStatus").textContent =
        data.note ||
        `مصدر البيانات: OKX — ${state.futuresInterval}`;
    }


    renderCards(
      container,
      list,
      "futures"
    );

  } catch (error) {

    console.error("Futures:", error);

    if (container) {

      container.innerHTML = `
        <div class="empty-card">
          ⚠️ تعذر تحميل بيانات الفيوتشر
        </div>
      `;
    }
  }
}


/* =========================================================
   SAUDI
========================================================= */

async function fetchSaudi() {

  const container =
    $("saudiList");

  if (container) {

    container.innerHTML = `
      <div class="loading-card">
        جاري تحميل السوق السعودي...
      </div>
    `;
  }


  try {

    const url =
      `/api/saudi/scan?interval=${encodeURIComponent(state.saudiInterval)}`;

    const data =
      await apiFetch(url);

    const list =
      normalizeResults(data);


    if ($("saudiStatus")) {

      $("saudiStatus").textContent =
        `السوق السعودي — ${state.saudiInterval}`;
    }


    renderCards(
      container,
      list,
      "saudi"
    );

  } catch (error) {

    console.error("Saudi:", error);

    if (container) {

      container.innerHTML = `
        <div class="empty-card">
          ⚠️ تعذر تحميل السوق السعودي
        </div>
      `;
    }
  }
}


/* =========================================================
   US MARKET
========================================================= */

async function fetchUSMarket() {

  const container =
    $("usMarketList");

  if (container) {

    container.innerHTML = `
      <div class="loading-card">
        جاري تحميل السوق الأمريكي...
      </div>
    `;
  }


  try {

    const url =
      `/api/usmarket/signals?interval=${encodeURIComponent(state.usInterval)}`;

    const data =
      await apiFetch(url);

    const list =
      normalizeResults(data);


    if ($("usStatus")) {

      $("usStatus").textContent =
        `السوق الأمريكي — ${state.usInterval}`;
    }


    renderCards(
      container,
      list,
      "us"
    );

  } catch (error) {

    console.error("US:", error);

    if (container) {

      container.innerHTML = `
        <div class="empty-card">
          ⚠️ تعذر تحميل السوق الأمريكي
        </div>
      `;
    }
  }
}


/* =========================================================
   FOREX
========================================================= */

async function fetchForex() {

  const container =
    $("forexList");

  if (container) {

    container.innerHTML = `
      <div class="loading-card">
        جاري تحميل الفوركس...
      </div>
    `;
  }


  try {

    const url =
      `/api/forex/signals?interval=${encodeURIComponent(state.forexInterval)}`;

    const data =
      await apiFetch(url);

    const list =
      normalizeResults(data);


    if ($("forexStatus")) {

      $("forexStatus").textContent =
        `الفوركس — ${state.forexInterval}`;
    }


    renderCards(
      container,
      list,
      "forex"
    );

  } catch (error) {

    console.error("Forex:", error);

    if (container) {

      container.innerHTML = `
        <div class="empty-card">
          ⚠️ تعذر تحميل الفوركس
        </div>
      `;
    }
  }
}


/* =========================================================
   GENERIC CARDS
========================================================= */

function renderCards(
  container,
  list,
  type = ""
) {

  if (!container) {
    return;
  }


  if (!Array.isArray(list) ||
      !list.length) {

    container.innerHTML = `
      <div class="empty-card">
        لا توجد بيانات متاحة حالياً
      </div>
    `;

    return;
  }


  container.innerHTML =
    list
      .filter(Boolean)
      .slice(0, 100)
      .map((item) => {

        const symbol =
          getSymbol(item);

        const price =
          getPrice(item);

        const change =
          getChange(item);

        const signal =
          getSignal(item);

        const score =
          getScore(item);


        return `
          <article
            class="market-card"
            data-symbol="${escapeHTML(symbol)}"
          >

            <div class="market-card-head">

              <div>

                <b>
                  ${escapeHTML(symbol)}
                </b>

                <small>
                  ${escapeHTML(type)}
                </small>

              </div>

              <span class="signal ${signalClass(signal)}">
                ${signalEmoji(signal)}
                ${escapeHTML(signal)}
              </span>

            </div>


            <div class="market-price">
              ${fmtPrice(price)}
            </div>


            <div class="market-card-info">

              <span>
                التغير
                <b class="${change >= 0 ? "positive" : "negative"}">
                  ${fmtPercent(change)}
                </b>
              </span>

              <span>
                القوة
                <b>
                  ${fmtScore(score)}
                </b>
              </span>

            </div>


            <button
              class="card-analyze"
              data-symbol="${escapeHTML(symbol)}"
              data-market="${escapeHTML(type)}"
            >
              📊 تحليل
            </button>

          </article>
        `;

      })
      .join("");


  container
    .querySelectorAll(".card-analyze")
    .forEach((button) => {

      button.addEventListener(
        "click",
        () => {

          const symbol =
            button.dataset.symbol;

          if (!symbol) return;


          state.symbol =
            symbol;


          if (
            button.dataset.market ===
            "saudi"
          ) {

            openSection("saudi");

          } else if (
            button.dataset.market ===
            "us"
          ) {

            openSection("usmarket");

          } else if (
            button.dataset.market ===
            "forex"
          ) {

            openSection("forex");

          } else {

            openSection("dashboard");

            loadDashboard(symbol);
          }

        }
      );

    });
}


/* =========================================================
   NEWS
========================================================= */

async function fetchNews() {

  const container =
    $("newsList");

  if (container) {

    container.innerHTML = `
      <div class="loading-card">
        جاري تحميل الأخبار...
      </div>
    `;
  }


  try {

    const data =
      await apiFetch("/api/news");


    let list = [];

    if (Array.isArray(data)) {
      list = data;
    } else if (
      Array.isArray(data.news)
    ) {
      list = data.news;
    } else if (
      Array.isArray(data.items)
    ) {
      list = data.items;
    } else if (
      Array.isArray(data.results)
    ) {
      list = data.results;
    }


    renderNews(list);


    if ($("newsStatus")) {

      $("newsStatus").textContent =
        list.length
          ? `تم تحميل ${list.length} خبر`
          : "لا توجد أخبار حالياً";
    }

  } catch (error) {

    console.error("News:", error);

    if (container) {

      container.innerHTML = `
        <div class="empty-card">
          ⚠️ تعذر تحميل الأخبار
        </div>
      `;
    }

    if ($("newsStatus")) {
      $("newsStatus").textContent =
        "تعذر تحميل الأخبار";
    }
  }
}


function renderNews(list) {

  const container =
    $("newsList");

  if (!container) return;


  if (!Array.isArray(list) ||
      !list.length) {

    container.innerHTML = `
      <div class="empty-card">
        📰 لا توجد أخبار متاحة
      </div>
    `;

    return;
  }


  container.innerHTML =
    list
      .filter(Boolean)
      .slice(0, 30)
      .map((item) => {

        const title =
          item.title ??
          item.name ??
          "خبر";


        const description =
          item.description ??
          item.summary ??
          item.content ??
          "";


        const link =
          item.link ??
          item.url ??
          "#";


        const date =
          item.pubDate ??
          item.date ??
          item.published ??
          "";


        return `
          <article class="news-card">

            <div class="news-card-head">
              <span>📰</span>

              <small>
                ${escapeHTML(
                  formatNewsDate(date)
                )}
              </small>
            </div>


            <h3>
              ${escapeHTML(title)}
            </h3>


            ${
              description
                ? `
                  <p>
                    ${escapeHTML(
                      stripHTML(
                        description
                      )
                    ).slice(0, 280)}
                  </p>
                `
                : ""
            }


            ${
              link &&
              link !== "#"
                ? `
                  <a
                    href="${escapeHTML(link)}"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    قراءة الخبر ↗
                  </a>
                `
                : ""
            }

          </article>
        `;

      })
      .join("");
}


function stripHTML(value) {

  const div =
    document.createElement("div");

  div.innerHTML =
    String(value ?? "");

  return div.textContent ||
    div.innerText ||
    "";
}


function formatNewsDate(value) {

  if (!value) {
    return "";
  }

  const date =
    new Date(value);

  if (
    Number.isNaN(
      date.getTime()
    )
  ) {
    return String(value);
  }

  return date.toLocaleString(
    "ar-SA",
    {
      dateStyle: "medium",
      timeStyle: "short"
    }
  );
}


/* =========================================================
   RECENT
========================================================= */

function loadRecent() {

  try {

    const saved =
      localStorage.getItem(
        "mudarib_recent"
      );

    const data =
      saved
        ? JSON.parse(saved)
        : [];

    state.recent =
      Array.isArray(data)
        ? data
        : [];

  } catch (_) {

    state.recent = [];
  }
}


function saveRecent(item) {

  if (!item) return;

  const symbol =
    getSymbol(item);

  const existing =
    state.recent.filter(
      (x) =>
        getSymbol(x) !==
        symbol
    );


  state.recent =
    [
      item,
      ...existing
    ].slice(0, 30);


  localStorage.setItem(
    "mudarib_recent",
    JSON.stringify(
      state.recent
    )
  );
}


function renderRecent() {

  const container =
    $("recentList");

  if (!container) return;


  if (!state.recent.length) {

    container.innerHTML = `
      <div class="empty-card">
        لا توجد إشارات محفوظة حتى الآن
      </div>
    `;

    return;
  }


  renderCards(
    container,
    state.recent,
    "crypto"
  );
}


function setupRecent() {

  const clear =
    $("clearRecent");

  if (!clear) return;


  clear.addEventListener(
    "click",
    () => {

      state.recent = [];

      localStorage.removeItem(
        "mudarib_recent"
      );

      renderRecent();
    }
  );
}


/* =========================================================
   REFRESH BUTTONS
========================================================= */

function setupRefreshButtons() {

  const map = {

    refreshFutures:
      fetchFutures,

    refreshSaudi:
      fetchSaudi,

    refreshUSMarket:
      fetchUSMarket,

    refreshForex:
      fetchForex,

    newsBtn:
      fetchNews
  };


  Object.entries(map)
    .forEach(
      ([id, fn]) => {

        const button = $(id);

        if (!button) return;

        button.addEventListener(
          "click",
          fn
        );

      }
    );
}


/* =========================================================
   AUTO REFRESH
========================================================= */

function startAutoRefresh() {

  setInterval(
    () => {

      const active =
        document.querySelector(
          ".section.active"
        );


      if (!active) {
        return;
      }


      if (
        active.id ===
        "dashboard"
      ) {

        loadDashboard();

      }

    },
    120000
  );
}


/* =========================================================
   CONNECTION TEST
========================================================= */

async function testConnection() {

  try {

    await apiFetch(
      "/api/okx/test"
    );

    setStatus(
      "متصل",
      "online"
    );

  } catch (error) {

    console.warn(
      "OKX test failed:",
      error
    );

    setStatus(
      "متصل بالسيرفر",
      "online"
    );
  }
}


/* =========================================================
   STARTUP
========================================================= */

async function init() {

  setupNavigation();

  setupTheme();

  setupIntervalButtons();

  setupScanner();

  setupRecent();

  setupRefreshButtons();

  loadRecent();

  await testConnection();

  await loadDashboard(
    state.symbol
  );

  startAutoRefresh();
}


/* =========================================================
   RUN
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
