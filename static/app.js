"use strict";

/* =========================================================
   مضارب أبو سعود
   Markets Dashboard
========================================================= */

const $ = (id) => document.getElementById(id);

const state = {
  section: "dashboard",
  interval: "15m",
  dashboardSymbol: "BTCUSDT",

  saudiInterval: "1d",
  usInterval: "1d",
  forexInterval: "1h",
  futuresInterval: "15m",

  scannerMarket: "crypto",
  scannerInterval: "15m",

  scannerResults: [],
  recent: JSON.parse(localStorage.getItem("mudarib_recent") || "[]"),

  sortField: "change",
  sortDir: -1,

  chart: null,
  busy: false
};


/* =========================================================
   API
========================================================= */

const API = {
  cryptoScan: "/api/okx/scan",
  cryptoAnalysis: "/api/okx/analysis",

  saudiScan: "/api/saudi/scan",
  saudiMarkets: "/api/saudi/markets",

  usScan: "/api/usmarket/signals",
  usMarkets: "/api/usmarket/markets",

  forexScan: "/api/forex/signals",
  forexMarkets: "/api/forex/markets",

  futuresScan: "/api/futures/scan",

  news: "/api/news"
};


/* =========================================================
   HELPERS
========================================================= */

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}


function num(value, digits = 4) {
  const n = Number(value);

  if (!Number.isFinite(n)) {
    return "—";
  }

  return n.toLocaleString("en-US", {
    maximumFractionDigits: digits
  });
}


function pct(value) {
  const n = Number(value);

  if (!Number.isFinite(n)) {
    return "—";
  }

  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}


function getSymbol(item) {
  return (
    item?.symbol ??
    item?.instId ??
    item?.ticker ??
    item?.code ??
    item?.name ??
    "—"
  );
}


function getName(item) {
  return (
    item?.name ??
    item?.longName ??
    item?.description ??
    getSymbol(item)
  );
}


function getPrice(item) {
  return Number(
    item?.price ??
    item?.last ??
    item?.close ??
    item?.c ??
    item?.regularMarketPrice ??
    0
  );
}


function getChange(item) {
  return Number(
    item?.change ??
    item?.change_percent ??
    item?.changePercent ??
    item?.pctChange ??
    item?.percent ??
    item?.regularMarketChangePercent ??
    0
  );
}


function getScore(item) {
  return Number(
    item?.score ??
    item?.score10 ??
    item?.strength ??
    0
  );
}


function getSignal(item) {
  return (
    item?.signal ??
    item?.direction ??
    item?.recommendation ??
    "حيادي"
  );
}


function getVolume(item) {
  return Number(
    item?.volume ??
    item?.quoteVolume ??
    item?.vol24h ??
    item?.volume24h ??
    0
  );
}


function getInterval(item, fallback = "15m") {
  return item?.interval ?? item?.timeframe ?? fallback;
}


function signalClass(signal) {

  if (signal.includes("شراء قوي")) return "strong-buy";
  if (signal.includes("شراء")) return "buy";
  if (signal.includes("بيع قوي")) return "strong-sell";
  if (signal.includes("بيع")) return "sell";

  return "neutral";
}


function normalizeResponse(data) {

  if (!data) return [];

  if (Array.isArray(data)) {
    return data;
  }

  if (Array.isArray(data.results)) {
    return data.results;
  }

  if (Array.isArray(data.data)) {
    return data.data;
  }

  if (Array.isArray(data.items)) {
    return data.items;
  }

  if (Array.isArray(data.markets)) {
    return data.markets;
  }

  if (Array.isArray(data.signals)) {
    return data.signals;
  }

  return [];
}


/* =========================================================
   FETCH
========================================================= */

async function api(url, params = {}) {

  const query = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {

    if (
      value !== undefined &&
      value !== null &&
      value !== ""
    ) {
      query.set(key, value);
    }

  });

  const finalUrl =
    query.toString()
      ? `${url}?${query.toString()}`
      : url;

  const response = await fetch(finalUrl, {
    cache: "no-store"
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  return await response.json();
}


/* =========================================================
   STATUS
========================================================= */

function setStatus(id, text) {

  const el = $(id);

  if (el) {
    el.textContent = text;
  }

}


function loading(id, text = "جاري التحميل...") {

  const el = $(id);

  if (el) {
    el.innerHTML = `
      <div class="empty-state">
        ⏳ ${esc(text)}
      </div>
    `;
  }

}


/* =========================================================
   NAVIGATION
========================================================= */

function openSection(section) {

  state.section = section;

  document
    .querySelectorAll(".section")
    .forEach(el => {
      el.classList.toggle(
        "active",
        el.id === section
      );
    });


  document
    .querySelectorAll(".nav-item")
    .forEach(el => {
      el.classList.toggle(
        "active",
        el.dataset.section === section
      );
    });


  const titles = {
    dashboard: "الرئيسية",
    scanner: "ماسح الفرص",
    recent: "صفقات السبوت",
    futures: "الفيوتشر",
    saudi: "السوق السعودي",
    usmarket: "السوق الأمريكي",
    forex: "الفوركس",
    news: "الأخبار"
  };


  if ($("pageTitle")) {
    $("pageTitle").textContent =
      titles[section] || "مضارب أبو سعود";
  }


  if (section === "dashboard") {
    loadDashboard();
  }

  if (section === "scanner") {
    loadScanner();
  }

  if (section === "recent") {
    renderRecent();
  }

  if (section === "futures") {
    loadFutures();
  }

  if (section === "saudi") {
    loadSaudi();
  }

  if (section === "usmarket") {
    loadUSMarket();
  }

  if (section === "forex") {
    loadForex();
  }

  if (section === "news") {
    loadNews();
  }

}


/* =========================================================
   DASHBOARD
========================================================= */

async function loadDashboard() {

  setStatus(
    "systemStatus",
    "جاري تحديث البيانات..."
  );


  try {

    const data = await api(
      API.cryptoAnalysis,
      {
        symbol: state.dashboardSymbol,
        interval: state.interval
      }
    );


    updateDashboard(data);

    setStatus(
      "systemStatus",
      "🟢 متصل"
    );

  } catch (error) {

    console.error(error);

    setStatus(
      "systemStatus",
      "🔴 تعذر الاتصال"
    );

  }

}


function updateDashboard(data) {

  const item =
    data?.analysis ??
    data?.result ??
    data;


  const symbol =
    item?.symbol ??
    state.dashboardSymbol;


  const price =
    getPrice(item);


  const change =
    getChange(item);


  const signal =
    getSignal(item);


  const score =
    getScore(item);


  if ($("dashSymbol")) {
    $("dashSymbol").textContent =
      symbol;
  }


  if ($("dashPrice")) {
    $("dashPrice").textContent =
      price ? num(price, 8) : "—";
  }


  if ($("homePrice")) {
    $("homePrice").textContent =
      price ? num(price, 8) : "—";
  }


  if ($("dashChange")) {
    $("dashChange").textContent =
      pct(change);
  }


  if ($("homeChange")) {
    $("homeChange").textContent =
      pct(change);
  }


  if ($("dashSignal")) {
    $("dashSignal").textContent =
      signal;
  }


  if ($("bigSignal")) {
    $("bigSignal").textContent =
      signal;
  }


  if ($("scoreText")) {
    $("scoreText").textContent =
      `${score || 0}/100`;
  }


  if ($("homeScore")) {
    $("homeScore").textContent =
      `${score || 0}/100`;
  }


  if ($("homeVolume")) {
    $("homeVolume").textContent =
      formatVolume(getVolume(item));
  }


  if ($("homeInterval")) {
    $("homeInterval").textContent =
      state.interval;
  }


  if ($("analysisMeta")) {
    $("analysisMeta").textContent =
      `OKX — ${symbol} — ${state.interval}`;
  }


  updateScoreBar(score);

  updateField("entry", item?.entry);
  updateField("tp1", item?.tp1);
  updateField("tp2", item?.tp2);
  updateField("tp3", item?.tp3);
  updateField("sl", item?.sl);

  updateField("rsi", item?.rsi, 2);
  updateField("ema20", item?.ema20, 6);
  updateField("ema50", item?.ema50, 6);
  updateField("ema200", item?.ema200, 6);
  updateField("macd", item?.macd, 6);
  updateField("atr", item?.atr, 6);


  if ($("trendText")) {

    $("trendText").textContent =
      signal.includes("شراء")
        ? "صاعد"
        : signal.includes("بيع")
          ? "هابط"
          : "محايد";

  }


  if ($("marketState")) {

    $("marketState").textContent =
      signal.includes("شراء")
        ? "إيجابي"
        : signal.includes("بيع")
          ? "سلبي"
          : "متوازن";

  }


  if ($("riskText")) {

    $("riskText").textContent =
      item?.risk ??
      "متوسط";

  }


  if ($("lastUpdate")) {

    $("lastUpdate").textContent =
      new Date().toLocaleTimeString(
        "ar-SA"
      );

  }


  renderReasons(
    item?.reasons ??
    item?.reason ??
    []
  );


  drawChart(
    item?.candles ??
    item?.klines ??
    data?.candles ??
    []
  );

}


/* =========================================================
   DASHBOARD HELPERS
========================================================= */

function updateField(id, value, digits = 8) {

  const el = $(id);

  if (!el) return;

  if (
    value === undefined ||
    value === null ||
    value === ""
  ) {
    el.textContent = "—";
    return;
  }

  const n = Number(value);

  el.textContent =
    Number.isFinite(n)
      ? num(n, digits)
      : String(value);

}


function updateScoreBar(score) {

  const bar = $("scoreBar");

  if (!bar) return;

  let value = Number(score);

  if (!Number.isFinite(value)) {
    value = 0;
  }

  value = Math.max(
    0,
    Math.min(100, value)
  );

  bar.style.width =
    `${value}%`;

}


function renderReasons(reasons) {

  const el = $("reasons");

  if (!el) return;

  if (!Array.isArray(reasons)) {

    reasons = reasons
      ? [reasons]
      : [];

  }


  if (!reasons.length) {

    el.innerHTML = `
      <li>
        لا توجد أسباب إضافية.
      </li>
    `;

    return;
  }


  el.innerHTML =
    reasons
      .slice(0, 10)
      .map(reason => `
        <li>
          ${esc(
            typeof reason === "object"
              ? reason.text ?? reason.reason ?? JSON.stringify(reason)
              : reason
          )}
        </li>
      `)
      .join("");

}


/* =========================================================
   CHART
========================================================= */

function drawChart(candles) {

  const canvas = $("priceChart");

  if (!canvas) return;

  if (!Array.isArray(candles)) {
    candles = [];
  }


  const labels = [];
  const prices = [];


  candles
    .slice(-100)
    .forEach((candle, index) => {

      if (Array.isArray(candle)) {

        labels.push(
          candle[0]
            ? new Date(Number(candle[0]))
                .toLocaleTimeString("ar-SA", {
                  hour: "2-digit",
                  minute: "2-digit"
                })
            : index
        );

        prices.push(
          Number(candle[4] ?? candle[1] ?? 0)
        );

      } else {

        labels.push(
          candle?.time ??
          candle?.t ??
          index
        );

        prices.push(
          Number(
            candle?.close ??
            candle?.c ??
            candle?.price ??
            0
          )
        );

      }

    });


  if (
    typeof Chart === "undefined"
  ) {
    return;
  }


  if (state.chart) {
    state.chart.destroy();
  }


  state.chart =
    new Chart(canvas, {

      type: "line",

      data: {

        labels,

        datasets: [{

          label: "السعر",

          data: prices,

          tension: 0.25,

          pointRadius: 0,

          borderWidth: 2,

          fill: false

        }]

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
            ticks: {
              maxTicksLimit: 8
            }
          },

          y: {
            beginAtZero: false
          }

        }

      }

    });

}


/* =========================================================
   GENERIC MARKET LOADER
========================================================= */

async function loadMarket({
  url,
  interval,
  listId,
  statusId,
  marketName,
  fallbackUrl = null
}) {

  loading(
    listId,
    `جاري تحميل ${marketName}...`
  );


  setStatus(
    statusId,
    `جاري تحميل ${marketName}...`
  );


  try {

    let data;

    try {

      data = await api(
        url,
        {
          interval,
          limit: 100
        }
      );

    } catch (firstError) {

      console.warn(
        `${marketName} primary endpoint failed`,
        firstError
      );


      if (!fallbackUrl) {
        throw firstError;
      }


      data = await api(
        fallbackUrl,
        {
          interval,
          limit: 100
        }
      );

    }


    const results =
      normalizeResponse(data);


    renderMarketCards(
      listId,
      results,
      interval
    );


    setStatus(
      statusId,
      results.length
        ? `🟢 تم تحميل ${results.length} أصل`
        : `⚠️ لم تصل بيانات`
    );


    return results;

  } catch (error) {

    console.error(
      marketName,
      error
    );


    const el = $(listId);

    if (el) {

      el.innerHTML = `
        <div class="empty-state">
          ⚠️ تعذر تحميل ${esc(marketName)}
          <br>
          <small>${esc(error.message)}</small>
        </div>
      `;

    }


    setStatus(
      statusId,
      "🔴 تعذر تحميل البيانات"
    );


    return [];

  }

}


/* =========================================================
   SAUDI
========================================================= */

async function loadSaudi() {

  return loadMarket({

    url: API.saudiScan,

    fallbackUrl: API.saudiMarkets,

    interval: state.saudiInterval,

    listId: "saudiList",

    statusId: "saudiStatus",

    marketName: "السوق السعودي"

  });

}


/* =========================================================
   US MARKET
========================================================= */

async function loadUSMarket() {

  return loadMarket({

    url: API.usScan,

    fallbackUrl: API.usMarkets,

    interval: state.usInterval,

    listId: "usMarketList",

    statusId: "usStatus",

    marketName: "السوق الأمريكي"

  });

}


/* =========================================================
   FOREX
========================================================= */

async function loadForex() {

  return loadMarket({

    url: API.forexScan,

    fallbackUrl: API.forexMarkets,

    interval: state.forexInterval,

    listId: "forexList",

    statusId: "forexStatus",

    marketName: "الفوركس"

  });

}


/* =========================================================
   FUTURES
========================================================= */

async function loadFutures() {

  return loadMarket({

    url: API.futuresScan,

    interval: state.futuresInterval,

    listId: "futuresList",

    statusId: "futuresStatus",

    marketName: "الفيوتشر"

  });

}


/* =========================================================
   MARKET CARDS
========================================================= */

function renderMarketCards(
  listId,
  results,
  interval
) {

  const container = $(listId);

  if (!container) return;


  if (!results.length) {

    container.innerHTML = `
      <div class="empty-state">
        لا توجد بيانات متاحة حاليًا.
      </div>
    `;

    return;
  }


  const sorted =
    [...results]
      .sort(
        (a, b) =>
          getScore(b) -
          getScore(a)
      )
      .slice(0, 100);


  container.innerHTML =
    sorted
      .map(item => {

        const symbol =
          getSymbol(item);

        const name =
          getName(item);

        const price =
          getPrice(item);

        const change =
          getChange(item);

        const score =
          getScore(item);

        const signal =
          getSignal(item);


        return `

          <div class="market-card">

            <div class="market-card-top">

              <div>

                <strong>
                  ${esc(symbol)}
                </strong>

                <small>
                  ${esc(name)}
                </small>

              </div>

              <span
                class="signal-badge ${signalClass(signal)}"
              >
                ${esc(signal)}
              </span>

            </div>


            <div class="market-card-price">

              ${price
                ? num(price, 8)
                : "—"}

            </div>


            <div class="market-card-info">

              <span>
                التغير
                <b>
                  ${pct(change)}
                </b>
              </span>


              <span>
                القوة
                <b>
                  ${score || 0}
                </b>
              </span>


              <span>
                الفريم
                <b>
                  ${esc(interval)}
                </b>
              </span>

            </div>

          </div>

        `;

      })
      .join("");

}


/* =========================================================
   SCANNER
========================================================= */

async function loadScanner() {

  const market =
    $("scannerMarket")?.value ??
    state.scannerMarket;


  state.scannerMarket =
    market;


  loading(
    "scannerBody",
    "جاري فحص السوق..."
  );


  setStatus(
    "scannerStatus",
    "جاري الفحص..."
  );


  let url =
    API.cryptoScan;


  if (market === "futures") {
    url = API.futuresScan;
  }

  if (market === "saudi") {
    url = API.saudiScan;
  }

  if (market === "usmarket") {
    url = API.usScan;
  }

  if (market === "forex") {
    url = API.forexScan;
  }


  try {

    const data =
      await api(url, {
        interval:
          state.scannerInterval,
        limit: 100
      });


    state.scannerResults =
      normalizeResponse(data);


    renderScanner();


    setStatus(
      "scannerStatus",
      `🟢 تم تحميل ${state.scannerResults.length} نتيجة`
    );

  } catch (error) {

    console.error(error);

    setStatus(
      "scannerStatus",
      "🔴 تعذر تحميل النتائج"
    );


    const body =
      $("scannerBody");

    if (body) {

      body.innerHTML = `
        <tr>
          <td colspan="7">
            تعذر تحميل البيانات
          </td>
        </tr>
      `;

    }

  }

}


function renderScanner() {

  const body =
    $("scannerBody");

  if (!body) return;


  let data =
    [...state.scannerResults];


  const search =
    (
      $("scannerSearch")?.value ??
      ""
    )
      .trim()
      .toLowerCase();


  if (search) {

    data =
      data.filter(item => {

        const text =
          `${getSymbol(item)} ${getName(item)}`
            .toLowerCase();

        return text.includes(search);

      });

  }


  data.sort((a, b) => {

    let av;
    let bv;


    switch (state.sortField) {

      case "score":
        av = getScore(a);
        bv = getScore(b);
        break;

      case "price":
        av = getPrice(a);
        bv = getPrice(b);
        break;

      case "volume":
        av = getVolume(a);
        bv = getVolume(b);
        break;

      case "symbol":
        av = getSymbol(a);
        bv = getSymbol(b);
        return (
          String(av)
            .localeCompare(
              String(bv)
            ) *
          state.sortDir
        );

      case "signal":
        av = getSignal(a);
        bv = getSignal(b);
        return (
          String(av)
            .localeCompare(
              String(bv)
            ) *
          state.sortDir
        );

      default:
        av = getChange(a);
        bv = getChange(b);

    }


    return (
      (bv - av) *
      state.sortDir
    );

  });


  if (!data.length) {

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
    data
      .map(item => {

        const signal =
          getSignal(item);


        return `

          <tr>

            <td>
              <strong>
                ${esc(getSymbol(item))}
              </strong>
            </td>

            <td>
              ${num(getPrice(item), 8)}
            </td>

            <td>
              ${pct(getChange(item))}
            </td>

            <td>
              <span
                class="signal-badge ${signalClass(signal)}"
              >
                ${esc(signal)}
              </span>
            </td>

            <td>
              ${getScore(item) || 0}
            </td>

            <td>
              ${formatVolume(getVolume(item))}
            </td>

            <td>
              ${esc(
                getInterval(
                  item,
                  state.scannerInterval
                )
              )}
            </td>

          </tr>

        `;

      })
      .join("");

}


/* =========================================================
   RECENT
========================================================= */

function saveRecent(item) {

  if (!item) return;


  state.recent.unshift({

    symbol:
      getSymbol(item),

    price:
      getPrice(item),

    signal:
      getSignal(item),

    change:
      getChange(item),

    time:
      new Date().toISOString()

  });


  state.recent =
    state.recent.slice(0, 30);


  localStorage.setItem(
    "mudarib_recent",
    JSON.stringify(
      state.recent
    )
  );

}


function renderRecent() {

  const el =
    $("recentList");

  if (!el) return;


  if (!state.recent.length) {

    el.innerHTML = `
      <div class="empty-state">
        لا توجد صفقات محفوظة حتى الآن.
      </div>
    `;

    return;
  }


  el.innerHTML =
    state.recent
      .map(item => `

        <div class="market-card">

          <div class="market-card-top">

            <div>

              <strong>
                ${esc(item.symbol)}
              </strong>

              <small>
                ${new Date(item.time)
                  .toLocaleString("ar-SA")}
              </small>

            </div>


            <span
              class="signal-badge ${signalClass(item.signal)}"
            >
              ${esc(item.signal)}
            </span>

          </div>


          <div class="market-card-price">

            ${num(item.price, 8)}

          </div>


          <div class="market-card-info">

            <span>
              التغير
              <b>
                ${pct(item.change)}
              </b>
            </span>

          </div>

        </div>

      `)
      .join("");

}


/* =========================================================
   NEWS
========================================================= */

async function loadNews() {

  loading(
    "newsList",
    "جاري تحميل الأخبار..."
  );


  setStatus(
    "newsStatus",
    "جاري تحميل الأخبار..."
  );


  try {

    const data =
      await api(API.news);


    const news =
      normalizeResponse(data);


    renderNews(
      "newsList",
      news
    );


    renderNews(
      "homeNewsList",
      news.slice(0, 5)
    );


    setStatus(
      "newsStatus",
      `🟢 تم تحميل ${news.length} خبر`
    );

  } catch (error) {

    console.error(error);


    setStatus(
      "newsStatus",
      "🔴 تعذر تحميل الأخبار"
    );


    const text = `
      <div class="empty-state">
        تعذر تحميل الأخبار حاليًا.
      </div>
    `;


    if ($("newsList")) {
      $("newsList").innerHTML = text;
    }


    if ($("homeNewsList")) {
      $("homeNewsList").innerHTML = text;
    }

  }

}


function renderNews(
  id,
  news
) {

  const el = $(id);

  if (!el) return;


  if (!news.length) {

    el.innerHTML = `
      <div class="empty-state">
        لا توجد أخبار متاحة.
      </div>
    `;

    return;
  }


  el.innerHTML =
    news
      .map(item => {

        const title =
          item?.title ??
          item?.name ??
          "خبر";


        const description =
          item?.description ??
          item?.summary ??
          "";


        const link =
          item?.link ??
          item?.url ??
          "#";


        return `

          <article class="news-card">

            <h3>
              ${esc(title)}
            </h3>

            <p>
              ${esc(
                String(description)
                  .replace(/<[^>]*>/g, "")
                  .slice(0, 220)
              )}
            </p>


            ${
              link !== "#"
                ? `
                  <a
                    href="${esc(link)}"
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

      })
      .join("");

}


/* =========================================================
   FORMAT VOLUME
========================================================= */

function formatVolume(value) {

  const n =
    Number(value);


  if (
    !Number.isFinite(n) ||
    n === 0
  ) {
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
    return `${(n / 1e3).toFixed(2)}K`;
  }


  return num(n, 2);

}


/* =========================================================
   INTERVAL BUTTONS
========================================================= */

function setupIntervals(
  containerId,
  callback
) {

  const container =
    $(containerId);

  if (!container) return;


  container
    .querySelectorAll(
      "[data-interval]"
    )
    .forEach(button => {

      button.addEventListener(
        "click",
        () => {

          container
            .querySelectorAll(
              "[data-interval]"
            )
            .forEach(btn =>
              btn.classList.remove(
                "active"
              )
            );


          button.classList.add(
            "active"
          );


          callback(
            button.dataset.interval
          );

        }
      );

    });

}


/* =========================================================
   EVENTS
========================================================= */

function setupEvents() {


  /* NAV */

  document
    .querySelectorAll(".nav-item")
    .forEach(button => {

      button.addEventListener(
        "click",
        () => {

          openSection(
            button.dataset.section
          );

        }
      );

    });


  /* MENU */

  $("menuBtn")?.addEventListener(
    "click",
    () => {

      $("sidebar")
        ?.classList.toggle(
          "open"
        );

    }
  );


  /* THEME */

  $("themeBtn")?.addEventListener(
    "click",
    () => {

      document.body
        .classList.toggle(
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

    }
  );


  /* DASHBOARD INTERVALS */

  setupIntervals(
    "dashIntervals",
    interval => {

      state.interval =
        interval;

      loadDashboard();

    }
  );


  /* SCANNER */

  $("scanBtn")?.addEventListener(
    "click",
    loadScanner
  );


  $("scannerMarket")?.addEventListener(
    "change",
    () => {

      state.scannerMarket =
        $("scannerMarket").value;

      loadScanner();

    }
  );


  $("scannerSearch")?.addEventListener(
    "input",
    renderScanner
  );


  $("sortField")?.addEventListener(
    "change",
    () => {

      state.sortField =
        $("sortField").value;

      renderScanner();

    }
  );


  $("sortDir")?.addEventListener(
    "click",
    () => {

      state.sortDir *= -1;

      $("sortDir").textContent =
        state.sortDir === -1
          ? "↓ تنازلي"
          : "↑ تصاعدي";

      renderScanner();

    }
  );


  setupIntervals(
    "intervalChips",
    interval => {

      state.scannerInterval =
        interval;

      loadScanner();

    }
  );


  /* RECENT */

  $("clearRecent")?.addEventListener(
    "click",
    () => {

      state.recent = [];

      localStorage.removeItem(
        "mudarib_recent"
      );

      renderRecent();

    }
  );


  /* FUTURES */

  $("refreshFutures")?.addEventListener(
    "click",
    loadFutures
  );


  setupIntervals(
    "futuresIntervals",
    interval => {

      state.futuresInterval =
        interval;

      loadFutures();

    }
  );


  /* SAUDI */

  $("refreshSaudi")?.addEventListener(
    "click",
    loadSaudi
  );


  setupIntervals(
    "saudiIntervals",
    interval => {

      state.saudiInterval =
        interval;

      loadSaudi();

    }
  );


  $("saudiSearch")?.addEventListener(
    "input",
    () => {

      filterCards(
        "saudiList",
        $("saudiSearch").value
      );

    }
  );


  /* US */

  $("refreshUSMarket")?.addEventListener(
    "click",
    loadUSMarket
  );


  setupIntervals(
    "usIntervals",
    interval => {

      state.usInterval =
        interval;

      loadUSMarket();

    }
  );


  $("usSearch")?.addEventListener(
    "input",
    () => {

      filterCards(
        "usMarketList",
        $("usSearch").value
      );

    }
  );


  /* FOREX */

  $("refreshForex")?.addEventListener(
    "click",
    loadForex
  );


  setupIntervals(
    "forexIntervals",
    interval => {

      state.forexInterval =
        interval;

      loadForex();

    }
  );


  $("forexSearch")?.addEventListener(
    "input",
    () => {

      filterCards(
        "forexList",
        $("forexSearch").value
      );

    }
  );


  /* NEWS */

  $("newsBtn")?.addEventListener(
    "click",
    loadNews
  );


  /* HOME BUTTONS */

  $("homeScannerBtn")?.addEventListener(
    "click",
    () => openSection("scanner")
  );


  $("homeNewsBtn")?.addEventListener(
    "click",
    () => openSection("news")
  );


  document
    .querySelectorAll(
      "[data-open-market]"
    )
    .forEach(card => {

      card.addEventListener(
        "click",
        () => {

          openSection(
            card.dataset.openMarket
          );

        }
      );

    });

}


/* =========================================================
   FILTER CARDS
========================================================= */

function filterCards(
  listId,
  search
) {

  const container =
    $(listId);

  if (!container) return;


  const value =
    String(search || "")
      .trim()
      .toLowerCase();


  container
    .querySelectorAll(
      ".market-card"
    )
    .forEach(card => {

      const text =
        card.textContent
          .toLowerCase();

      card.style.display =
        !value ||
        text.includes(value)
          ? ""
          : "none";

    });

}


/* =========================================================
   HOME OPPORTUNITIES
========================================================= */

async function loadHomeOpportunities() {

  try {

    const data =
      await api(
        API.cryptoScan,
        {
          interval: "15m",
          limit: 20
        }
      );


    const results =
      normalizeResponse(data)
        .sort(
          (a, b) =>
            getScore(b) -
            getScore(a)
        )
        .slice(0, 6);


    const el =
      $("homeOpportunities");

    if (!el) return;


    if (!results.length) {

      el.innerHTML = `
        <div class="empty-state">
          لا توجد فرص حاليًا.
        </div>
      `;

      return;
    }


    el.innerHTML =
      results
        .map(item => `

          <div class="market-card">

            <div class="market-card-top">

              <div>

                <strong>
                  ${esc(getSymbol(item))}
                </strong>

                <small>
                  ${esc(getInterval(item, "15m"))}
                </small>

              </div>


              <span
                class="signal-badge ${signalClass(getSignal(item))}"
              >
                ${esc(getSignal(item))}
              </span>

            </div>


            <div class="market-card-price">
              ${num(getPrice(item), 8)}
            </div>


            <div class="market-card-info">

              <span>
                التغير
                <b>
                  ${pct(getChange(item))}
                </b>
              </span>

              <span>
                القوة
                <b>
                  ${getScore(item) || 0}
                </b>
              </span>

            </div>

          </div>

        `)
        .join("");

  } catch (error) {

    console.error(
      "Home opportunities",
      error
    );

  }

}


/* =========================================================
   THEME
========================================================= */

function loadTheme() {

  const theme =
    localStorage.getItem(
      "mudarib_theme"
    );


  if (theme === "dark") {

    document.body
      .classList.add("dark");

  }

}


/* =========================================================
   START
========================================================= */

async function startApp() {

  loadTheme();

  setupEvents();

  openSection("dashboard");

  loadHomeOpportunities();

  loadNews();

  loadSaudi();

  loadUSMarket();

  loadForex();

  loadFutures();

}


document.addEventListener(
  "DOMContentLoaded",
  startApp
);
