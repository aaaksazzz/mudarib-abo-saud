(() => {
  "use strict";

  /* =========================================================
     مضارب أبو سعود — Live Market Signals
     API: /api/scan
     بدون تسجيل دخول
     بدون شارت
     بدون بيانات وهمية
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

  function firstNumber(...values) {
    for (const value of values) {
      const n = Number(value);

      if (Number.isFinite(n)) {
        return n;
      }
    }

    return null;
  }

  /* =========================================================
     SIGNAL
  ========================================================= */

  function signalType(item) {
    const raw = [
      item?.signal,
      item?.direction,
      item?.side,
      item?.action
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();

    if (
      raw.includes("شراء قوي") ||
      raw.includes("strong buy") ||
      raw.includes("strong_buy")
    ) {
      return "buy-strong";
    }

    if (
      raw.includes("بيع قوي") ||
      raw.includes("strong sell") ||
      raw.includes("strong_sell")
    ) {
      return "sell-strong";
    }

    if (
      raw.includes("buy") ||
      raw.includes("شراء") ||
      raw.includes("long")
    ) {
      return "buy";
    }

    if (
      raw.includes("sell") ||
      raw.includes("بيع") ||
      raw.includes("short")
    ) {
      return "sell";
    }

    return "neutral";
  }

  function signalText(type, original = "") {
    if (type === "buy-strong") return "شراء قوي";
    if (type === "buy") return "شراء";
    if (type === "sell-strong") return "بيع قوي";
    if (type === "sell") return "بيع";

    return original || "محايد";
  }

  function getScore(item) {
    const score = firstNumber(
      item?.score,
      item?.strength,
      item?.confidence
    );

    if (score === null) {
      const score10 = Number(item?.score10);

      if (Number.isFinite(score10)) {
        return score10 <= 10 ? score10 * 10 : score10;
      }

      return 0;
    }

    return score <= 10 &&
      Number.isFinite(Number(item?.score10))
      ? score * 10
      : score;
  }

  function getSymbol(item) {
    return (
      item?.symbol ||
      item?.ticker ||
      item?.pair ||
      item?.code ||
      item?.name ||
      "-"
    );
  }

  function getMarket(item) {
    return (
      item?.market ||
      item?.market_name ||
      item?.category ||
      item?.asset_class ||
      item?.type ||
      item?.exchange ||
      ""
    );
  }

  function getPrice(item) {
    return firstNumber(
      item?.price,
      item?.last_price,
      item?.last,
      item?.close,
      item?.current_price,
      item?.entry
    );
  }

  function getEntry(item) {
    return firstNumber(
      item?.entry,
      item?.entry_price,
      getPrice(item)
    );
  }

  function getTP(item) {
    return firstNumber(
      item?.tp1,
      item?.tp,
      item?.target,
      item?.take_profit,
      item?.target1,
      item?.takeProfit
    );
  }

  function getSL(item) {
    return firstNumber(
      item?.sl,
      item?.stop,
      item?.stop_loss,
      item?.stopLoss
    );
  }

  function getChange(item) {
    return firstNumber(
      item?.change,
      item?.change24h,
      item?.change_percent,
      item?.percent,
      item?.price_change_percent
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
      item?.updatedAt ||
      item?.date ||
      ""
    );
  }

  /* =========================================================
     MARKET NORMALIZATION
  ========================================================= */

  function detectMarket(item) {
    const symbol = String(
      getSymbol(item)
    ).toUpperCase();

    const raw = [
      item?.market,
      item?.market_name,
      item?.category,
      item?.asset_class,
      item?.type,
      item?.exchange,
      symbol
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();

    /* 🇸🇦 السعودية */

    if (
      raw.includes("saudi") ||
      raw.includes("ksa") ||
      raw.includes("tasi") ||
      raw.includes("السعود") ||
      raw.includes("تاسي") ||
      /\.SR$/i.test(symbol)
    ) {
      return "saudi";
    }

    /* ₿ العملات الرقمية */

    if (
      raw.includes("crypto") ||
      raw.includes("cryptocurrency") ||
      raw.includes("digital asset") ||
      raw.includes("كريبتو") ||
      raw.includes("عملات رقمية") ||
      symbol.endsWith("USDT") ||
      symbol.endsWith("USDC") ||
      symbol.endsWith("BTC") ||
      symbol.endsWith("ETH")
    ) {
      return "crypto";
    }

    /* 💵 الفوركس */

    const forexSymbols = [
      "EURUSD=X",
      "GBPUSD=X",
      "USDJPY=X",
      "USDCHF=X",
      "AUDUSD=X",
      "USDCAD=X",
      "NZDUSD=X",
      "EURGBP=X"
    ];

    if (
      raw.includes("forex") ||
      raw.includes("fx") ||
      raw.includes("فوركس") ||
      forexSymbols.includes(symbol) ||
      /^[A-Z]{6}$/.test(symbol)
    ) {
      return "forex";
    }

    /* 🛢️ السلع */

    const commoditySymbols = [
      "GC=F",
      "SI=F",
      "CL=F",
      "BZ=F",
      "NG=F"
    ];

    if (
      raw.includes("gold") ||
      raw.includes("silver") ||
      raw.includes("oil") ||
      raw.includes("crude") ||
      raw.includes("commodity") ||
      raw.includes("commodities") ||
      raw.includes("ذهب") ||
      raw.includes("فضة") ||
      raw.includes("نفط") ||
      commoditySymbols.includes(symbol)
    ) {
      return "commodities";
    }

    /* 📊 العقود الآجلة */

    const futuresSymbols = [
      "ES=F",
      "NQ=F",
      "YM=F",
      "RTY=F"
    ];

    if (
      raw.includes("future") ||
      raw.includes("futures") ||
      raw.includes("فيوتشر") ||
      raw.includes("عقود آجلة") ||
      raw.includes("عقود") ||
      futuresSymbols.includes(symbol)
    ) {
      return "futures";
    }

    /* 📈 المؤشرات */

    const indexSymbols = [
      "^GSPC",
      "^IXIC",
      "^DJI",
      "^RUT",
      "^VIX",
      "^FTSE",
      "^GDAXI",
      "^N225",
      "^HSI"
    ];

    if (
      raw.includes("index") ||
      raw.includes("indices") ||
      raw.includes("مؤشر") ||
      raw.includes("sp500") ||
      raw.includes("s&p") ||
      raw.includes("nasdaq") ||
      raw.includes("dow") ||
      raw.includes("russell") ||
      raw.includes("dax") ||
      raw.includes("ftse") ||
      indexSymbols.includes(symbol)
    ) {
      return "indices";
    }

    /* 🇺🇸 الأسهم الأمريكية */

    if (
      raw.includes("us stock") ||
      raw.includes("usa") ||
      raw.includes("america") ||
      raw.includes("american") ||
      raw.includes("nasdaq stock") ||
      raw.includes("nyse") ||
      raw.includes("الأسهم الأمريكية") ||
      raw.includes("امريكا") ||
      raw.includes("أمريكا")
    ) {
      return "us";
    }

    /* الرموز الأمريكية المعروفة */

    const usSymbols = [
      "AAPL",
      "NVDA",
      "MSFT",
      "AMZN",
      "META",
      "TSLA",
      "GOOGL",
      "AMD",
      "AVGO",
      "NFLX",
      "JPM",
      "PLTR",
      "COIN",
      "MSTR",
      "BA"
    ];

    if (usSymbols.includes(symbol)) {
      return "us";
    }

    return "other";
  }

  function normalizeItem(item) {
    if (!item || typeof item !== "object") {
      return null;
    }

    const type = signalType(item);

    const originalSignal =
      item?.signal ||
      item?.direction ||
      item?.side ||
      "";

    const marketKey = detectMarket(item);

    return {
      ...item,

      symbol: getSymbol(item),
      market: getMarket(item),
      marketKey,

      price: getPrice(item),
      entry: getEntry(item),
      tp1: getTP(item),
      sl: getSL(item),

      score: getScore(item),
      change: getChange(item),

      timeframe: getTimeframe(item),
      time: getTime(item),

      signal:
        originalSignal ||
        signalText(type),

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

    const signal = signalText(
      type,
      item.signal
    );

    const symbol = escapeHTML(item.symbol);

    const marketName =
      marketLabel(item.marketKey, item.market);

    const market = escapeHTML(
      marketName
    );

    const timeframe = escapeHTML(
      item.timeframe
    );

    const price = number(
      item.price,
      8
    );

    const entry = number(
      item.entry,
      8
    );

    const tp = number(
      item.tp1,
      8
    );

    const sl = number(
      item.sl,
      8
    );

    const score = number(
      item.score,
      1
    );

    const change = percent(
      item.change
    );

    const time = escapeHTML(
      item.time
        ? String(item.time)
            .replace("T", " ")
            .slice(0, 19)
        : "مباشر"
    );

    return `
      <article class="signal-card ${escapeHTML(type)}">

        <div class="signal-top">

          <div>
            <div class="signal-symbol">
              ${symbol}
            </div>

            <div class="signal-market">
              ${market}
            </div>
          </div>

          <div class="signal-badge ${escapeHTML(type)}">
            ${escapeHTML(signal)}
          </div>

        </div>

        <div class="signal-price">

          <span>
            السعر الحالي
          </span>

          <strong>
            ${price}
          </strong>

        </div>

        <div class="signal-levels">

          <div class="level entry">
            <span>الدخول</span>
            <strong>
              ${entry}
            </strong>
          </div>

          <div class="level tp">
            <span>الهدف</span>
            <strong>
              ${tp}
            </strong>
          </div>

          <div class="level sl">
            <span>الوقف</span>
            <strong>
              ${sl}
            </strong>
          </div>

        </div>

        <div class="signal-bottom">

          <span>
            ${timeframe}
          </span>

          <span class="score">
            قوة ${score}
          </span>

          <span>
            ${change}
          </span>

          <span>
            ${time}
          </span>

        </div>

      </article>
    `;
  };

  /* =========================================================
     MARKET LABEL
  ========================================================= */

  function marketLabel(type, fallback = "") {
    const labels = {
      saudi: "🇸🇦 السوق السعودي",
      crypto: "₿ العملات الرقمية",
      forex: "💵 الفوركس",
      us: "🇺🇸 الأسهم الأمريكية",
      commodities: "🛢️ الذهب والنفط",
      indices: "📈 المؤشرات العالمية",
      futures: "📊 العقود الآجلة",
      other: fallback || "السوق"
    };

    return labels[type] || fallback || "السوق";
  }

  /* =========================================================
     MARKET SIGNALS
  ========================================================= */

  window.renderMarketSignals = function (
    containerId,
    items
  ) {
    const container = $(containerId);

    if (!container) {
      return;
    }

    if (
      !Array.isArray(items) ||
      !items.length
    ) {
      container.innerHTML = `
        <div class="empty">
          <strong>
            ما فيه إشارات حالياً
          </strong>

          ننتظر فرصة مطابقة لشروط التحليل.
        </div>
      `;

      return;
    }

    container.innerHTML = items
      .slice(0, 30)
      .map(
        window.renderSignalCard
      )
      .join("");
  };

  /* =========================================================
     LIVE UPDATE
  ========================================================= */

  window.updateLiveSignals = function (
    data
  ) {
    let items = [];

    if (Array.isArray(data)) {
      items = data;
    } else if (
      data &&
      typeof data === "object"
    ) {
      items =
        data.results ||
        data.signals ||
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

    state.results = [
      ...state.signals
    ];

    state.lastUpdate =
      new Date();

    renderAll();
  };

  /* =========================================================
     RENDER ALL
  ========================================================= */

  function renderAll() {
    const items =
      state.signals;

    const buyCount =
      items.filter(
        x =>
          x._type === "buy" ||
          x._type === "buy-strong"
      ).length;

    const sellCount =
      items.filter(
        x =>
          x._type === "sell" ||
          x._type === "sell-strong"
      ).length;

    const countEl =
      $("liveSignalsCount");

    const buyEl =
      $("liveBuyCount");

    const sellEl =
      $("liveSellCount");

    const updateEl =
      $("liveLastUpdate");

    if (countEl) {
      countEl.textContent =
        items.length;
    }

    if (buyEl) {
      buyEl.textContent =
        buyCount;
    }

    if (sellEl) {
      sellEl.textContent =
        sellCount;
    }

    if (updateEl) {
      updateEl.textContent =
        state.lastUpdate
          ? state.lastUpdate.toLocaleTimeString(
              "ar-SA"
            )
          : "-";
    }

    renderTopSignals(
      items
    );

    renderMarket(
      "saudi",
      "saudiSignals"
    );

    renderMarket(
      "forex",
      "forexSignals"
    );

    renderMarket(
      "crypto",
      "cryptoSignals"
    );

    renderMarket(
      "us",
      "usSignals"
    );

    renderMarket(
      "commodities",
      "commoditiesSignals"
    );

    renderMarket(
      "indices",
      "indicesSignals"
    );

    renderMarket(
      "futures",
      "futuresSignals"
    );

    renderRecent(
      items
    );

    renderScanner(
      items
    );
  }

  /* =========================================================
     TOP SIGNALS
  ========================================================= */

  function renderTopSignals(
    items
  ) {
    const container =
      $("topSignals");

    if (!container) {
      return;
    }

    const sorted = [
      ...items
    ]
      .sort(
        (a, b) =>
          getScore(b) -
          getScore(a)
      )
      .slice(0, 6);

    if (!sorted.length) {
      container.innerHTML = `
        <div class="empty">

          <strong>
            بانتظار الإشارات المباشرة
          </strong>

          النظام يعرض الفرص عند وصول بيانات السوق وتحقيق شروط التحليل.

        </div>
      `;

      return;
    }

    container.innerHTML =
      sorted
        .map(
          window.renderSignalCard
        )
        .join("");
  }

  /* =========================================================
     MARKET FILTER
  ========================================================= */

  function renderMarket(
    type,
    containerId
  ) {
    const items =
      state.signals.filter(
        item =>
          item.marketKey === type
      );

    window.renderMarketSignals(
      containerId,
      items
    );
  }

  /* =========================================================
     RECENT
  ========================================================= */

  function renderRecent(
    items
  ) {
    const container =
      $("recentList");

    if (!container) {
      return;
    }

    const recent = [
      ...items
    ]
      .sort(
        (a, b) => {
          const ta =
            Date.parse(
              a.time || ""
            ) || 0;

          const tb =
            Date.parse(
              b.time || ""
            ) || 0;

          return tb - ta;
        }
      )
      .slice(0, 20);

    if (!recent.length) {
      container.innerHTML = `
        <div class="empty">

          <strong>
            لا توجد إشارات حديثة
          </strong>

          ستظهر هنا آخر الإشارات القادمة من السيرفر.

        </div>
      `;

      return;
    }

    container.innerHTML =
      recent
        .map(
          window.renderSignalCard
        )
        .join("");
  }

  /* =========================================================
     SCANNER
  ========================================================= */

  function renderScanner(
    items = state.results
  ) {
    const body =
      $("scannerBody");

    if (!body) {
      return;
    }

    const search =
      (
        $("scannerSearch")
          ?.value || ""
      )
        .trim()
        .toUpperCase();

    let list = [
      ...items
    ];

    if (search) {
      list =
        list.filter(
          item =>
            String(
              item.symbol || ""
            )
              .toUpperCase()
              .includes(search)
        );
    }

    const field =
      $("sortField")
        ?.value ||
      state.sortField;

    list.sort(
      (a, b) => {
        let av = 0;
        let bv = 0;

        if (field === "change") {
          av =
            Number(
              a.change ?? 0
            );

          bv =
            Number(
              b.change ?? 0
            );
        } else if (
          field === "price"
        ) {
          av =
            Number(
              a.price ?? 0
            );

          bv =
            Number(
              b.price ?? 0
            );
        } else {
          av =
            getScore(a);

          bv =
            getScore(b);
        }

        if (
          !Number.isFinite(av)
        ) {
          av = 0;
        }

        if (
          !Number.isFinite(bv)
        ) {
          bv = 0;
        }

        return (
          av - bv
        ) *
        state.sortDir;
      }
    );

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

    body.innerHTML =
      list
        .slice(0, 100)
        .map(
          item => {
            const type =
              item._type ||
              signalType(item);

            const signal =
              signalText(
                type,
                item.signal
              );

            const cls =
              type.includes("buy")
                ? "buy-text"
                : type.includes("sell")
                  ? "sell-text"
                  : "neutral-text";

            const change =
              Number(
                item.change
              );

            const changeClass =
              Number.isFinite(
                change
              )
                ? change >= 0
                  ? "buy-text"
                  : "sell-text"
                : "neutral-text";

            return `
              <tr>

                <td>
                  <strong>
                    ${escapeHTML(
                      item.symbol
                    )}
                  </strong>
                </td>

                <td>
                  ${escapeHTML(
                    marketLabel(
                      item.marketKey,
                      item.market
                    )
                  )}
                </td>

                <td>
                  ${number(
                    item.price,
                    8
                  )}
                </td>

                <td class="${cls}">
                  ${escapeHTML(
                    signal
                  )}
                </td>

                <td class="${changeClass}">
                  ${percent(
                    change
                  )}
                </td>

                <td>
                  ${number(
                    item.score,
                    1
                  )}
                </td>

                <td>
                  ${escapeHTML(
                    item.timeframe ||
                    state.interval
                  )}
                </td>

              </tr>
            `;
          }
        )
        .join("");
  }

  /* =========================================================
     API
  ========================================================= */

  async function fetchJSON(
    url
  ) {
    const response =
      await fetch(
        url,
        {
          method: "GET",
          cache: "no-store",
          headers: {
            Accept:
              "application/json"
          }
        }
      );

    if (!response.ok) {
      throw new Error(
        `HTTP ${response.status}`
      );
    }

    return await response.json();
  }

  /* =========================================================
     SCAN
  ========================================================= */

  async function runScanner() {
    if (state.busy) {
      return;
    }

    state.busy = true;

    const button =
      $("scanBtn");

    const status =
      $("scannerStatus");

    if (button) {
      button.disabled =
        true;

      button.textContent =
        "جاري التحليل...";
    }

    if (status) {
      status.innerHTML =
        `<span class="loading">
          جاري جلب البيانات وتحليل الأسواق...
        </span>`;
    }

    try {
      /*
        السيرفر الحالي يدعم /api/scan
      */

      const url =
        `/api/scan?interval=${encodeURIComponent(
          state.interval
        )}`;

      const data =
        await fetchJSON(
          url
        );

      /*
        لا نستخدم بيانات وهمية.
        إذا السيرفر رجع نتائج فارغة
        نعرض الفراغ فقط.
      */

      window.updateLiveSignals(
        data
      );

      if (status) {
        const count =
          state.signals.length;

        status.textContent =
          `تم تحديث التحليل • ${count} نتيجة • ${new Date().toLocaleTimeString("ar-SA")}`;
      }

    } catch (error) {

      console.error(
        "Mudarib API error:",
        error
      );

      if (status) {
        status.textContent =
          "تعذر جلب بيانات السوق من السيرفر حالياً.";
      }

    } finally {

      state.busy =
        false;

      if (button) {
        button.disabled =
          false;

        button.textContent =
          "تحديث التحليل";
      }
    }
  }

  /* =========================================================
     INTERVALS
  ========================================================= */

  function setupIntervals() {
    const box =
      $("intervalChips");

    if (!box) {
      return;
    }

    const buttons =
      box.querySelectorAll(
        "button"
      );

    buttons.forEach(
      button => {
        button.addEventListener(
          "click",
          () => {

            buttons.forEach(
              x =>
                x.classList.remove(
                  "active"
                )
            );

            button.classList.add(
              "active"
            );

            state.interval =
              button.dataset.interval ||
              button.textContent.trim() ||
              "15m";

            runScanner();
          }
        );
      }
    );
  }

  /* =========================================================
     SEARCH
  ========================================================= */

  function setupSearch() {
    const input =
      $("scannerSearch");

    if (!input) {
      return;
    }

    input.addEventListener(
      "input",
      () =>
        renderScanner()
    );
  }

  /* =========================================================
     SORT
  ========================================================= */

  function setupSort() {
    const select =
      $("sortField");

    if (select) {
      select.addEventListener(
        "change",
        () => {

          state.sortField =
            select.value;

          renderScanner();
        }
      );
    }

    const dir =
      $("sortDir");

    if (dir) {
      dir.addEventListener(
        "click",
        () => {

          state.sortDir *=
            -1;

          dir.textContent =
            state.sortDir === -1
              ? "↓"
              : "↑";

          renderScanner();
        }
      );
    }
  }

  /* =========================================================
     NEWS
  ========================================================= */

  async function loadNews() {
    const container =
      $("newsList");

    if (!container) {
      return;
    }

    const button =
      $("newsBtn");

    if (button) {
      button.disabled =
        true;
    }

    container.innerHTML = `
      <div class="empty">

        <span class="loading">
          جاري جلب الأخبار...
        </span>

      </div>
    `;

    try {

      const data =
        await fetchJSON(
          "/api/news"
        );

      const news =
        Array.isArray(data)
          ? data
          : (
              data?.news ||
              data?.items ||
              data?.results ||
              []
            );

      if (
        !Array.isArray(news) ||
        !news.length
      ) {
        throw new Error(
          "No news"
        );
      }

      container.innerHTML =
        news
          .slice(0, 30)
          .map(
            item => {

              const title =
                item?.title ||
                item?.headline ||
                item?.name ||
                "خبر";

              const source =
                item?.source ||
                item?.publisher ||
                "";

              const time =
                item?.time ||
                item?.date ||
                item?.published_at ||
                "";

              return `
                <article class="news-item">

                  <strong>
                    ${escapeHTML(
                      title
                    )}
                  </strong>

                  <span>
                    ${escapeHTML(
                      source
                    )}

                    ${
                      source &&
                      time
                        ? " • "
                        : ""
                    }

                    ${escapeHTML(
                      time
                    )}
                  </span>

                </article>
              `;
            }
          )
          .join("");

    } catch (error) {

      console.error(
        "News error:",
        error
      );

      container.innerHTML = `
        <div class="empty">

          <strong>
            الأخبار غير متاحة حالياً
          </strong>

          قسم الإشارات لا يعتمد على الأخبار.

        </div>
      `;

    } finally {

      if (button) {
        button.disabled =
          false;
      }
    }
  }

  /* =========================================================
     NAVIGATION
  ========================================================= */

  window.openSection =
    function (id) {

      document
        .querySelectorAll(
          ".section"
        )
        .forEach(
          section =>
            section.classList.remove(
              "active"
            )
        );

      const target =
        $(id);

      if (target) {
        target.classList.add(
          "active"
        );
      }

      document
        .querySelectorAll(
          ".nav button"
        )
        .forEach(
          button => {

            button.classList.remove(
              "active"
            );

            if (
              button.dataset.section ===
                id ||
              button
                .getAttribute(
                  "onclick"
                )
                ?.includes(id)
            ) {
              button.classList.add(
                "active"
              );
            }

          }
        );

      localStorage.setItem(
        "mudarib_last_section",
        id
      );
    };

  function setupNavigation() {
    document
      .querySelectorAll(
        ".nav button"
      )
      .forEach(
        button => {

          button.addEventListener(
            "click",
            () => {

              const section =
                button.dataset.section;

              if (section) {
                window.openSection(
                  section
                );
              }

            }
          );

        }
      );
  }

  /* =========================================================
     MARKET BUTTONS
  ========================================================= */

  function setupMarketButtons() {
    document
      .querySelectorAll(
        "[data-open-section]"
      )
      .forEach(
        button => {

          button.addEventListener(
            "click",
            () => {

              const id =
                button.dataset
                  .openSection;

              if (id) {
                window.openSection(
                  id
                );
              }

            }
          );

        }
      );
  }

  /* =========================================================
     SERVER EVENT
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

    setInterval(
      () => {

        if (
          !document.hidden
        ) {
          runScanner();
        }

      },
      60000
    );
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

    const scanButton =
      $("scanBtn");

    if (scanButton) {
      scanButton.addEventListener(
        "click",
        runScanner
      );
    }

    const newsButton =
      $("newsBtn");

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
      window.openSection(
        savedSection
      );
    } else {
      window.openSection(
        "dashboard"
      );
    }

    /*
      أول تحليل مباشر
    */

    await runScanner();

    startAutoRefresh();
  }

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
