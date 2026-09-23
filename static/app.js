(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const qs = (sel) => document.querySelector(sel);
  const qsa = (sel) => [...document.querySelectorAll(sel)];

  const state = {
    market: "crypto",
    interval: "15m",
    results: [],
    signals: [],
    loading: false,
    lastUpdated: null,
    sortField: "change",
    sortDesc: true,
    signalFilter: null,
    search: "",
    cryptoSymbols: [],
    recent: JSON.parse(
      localStorage.getItem("mudarib_recent") || "[]"
    )
  };

  const marketNames = {
    dashboard: "الرئيسية",
    scanner: "ماسح الفرص",
    recent: "الصفقات",
    saudi: "السوق السعودي",
    forex: "الفوركس",
    crypto: "العملات الرقمية",
    usmarket: "الأسهم الأمريكية",
    commodities: "الذهب والنفط",
    indices: "المؤشرات العالمية",
    futures: "الفيوتشرز",
    news: "الأخبار",
    subscription: "الاشتراك"
  };

  const marketContainers = {
    saudi: "saudiSignals",
    forex: "forexSignals",
    crypto: "cryptoSignals",
    usmarket: "usSignals",
    commodities: "commoditiesSignals",
    indices: "indicesSignals",
    futures: "futuresSignals"
  };

  const marketLabels = {
    saudi: "السعودي",
    forex: "الفوركس",
    crypto: "العملات الرقمية",
    usmarket: "الأمريكي",
    commodities: "الذهب والنفط",
    indices: "المؤشرات",
    futures: "الفيوتشرز"
  };

  /*
   * الفريمات حسب السوق
   */
  const MARKET_INTERVALS = {
    crypto: ["15m", "1h", "4h", "1d"],
    saudi: ["15m", "1h", "4h", "1d"],
    usmarket: ["15m", "1h", "4h", "1d"],
    forex: ["15m", "1h", "4h", "1d"]
  };

  /*
   * مسارات الفاحص الحقيقية الموجودة في server.py
   */
  const SCANNER_ENDPOINTS = {
    crypto: "/api/okx/scan",
    saudi: "/api/saudi/scan",
    usmarket: "/api/usmarket/signals",
    forex: "/api/forex/signals"
  };

  /* =========================================================
     حماية النصوص
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
     الأرقام
  ========================================================= */

  function num(value, digits = 4) {
    const n = Number(value);

    if (!Number.isFinite(n)) {
      return "—";
    }

    if (Math.abs(n) >= 1000000) {
      return n.toLocaleString("en-US", {
        maximumFractionDigits: 2
      });
    }

    if (Math.abs(n) >= 1000) {
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

  function percent(value, digits = 2) {
    const n = Number(value);

    if (!Number.isFinite(n)) {
      return "—";
    }

    return `${n.toFixed(digits)}%`;
  }

  function formatVolume(value) {
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

    return num(n, 0);
  }

  function formatTime(value) {
    if (!value) {
      return "الآن";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
      return String(value);
    }

    return date.toLocaleTimeString("ar-SA", {
      hour: "2-digit",
      minute: "2-digit"
    });
  }

  /* =========================================================
     قراءة البيانات
  ========================================================= */

  function getSymbol(item) {
    return (
      item?.symbol ||
      item?.name ||
      item?.ticker ||
      "—"
    );
  }

  function getPrice(item) {
    return (
      item?.price ??
      item?.last ??
      item?.close ??
      item?.entry
    );
  }

  function getEntry(item) {
    return (
      item?.entry ??
      getPrice(item)
    );
  }

  function getTP(item) {
    return (
      item?.takeProfit ??
      item?.target ??
      item?.tp ??
      item?.tp1
    );
  }

  function getSL(item) {
    return (
      item?.stopLoss ??
      item?.stop ??
      item?.sl
    );
  }

  function getSignal(item) {
    return String(
      item?.signal ||
      item?.direction ||
      "حيادي"
    );
  }

  function getScore(item) {
    const raw =
      item?.score ??
      item?.score10 ??
      0;

    const n = Number(raw);

    return Number.isFinite(n) ? n : 0;
  }

  function getChange(item) {
    const value =
      item?.change24h ??
      item?.change ??
      item?.changePercent ??
      item?.percentChange ??
      item?.candleChange ??
      0;

    const n = Number(value);

    return Number.isFinite(n) ? n : 0;
  }

  function getVolume(item) {
    const value =
      item?.volume_usdt ??
      item?.volume ??
      item?.volCcy24h ??
      item?.volume24h ??
      0;

    const n = Number(value);

    return Number.isFinite(n) ? n : 0;
  }

  function getInterval(item) {
    return (
      item?.interval ||
      item?.timeframe ||
      state.interval
    );
  }

  function getTime(item) {
    return (
      item?.updatedAt ||
      item?.updated_at ||
      item?.time ||
      Date.now()
    );
  }

  function isSignal(item) {
    const signal = getSignal(item);

    return (
      signal.includes("شراء") ||
      signal.includes("بيع") ||
      signal.toUpperCase().includes("BUY") ||
      signal.toUpperCase().includes("SELL")
    );
  }

  function signalClass(signal) {
    const s = String(signal || "");

    if (
      s.includes("شراء") ||
      s.toUpperCase().includes("BUY")
    ) {
      return "signal-buy";
    }

    if (
      s.includes("بيع") ||
      s.toUpperCase().includes("SELL")
    ) {
      return "signal-sell";
    }

    return "signal-neutral";
  }

  function signalIcon(signal) {
    const s = String(signal || "");

    if (s.includes("شراء")) {
      return "🟢";
    }

    if (s.includes("بيع")) {
      return "🔴";
    }

    if (s.toUpperCase().includes("BUY")) {
      return "🟢";
    }

    if (s.toUpperCase().includes("SELL")) {
      return "🔴";
    }

    return "⚪";
  }

  /* =========================================================
     حالة الاتصال
  ========================================================= */

  function setStatus(text) {
    const el = $("systemStatus");

    if (el) {
      el.textContent = text;
    }
  }

  /* =========================================================
     API
  ========================================================= */

  async function api(url) {
    const response = await fetch(url, {
      method: "GET",
      cache: "no-store",
      headers: {
        Accept: "application/json"
      }
    });

    let data;

    try {
      data = await response.json();
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

    if (data?.ok === false) {
      throw new Error(
        data?.error ||
        data?.message ||
        "تعذر الحصول على البيانات"
      );
    }

    return data;
  }

  /* =========================================================
     التنقل
  ========================================================= */

  function openSection(id) {
    qsa(".section").forEach((section) => {
      section.classList.toggle(
        "active",
        section.id === id
      );
    });

    qsa(".nav-item[data-section]").forEach((button) => {
      button.classList.toggle(
        "active",
        button.dataset.section === id
      );
    });

    const title = $("pageTitle");

    if (title) {
      title.textContent =
        marketNames[id] || id;
    }

    localStorage.setItem(
      "mudarib_last_market",
      id
    );

    if (marketContainers[id]) {
      state.market = id;
      loadMarket(id);
    }

    if (id === "scanner") {
      loadScanner();
    }

    if (id === "recent") {
      renderRecent();
    }

    if (id === "news") {
      renderNews();
    }
  }

  function setupNavigation() {
    qsa(".nav-item[data-section]").forEach((button) => {
      button.addEventListener("click", () => {
        openSection(button.dataset.section);

        const sidebar = $("sidebar");

        if (
          sidebar &&
          window.innerWidth <= 700
        ) {
          sidebar.classList.remove("open");
        }
      });
    });

    const menu = $("menuBtn");

    if (menu) {
      menu.addEventListener("click", () => {
        const sidebar = $("sidebar");

        if (sidebar) {
          sidebar.classList.toggle("open");
        }
      });
    }
  }

  /* =========================================================
     الوضع الليلي
  ========================================================= */

  function setupTheme() {
    const button = $("themeBtn");

    const saved =
      localStorage.getItem("mudarib_theme");

    if (saved === "dark") {
      document.body.classList.add("dark");
    }

    updateThemeButton();

    if (button) {
      button.addEventListener("click", () => {
        document.body.classList.toggle("dark");

        localStorage.setItem(
          "mudarib_theme",
          document.body.classList.contains("dark")
            ? "dark"
            : "light"
        );

        updateThemeButton();
      });
    }
  }

  function updateThemeButton() {
    const button = $("themeBtn");

    if (!button) {
      return;
    }

    button.textContent =
      document.body.classList.contains("dark")
        ? "☀️ الوضع النهاري"
        : "🌙 الوضع الليلي";
  }

  /* =========================================================
     بطاقة الإشارة
  ========================================================= */

  function renderCard(item) {
    const symbol = escapeHTML(
      getSymbol(item)
    );

    const signal =
      getSignal(item);

    const safeSignal =
      escapeHTML(signal);

    const price =
      getPrice(item);

    const entry =
      getEntry(item);

    const tp =
      getTP(item);

    const sl =
      getSL(item);

    const score =
      getScore(item);

    const rsi =
      item?.rsi != null
        ? num(item.rsi, 1)
        : "—";

    const trend =
      item?.trend || "—";

    const volumeRatio =
      item?.volumeRatio != null
        ? `${num(item.volumeRatio, 2)}x`
        : "—";

    const change =
      getChange(item);

    const interval =
      getInterval(item);

    const source =
      item?.source || "";

    const cls =
      signalClass(signal);

    return `
      <div class="signal-card ${cls}">

        <div class="signal-card-header">

          <div class="signal-symbol">
            ${signalIcon(signal)}
            <strong>${symbol}</strong>
          </div>

          <span class="signal-badge ${cls}">
            ${safeSignal}
          </span>

        </div>

        <div class="signal-price">
          ${num(price)}
        </div>

        <div class="signal-grid">

          <div class="signal-item">
            <span>الدخول</span>
            <strong>${num(entry)}</strong>
          </div>

          <div class="signal-item">
            <span>الهدف</span>
            <strong>${num(tp)}</strong>
          </div>

          <div class="signal-item">
            <span>وقف الخسارة</span>
            <strong>${num(sl)}</strong>
          </div>

          <div class="signal-item">
            <span>القوة</span>
            <strong>${num(score, 1)}</strong>
          </div>

          <div class="signal-item">
            <span>RSI</span>
            <strong>${rsi}</strong>
          </div>

          <div class="signal-item">
            <span>الاتجاه</span>
            <strong>${escapeHTML(trend)}</strong>
          </div>

        </div>

        <div class="signal-footer">

          <span>
            ${escapeHTML(interval)}
          </span>

          <span>
            ${percent(change)}
          </span>

          <span>
            حجم ${volumeRatio}
          </span>

          ${
            source
              ? `<span>${escapeHTML(source)}</span>`
              : ""
          }

        </div>

      </div>
    `;
  }

  /* =========================================================
     عرض الإشارات
  ========================================================= */

  function renderSignals(
    containerId,
    items,
    emptyText
  ) {
    const box =
      $(containerId);

    if (!box) {
      return;
    }

    if (
      !Array.isArray(items) ||
      items.length === 0
    ) {
      box.innerHTML = `
        <div class="empty-state">
          ${escapeHTML(
            emptyText ||
            "ما فيه فرصة مطابقة حالياً — مستمرين بالمراقبة."
          )}
        </div>
      `;

      return;
    }

    box.innerHTML =
      items
        .map(renderCard)
        .join("");
  }

  /* =========================================================
     الرئيسية
  ========================================================= */

  function updateDashboard(data) {
    const all =
      Array.isArray(data)
        ? data
        : (
            data?.signals ||
            data?.results ||
            []
          );

    const signals =
      all.filter(isSignal);

    const buys =
      signals.filter((item) =>
        getSignal(item).includes("شراء") ||
        getSignal(item).toUpperCase().includes("BUY")
      );

    const sells =
      signals.filter((item) =>
        getSignal(item).includes("بيع") ||
        getSignal(item).toUpperCase().includes("SELL")
      );

    const count =
      $("liveSignalsCount");

    const buy =
      $("liveBuyCount");

    const sell =
      $("liveSellCount");

    const update =
      $("liveLastUpdate");

    if (count) {
      count.textContent =
        signals.length;
    }

    if (buy) {
      buy.textContent =
        buys.length;
    }

    if (sell) {
      sell.textContent =
        sells.length;
    }

    if (update) {
      update.textContent =
        new Date().toLocaleTimeString(
          "ar-SA",
          {
            hour: "2-digit",
            minute: "2-digit"
          }
        );
    }

    const top =
      [...signals]
        .sort(
          (a, b) =>
            getScore(b) -
            getScore(a)
        )
        .slice(0, 6);

    renderSignals(
      "topSignals",
      top,
      "جاري البحث عن أقوى الفرص..."
    );

    const strong =
      signals.filter((item) => {
        const signal =
          getSignal(item);

        return (
          signal === "شراء قوي" ||
          signal === "بيع قوي"
        );
      });

    if (strong.length) {
      addRecent(strong);
    }
  }

  /* =========================================================
     تحديد API الفاحص
  ========================================================= */

  function getScannerEndpoint(market) {
    return (
      SCANNER_ENDPOINTS[market] ||
      SCANNER_ENDPOINTS.crypto
    );
  }

  /* =========================================================
     الفريمات حسب السوق
  ========================================================= */

  function updateScannerIntervals() {
    const market =
      $("scannerMarket")?.value ||
      state.market ||
      "crypto";

    const allowed =
      MARKET_INTERVALS[market] ||
      MARKET_INTERVALS.crypto;

    /*
     * إذا الفريم الحالي غير مناسب للسوق
     * نختار أول فريم مناسب.
     */
    if (!allowed.includes(state.interval)) {
      state.interval =
        market === "forex"
          ? "1h"
          : market === "saudi"
            ? "1d"
            : market === "usmarket"
              ? "1d"
              : "15m";
    }

    qsa(
      "#intervalChips [data-interval]"
    ).forEach((button) => {
      const interval =
        button.dataset.interval;

      const enabled =
        allowed.includes(interval);

      button.disabled = !enabled;

      button.classList.toggle(
        "active",
        enabled &&
        interval === state.interval
      );

      if (!enabled) {
        button.title =
          "هذا الفريم غير متاح لهذا السوق";
      } else {
        button.title = "";
      }
    });
  }

  /* =========================================================
     الماسح
  ========================================================= */

  async function loadScanner() {
    if (state.loading) {
      return;
    }

    /*
     * نقرأ السوق من select مباشرة.
     */
    const selectedMarket =
      $("scannerMarket")?.value ||
      state.market ||
      "crypto";

    state.market =
      selectedMarket;

    updateScannerIntervals();

    state.loading = true;

    const status =
      $("scannerStatus");

    const button =
      $("scanBtn");

    const endpoint =
      getScannerEndpoint(
        state.market
      );

    if (status) {
      status.textContent =
        `جاري فحص ${marketLabels[state.market] || state.market} على ${state.interval}...`;
    }

    if (button) {
      button.disabled = true;
      button.textContent =
        "⏳ جاري الفحص";
    }

    try {
      const url =
        `${endpoint}?interval=${encodeURIComponent(
          state.interval
        )}`;

      console.log(
        "Scanner request:",
        url
      );

      const data =
        await api(url);

      /*
       * كل APIs الحالية ترجع results.
       * نضيف دعم signals احتياطياً.
       */
      state.results =
        Array.isArray(data?.results)
          ? data.results
          : Array.isArray(data?.signals)
            ? data.signals
            : Array.isArray(data)
              ? data
              : [];

      state.signals =
        Array.isArray(data?.signals)
          ? data.signals
          : state.results.filter(
              isSignal
            );

      /*
       * بعض APIs مثل US/Forex/Saudi
       * لا ترجع updatedAt.
       */
      state.lastUpdated =
        data?.updatedAt ||
        Date.now();

      renderScanner();

      /*
       * لا نغيّر بيانات لوحة الرئيسية
       * إلا إذا كان السوق عملات رقمية.
       */
      if (state.market === "crypto") {
        updateDashboard({
          results:
            state.results,
          signals:
            state.signals
        });
      }

      if (status) {
        const analyzed =
          data?.analyzedCount ??
          data?.count ??
          state.results.length;

        const total =
          data?.allSymbols ??
          data?.total ??
          data?.count ??
          analyzed;

        status.textContent =
          `🇦🇪 ${marketLabels[state.market] || state.market} • ` +
          `تم تحليل ${analyzed} من ${total} أصل • ` +
          `${state.signals.length} إشارة • ` +
          `${formatTime(
            state.lastUpdated
          )}`;
      }

      setStatus(
        `● ${
          marketLabels[state.market] ||
          state.market
        } مباشر • ${formatTime(
          state.lastUpdated
        )}`
      );

    } catch (error) {
      console.error(
        "Scanner error:",
        error
      );

      state.results = [];
      state.signals = [];

      renderScanner();

      if (status) {
        status.textContent =
          `❌ ${error.message}`;
      }

      setStatus(
        "● تعذر تحديث بيانات الفاحص"
      );

    } finally {
      state.loading = false;

      if (button) {
        button.disabled = false;
        button.textContent =
          "🔄 تحديث";
      }
    }
  }

  function filteredResults() {
    let items =
      [...state.results];

    const search =
      state.search
        .trim()
        .toLowerCase();

    if (search) {
      items =
        items.filter((item) =>
          String(
            getSymbol(item)
          )
            .toLowerCase()
            .includes(search)
        );
    }

    if (state.signalFilter) {
      items =
        items.filter(
          (item) =>
            getSignal(item) ===
            state.signalFilter
        );
    }

    items.sort((a, b) => {
      let av;
      let bv;

      switch (state.sortField) {

        case "score":
          av = getScore(a);
          bv = getScore(b);
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
          av = getVolume(a);
          bv = getVolume(b);
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
          av = getChange(a);
          bv = getChange(b);
          break;
      }

      return state.sortDesc
        ? bv - av
        : av - bv;
    });

    return items;
  }

  function renderScanner() {
    const body =
      $("scannerBody");

    if (!body) {
      return;
    }

    const items =
      filteredResults();

    if (!items.length) {
      body.innerHTML = `
        <tr>
          <td colspan="7">
            لا توجد نتائج مطابقة.
          </td>
        </tr>
      `;

      return;
    }

    body.innerHTML =
      items
        .map((item) => {

          const symbol =
            escapeHTML(
              getSymbol(item)
            );

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

          const interval =
            getInterval(item);

          const cls =
            signalClass(signal);

          return `
            <tr>

              <td>
                <strong>
                  ${signalIcon(signal)}
                  ${symbol}
                </strong>
              </td>

              <td>
                ${num(price)}
              </td>

              <td>
                <span class="${cls}">
                  ${percent(change)}
                </span>
              </td>

              <td>
                <span class="signal-badge ${cls}">
                  ${escapeHTML(signal)}
                </span>
              </td>

              <td>
                ${num(score, 1)}
              </td>

              <td>
                ${formatVolume(volume)}
              </td>

              <td>
                ${escapeHTML(interval)}
              </td>

            </tr>
          `;
        })
        .join("");
  }

  function setupScanner() {
    const scanBtn =
      $("scanBtn");

    if (scanBtn) {
      scanBtn.addEventListener(
        "click",
        loadScanner
      );
    }

    /*
     * اختيار السوق
     */
    const scannerMarket =
      $("scannerMarket");

    if (scannerMarket) {
      scannerMarket.value =
        state.market;

      scannerMarket.addEventListener(
        "change",
        () => {

          state.market =
            scannerMarket.value ||
            "crypto";

          /*
           * عند تغيير السوق نمسح فلتر البحث
           * حتى لا يظل عالقاً من السوق السابق.
           */
          state.search = "";

          const search =
            $("scannerSearch");

          if (search) {
            search.value = "";
          }

          state.signalFilter =
            null;

          qsa(
            ".signal-chips [data-signal]"
          ).forEach((button) => {
            button.classList.remove(
              "active"
            );
          });

          /*
           * اختيار فريم مناسب للسوق.
           */
          if (state.market === "forex") {
            state.interval = "1h";
          } else if (
            state.market === "saudi"
          ) {
            state.interval = "1d";
          } else if (
            state.market === "usmarket"
          ) {
            state.interval = "1d";
          } else {
            state.interval = "15m";
          }

          updateScannerIntervals();

          /*
           * الفحص يتغير مباشرة.
           */
          loadScanner();
        }
      );
    }

    /*
     * الفريمات
     */
    qsa(
      "#intervalChips [data-interval]"
    ).forEach((button) => {

      const interval =
        button.dataset.interval;

      button.addEventListener(
        "click",
        () => {

          const market =
            $("scannerMarket")?.value ||
            state.market ||
            "crypto";

          const allowed =
            MARKET_INTERVALS[market] ||
            MARKET_INTERVALS.crypto;

          if (!allowed.includes(interval)) {
            return;
          }

          state.interval =
            interval;

          qsa(
            "#intervalChips [data-interval]"
          ).forEach((btn) => {
            btn.classList.toggle(
              "active",
              btn === button
            );
          });

          /*
           * الفحص يتغير مباشرة.
           */
          loadScanner();
        }
      );
    });

    /*
     * فلاتر الإشارة
     */
    qsa(
      ".signal-chips [data-signal]"
    ).forEach((button) => {

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
            ).forEach((btn) => {

              btn.classList.toggle(
                "active",
                btn === button
              );

            });
          }

          renderScanner();
        }
      );
    });

    /*
     * البحث
     */
    const search =
      $("scannerSearch");

    if (search) {

      search.addEventListener(
        "input",
        () => {

          state.search =
            search.value;

          renderScanner();
        }
      );
    }

    /*
     * الترتيب
     */
    const sortField =
      $("sortField");

    if (sortField) {

      sortField.addEventListener(
        "change",
        () => {

          state.sortField =
            sortField.value;

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

    updateScannerIntervals();
  }

  /* =========================================================
     الأسواق
  ========================================================= */

  async function loadMarket(market) {

    const container =
      marketContainers[market];

    if (!container) {
      return;
    }

    const box =
      $(container);

    if (box) {
      box.innerHTML = `
        <div class="empty-state">
          ⏳ جاري تحليل
          ${escapeHTML(
            marketLabels[market] ||
            market
          )}...
        </div>
      `;
    }

    try {

      const marketInterval =
        market === "forex"
          ? "1h"
          : market === "saudi"
            ? "1d"
            : market === "usmarket"
              ? "1d"
              : state.interval;

      const endpoint =
        getScannerEndpoint(
          market
        );

      const data =
        await api(
          `${endpoint}?interval=${encodeURIComponent(
            marketInterval
          )}`
        );

      const results =
        Array.isArray(data?.results)
          ? data.results
          : Array.isArray(data?.signals)
            ? data.signals
            : [];

      const signals =
        Array.isArray(data?.signals)
          ? data.signals
          : results.filter(
              isSignal
            );

      const display =
        signals.length
          ? signals
          : results;

      renderSignals(
        container,
        display.slice(0, 30),
        "ما فيه فرصة مطابقة حالياً — مستمرين بالمراقبة."
      );

      setStatus(
        `● ${
          marketLabels[market] ||
          market
        } مباشر • ${
          formatTime(
            data?.updatedAt
          )
        }`
      );

      if (market === "crypto") {

        state.results =
          results;

        state.signals =
          signals;

        state.lastUpdated =
          data?.updatedAt ||
          Date.now();

        renderScanner();

        updateDashboard({
          results,
          signals
        });
      }

    } catch (error) {

      console.error(
        `Market ${market}:`,
        error
      );

      if (box) {
        box.innerHTML = `
          <div class="empty-state">
            ❌ تعذر تحميل البيانات
            <br>
            ${escapeHTML(
              error.message
            )}
          </div>
        `;
      }

      setStatus(
        "● تعذر تحديث السوق"
      );
    }
  }

  function setupMarketRefresh() {

    qsa(
      "[data-market-refresh]"
    ).forEach((button) => {

      button.addEventListener(
        "click",
        () => {

          const market =
            button.dataset.marketRefresh;

          if (market) {
            loadMarket(market);
          }
        }
      );

    });
  }

  /* =========================================================
     الصفقات
  ========================================================= */

  function getRecent() {

    try {

      const data =
        JSON.parse(
          localStorage.getItem(
            "mudarib_recent"
          ) || "[]"
        );

      return Array.isArray(data)
        ? data
        : [];

    } catch {

      return [];
    }
  }

  function saveRecent(items) {

    state.recent =
      items.slice(0, 50);

    localStorage.setItem(
      "mudarib_recent",
      JSON.stringify(
        state.recent
      )
    );
  }

  function addRecent(items) {

    if (
      !Array.isArray(items) ||
      !items.length
    ) {
      return;
    }

    const old =
      getRecent();

    const merged = [
      ...items,
      ...old
    ];

    const seen =
      new Set();

    const unique =
      merged.filter((item) => {

        const key =
          `${getSymbol(item)}|` +
          `${getSignal(item)}|` +
          `${getTime(item)}`;

        if (
          seen.has(key)
        ) {
          return false;
        }

        seen.add(key);

        return true;
      });

    saveRecent(unique);
  }

  function renderRecent() {

    const box =
      $("recentList");

    if (!box) {
      return;
    }

    const items =
      getRecent();

    if (!items.length) {

      box.innerHTML = `
        <div class="empty-state">
          ما فيه صفقات محفوظة حالياً.
        </div>
      `;

      return;
    }

    box.innerHTML =
      items
        .slice(0, 30)
        .map(renderCard)
        .join("");
  }

  function setupRecent() {

    const clear =
      $("clearRecent");

    if (!clear) {
      return;
    }

    clear.addEventListener(
      "click",
      () => {

        localStorage.removeItem(
          "mudarib_recent"
        );

        state.recent = [];

        renderRecent();
      }
    );
  }

  /* =========================================================
     الأخبار
  ========================================================= */

  function renderNews() {

    const box =
      $("newsList");

    if (!box) {
      return;
    }

    box.innerHTML = `
      <div class="empty-state">
        📰 الأخبار غير مفعلة حالياً.
        <br>
        السيرفر الحالي لا يحتوي على API للأخبار.
      </div>
    `;
  }

  function setupNews() {

    const button =
      $("newsBtn");

    if (button) {

      button.addEventListener(
        "click",
        renderNews
      );
    }

    renderNews();
  }

  /* =========================================================
     صحة السيرفر
  ========================================================= */

  async function checkHealth() {

    try {

      const data =
        await api(
          "/health"
        );

      if (
        data?.ok === true &&
        data?.online !== false
      ) {

        if (
          data?.source === "OKX"
        ) {

          setStatus(
            "● مباشر — OKX متصل"
          );

        } else {

          setStatus(
            "● السيرفر متصل"
          );
        }

      } else {

        setStatus(
          "● السيرفر متصل"
        );
      }

    } catch (error) {

      console.error(
        "Health:",
        error
      );

      setStatus(
        "● تعذر الاتصال بالسيرفر"
      );
    }
  }

  /* =========================================================
     العملات
  ========================================================= */

  async function loadCryptoSymbols() {

    try {

      const data =
        await api(
          "/api/okx/markets"
        );

      state.cryptoSymbols =
        Array.isArray(data)
          ? data
          : (
              data?.symbols ||
              data?.markets ||
              []
            );

    } catch (error) {

      console.warn(
        "Crypto symbols:",
        error
      );

      state.cryptoSymbols =
        [];
    }
  }

  /* =========================================================
     التحميل الأول
  ========================================================= */

  async function initialLoad() {

    setStatus(
      "● جاري الاتصال بالسوق..."
    );

    await checkHealth();

    await loadCryptoSymbols();

    /*
     * الرئيسية تبدأ بالعملات الرقمية.
     */
    await loadMarket(
      "crypto"
    );

    renderRecent();

    /*
     * إذا كان المستخدم داخل الفاحص
     * نجهزه مباشرة.
     */
    const active =
      qs(".section.active");

    if (active?.id === "scanner") {
      loadScanner();
    }
  }

  /* =========================================================
     التحديث التلقائي
  ========================================================= */

  function setupAutoRefresh() {

    window.setInterval(
      () => {

        const active =
          qs(".section.active");

        const id =
          active?.id;

        if (
          id === "dashboard" ||
          id === "crypto"
        ) {

          loadMarket(
            "crypto"
          );

        } else if (
          id === "scanner"
        ) {

          /*
           * هنا نستخدم السوق المختار
           * من الفاحص، وليس crypto دائماً.
           */
          loadScanner();

        } else if (
          marketContainers[id]
        ) {

          loadMarket(id);
        }

      },
      30000
    );

    window.setInterval(
      checkHealth,
      60000
    );
  }

  /* =========================================================
     التشغيل
  ========================================================= */

  function init() {

    setupNavigation();

    setupTheme();

    setupScanner();

    setupMarketRefresh();

    setupRecent();

    setupNews();

    initialLoad();

    setupAutoRefresh();
  }

  /* =========================================================
     توافق index.html
  ========================================================= */

  window.renderSignalCard =
    renderCard;

  window.renderMarketSignals =
    renderSignals;

  window.updateLiveSignals =
    updateDashboard;

  window.loadMarket =
    loadMarket;

  window.loadScanner =
    loadScanner;

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
