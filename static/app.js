(() => {
  "use strict";

  /* =========================================================
     HELPERS
  ========================================================= */

  const $ = (id) => document.getElementById(id);

  const qs = (selector) =>
    document.querySelector(selector);

  const qsa = (selector) =>
    [...document.querySelectorAll(selector)];


  /* =========================================================
     STATE
  ========================================================= */

  const state = {
    market: "crypto",
    scannerMarket: "crypto",

    // الفريم الداخلي فقط للـ API
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

    user: null,
    admin: false,

    subscription: null,
    plans: [],

    chart: null,

    selectedPlan: null
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
     NUMBER
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
     DATA HELPERS
  ========================================================= */

  function getSymbol(item) {

    return (
      item?.symbol ||
      item?.ticker ||
      item?.name ||
      "—"
    );
  }


  function getName(item) {

    return (
      item?.name ||
      item?.symbol ||
      item?.ticker ||
      "—"
    );
  }


  function getPrice(item) {

    return (
      item?.price ??
      item?.close ??
      item?.last ??
      item?.entry
    );
  }


  function getEntry(item) {

    return (
      item?.entry ??
      getPrice(item)
    );
  }


  function getTP1(item) {

    return (
      item?.tp1 ??
      item?.takeProfit ??
      item?.target ??
      item?.tp
    );
  }


  function getTP2(item) {

    return (
      item?.tp2 ??
      item?.tp1 ??
      item?.takeProfit ??
      item?.target ??
      item?.tp
    );
  }


  function getTP3(item) {

    return (
      item?.tp3 ??
      item?.tp2 ??
      item?.tp1 ??
      item?.takeProfit ??
      item?.target ??
      item?.tp
    );
  }


  function getSL(item) {

    return (
      item?.sl ??
      item?.stopLoss ??
      item?.stop
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

    let score =
      Number(item?.score);

    if (!Number.isFinite(score)) {
      score =
        Number(item?.score10) * 10;
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

    const value =
      item?.change ??
      item?.change24h ??
      item?.changePercent ??
      item?.percentChange ??
      0;

    const n = Number(value);

    return Number.isFinite(n)
      ? n
      : 0;
  }


  function getVolume(item) {

    const value =
      item?.volume ??
      item?.volume24h ??
      item?.volCcy24h ??
      item?.volume_usdt ??
      0;

    const n = Number(value);

    return Number.isFinite(n)
      ? n
      : 0;
  }


  function getRSI(item) {

    const n =
      Number(item?.rsi);

    return Number.isFinite(n)
      ? n
      : null;
  }


  /* =========================================================
     SIGNAL CHECK
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


  /*
   * مهم:
   * لا نعرض الحيادي.
   * الصفقات فقط شراء أو بيع.
   */

  function isSignal(item) {

    return (
      isBuy(item) ||
      isSell(item)
    );
  }


  function signalClass(signal) {

    const s =
      String(signal || "").toUpperCase();

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
      String(signal || "").toUpperCase();

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
      await fetch(url, {
        cache: "no-store",
        credentials: "same-origin",
        ...options,
        headers: {
          Accept: "application/json",
          ...(options.headers || {})
        }
      });

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

    if (data?.ok === false) {

      throw new Error(
        data?.error ||
        data?.message ||
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
     NORMALIZE
  ========================================================= */

  function normalizeResults(data) {

    if (
      Array.isArray(data?.results)
    ) {
      return data.results;
    }

    if (
      Array.isArray(data?.signals)
    ) {
      return data.signals;
    }

    if (
      Array.isArray(data?.data)
    ) {
      return data.data;
    }

    if (
      Array.isArray(data)
    ) {
      return data;
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
      (item) => {

        if (!isSignal(item)) {
          return false;
        }

        const entry =
          Number(getEntry(item));

        const target =
          Number(getTP1(item));

        const stop =
          Number(getSL(item));

        /*
         * نقبل الصفقة حتى لو بعض المستويات
         * غير موجودة، لأن بعض المصادر قد ترسل
         * الإشارة قبل اكتمال المستويات.
         */

        return true;
      }
    );
  }


  /* =========================================================
     NAVIGATION
  ========================================================= */

  function openSection(id) {

    qsa(".section").forEach(
      (section) => {

        section.classList.toggle(
          "active",
          section.id === id
        );
      }
    );


    qsa(
      ".nav-item[data-section]"
    ).forEach(
      (button) => {

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

      news: "الأخبار",

      subscription: "الاشتراك"
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


    /*
     * تحميل مباشر عند فتح القسم
     */

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

    if (id === "subscription") {
      loadSubscription();
    }
  }


  function setupNavigation() {

    qsa(
      ".nav-item[data-section]"
    ).forEach(
      (button) => {

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

    const symbol =
      escapeHTML(
        getSymbol(item)
      );

    const signal =
      getSignal(item);

    const cls =
      signalClass(signal);

    const price =
      getPrice(item);

    const entry =
      getEntry(item);

    const tp1 =
      getTP1(item);

    const sl =
      getSL(item);

    const score =
      getScore(item);

    const change =
      getChange(item);

    const rsi =
      getRSI(item);


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

            <span>
              الدخول
            </span>

            <strong>
              ${number(entry)}
            </strong>

          </div>


          <div class="signal-item">

            <span>
              الهدف
            </span>

            <strong>
              ${number(tp1)}
            </strong>

          </div>


          <div class="signal-item">

            <span>
              وقف
            </span>

            <strong>
              ${number(sl)}
            </strong>

          </div>


          <div class="signal-item">

            <span>
              القوة
            </span>

            <strong>
              ${number(score, 1)}
            </strong>

          </div>


          <div class="signal-item">

            <span>
              RSI
            </span>

            <strong>
              ${
                rsi === null
                  ? "—"
                  : number(rsi, 1)
              }
            </strong>

          </div>


          <div class="signal-item">

            <span>
              التغير
            </span>

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
            ${timeText(item?.updatedAt)}
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


    if (
      !Array.isArray(items) ||
      !items.length
    ) {

      box.innerHTML =
        `
          <div class="empty-state">
            ${escapeHTML(empty)}
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


    const endpoint =
      MARKET_API[market];


    if (!endpoint) {
      return;
    }


    state.loading = true;


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
        `⏳ جاري جلب صفقات ${MARKET_NAMES[market]}...`;
    }


    try {

      /*
       * الفريم هنا داخلي فقط.
       * المستخدم ما يحتاج يختار فريم.
       */

      let interval =
        "15m";


      if (market === "saudi") {
        interval = "1d";
      }

      if (market === "usmarket") {
        interval = "1d";
      }

      if (market === "forex") {
        interval = "1h";
      }

      if (market === "futures") {
        interval = "15m";
      }


      const url =
        `${endpoint}?interval=${encodeURIComponent(
          interval
        )}`;


      console.log(
        "DIRECT SCANNER:",
        market,
        url
      );


      const data =
        await api(url);


      state.results =
        onlyTrades(
          normalizeResults(data)
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
          `${state.results.length} صفقة مباشرة`;
      }


      setStatus(
        `● ${MARKET_NAMES[market]} — صفقات مباشرة`
      );

    } catch (error) {

      console.error(
        "Scanner:",
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
        "● تعذر تحميل الصفقات"
      );

    } finally {

      state.loading = false;


      if (btn) {

        btn.disabled = false;

        btn.textContent =
          "🔄 تحديث";
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
          (item) =>
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


    items.sort(
      (a, b) => {

        let av = 0;
        let bv = 0;


        switch (
          state.sortField
        ) {

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
      items.map(
        (item) => {

          const signal =
            getSignal(item);

          const cls =
            signalClass(signal);


          return `
            <tr>

              <td>

                <strong>

                  ${signalIcon(signal)}

                  ${escapeHTML(
                    getSymbol(item)
                  )}

                </strong>

              </td>


              <td>
                ${number(
                  getPrice(item)
                )}
              </td>


              <td>

                <span class="${cls}">

                  ${percent(
                    getChange(item)
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
                  getScore(item),
                  1
                )}
              </td>


              <td>
                ${volume(
                  getVolume(item)
                )}
              </td>


              <td>
                صفقة مباشرة
              </td>

            </tr>
          `;
        }
      ).join("");
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
            (button) => {

              button.classList.remove(
                "active"
              );
            }
          );


          loadScanner();
        }
      );
    }


    /*
     * أزرار الفريمات القديمة:
     * نخليها غير مؤثرة.
     */

    qsa(
      "#intervalChips [data-interval]"
    ).forEach(
      (button) => {

        button.addEventListener(
          "click",
          () => {

            loadScanner();
          }
        );
      }
    );


    qsa(
      ".signal-chips [data-signal]"
    ).forEach(
      (button) => {

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
                (b) => {

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
        (event) => {

          state.search =
            event.target.value;

          renderScanner();
        }
      );


    $("sortField")
      ?.addEventListener(
        "change",
        (event) => {

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

      const data =
        await api(
          `/api/okx/scan?interval=${encodeURIComponent(
            state.interval
          )}`
        );


      const results =
        normalizeResults(data);


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
        "● العملات الرقمية مباشر — OKX"
      );

    } catch (error) {

      console.error(
        "Dashboard:",
        error
      );

      setStatus(
        "● تعذر تحديث الرئيسية"
      );
    }
  }


  function updateDashboard(results) {

    const items =
      Array.isArray(results)
        ? results
        : [];


    const best =
      onlyTrades(items)
        .sort(
          (a, b) =>
            getScore(b) -
            getScore(a)
        )
        .slice(0, 6);


    if ($("dashSymbol")) {

      $("dashSymbol").textContent =
        best[0]
          ? getSymbol(best[0])
          : "BTCUSDT";
    }


    if ($("dashPrice")) {

      $("dashPrice").textContent =
        best[0]
          ? number(
              getPrice(best[0])
            )
          : "—";
    }


    if ($("dashChange")) {

      $("dashChange").textContent =
        best[0]
          ? percent(
              getChange(best[0])
            )
          : "—";
    }


    if ($("dashSignal")) {

      $("dashSignal").textContent =
        best[0]
          ? getSignal(best[0])
          : "—";
    }
  }


  function updateDashboardDetails(item) {

    if (!item) {
      return;
    }


    const signal =
      getSignal(item);


    if ($("bigSignal")) {

      $("bigSignal").textContent =
        `${signalIcon(signal)} ${signal}`;
    }


    if ($("scoreText")) {

      $("scoreText").textContent =
        `${number(
          getScore(item),
          1
        )}/100`;
    }


    if ($("scoreBar")) {

      $("scoreBar").style.width =
        `${getScore(item)}%`;
    }


    if ($("entry")) {

      $("entry").textContent =
        number(
          getEntry(item)
        );
    }


    if ($("tp1")) {

      $("tp1").textContent =
        number(
          getTP1(item)
        );
    }


    if ($("tp2")) {

      $("tp2").textContent =
        number(
          getTP2(item)
        );
    }


    if ($("tp3")) {

      $("tp3").textContent =
        number(
          getTP3(item)
        );
    }


    if ($("sl")) {

      $("sl").textContent =
        number(
          getSL(item)
        );
    }


    if ($("rsi")) {

      $("rsi").textContent =
        getRSI(item) === null
          ? "—"
          : number(
              getRSI(item),
              1
            );
    }


    if ($("ema20")) {

      $("ema20").textContent =
        number(
          item?.ema20
        );
    }


    if ($("ema50")) {

      $("ema50").textContent =
        number(
          item?.ema50
        );
    }


    if ($("ema200")) {

      $("ema200").textContent =
        number(
          item?.ema200
        );
    }


    if ($("analysisMeta")) {

      $("analysisMeta").textContent =
        "صفقة مباشرة";
    }


    const reasons =
      $("reasons");


    if (reasons) {

      const list =
        Array.isArray(
          item?.reasons
        )
          ? item.reasons
          : [];


      reasons.innerHTML =
        list.length

          ? list
              .map(
                (r) =>
                  `<li>${escapeHTML(r)}</li>`
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
      (button) => {

        button.addEventListener(
          "click",
          () => {

            state.interval =
              button.dataset.interval;


            qsa(
              "#dashIntervals [data-interval]"
            ).forEach(
              (b) => {

                b.classList.toggle(
                  "active",
                  b === button
                );
              }
            );


            loadCryptoDashboard();
          }
        );
      }
    );
  }


  /* =========================================================
     SAUDI — DIRECT TRADES
  ========================================================= */

  async function loadSaudi() {

    const box =
      $("saudiList");


    if (!box) {
      return;
    }


    box.innerHTML =
      `
        <div class="empty-state">
          ⏳ جاري جلب الصفقات السعودية...
        </div>
      `;


    try {

      /*
       * لا اختيار فريم.
       * السيرفر يستخدم 1D كمصدر داخلي.
       */

      const data =
        await api(
          "/api/saudi/scan?interval=1d"
        );


      let results =
        onlyTrades(
          normalizeResults(data)
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
        `● السعودي — ${results.length} صفقة`
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
     US — DIRECT TRADES
  ========================================================= */

  async function loadUSMarket() {

    const box =
      $("usMarketList");


    if (!box) {
      return;
    }


    box.innerHTML =
      `
        <div class="empty-state">
          ⏳ جاري جلب الصفقات الأمريكية...
        </div>
      `;


    try {

      const data =
        await api(
          "/api/usmarket/signals?interval=1d"
        );


      let results =
        onlyTrades(
          normalizeResults(data)
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
        `● الأمريكي — ${results.length} صفقة`
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
     FOREX — DIRECT TRADES
  ========================================================= */

  async function loadForex() {

    const box =
      $("forexList");


    if (!box) {
      return;
    }


    box.innerHTML =
      `
        <div class="empty-state">
          ⏳ جاري جلب صفقات الفوركس...
        </div>
      `;


    try {

      const data =
        await api(
          "/api/forex/signals?interval=1h"
        );


      let results =
        onlyTrades(
          normalizeResults(data)
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
        `● الفوركس — ${results.length} صفقة`
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
      (item) =>
        String(
          getSymbol(item)
        )
          .toLowerCase()
          .includes(value) ||

        String(
          getName(item)
        )
          .toLowerCase()
          .includes(value)
    );
  }


  /* =========================================================
     OLD MARKET INTERVALS
     لا تستخدم للفريمات.
     فقط التحديث والبحث.
  ========================================================= */

  function setupMarketIntervals() {

    /*
     * السعودي
     */

    $("refreshSaudi")
      ?.addEventListener(
        "click",
        loadSaudi
      );


    /*
     * الأمريكي
     */

    $("refreshUSMarket")
      ?.addEventListener(
        "click",
        loadUSMarket
      );


    /*
     * الفوركس
     */

    $("refreshForex")
      ?.addEventListener(
        "click",
        loadForex
      );


    /*
     * البحث
     */

    $("saudiSearch")
      ?.addEventListener(
        "input",
        loadSaudi
      );


    $("usSearch")
      ?.addEventListener(
        "input",
        loadUSMarket
      );


    $("forexSearch")
      ?.addEventListener(
        "input",
        loadForex
      );


    /*
     * منع أزرار الفريم القديمة من تغيير مصدر الصفقات.
     * إذا ضغط المستخدم عليها، نعيد تحميل الصفقة المباشرة.
     */

    qsa(
      "#saudiIntervals [data-interval]"
    ).forEach(
      (button) => {

        button.addEventListener(
          "click",
          () => {

            loadSaudi();
          }
        );
      }
    );


    qsa(
      "#usIntervals [data-interval]"
    ).forEach(
      (button) => {

        button.addEventListener(
          "click",
          () => {

            loadUSMarket();
          }
        );
      }
    );


    qsa(
      "#forexIntervals [data-interval]"
    ).forEach(
      (button) => {

        button.addEventListener(
          "click",
          () => {

            loadForex();
          }
        );
      }
    );
  }


  /* =========================================================
     FUTURES — DIRECT TRADES
  ========================================================= */

  async function loadFutures() {

    const box =
      $("futuresList");


    if (!box) {
      return;
    }


    box.innerHTML =
      `
        <div class="empty-state">
          ⏳ جاري جلب صفقات الفيوتشر...
        </div>
      `;


    try {

      /*
       * الفيوتشر مباشر.
       * الفريم داخلي فقط للسيرفر.
       */

      const data =
        await api(
          "/api/futures/scan?interval=15m&limit=40"
        );


      let results =
        onlyTrades(
          normalizeResults(data)
        );


      renderCards(
        "futuresList",
        results,
        "لا توجد صفقات فيوتشر حالياً."
      );


      addRecent(results);


      setStatus(
        `● الفيوتشر — ${results.length} صفقة`
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

    localStorage.setItem(
      "mudarib_recent",
      JSON.stringify(
        state.recent
      )
    );
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
          (item) => {

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


    if (
      !state.recent.length
    ) {

      box.innerHTML =
        `
          <div class="empty-state">
            لا توجد صفقات محفوظة حالياً.
          </div>
        `;

      return;
    }


    box.innerHTML =
      state.recent
        .filter(isSignal)
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
          .map(
            (item) => {

              const title =
                item?.title ||
                item?.name ||
                "خبر";


              const source =
                item?.source ||
                "";


              const link =
                item?.url ||
                item?.link ||
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
     AUTH
  ========================================================= */

  function showAuth(mode = "login") {

    const modal =
      $("authModal");


    if (!modal) {
      return;
    }


    modal.classList.add(
      "open"
    );


    if (mode === "register") {

      showRegisterForm();

    } else {

      showLoginForm();
    }
  }


  function closeAuth() {

    $("authModal")
      ?.classList.remove(
        "open"
      );
  }


  function showLoginForm() {

    $("loginForm")?.removeAttribute(
      "hidden"
    );

    $("registerForm")?.setAttribute(
      "hidden",
      ""
    );


    $("loginTab")
      ?.classList.add(
        "active"
      );

    $("registerTab")
      ?.classList.remove(
        "active"
      );


    if ($("authMsg")) {

      $("authMsg").textContent =
        "";
    }
  }


  function showRegisterForm() {

    $("loginForm")?.setAttribute(
      "hidden",
      ""
    );

    $("registerForm")?.removeAttribute(
      "hidden"
    );


    $("registerTab")
      ?.classList.add(
        "active"
      );

    $("loginTab")
      ?.classList.remove(
        "active"
      );


    if ($("authMsg")) {

      $("authMsg").textContent =
        "";
    }
  }


  async function checkAuth() {

    try {

      const data =
        await api(
          "/api/auth/me"
        );


      state.user =
        data?.user ||
        data?.data ||
        null;


      updateUserUI();

    } catch {

      state.user = null;

      updateUserUI();
    }
  }


  function updateUserUI() {

    const badge =
      $("userBadge");

    const login =
      $("loginBtn");

    const register =
      $("registerBtn");

    const logout =
      $("logoutBtn");

    const subscription =
      $("subscriptionNav");


    if (state.user) {

      if (badge) {

        badge.textContent =
          state.user.name ||
          state.user.email ||
          "مستخدم";
      }


      login?.setAttribute(
        "hidden",
        ""
      );

      register?.setAttribute(
        "hidden",
        ""
      );

      logout?.removeAttribute(
        "hidden"
      );

      subscription?.removeAttribute(
        "hidden"
      );

    } else {

      if (badge) {

        badge.textContent =
          "زائر";
      }


      login?.removeAttribute(
        "hidden"
      );

      register?.removeAttribute(
        "hidden"
      );

      logout?.setAttribute(
        "hidden",
        ""
      );

      subscription?.setAttribute(
        "hidden",
        ""
      );
    }
  }


  async function login(event) {

    event.preventDefault();


    const email =
      $("loginEmail")?.value.trim();

    const password =
      $("loginPassword")?.value;


    const msg =
      $("authMsg");


    try {

      const data =
        await api(
          "/api/auth/login",
          {
            method: "POST",

            headers: {
              "Content-Type":
                "application/json"
            },

            body:
              JSON.stringify({
                email,
                password
              })
          }
        );


      state.user =
        data?.user ||
        data?.data ||
        null;


      if (msg) {

        msg.textContent =
          "تم تسجيل الدخول بنجاح ✅";
      }


      updateUserUI();


      setTimeout(
        closeAuth,
        500
      );

    } catch (error) {

      if (msg) {

        msg.textContent =
          `❌ ${error.message}`;
      }
    }
  }


  async function register(event) {

    event.preventDefault();


    const name =
      $("regName")?.value.trim();

    const email =
      $("regEmail")?.value.trim();

    const password =
      $("regPassword")?.value;


    const msg =
      $("authMsg");


    try {

      const data =
        await api(
          "/api/auth/register",
          {
            method: "POST",

            headers: {
              "Content-Type":
                "application/json"
            },

            body:
              JSON.stringify({
                name,
                email,
                password
              })
          }
        );


      state.user =
        data?.user ||
        data?.data ||
        null;


      if (msg) {

        msg.textContent =
          "تم إنشاء الحساب بنجاح ✅";
      }


      updateUserUI();


      setTimeout(
        closeAuth,
        500
      );

    } catch (error) {

      if (msg) {

        msg.textContent =
          `❌ ${error.message}`;
      }
    }
  }


  async function logout() {

    try {

      await api(
        "/api/auth/logout",
        {
          method: "POST"
        }
      );

    } catch (error) {

      console.warn(
        "Logout:",
        error
      );
    }


    state.user = null;

    updateUserUI();

    openSection(
      "dashboard"
    );
  }


  function setupAuth() {

    $("loginBtn")
      ?.addEventListener(
        "click",
        () => showAuth("login")
      );


    $("registerBtn")
      ?.addEventListener(
        "click",
        () => showAuth("register")
      );


    $("logoutBtn")
      ?.addEventListener(
        "click",
        logout
      );


    $("loginTab")
      ?.addEventListener(
        "click",
        showLoginForm
      );


    $("registerTab")
      ?.addEventListener(
        "click",
        showRegisterForm
      );


    $("loginForm")
      ?.addEventListener(
        "submit",
        login
      );


    $("registerForm")
      ?.addEventListener(
        "submit",
        register
      );


    qsa(
      "[data-close='authModal']"
    ).forEach(
      (button) => {

        button.addEventListener(
          "click",
          closeAuth
        );
      }
    );


    $("authModal")
      ?.addEventListener(
        "click",
        (event) => {

          if (
            event.target ===
            $("authModal")
          ) {

            closeAuth();
          }
        }
      );
  }


  /* =========================================================
     SUBSCRIPTION
  ========================================================= */

  async function loadSubscription() {

    if (!state.user) {

      const status =
        $("subscriptionStatus");


      if (status) {

        status.innerHTML =
          "🔐 سجل دخولك أولاً للوصول للاشتراك.";
      }


      return;
    }


    try {

      const plansData =
        await api(
          "/api/subscription/plans"
        );


      state.plans =
        Array.isArray(
          plansData?.plans
        )

          ? plansData.plans

          : Array.isArray(
              plansData
            )
            ? plansData

            : [];


      renderPlans();

    } catch (error) {

      console.error(
        "Plans:",
        error
      );
    }


    try {

      const data =
        await api(
          "/api/subscription/my"
        );


      state.subscription =
        data?.subscription ||
        data?.data ||
        null;


      renderSubscriptionStatus();

    } catch (error) {

      console.error(
        "Subscription:",
        error
      );
    }


    loadPaymentHistory();
  }


  function renderPlans() {

    const box =
      $("plans");


    if (!box) {
      return;
    }


    if (!state.plans.length) {

      box.innerHTML =
        `
          <div class="empty-state">
            لا توجد خطط حالياً.
          </div>
        `;

      return;
    }


    box.innerHTML =
      state.plans
        .map(
          (plan) => {

            const id =
              plan.id ||
              plan.key ||
              plan.plan;


            const name =
              plan.name ||
              id;


            const amount =
              plan.amount ??
              plan.price ??
              0;


            const days =
              plan.days ||
              "";


            return `
              <div class="plan-card">

                <h3>
                  ${escapeHTML(name)}
                </h3>

                <strong>
                  ${number(amount, 2)} USDT
                </strong>

                <span>
                  ${escapeHTML(
                    String(days)
                  )} يوم
                </span>

                <button
                  class="btn primary"
                  data-plan="${escapeHTML(id)}"
                >
                  اختيار الخطة
                </button>

              </div>
            `;
          }
        )
        .join("");


    qsa(
      "[data-plan]"
    ).forEach(
      (button) => {

        button.addEventListener(
          "click",
          () => {

            const id =
              button.dataset.plan;


            const plan =
              state.plans.find(
                (p) =>
                  String(
                    p.id ||
                    p.key ||
                    p.plan
                  ) ===
                  String(id)
              );


            choosePlan(plan);
          }
        );
      }
    );
  }


  function choosePlan(plan) {

    if (!plan) {
      return;
    }


    state.selectedPlan =
      plan;


    const paymentBox =
      $("paymentBox");


    if (paymentBox) {

      paymentBox.removeAttribute(
        "hidden"
      );
    }


    const chosen =
      $("chosenPlan");


    if (chosen) {

      chosen.innerHTML =
        `
          <b>
            ${escapeHTML(
              plan.name ||
              plan.id ||
              "الخطة"
            )}
          </b>

          —
          ${number(
            plan.amount ??
            plan.price ??
            0,
            2
          )}
          USDT
        `;
    }


    loadPaymentAddress();
  }


  async function loadPaymentAddress() {

    try {

      const data =
        await api(
          "/api/subscription/plans"
        );


      const address =
        data?.trc20_address ||
        data?.TRC20_ADDRESS ||
        "";


      if ($("payAddress")) {

        $("payAddress").value =
          address;
      }


      generateQR(
        address
      );

    } catch (error) {

      console.warn(
        "Payment address:",
        error
      );
    }
  }


  function generateQR(address) {

    const box =
      $("qrBox");


    if (!box) {
      return;
    }


    box.innerHTML = "";


    if (
      !address ||
      !window.QRCode
    ) {

      return;
    }


    try {

      QRCode.toCanvas(
        address,

        {
          width: 180
        },

        (error, canvas) => {

          if (!error) {

            box.appendChild(
              canvas
            );
          }
        }
      );

    } catch (error) {

      console.warn(
        "QR:",
        error
      );
    }
  }


  function renderSubscriptionStatus() {

    const box =
      $("subscriptionStatus");


    if (!box) {
      return;
    }


    const sub =
      state.subscription;


    if (!sub) {

      box.innerHTML =
        "لا يوجد اشتراك فعال حالياً.";

      return;
    }


    box.innerHTML =
      `
        <div class="subscription-current">

          <b>
            الاشتراك الحالي:
          </b>

          ${escapeHTML(
            sub.plan_name ||
            sub.name ||
            sub.plan ||
            ""
          )}

          <br>

          الحالة:
          ${escapeHTML(
            sub.status ||
            "غير معروف"
          )}

        </div>
      `;
  }


  async function loadPaymentHistory() {

    const box =
      $("paymentHistory");


    if (!box) {
      return;
    }


    try {

      const data =
        await api(
          "/api/subscription/history"
        );


      const history =
        Array.isArray(
          data?.history
        )

          ? data.history

          : Array.isArray(
              data
            )
            ? data

            : [];


      if (!history.length) {

        box.innerHTML =
          `
            <div class="empty-state">
              لا توجد طلبات دفع سابقة.
            </div>
          `;

        return;
      }


      box.innerHTML =
        history
          .map(
            (item) => `
              <div class="payment-history-item">

                <b>
                  ${escapeHTML(
                    item.plan_name ||
                    item.plan ||
                    "اشتراك"
                  )}
                </b>

                <span>
                  ${escapeHTML(
                    item.status ||
                    ""
                  )}
                </span>

              </div>
            `
          )
          .join("");

    } catch (error) {

      console.warn(
        "History:",
        error
      );
    }
  }


  async function sendPayment() {

    if (!state.selectedPlan) {

      $("paymentMsg").textContent =
        "اختر خطة أولاً.";

      return;
    }


    const txid =
      $("txid")?.value.trim();


    if (!txid) {

      $("paymentMsg").textContent =
        "أدخل TXID بعد التحويل.";

      return;
    }


    const button =
      $("sendPayment");


    try {

      if (button) {

        button.disabled = true;

        button.textContent =
          "⏳ جاري الإرسال...";
      }


      await api(
        "/api/subscription/request",
        {
          method: "POST",

          headers: {
            "Content-Type":
              "application/json"
          },

          body:
            JSON.stringify({

              plan:
                state.selectedPlan.id ||
                state.selectedPlan.key ||
                state.selectedPlan.plan,

              txid
            })
        }
      );


      $("paymentMsg").textContent =
        "تم إرسال طلب الاشتراك للمراجعة ✅";


      if ($("txid")) {

        $("txid").value =
          "";
      }


      loadPaymentHistory();

    } catch (error) {

      $("paymentMsg").textContent =
        `❌ ${error.message}`;

    } finally {

      if (button) {

        button.disabled = false;

        button.textContent =
          "إرسال طلب الاشتراك";
      }
    }
  }


  $("sendPayment")
    ?.addEventListener(
      "click",
      sendPayment
    );


  $("copyAddress")
    ?.addEventListener(
      "click",
      async () => {

        const input =
          $("payAddress");


        if (!input?.value) {
          return;
        }


        try {

          await navigator.clipboard.writeText(
            input.value
          );


          $("copyAddress").textContent =
            "تم النسخ ✓";


          setTimeout(
            () => {

              $("copyAddress").textContent =
                "نسخ";
            },
            1500
          );

        } catch {

          input.select();

          document.execCommand(
            "copy"
          );
        }
      }
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


      if (
        data?.ok === true
      ) {

        setStatus(
          "● السيرفر متصل"
        );

      } else {

        setStatus(
          "● السيرفر متصل"
        );
      }

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

    /*
     * تحديث كل دقيقة.
     * وكل قسم يجلب الصفقات المباشرة الخاصة به.
     */

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
     INIT
  ========================================================= */

  async function init() {

    console.log(
      "مضارب أبو سعود — DIRECT TRADES MODE"
    );


    setupNavigation();

    setupTheme();

    setupScanner();

    setupDashboardIntervals();

    setupMarketIntervals();

    setupAuth();


    await checkAuth();

    await checkHealth();


    /*
     * الرئيسية
     */

    await loadCryptoDashboard();


    /*
     * الصفقات المحفوظة
     */

    renderRecent();


    /*
     * التحديث التلقائي
     */

    setupAutoRefresh();


    /*
     * استرجاع القسم الأخير
     */

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
        "news",
        "subscription"
      ].includes(active)
    ) {

      openSection(active);
    }
  }


  /* =========================================================
     GLOBAL FUNCTIONS
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
