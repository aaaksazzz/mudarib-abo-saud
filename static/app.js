(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const API = "";

  const state = {
    market: "crypto",
    interval: "15m",
    results: [],
    signals: [],
    loading: false,
    lastUpdate: 0
  };

  const MARKET_NAMES = {
    crypto: "العملات الرقمية",
    saudi: "السوق السعودي",
    us: "الأسهم الأمريكية",
    forex: "الفوركس",
    commodities: "الذهب والنفط",
    indices: "المؤشرات العالمية",
    futures: "العقود الآجلة"
  };

  const SIGNAL_CLASS = {
    "شراء قوي": "buy-strong",
    "شراء": "buy",
    "حيادي": "neutral",
    "بيع": "sell",
    "بيع قوي": "sell-strong"
  };

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function num(value, digits = 2) {
    const n = Number(value);

    if (!Number.isFinite(n)) {
      return "--";
    }

    return n.toLocaleString("en-US", {
      maximumFractionDigits: digits,
      minimumFractionDigits: digits
    });
  }

  function price(value) {
    const n = Number(value);

    if (!Number.isFinite(n)) {
      return "--";
    }

    if (Math.abs(n) >= 1000) {
      return n.toLocaleString("en-US", {
        maximumFractionDigits: 2
      });
    }

    if (Math.abs(n) >= 1) {
      return n.toLocaleString("en-US", {
        maximumFractionDigits: 4
      });
    }

    return n.toLocaleString("en-US", {
      maximumFractionDigits: 8
    });
  }

  function percent(value) {
    const n = Number(value);

    if (!Number.isFinite(n)) {
      return "--";
    }

    return `${n > 0 ? "+" : ""}${n.toFixed(2)}%`;
  }

  function signalClass(signal) {
    return SIGNAL_CLASS[signal] || "neutral";
  }

  function directionText(direction) {
    if (direction === "BUY") return "شراء";
    if (direction === "SELL") return "بيع";
    return "حيادي";
  }

  function formatTime(timestamp) {
    if (!timestamp) return "--";

    const date = new Date(Number(timestamp));

    if (Number.isNaN(date.getTime())) {
      return "--";
    }

    return date.toLocaleTimeString("ar-SA", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit"
    });
  }

  async function api(path) {
    const response = await fetch(`${API}${path}`, {
      method: "GET",
      cache: "no-store",
      headers: {
        "Accept": "application/json"
      }
    });

    let data;

    try {
      data = await response.json();
    } catch {
      throw new Error(`HTTP ${response.status}`);
    }

    if (!response.ok || data.ok === false) {
      throw new Error(
        data.error ||
        `HTTP ${response.status}`
      );
    }

    return data;
  }

  function findElement(ids) {
    for (const id of ids) {
      const el = $(id);

      if (el) {
        return el;
      }
    }

    return null;
  }

  function setText(ids, value) {
    const el = findElement(ids);

    if (el) {
      el.textContent = value;
    }
  }

  function setStatus(text, type = "normal") {
    const elements = [
      $("connectionStatus"),
      $("status"),
      $("serverStatus"),
      $("apiStatus")
    ].filter(Boolean);

    elements.forEach((el) => {
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
    });
  }

  function setLastUpdate(timestamp) {
    state.lastUpdate = timestamp || Date.now();

    setText(
      ["lastUpdate", "updatedAt", "updateTime"],
      `آخر تحديث: ${formatTime(state.lastUpdate)}`
    );
  }

  function getSignalTitle(item) {
    if (!item) return "حيادي";

    return item.signal ||
      directionText(item.direction);
  }

  function renderSignalCard(item) {
    const signal = getSignalTitle(item);
    const cls = signalClass(signal);

    const direction =
      item.direction === "SELL"
        ? "بيع"
        : item.direction === "BUY"
          ? "شراء"
          : "حيادي";

    return `
      <article class="signal-card ${esc(cls)}">

        <div class="signal-top">
          <div>
            <div class="signal-symbol">
              ${esc(item.name || item.symbol)}
            </div>

            <div class="signal-pair">
              ${esc(item.symbol || "")}
            </div>
          </div>

          <div class="signal-badge">
            ${esc(signal)}
          </div>
        </div>

        <div class="signal-price">
          ${price(item.price)}
        </div>

        <div class="signal-direction">
          الاتجاه: <strong>${esc(direction)}</strong>
        </div>

        <div class="signal-grid">

          <div class="signal-box">
            <span>الدخول</span>
            <strong>${price(item.entry)}</strong>
          </div>

          <div class="signal-box target">
            <span>الهدف</span>
            <strong>${price(item.takeProfit)}</strong>
          </div>

          <div class="signal-box stop">
            <span>الوقف</span>
            <strong>${price(item.stopLoss)}</strong>
          </div>

          <div class="signal-box">
            <span>القوة</span>
            <strong>${num(item.score10, 1)}/10</strong>
          </div>

        </div>

        <div class="signal-details">

          <div>
            <span>RSI</span>
            <b>${num(item.rsi, 2)}</b>
          </div>

          <div>
            <span>EMA20</span>
            <b>${price(item.ema20)}</b>
          </div>

          <div>
            <span>EMA50</span>
            <b>${price(item.ema50)}</b>
          </div>

          <div>
            <span>EMA200</span>
            <b>${price(item.ema200)}</b>
          </div>

          <div>
            <span>الحجم</span>
            <b>${num(item.volumeRatio, 2)}x</b>
          </div>

          <div>
            <span>الزخم</span>
            <b>${percent(item.momentum)}</b>
          </div>

        </div>

        <div class="signal-footer">
          <span>${esc(item.source || "Live Market")}</span>
          <span>${esc(item.interval || state.interval)}</span>
          <span>${formatTime(item.updatedAt)}</span>
        </div>

      </article>
    `;
  }

  function renderResultRow(item) {
    const signal = getSignalTitle(item);
    const cls = signalClass(signal);

    return `
      <div class="market-row ${esc(cls)}">

        <div class="market-name">
          <strong>${esc(item.name || item.symbol)}</strong>
          <small>${esc(item.symbol || "")}</small>
        </div>

        <div class="market-price">
          ${price(item.price)}
        </div>

        <div class="market-signal">
          <span class="signal-badge">
            ${esc(signal)}
          </span>
        </div>

        <div class="market-score">
          ${num(item.score10, 1)}/10
        </div>

        <div class="market-entry">
          ${price(item.entry)}
        </div>

        <div class="market-target">
          ${price(item.takeProfit)}
        </div>

        <div class="market-stop">
          ${price(item.stopLoss)}
        </div>

      </div>
    `;
  }

  function findContainer(ids) {
    return findElement(ids);
  }

  function renderSignals() {
    const containers = [
      findContainer([
        "signalsList",
        "signals",
        "signalList",
        "tradesList",
        "liveSignals"
      ])
    ].filter(Boolean);

    if (!containers.length) {
      return;
    }

    const html = state.signals.length
      ? state.signals.map(renderSignalCard).join("")
      : `
        <div class="empty-state">
          <div class="empty-icon">📊</div>
          <strong>لا توجد إشارة مؤكدة الآن</strong>
          <span>السوق تتم مراقبته بالبيانات المباشرة.</span>
        </div>
      `;

    containers.forEach((el) => {
      el.innerHTML = html;
    });
  }

  function renderResults() {
    const container = findContainer([
      "resultsList",
      "marketList",
      "coinsList",
      "scanResults",
      "results"
    ]);

    if (!container) {
      return;
    }

    if (!state.results.length) {
      container.innerHTML = `
        <div class="empty-state">
          لا توجد بيانات متاحة حاليًا.
        </div>
      `;

      return;
    }

    container.innerHTML = `
      <div class="market-header">
        <div>الأصل</div>
        <div>السعر</div>
        <div>الإشارة</div>
        <div>القوة</div>
        <div>الدخول</div>
        <div>الهدف</div>
        <div>الوقف</div>
      </div>

      ${state.results.map(renderResultRow).join("")}
    `;
  }

  function updateCounters() {
    const buys = state.results.filter(
      x => x.direction === "BUY"
    ).length;

    const sells = state.results.filter(
      x => x.direction === "SELL"
    ).length;

    const strong = state.results.filter(
      x =>
        x.signal === "شراء قوي" ||
        x.signal === "بيع قوي"
    ).length;

    setText(
      ["resultCount", "marketCount", "totalCount"],
      String(state.results.length)
    );

    setText(
      ["buyCount", "longCount"],
      String(buys)
    );

    setText(
      ["sellCount", "shortCount"],
      String(sells)
    );

    setText(
      ["strongCount", "strongSignals"],
      String(strong)
    );

    setText(
      ["signalCount", "liveSignalCount"],
      String(state.signals.length)
    );
  }

  function renderHeaderInfo(data) {
    setText(
      ["marketTitle", "currentMarket"],
      MARKET_NAMES[state.market] || state.market
    );

    setText(
      ["intervalText", "currentInterval"],
      state.interval
    );

    if (data && data.source) {
      setText(
        ["dataSource", "source"],
        data.source
      );
    }
  }

  function renderAll(data) {
    renderHeaderInfo(data);
    renderSignals();
    renderResults();
    updateCounters();
    setLastUpdate(data.updatedAt || Date.now());
  }

  async function checkServer() {
    try {
      const data = await api("/health");

      if (data.ok && data.online) {
        setStatus("متصل بالسيرفر و OKX", "online");
        return true;
      }

      setStatus("السيرفر غير متصل", "offline");
      return false;

    } catch (error) {
      console.error("Health error:", error);
      setStatus("تعذر الاتصال بالسيرفر", "error");
      return false;
    }
  }

  async function loadScan() {
    if (state.loading) {
      return;
    }

    state.loading = true;

    setStatus(
      "جاري جلب التحليل المباشر...",
      "loading"
    );

    try {
      const market = encodeURIComponent(
        state.market
      );

      const interval = encodeURIComponent(
        state.interval
      );

      const data = await api(
        `/api/scan?market=${market}&interval=${interval}`
      );

      state.results = Array.isArray(data.results)
        ? data.results
        : [];

      state.signals = Array.isArray(data.signals)
        ? data.signals
        : [];

      /*
       * لا نعرض أي صفقة مصطنعة.
       * الإشارات هنا تأتي فقط من API السيرفر.
       */

      renderAll(data);

      if (data.errors && data.errors.length) {
        console.warn(
          "Market data errors:",
          data.errors
        );
      }

      setStatus(
        `متصل — ${state.results.length} أصل`,
        "online"
      );

    } catch (error) {
      console.error("Scan error:", error);

      state.results = [];
      state.signals = [];

      renderSignals();
      renderResults();
      updateCounters();

      setStatus(
        `خطأ: ${error.message}`,
        "error"
      );

    } finally {
      state.loading = false;
    }
  }

  async function loadCryptoSignals() {
    if (state.market !== "crypto") {
      return;
    }

    try {
      const interval = encodeURIComponent(
        state.interval
      );

      const data = await api(
        `/api/signals?interval=${interval}`
      );

      if (Array.isArray(data.signals)) {
        state.signals = data.signals;
        renderSignals();
        updateCounters();
      }

    } catch (error) {
      console.warn(
        "Signals endpoint error:",
        error
      );
    }
  }

  async function loadAnalysis(symbol) {
    try {
      const interval = encodeURIComponent(
        state.interval
      );

      const encodedSymbol = encodeURIComponent(
        symbol
      );

      return await api(
        `/api/analysis/${encodedSymbol}?interval=${interval}`
      );

    } catch (error) {
      console.error(
        "Analysis error:",
        error
      );

      return null;
    }
  }

  function setMarket(market) {
    if (!market) {
      return;
    }

    state.market = market.toLowerCase();

    document
      .querySelectorAll("[data-market]")
      .forEach((button) => {
        button.classList.toggle(
          "active",
          button.dataset.market === state.market
        );
      });

    loadScan();
  }

  function setIntervalValue(interval) {
    if (!interval) {
      return;
    }

    const allowed = [
      "5m",
      "15m",
      "1h",
      "4h",
      "1d"
    ];

    if (!allowed.includes(interval)) {
      return;
    }

    state.interval = interval;

    document
      .querySelectorAll("[data-interval]")
      .forEach((button) => {
        button.classList.toggle(
          "active",
          button.dataset.interval === state.interval
        );
      });

    loadScan();
  }

  function bindButtons() {
    document
      .querySelectorAll("[data-market]")
      .forEach((button) => {
        button.addEventListener(
          "click",
          () => {
            setMarket(
              button.dataset.market
            );
          }
        );
      });

    document
      .querySelectorAll("[data-interval]")
      .forEach((button) => {
        button.addEventListener(
          "click",
          () => {
            setIntervalValue(
              button.dataset.interval
            );
          }
        );
      });

    const refreshButtons = [
      "refreshBtn",
      "refresh",
      "scanBtn",
      "reloadBtn"
    ];

    refreshButtons.forEach((id) => {
      const button = $(id);

      if (!button) {
        return;
      }

      button.addEventListener(
        "click",
        () => {
          loadScan();
        }
      );
    });
  }

  function autoRefresh() {
    /*
     * تحديث كل 20 ثانية.
     * السيرفر نفسه يستخدم Cache قصير لتخفيف الضغط
     * على مصدر البيانات.
     */

    setInterval(
      async () => {
        await loadScan();

        if (state.market === "crypto") {
          await loadCryptoSignals();
        }
      },
      20000
    );
  }

  async function start() {
    bindButtons();

    setStatus(
      "جاري الاتصال...",
      "loading"
    );

    const connected =
      await checkServer();

    if (!connected) {
      return;
    }

    await loadScan();

    if (state.market === "crypto") {
      await loadCryptoSignals();
    }

    autoRefresh();
  }

  /*
   * دعم الأزرار القديمة الموجودة في بعض نسخ الواجهة.
   */

  window.mudarib = {
    state,

    refresh: loadScan,

    scan: loadScan,

    setMarket,

    setInterval: setIntervalValue,

    analysis: loadAnalysis
  };

  if (
    document.readyState === "loading"
  ) {
    document.addEventListener(
      "DOMContentLoaded",
      start
    );
  } else {
    start();
  }

})();
