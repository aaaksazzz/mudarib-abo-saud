(() => {
  "use strict";

  /* =========================================================
     مضارب أبو سعود — Lightweight Live Signals
     متوافق مع index.html الخفيف
  ========================================================= */

  const $ = (id) => document.getElementById(id);

  const state = {
    interval: "15m",
    results: [],
    signals: [],
    sortField: "score",
    sortDir: -1,
    busy: false,
    lastUpdate: null
  };

  /* =========================================================
     HELPERS
  ========================================================= */

  function escapeHTML(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function number(value, digits = 4) {
    const n = Number(value);

    if (!Number.isFinite(n)) {
      return "-";
    }

    return n.toLocaleString("en-US", {
      minimumFractionDigits: 0,
      maximumFractionDigits: digits
    });
  }

  function percent(value) {
    const n = Number(value);

    if (!Number.isFinite(n)) {
      return "-";
    }

    return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
  }

  function signalType(item) {
    const s = String(
      item?.signal ??
      item?.direction ??
      item?.side ??
      ""
    ).toLowerCase();

    if (
      s.includes("buy") ||
      s.includes("شراء") ||
      s.includes("long")
    ) {
      return "buy";
    }

    if (
      s.includes("sell") ||
      s.includes("بيع") ||
      s.includes("short")
    ) {
      return "sell";
    }

    return "neutral";
  }

  function signalText(type, original) {
    if (type === "buy") return "شراء";
    if (type === "sell") return "بيع";

    return original || "محايد";
  }

  function getScore(item) {
    const candidates = [
      item?.score,
      item?.score10,
      item?.strength,
      item?.confidence
    ];

    for (const value of candidates) {
      const n = Number(value);
      if (Number.isFinite(n)) {
        return n;
      }
    }

    return 0;
  }

  function getSymbol(item) {
    return (
      item?.symbol ||
      item?.ticker ||
      item?.pair ||
      item?.name ||
      "-"
    );
  }

  function getMarket(item) {
    return (
      item?.market ||
      item?.category ||
      item?.type ||
      item?.exchange ||
      ""
    );
  }

  function getPrice(item) {
    return (
      item?.price ??
      item?.last_price ??
      item?.last ??
      item?.close ??
      item?.entry
    );
  }

  function getEntry(item) {
    return item?.entry ?? getPrice(item);
  }

  function getTP(item) {
    return (
      item?.tp1 ??
      item?.tp ??
      item?.target ??
      item?.take_profit ??
      item?.target1
    );
  }

  function getSL(item) {
    return (
      item?.sl ??
      item?.stop ??
      item?.stop_loss
    );
  }

  function getTimeframe(item) {
    return (
      item?.timeframe ||
      item?.interval ||
      state.interval
    );
  }

  function getTime(item) {
    return (
      item?.time ||
      item?.timestamp ||
      item?.updated_at ||
      item?.date ||
      ""
    );
  }

  function normalizeItem(item) {
    if (!item || typeof item !== "object") {
      return null;
    }

    const type = signalType(item);

    return {
      ...item,
      symbol: getSymbol(item),
      market: getMarket(item),
      price: getPrice(item),
      entry: getEntry(item),
      tp1: getTP(item),
      sl: getSL(item),
      score: getScore(item),
      timeframe: getTimeframe(item),
      time: getTime(item),
      _type: type
    };
  }

  /* =========================================================
     SIGNAL CARD
  ========================================================= */

  window.renderSignalCard = function (raw) {
    const item = normalizeItem(raw);

    if (!item) {
      return "";
    }

    const type = item._type;
    const originalSignal =
      item.signal ||
      item.direction ||
      item.side ||
      "";

    const signal = signalText(type, originalSignal);

    const symbol = escapeHTML(item.symbol);
    const market = escapeHTML(item.market || "السوق");
    const timeframe = escapeHTML(item.timeframe);

    const price = number(item.price, 8);
    const entry = number(item.entry, 8);
    const tp = number(item.tp1, 8);
    const sl = number(item.sl, 8);
    const score = number(item.score, 1);

    const time = escapeHTML(
      item.time
        ? String(item.time).replace("T", " ").slice(0, 19)
        : "مباشر"
    );

    return `
      <article class="signal-card ${type}">
        <div class="signal-top">
          <div>
            <div class="signal-symbol">${symbol}</div>
            <div class="signal-market">${market}</div>
          </div>

          <div class="signal-badge ${type}">
            ${escapeHTML(signal)}
          </div>
        </div>

        <div class="signal-price">
          <span>السعر الحالي</span>
          <strong>${price}</strong>
        </div>

        <div class="signal-levels">
          <div class="level entry">
            <span>الدخول</span>
            <strong>${entry}</strong>
          </div>

          <div class="level tp">
            <span>الهدف</span>
            <strong>${tp}</strong>
          </div>

          <div class="level sl">
            <span>الوقف</span>
            <strong>${sl}</strong>
          </div>
        </div>

        <div class="signal-bottom">
          <span>${timeframe}</span>
          <span class="score">قوة ${score}</span>
          <span>${time}</span>
        </div>
      </article>
    `;
  };

  /* =========================================================
     MARKET SIGNALS
  ========================================================= */

  window.renderMarketSignals = function (containerId, items) {
    const container = $(containerId);

    if (!container) {
      return;
    }

    if (!Array.isArray(items) || !items.length) {
      container.innerHTML = `
        <div class="empty">
          <strong>ما فيه إشارات حالياً</strong>
          ننتظر ظهور فرصة مطابقة لشروط التحليل.
        </div>
      `;
      return;
    }

    container.innerHTML = items
      .slice(0, 30)
      .map(window.renderSignalCard)
      .join("");
  };

  /* =========================================================
     MARKET DETECTION
  ========================================================= */

  function marketMatches(item, type) {
    const value = (
      `${item.market || ""} ${item.category || ""} ${item.type || ""} ${item.symbol || ""}`
    ).toLowerCase();

    if (type === "saudi") {
      return (
        value.includes("saudi") ||
        value.includes("ksa") ||
        value.includes("tasi") ||
        value.includes("سعود") ||
        value.includes("تاسي")
      );
    }

    if (type === "forex") {
      return (
        value.includes("forex") ||
        value.includes("fx") ||
        value.includes("فوركس") ||
        /^[a-z]{6}$/.test(String(item.symbol || "").replace("/", ""))
      );
    }

    if (type === "crypto") {
      return (
        value.includes("crypto") ||
        value.includes("cryptocurrency") ||
        value.includes("كريبتو") ||
        value.includes("عملات رقمية") ||
        String(item.symbol || "").toUpperCase().endsWith("USDT")
      );
    }

    if (type === "us") {
      return (
        value.includes("us") ||
        value.includes("usa") ||
        value.includes("america") ||
        value.includes("أمريكا") ||
        value.includes("امريكا") ||
        value.includes("nasdaq") ||
        value.includes("nyse")
      );
    }

    if (type === "commodities") {
      return (
        value.includes("gold") ||
        value.includes("oil") ||
        value.includes("commodity") ||
        value.includes("commodities") ||
        value.includes("ذهب") ||
        value.includes("نفط")
      );
    }

    if (type === "indices") {
      return (
        value.includes("index") ||
        value.includes("indices") ||
        value.includes("مؤشر") ||
        value.includes("spx") ||
        value.includes("nasdaq") ||
        value.includes("dow") ||
        value.includes("dax") ||
        value.includes("ftse")
      );
    }

    if (type === "futures") {
      return (
        value.includes("future") ||
        value.includes("futures") ||
        value.includes("فيوتشر") ||
        value.includes("عقود")
      );
    }

    return false;
  }

  /* =========================================================
     LIVE SIGNAL UPDATE
  ========================================================= */

  window.updateLiveSignals = function (data) {
    let items = [];

    if (Array.isArray(data)) {
      items = data;
    } else if (data && typeof data === "object") {
      items =
        data.signals ||
        data.results ||
        data.trades ||
        data.data ||
        [];
    }

    if (!Array.isArray(items)) {
      items = [];
    }

    state.signals = items
      .map(normalizeItem)
      .filter(Boolean);

    state.results = [...state.signals];
    state.lastUpdate = new Date();

    renderAll();
  };

  /* =========================================================
     RENDER ALL
  ========================================================= */

  function renderAll() {
    const items = state.signals;

    const buyCount = items.filter(
      x => x._type === "buy"
    ).length;

    const sellCount = items.filter(
      x => x._type === "sell"
    ).length;

    const countEl = $("liveSignalsCount");
    const buyEl = $("liveBuyCount");
    const sellEl = $("liveSellCount");
    const updateEl = $("liveLastUpdate");

    if (countEl) {
      countEl.textContent = items.length;
    }

    if (buyEl) {
      buyEl.textContent = buyCount;
    }

    if (sellEl) {
      sellEl.textContent = sellCount;
    }

    if (updateEl) {
      updateEl.textContent = state.lastUpdate
        ? state.lastUpdate.toLocaleTimeString("ar-SA")
        : "-";
    }

    renderTopSignals(items);
    renderMarket("saudi", "saudiSignals");
    renderMarket("forex", "forexSignals");
    renderMarket("crypto", "cryptoSignals");
    renderMarket("us", "usSignals");
    renderMarket("commodities", "commoditiesSignals");
    renderMarket("indices", "indicesSignals");
    renderMarket("futures", "futuresSignals");

    renderRecent(items);
    renderScanner(items);
  }

  function renderTopSignals(items) {
    const container = $("topSignals");

    if (!container) {
      return;
    }

    const sorted = [...items]
      .sort((a, b) => getScore(b) - getScore(a))
      .slice(0, 6);

    if (!sorted.length) {
      container.innerHTML = `
        <div class="empty">
          <strong>بانتظار الإشارات المباشرة</strong>
          النظام يعرض الفرص عند وصول بيانات السوق وتحقيق شروط التحليل.
        </div>
      `;
      return;
    }

    container.innerHTML = sorted
      .map(window.renderSignalCard)
      .join("");
  }

  function renderMarket(type, containerId) {
    const items = state.signals.filter(
      item => marketMatches(item, type)
    );

    window.renderMarketSignals(
      containerId,
      items
    );
  }

  function renderRecent(items) {
    const container = $("recentList");

    if (!container) {
      return;
    }

    const recent = [...items]
      .sort((a, b) => {
        const ta = Date.parse(a.time || "") || 0;
        const tb = Date.parse(b.time || "") || 0;
        return tb - ta;
      })
      .slice(0, 20);

    if (!recent.length) {
      container.innerHTML = `
        <div class="empty">
          <strong>لا توجد صفقات حديثة</strong>
          ستظهر هنا آخر الإشارات التي وصلت من السيرفر.
        </div>
      `;
      return;
    }

    container.innerHTML = recent
      .map(window.renderSignalCard)
      .join("");
  }

  /* =========================================================
     SCANNER
  ========================================================= */

  function renderScanner(items = state.results) {
    const body = $("scannerBody");

    if (!body) {
      return;
    }

    const search = (
      $("scannerSearch")?.value || ""
    ).trim().toUpperCase();

    let list = [...items];

    if (search) {
      list = list.filter(item =>
        String(item.symbol || "")
          .toUpperCase()
          .includes(search)
      );
    }

    const field =
      $("sortField")?.value ||
      state.sortField;

    list.sort((a, b) => {
      let av;
      let bv;

      if (field === "change") {
        av = Number(
          a.change ??
          a.change24h ??
          a.percent ??
          0
        );

        bv = Number(
          b.change ??
          b.change24h ??
          b.percent ??
          0
        );
      } else if (field === "price") {
        av = Number(a.price || 0);
        bv = Number(b.price || 0);
      } else {
        av = getScore(a);
        bv = getScore(b);
      }

      if (!Number.isFinite(av)) av = 0;
      if (!Number.isFinite(bv)) bv = 0;

      return (av - bv) * state.sortDir;
    });

    if (!list.length) {
      body.innerHTML = `
        <tr>
          <td colspan="7">
            <div class="empty">
              لا توجد نتائج حالياً
            </div>
          </td>
        </tr>
      `;
      return;
    }

    body.innerHTML = list
      .slice(0, 100)
      .map(item => {
        const type = item._type || signalType(item);
        const signal =
          type === "buy"
            ? "شراء"
            : type === "sell"
              ? "بيع"
              : "محايد";

        const cls =
          type === "buy"
            ? "buy-text"
            : type === "sell"
              ? "sell-text"
              : "neutral-text";

        const change = Number(
          item.change ??
          item.change24h ??
          item.percent
        );

        return `
          <tr>
            <td>
              <strong>${escapeHTML(item.symbol)}</strong>
            </td>

            <td>${escapeHTML(item.market || "-")}</td>

            <td>${number(item.price, 8)}</td>

            <td class="${cls}">
              ${signal}
            </td>

            <td class="${change >= 0 ? "buy-text" : "sell-text"}">
              ${percent(change)}
            </td>

            <td>
              ${number(item.score, 1)}
            </td>

            <td>
              ${escapeHTML(item.timeframe || state.interval)}
            </td>
          </tr>
        `;
      })
      .join("");
  }

  /* =========================================================
     SCAN BUTTON
  ========================================================= */

  async function runScanner() {
    if (state.busy) {
      return;
    }

    state.busy = true;

    const button = $("scanBtn");
    const status = $("scannerStatus");

    if (button) {
      button.disabled = true;
      button.textContent = "جاري التحليل...";
    }

    if (status) {
      status.innerHTML =
        `<span class="loading">جاري جلب البيانات وتحليل السوق...</span>`;
    }

    try {
      const urls = [
        `/api/scan?interval=${encodeURIComponent(state.interval)}`,
        `/api/signals?interval=${encodeURIComponent(state.interval)}`,
        `/api/market-signals?interval=${encodeURIComponent(state.interval)}`
      ];

      let response = null;

      for (const url of urls) {
        try {
          const r = await fetch(url, {
            method: "GET",
            cache: "no-store",
            headers: {
              "Accept": "application/json"
            }
          });

          if (r.ok) {
            response = r;
            break;
          }
        } catch (_) {
          // جرّب المصدر التالي
        }
      }

      if (!response) {
        throw new Error("API unavailable");
      }

      const data = await response.json();

      window.updateLiveSignals(data);

      if (status) {
        status.textContent =
          `تم تحديث التحليل ${new Date().toLocaleTimeString("ar-SA")}`;
      }
    } catch (error) {
      if (status) {
        status.textContent =
          "تعذر جلب الإشارات من السيرفر حالياً.";
      }
    } finally {
      state.busy = false;

      if (button) {
        button.disabled = false;
        button.textContent = "تحديث التحليل";
      }
    }
  }

  /* =========================================================
     INTERVAL BUTTONS
  ========================================================= */

  function setupIntervals() {
    const box = $("intervalChips");

    if (!box) {
      return;
    }

    const buttons = box.querySelectorAll("button");

    buttons.forEach(button => {
      button.addEventListener("click", () => {
        buttons.forEach(x =>
          x.classList.remove("active")
        );

        button.classList.add("active");

        state.interval =
          button.dataset.interval ||
          button.textContent.trim() ||
          "15m";

        runScanner();
      });
    });
  }

  /* =========================================================
     SEARCH
  ========================================================= */

  function setupSearch() {
    const input = $("scannerSearch");

    if (!input) {
      return;
    }

    input.addEventListener("input", () => {
      renderScanner();
    });
  }

  /* =========================================================
     SORT
  ========================================================= */

  function setupSort() {
    const select = $("sortField");

    if (select) {
      select.addEventListener("change", () => {
        state.sortField = select.value;
        renderScanner();
      });
    }

    const dir = $("sortDir");

    if (dir) {
      dir.addEventListener("click", () => {
        state.sortDir *= -1;

        dir.textContent =
          state.sortDir === -1
            ? "↓"
            : "↑";

        renderScanner();
      });
    }
  }

  /* =========================================================
     NEWS
  ========================================================= */

  async function loadNews() {
    const container = $("newsList");

    if (!container) {
      return;
    }

    const button = $("newsBtn");

    if (button) {
      button.disabled = true;
    }

    container.innerHTML = `
      <div class="empty">
        <span class="loading">جاري جلب الأخبار...</span>
      </div>
    `;

    try {
      const response = await fetch(
        "/api/news",
        {
          cache: "no-store",
          headers: {
            "Accept": "application/json"
          }
        }
      );

      if (!response.ok) {
        throw new Error("news error");
      }

      const data = await response.json();

      const news =
        Array.isArray(data)
          ? data
          : (
              data.news ||
              data.items ||
              data.results ||
              []
            );

      if (!news.length) {
        throw new Error("empty news");
      }

      container.innerHTML = news
        .slice(0, 30)
        .map(item => {
          const title =
            item.title ||
            item.headline ||
            item.name ||
            "خبر";

          const source =
            item.source ||
            item.publisher ||
            "";

          const time =
            item.time ||
            item.date ||
            item.published_at ||
            "";

          return `
            <article class="news-item">
              <strong>
                ${escapeHTML(title)}
              </strong>

              <span>
                ${escapeHTML(source)}
                ${source && time ? " • " : ""}
                ${escapeHTML(time)}
              </span>
            </article>
          `;
        })
        .join("");
    } catch (_) {
      container.innerHTML = `
        <div class="empty">
          <strong>الأخبار غير متاحة حالياً</strong>
          قسم الإشارات لا يعتمد على الأخبار.
        </div>
      `;
    } finally {
      if (button) {
        button.disabled = false;
      }
    }
  }

  /* =========================================================
     NAVIGATION
  ========================================================= */

  window.openSection = function (id) {
    document
      .querySelectorAll(".section")
      .forEach(section => {
        section.classList.remove("active");
      });

    const target = $(id);

    if (target) {
      target.classList.add("active");
    }

    document
      .querySelectorAll(".nav button")
      .forEach(button => {
        button.classList.remove("active");

        if (
          button.dataset.section === id ||
          button.getAttribute("onclick")?.includes(id)
        ) {
          button.classList.add("active");
        }
      });

    localStorage.setItem(
      "mudarib_last_section",
      id
    );
  };

  function setupNavigation() {
    document
      .querySelectorAll(".nav button")
      .forEach(button => {
        button.addEventListener("click", () => {
          const section =
            button.dataset.section;

          if (section) {
            window.openSection(section);
          }
        });
      });
  }

  /* =========================================================
     HOME MARKET BUTTONS
  ========================================================= */

  function setupMarketButtons() {
    document
      .querySelectorAll("[data-open-section]")
      .forEach(button => {
        button.addEventListener("click", () => {
          const id =
            button.dataset.openSection;

          if (id) {
            window.openSection(id);
          }
        });
      });
  }

  /* =========================================================
     EVENT FROM SERVER / OTHER JS
  ========================================================= */

  window.addEventListener(
    "mudarib:signals",
    event => {
      window.updateLiveSignals(
        event.detail
      );
    }
  );

  /* =========================================================
     AUTO REFRESH
  ========================================================= */

  function startAutoRefresh() {
    /*
      تحديث كل 60 ثانية.
      السيرفر هو المسؤول عن البيانات الحقيقية.
    */

    setInterval(() => {
      runScanner();
    }, 60000);
  }

  /* =========================================================
     SYSTEM STATUS
  ========================================================= */

  function setSystemStatus() {
    const status =
      document.querySelector(
        ".system-status"
      );

    if (status) {
      status.textContent =
        "● مباشر";
    }
  }

  /* =========================================================
     INIT
  ========================================================= */

  async function init() {
    setSystemStatus();

    setupNavigation();
    setupMarketButtons();
    setupIntervals();
    setupSearch();
    setupSort();

    const scanButton = $("scanBtn");

    if (scanButton) {
      scanButton.addEventListener(
        "click",
        runScanner
      );
    }

    const newsButton = $("newsBtn");

    if (newsButton) {
      newsButton.addEventListener(
        "click",
        loadNews
      );
    }

    const savedSection =
      localStorage.getItem(
        "mudarib_last_section"
      );

    if (
      savedSection &&
      $(savedSection)
    ) {
      window.openSection(savedSection);
    } else {
      window.openSection("dashboard");
    }

    /*
      أول جلب مباشر عند فتح الموقع
    */
    await runScanner();

    startAutoRefresh();
  }

  if (
    document.readyState === "loading"
  ) {
    document.addEventListener(
      "DOMContentLoaded",
      init
    );
  } else {
    init();
  }

})();
