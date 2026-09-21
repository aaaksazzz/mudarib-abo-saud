"use strict";

/* =====================================================
   إعدادات عامة
===================================================== */

const state = {
  symbol: "BTCUSDT",
  interval: "15m",
  markets: [],
  analysis: null,
  chart: null,
  favorites: JSON.parse(localStorage.getItem("favorites") || "[]")
};

const RECENT_KEY = "recent_opportunities_v2";
const HISTORY_KEY = "analysis_history_v1";


/* =====================================================
   أدوات
===================================================== */

const $ = id => document.getElementById(id);

function escapeHTML(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatPrice(value) {

  const n = Number(value);

  if (!Number.isFinite(n)) return "--";

  if (n >= 1000)
    return n.toLocaleString("en-US", {
      maximumFractionDigits: 2
    });

  if (n >= 1)
    return n.toFixed(4);

  if (n >= 0.01)
    return n.toFixed(6);

  return n.toFixed(8);
}

function formatNumber(value) {

  const n = Number(value);

  if (!Number.isFinite(n)) return "--";

  return n.toLocaleString("en-US", {
    maximumFractionDigits: 2
  });
}

function formatPercent(value) {

  const n = Number(value);

  if (!Number.isFinite(n)) return "--";

  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function showStatus(message) {

  if ($("status"))
    $("status").textContent = message;
}

function showError(message) {

  if (!$("errorBox")) return;

  $("errorBox").textContent = message;
  $("errorBox").classList.remove("hidden");
}

function clearError() {

  $("errorBox")?.classList.add("hidden");
}


/* =====================================================
   API
===================================================== */

async function api(url, options = {}) {

  const response = await fetch(url, {
    credentials: "same-origin",
    ...options,
    headers: {
      ...(options.headers || {}),
      "Content-Type": "application/json"
    }
  });

  let data = {};

  try {
    data = await response.json();
  } catch {
    data = {};
  }

  if (!response.ok) {
    throw new Error(
      data.error ||
      data.message ||
      `HTTP ${response.status}`
    );
  }

  if (data.ok === false) {
    throw new Error(data.error || "حدث خطأ");
  }

  return data;
}


/* =====================================================
   التنقل
===================================================== */

function openSection(name) {

  document.querySelectorAll(".section")
    .forEach(section => {
      section.classList.remove("active");
    });

  const target = $(`section-${name}`);

  if (target)
    target.classList.add("active");

  document.querySelectorAll(".nav-item")
    .forEach(btn => {
      btn.classList.toggle(
        "active",
        btn.dataset.section === name
      );
    });

  document.querySelectorAll(".sidebar")
    .forEach(x => x.classList.remove("open"));

  $("sidebarOverlay")?.classList.remove("show");
}


/* =====================================================
   Sidebar
===================================================== */

$("menuBtn")?.addEventListener("click", () => {

  $("sidebar")?.classList.add("open");
  $("sidebarOverlay")?.classList.add("show");

});

$("closeSidebar")?.addEventListener("click", () => {

  $("sidebar")?.classList.remove("open");
  $("sidebarOverlay")?.classList.remove("show");

});

$("sidebarOverlay")?.addEventListener("click", () => {

  $("sidebar")?.classList.remove("open");
  $("sidebarOverlay")?.classList.remove("show");

});

document.querySelectorAll(".nav-item")
  .forEach(btn => {

    btn.addEventListener("click", () => {

      openSection(btn.dataset.section);

      if (btn.dataset.section === "recent")
        renderRecentTrades();

      if (btn.dataset.section === "favorites")
        renderFavorites();

    });

  });


/* =====================================================
   Binance Markets
===================================================== */

async function loadMarkets() {

  try {

    showStatus("جاري تحميل العملات...");
    clearError();

    const data =
      await api("/api/binance/markets");

    let markets =
      data.markets ||
      data.symbols ||
      data.data ||
      [];

    if (!Array.isArray(markets))
      markets = [];

    state.markets = markets
      .map(item => {

        if (typeof item === "string")
          return {
            symbol: item,
            baseAsset: item.replace("USDT", "")
          };

        return {
          symbol:
            item.symbol ||
            item.s ||
            "",
          baseAsset:
            item.baseAsset ||
            item.base ||
            ""
        };

      })
      .filter(x => x.symbol);

    renderMarkets();

    $("coinCount").textContent =
      state.markets.length;

    $("coinCountSmall").textContent =
      state.markets.length;

    showStatus(
      `تم تحميل ${state.markets.length} عملة`
    );

    if (
      state.markets.length &&
      !state.markets.some(
        x => x.symbol === state.symbol
      )
    ) {
      state.symbol =
        state.markets[0].symbol;
    }

    await analyzeCurrent();

  } catch (error) {

    console.error(error);

    showError(
      "تعذر تحميل العملات: " +
      error.message
    );

    showStatus("تعذر الاتصال بالسوق");

  }

}


function renderMarkets(filter = "") {

  const box = $("coinList");

  if (!box) return;

  const search =
    filter.trim().toUpperCase();

  const list =
    state.markets
      .filter(item =>
        item.symbol.includes(search)
      )
      .slice(0, 150);

  if (!list.length) {

    box.innerHTML =
      `<div class="empty">لا توجد عملات.</div>`;

    return;
  }

  box.innerHTML = list.map(item => {

    const active =
      item.symbol === state.symbol
        ? "active"
        : "";

    const fav =
      state.favorites.includes(item.symbol)
        ? "★"
        : "☆";

    return `
      <button
        class="coin-row ${active}"
        data-symbol="${escapeHTML(item.symbol)}"
      >
        <span class="coin-row-name">
          <strong>${escapeHTML(item.symbol)}</strong>
        </span>

        <span class="coin-fav">
          ${fav}
        </span>
      </button>
    `;

  }).join("");

  box.querySelectorAll(".coin-row")
    .forEach(row => {

      row.addEventListener("click", () => {

        state.symbol =
          row.dataset.symbol;

        renderMarkets(
          $("coinSearch")?.value || ""
        );

        analyzeCurrent();

      });

    });

}


/* =====================================================
   Price
===================================================== */

async function loadPrice() {

  try {

    const data =
      await api(
        `/api/binance/price?symbol=${encodeURIComponent(state.symbol)}`
      );

    const price =
      data.price ??
      data.lastPrice ??
      data.data?.price;

    if (price != null)
      $("currentPrice").textContent =
        formatPrice(price);

    const change =
      data.changePercent ??
      data.change ??
      data.data?.changePercent;

    if (change != null) {

      const n = Number(change);

      $("priceChange").textContent =
        formatPercent(n);

      $("priceChange").className =
        n >= 0
          ? "positive price-change"
          : "negative price-change";

    }

    if (data.highPrice != null)
      $("high24h").textContent =
        formatPrice(data.highPrice);

    if (data.lowPrice != null)
      $("low24h").textContent =
        formatPrice(data.lowPrice);

    if (data.volume != null)
      $("volume24h").textContent =
        formatNumber(data.volume);

  } catch (error) {

    console.error("PRICE", error);

  }

}


/* =====================================================
   Analysis
===================================================== */

async function analyzeCurrent() {

  if (!state.symbol) return;

  try {

    clearError();

    $("symbolName").textContent =
      state.symbol;

    $("signal").textContent =
      "جاري التحليل...";

    showStatus(
      `جاري تحليل ${state.symbol} على ${state.interval}`
    );

    await loadPrice();

    const data =
      await api(
        `/api/binance/analysis?symbol=${encodeURIComponent(state.symbol)}&interval=${encodeURIComponent(state.interval)}`
      );

    const a =
      data.analysis ||
      data.data ||
      data;

    state.analysis = a;

    renderAnalysis(a);

    await loadChart(a);

    saveHistory(a);

    showStatus(
      `تم تحليل ${state.symbol}`
    );

  } catch (error) {

    console.error("ANALYSIS", error);

    showError(
      "تعذر تحليل العملة: " +
      error.message
    );

    $("signal").textContent =
      "تعذر التحليل";

  }

}


function renderAnalysis(a) {

  if (!a) return;

  const signal =
    a.signal ||
    "حيادي";

  const score =
    Number(
      a.score ??
      a.score10 ??
      0
    );

  $("signal").textContent =
    signal;

  $("score").textContent =
    Math.round(score);

  $("signalProgress").style.width =
    `${Math.max(0, Math.min(100, score))}%`;

  setSignalStyle(
    $("signal"),
    signal
  );


  $("entry").textContent =
    formatPrice(a.entry);

  $("tp1").textContent =
    formatPrice(a.tp1);

  $("tp2").textContent =
    formatPrice(a.tp2);

  $("tp3").textContent =
    formatPrice(a.tp3);

  $("sl").textContent =
    formatPrice(a.sl);

  $("rr").textContent =
    a.rr != null
      ? String(a.rr)
      : "--";


  $("rsi").textContent =
    formatNumber(a.rsi);

  $("ema20").textContent =
    formatPrice(a.ema20);

  $("ema50").textContent =
    formatPrice(a.ema50);

  $("ema200").textContent =
    formatPrice(a.ema200);

  $("macd").textContent =
    formatNumber(a.macd);

  $("atr").textContent =
    formatPrice(a.atr);

  $("volumeRatio").textContent =
    a.volume_ratio != null
      ? `${Number(a.volume_ratio).toFixed(2)}x`
      : "--";

  $("support").textContent =
    formatPrice(a.support);

  $("resistance").textContent =
    formatPrice(a.resistance);


  $("rsiStatus").textContent =
    rsiStatus(a.rsi);

  $("macdStatus").textContent =
    Number(a.macd_histogram || 0) >= 0
      ? "إيجابي"
      : "سلبي";

  $("trend").textContent =
    a.direction ||
    trendFromEMA(a);


  const reasons =
    a.reasons || [];

  if (Array.isArray(reasons)) {

    $("reasons").innerHTML =
      reasons.length
        ? reasons.map(x =>
            `<div class="reason">• ${escapeHTML(x)}</div>`
          ).join("")
        : "لا توجد أسباب.";

  } else {

    $("reasons").textContent =
      String(reasons || "لا توجد أسباب.");

  }

  $("marketRegime").textContent =
    signal;

}


function setSignalStyle(element, signal) {

  if (!element) return;

  element.classList.remove(
    "signal-strong-buy",
    "signal-buy",
    "signal-neutral",
    "signal-sell",
    "signal-strong-sell"
  );

  if (signal === "شراء قوي")
    element.classList.add("signal-strong-buy");

  else if (signal === "شراء")
    element.classList.add("signal-buy");

  else if (signal === "بيع قوي")
    element.classList.add("signal-strong-sell");

  else if (signal === "بيع")
    element.classList.add("signal-sell");

  else
    element.classList.add("signal-neutral");

}


function rsiStatus(rsi) {

  const n = Number(rsi);

  if (!Number.isFinite(n))
    return "--";

  if (n >= 70)
    return "تشبع شراء";

  if (n <= 30)
    return "تشبع بيع";

  if (n >= 50)
    return "إيجابي";

  return "ضعيف";
}


function trendFromEMA(a) {

  const price =
    Number(a.price || 0);

  const ema =
    Number(a.ema200 || 0);

  if (!price || !ema)
    return "--";

  return price >= ema
    ? "صاعد"
    : "هابط";
}


/* =====================================================
   Timeframes
===================================================== */

document.querySelectorAll(
  "[data-interval]"
).forEach(btn => {

  btn.addEventListener("click", () => {

    state.interval =
      btn.dataset.interval;

    document
      .querySelectorAll("[data-interval]")
      .forEach(x =>
        x.classList.remove("active")
      );

    document
      .querySelectorAll(
        `[data-interval="${state.interval}"]`
      )
      .forEach(x =>
        x.classList.add("active")
      );

    const chartTF =
      $("chartTimeframe");

    if (chartTF)
      chartTF.value =
        state.interval;

    analyzeCurrent();

  });

});


$("chartTimeframe")
  ?.addEventListener("change", e => {

    state.interval =
      e.target.value;

    analyzeCurrent();

  });


/* =====================================================
   Chart
===================================================== */

async function loadChart(analysis) {

  if (!window.Chart)
    return;

  const candles =
    analysis?.candles || [];

  if (!Array.isArray(candles) ||
      candles.length < 2)
    return;

  const labels =
    candles.map(c =>
      new Date(
        Number(c[0] || c.time || 0)
      ).toLocaleTimeString(
        "ar-SA",
        {
          hour: "2-digit",
          minute: "2-digit"
        }
      )
    );

  const values =
    candles.map(c =>
      Number(c[4] || c.close || 0)
    );

  const canvas =
    $("priceChart");

  if (!canvas) return;

  if (state.chart)
    state.chart.destroy();

  state.chart =
    new Chart(
      canvas.getContext("2d"),
      {
        type: "line",

        data: {
          labels,

          datasets: [
            {
              label: state.symbol,
              data: values,
              borderWidth: 2,
              pointRadius: 0,
              tension: .25
            }
          ]
        },

        options: {
          responsive: true,
          maintainAspectRatio: false,

          plugins: {
            legend: {
              display: false
            }
          },

          scales: {
            x: {
              display: true
            },

            y: {
              display: true
            }
          }
        }
      }
    );

}


/* =====================================================
   🔎 ماسح الفرص
===================================================== */

async function runScanner() {

  const tbody =
    $("scannerResults");

  if (!tbody)
    return;

  const interval =
    $("scannerInterval")?.value ||
    "15m";

  const signalFilter =
    $("scannerSignal")?.value ||
    "ALL";

  const sortBy =
    $("scannerSort")?.value ||
    "change";

  const limit =
    Number(
      $("scannerLimit")?.value ||
      100
    );

  tbody.innerHTML =
    `<tr>
      <td colspan="6">
        🔄 جاري فحص العملات...
      </td>
    </tr>`;

  showStatus(
    `جاري فحص الفرص على ${interval}...`
  );

  try {

    const data =
      await api(
        `/api/binance/scan?interval=${encodeURIComponent(interval)}&limit=${limit}`
      );

    let results =
      Array.isArray(data.results)
        ? data.results
        : [];

    if (signalFilter !== "ALL") {

      results =
        results.filter(
          item =>
            item.signal === signalFilter
        );

    }

    results.sort(
      (a, b) =>
        scannerValue(b, sortBy) -
        scannerValue(a, sortBy)
    );

    $("scannerCount").textContent =
      results.length;

    if (!results.length) {

      tbody.innerHTML =
        `<tr>
          <td colspan="6">
            لا توجد نتائج مطابقة.
          </td>
        </tr>`;

      return;
    }

    tbody.innerHTML =
      results.map(item => {

        const signal =
          item.signal || "حيادي";

        const price =
          item.price ??
          item.entry ??
          0;

        const change =
          Number(
            item.change ??
            item.changePercent ??
            0
          );

        const score =
          Number(
            item.score ??
            item.score10 ??
            0
          );

        return `
          <tr
            class="scanner-row"
            data-symbol="${escapeHTML(item.symbol || "")}"
          >

            <td>
              <strong>
                ${escapeHTML(item.symbol || "--")}
              </strong>
            </td>

            <td>
              ${formatPrice(price)}
            </td>

            <td class="${
              change >= 0
                ? "positive"
                : "negative"
            }">
              ${formatPercent(change)}
            </td>

            <td class="${signalClass(signal)}">
              ${signalIcon(signal)}
              ${escapeHTML(signal)}
            </td>

            <td>
              <strong>${Math.round(score)}</strong>
            </td>

            <td>${interval}</td>

          </tr>
        `;

      }).join("");


    tbody.querySelectorAll(
      ".scanner-row"
    ).forEach(row => {

      row.addEventListener(
        "click",
        () => {

          const symbol =
            row.dataset.symbol;

          if (!symbol)
            return;

          state.symbol =
            symbol;

          state.interval =
            interval;

          renderMarkets();

          openSection("dashboard");

          analyzeCurrent();

        }
      );

    });


    /*
      حفظ الإشارات الجديدة
    */

    results.forEach(item => {

      const signal =
        item.signal || "حيادي";

      if (
        signal === "شراء قوي" ||
        signal === "شراء" ||
        signal === "بيع قوي" ||
        signal === "بيع"
      ) {

        addRecentTrade({

          symbol:
            item.symbol,

          price:
            item.price ??
            item.entry ??
            0,

          change:
            item.change ??
            item.changePercent ??
            0,

          signal,

          interval,

          score:
            item.score ??
            item.score10 ??
            0,

          tp1:
            item.tp1,

          tp2:
            item.tp2,

          tp3:
            item.tp3,

          sl:
            item.sl,

          time:
            new Date().toLocaleString(
              "ar-SA"
            )

        });

      }

    });

    showStatus(
      `تم فحص ${results.length} فرصة`
    );

  } catch (error) {

    console.error(error);

    tbody.innerHTML =
      `<tr>
        <td colspan="6">
          ❌ ${escapeHTML(error.message)}
        </td>
      </tr>`;

    showError(
      "ماسح الفرص: " +
      error.message
    );

  }

}


function scannerValue(item, sortBy) {

  if (sortBy === "price")
    return Number(
      item.price ||
      item.entry ||
      0
    );

  if (sortBy === "score")
    return Number(
      item.score ||
      item.score10 ||
      0
    );

  if (sortBy === "volume")
    return Number(
      item.volume ||
      item.volume24h ||
      0
    );

  return Number(
    item.change ||
    item.changePercent ||
    0
  );

}


function signalClass(signal) {

  if (signal === "شراء قوي")
    return "signal-strong-buy";

  if (signal === "شراء")
    return "signal-buy";

  if (signal === "بيع قوي")
    return "signal-strong-sell";

  if (signal === "بيع")
    return "signal-sell";

  return "signal-neutral";
}


function signalIcon(signal) {

  if (signal === "شراء قوي")
    return "🟢🟢";

  if (signal === "شراء")
    return "🟢";

  if (signal === "بيع قوي")
    return "🔴🔴";

  if (signal === "بيع")
    return "🔴";

  return "⚪";
}


/* =====================================================
   ⚡ الصفقات الحديثة
===================================================== */

function getRecentTrades() {

  try {

    return JSON.parse(
      localStorage.getItem(
        RECENT_KEY
      ) || "[]"
    );

  } catch {

    return [];

  }

}


function saveRecentTrades(list) {

  localStorage.setItem(
    RECENT_KEY,
    JSON.stringify(
      list.slice(0, 100)
    )
  );

}


function addRecentTrade(item) {

  const list =
    getRecentTrades();

  /*
    منع تكرار نفس العملة والإشارة
    في نفس الفاصل خلال الفحص الحالي
  */

  const duplicate =
    list.find(x =>
      x.symbol === item.symbol &&
      x.interval === item.interval &&
      x.signal === item.signal
    );

  if (duplicate)
    return;

  list.unshift(item);

  saveRecentTrades(list);

  renderRecentTrades();

}


function renderRecentTrades() {

  const tbody =
    $("recentTradeRows");

  if (!tbody)
    return;

  const list =
    getRecentTrades();

  if (!list.length) {

    tbody.innerHTML =
      `<tr>
        <td colspan="6">
          لا توجد إشارات حديثة
        </td>
      </tr>`;

    return;
  }

  tbody.innerHTML =
    list.map(item => {

      const change =
        Number(item.change || 0);

      return `
        <tr>

          <td>
            <strong>
              ${escapeHTML(item.symbol)}
            </strong>
          </td>

          <td>
            ${formatPrice(item.price)}
          </td>

          <td class="${
            change >= 0
              ? "positive"
              : "negative"
          }">
            ${formatPercent(change)}
          </td>

          <td class="${signalClass(item.signal)}">
            ${signalIcon(item.signal)}
            ${escapeHTML(item.signal)}
          </td>

          <td>
            ${escapeHTML(item.interval)}
          </td>

          <td>
            ${escapeHTML(item.time)}
          </td>

        </tr>
      `;

    }).join("");

}


/* =====================================================
   Favorites
===================================================== */

function saveFavorites() {

  localStorage.setItem(
    "favorites",
    JSON.stringify(
      state.favorites
    )
  );

}


function toggleFavorite() {

  const index =
    state.favorites.indexOf(
      state.symbol
    );

  if (index >= 0)
    state.favorites.splice(index, 1);
  else
    state.favorites.push(
      state.symbol
    );

  saveFavorites();

  updateFavoriteButton();

  renderMarkets(
    $("coinSearch")?.value || ""
  );

  renderFavorites();

}


function updateFavoriteButton() {

  const btn =
    $("favoriteBtn");

  if (!btn)
    return;

  btn.textContent =
    state.favorites.includes(
      state.symbol
    )
      ? "★"
      : "☆";

}


function renderFavorites() {

  const box =
    $("favoritesList");

  if (!box)
    return;

  if (!state.favorites.length) {

    box.innerHTML =
      `<div class="empty">
        لا توجد عملات مفضلة.
      </div>`;

    return;
  }

  box.innerHTML =
    state.favorites.map(symbol => `
      <button
        class="favorite-card"
        data-symbol="${escapeHTML(symbol)}"
      >
        ⭐
        <strong>${escapeHTML(symbol)}</strong>
      </button>
    `).join("");

  box.querySelectorAll(
    ".favorite-card"
  ).forEach(btn => {

    btn.addEventListener(
      "click",
      () => {

        state.symbol =
          btn.dataset.symbol;

        openSection("dashboard");

        renderMarkets();

        analyzeCurrent();

      }
    );

  });

}


/* =====================================================
   History
===================================================== */

function saveHistory(analysis) {

  if (!analysis)
    return;

  let list = [];

  try {

    list =
      JSON.parse(
        localStorage.getItem(
          HISTORY_KEY
        ) || "[]"
      );

  } catch {

    list = [];

  }

  list.unshift({

    symbol:
      state.symbol,

    interval:
      state.interval,

    signal:
      analysis.signal,

    score:
      analysis.score ??
      analysis.score10,

    price:
      analysis.price,

    time:
      new Date().toLocaleString(
        "ar-SA"
      )

  });

  localStorage.setItem(
    HISTORY_KEY,
    JSON.stringify(
      list.slice(0, 100)
    )
  );

  renderHistory();

}


function renderHistory() {

  const box =
    $("historyList");

  if (!box)
    return;

  let list = [];

  try {

    list =
      JSON.parse(
        localStorage.getItem(
          HISTORY_KEY
        ) || "[]"
      );

  } catch {}

  if (!list.length) {

    box.innerHTML =
      `<div class="empty">
        لا يوجد سجل.
      </div>`;

    return;

  }

  box.innerHTML =
    list.slice(0, 50).map(item => `
      <div class="history-row">

        <strong>
          ${escapeHTML(item.symbol)}
        </strong>

        <span>
          ${escapeHTML(item.interval)}
        </span>

        <span class="${signalClass(item.signal)}">
          ${signalIcon(item.signal)}
          ${escapeHTML(item.signal)}
        </span>

        <span>
          ${formatPrice(item.price)}
        </span>

        <small>
          ${escapeHTML(item.time)}
        </small>

      </div>
    `).join("");

}


/* =====================================================
   Auth
===================================================== */

async function checkAuth() {

  try {

    const data =
      await api("/api/auth/me");

    const user =
      data.user ||
      data.data ||
      null;

    if (user) {

      $("loginBtn")
        ?.classList.add("hidden");

      $("logoutBtn")
        ?.classList.remove("hidden");

      if (
        user.is_admin ||
        user.admin
      ) {

        $("adminLink")
          ?.classList.remove("hidden");

      }

    } else {

      $("loginBtn")
        ?.classList.remove("hidden");

      $("logoutBtn")
        ?.classList.add("hidden");

    }

  } catch {

    $("loginBtn")
      ?.classList.remove("hidden");

  }

}


$("loginBtn")
  ?.addEventListener(
    "click",
    () => {

      $("authModal")
        ?.classList.remove("hidden");

      showLogin();

    }
  );


$("closeAuth")
  ?.addEventListener(
    "click",
    () =>
      $("authModal")
        ?.classList.add("hidden")
  );


function showLogin() {

  $("loginForm")
    ?.classList.remove("hidden");

  $("registerForm")
    ?.classList.add("hidden");

  $("showRegisterBtn")
    ?.classList.remove("hidden");

  $("showLoginBtn")
    ?.classList.add("hidden");

  $("authTitle").textContent =
    "تسجيل الدخول";

  $("authSubtitle").textContent =
    "ادخل لحسابك.";

}


function showRegister() {

  $("loginForm")
    ?.classList.add("hidden");

  $("registerForm")
    ?.classList.remove("hidden");

  $("showRegisterBtn")
    ?.classList.add("hidden");

  $("showLoginBtn")
    ?.classList.remove("hidden");

  $("authTitle").textContent =
    "إنشاء حساب";

  $("authSubtitle").textContent =
    "أنشئ حسابك للمتابعة.";

}


$("showRegisterBtn")
  ?.addEventListener(
    "click",
    showRegister
  );

$("showLoginBtn")
  ?.addEventListener(
    "click",
    showLogin
  );


$("loginForm")
  ?.addEventListener(
    "submit",
    async event => {

      event.preventDefault();

      try {

        const email =
          $("loginEmail").value;

        const password =
          $("loginPassword").value;

        await api(
          "/api/auth/login",
          {
            method: "POST",

            body: JSON.stringify({
              email,
              password
            })
          }
        );

        $("authModal")
          .classList.add("hidden");

        await checkAuth();

      } catch (error) {

        alert(
          error.message
        );

      }

    }
  );


$("registerForm")
  ?.addEventListener(
    "submit",
    async event => {

      event.preventDefault();

      try {

        const name =
          $("registerName").value;

        const email =
          $("registerEmail").value;

        const password =
          $("registerPassword").value;

        await api(
          "/api/auth/register",
          {
            method: "POST",

            body: JSON.stringify({
              name,
              email,
              password
            })
          }
        );

        alert(
          "تم إنشاء الحساب"
        );

        showLogin();

      } catch (error) {

        alert(
          error.message
        );

      }

    }
  );


$("logoutBtn")
  ?.addEventListener(
    "click",
    async () => {

      try {

        await api(
          "/api/auth/logout",
          {
            method: "POST"
          }
        );

      } catch {}

      await checkAuth();

    }
  );


/* =====================================================
   Premium
===================================================== */

function openPremium() {

  $("premiumModal")
    ?.classList.remove("hidden");

}

function closePremium() {

  $("premiumModal")
    ?.classList.add("hidden");

}

$("premiumBtn")
  ?.addEventListener(
    "click",
    openPremium
  );

$("premiumOpenBtn")
  ?.addEventListener(
    "click",
    openPremium
  );

$("closePremium")
  ?.addEventListener(
    "click",
    closePremium
  );

$("subscribeBtn")
  ?.addEventListener(
    "click",
    () => {

      alert(
        "سيتم إضافة طريقة الدفع عند تفعيل الاشتراك."
      );

    }
  );


/* =====================================================
   Settings
===================================================== */

async function loadSettings() {

  try {

    const data =
      await api("/api/settings");

    const settings =
      data.settings ||
      data.data ||
      data;

    if (settings.interval)
      $("intervalSetting").value =
        settings.interval;

    if (settings.refresh)
      $("refreshSetting").value =
        settings.refresh;

    if (
      settings.notifications !== undefined
    ) {

      $("notificationsSetting").checked =
        Boolean(
          settings.notifications
        );

    }

  } catch {}

}


$("saveSettingsBtn")
  ?.addEventListener(
    "click",
    async () => {

      try {

        await api(
          "/api/settings",
          {
            method: "POST",

            body: JSON.stringify({

              interval:
                $("intervalSetting").value,

              refresh:
                $("refreshSetting").value,

              notifications:
                $("notificationsSetting").checked

            })
          }
        );

        $("settingsMessage").textContent =
          "تم حفظ الإعدادات ✓";

      } catch (error) {

        $("settingsMessage").textContent =
          error.message;

      }

    }
  );


/* =====================================================
   Search / Refresh
===================================================== */

$("coinSearch")
  ?.addEventListener(
    "input",
    event =>
      renderMarkets(
        event.target.value
      )
  );


$("refreshBtn")
  ?.addEventListener(
    "click",
    async () => {

      await loadMarkets();

    }
  );


$("favoriteBtn")
  ?.addEventListener(
    "click",
    toggleFavorite
  );


/* =====================================================
   Scanner controls
===================================================== */

$("runScannerBtn")
  ?.addEventListener(
    "click",
    runScanner
  );

$("scannerInterval")
  ?.addEventListener(
    "change",
    runScanner
  );

$("scannerSignal")
  ?.addEventListener(
    "change",
    runScanner
  );

$("scannerSort")
  ?.addEventListener(
    "change",
    runScanner
  );

$("scannerLimit")
  ?.addEventListener(
    "change",
    runScanner
  );


$("clearRecentBtn")
  ?.addEventListener(
    "click",
    () => {

      localStorage.removeItem(
        RECENT_KEY
      );

      renderRecentTrades();

    }
  );


/* =====================================================
   Theme
===================================================== */

$("themeDark")
  ?.addEventListener(
    "click",
    () => {

      document.body.classList.add(
        "dark"
      );

      localStorage.setItem(
        "theme",
        "dark"
      );

    }
  );


$("themeLight")
  ?.addEventListener(
    "click",
    () => {

      document.body.classList.remove(
        "dark"
      );

      localStorage.setItem(
        "theme",
        "light"
      );

    }
  );


function loadTheme() {

  const theme =
    localStorage.getItem(
      "theme"
    );

  if (theme === "dark")
    document.body.classList.add(
      "dark"
    );

}


/* =====================================================
   Auto Scanner
===================================================== */

let scannerTimer = null;

function startScannerTimer() {

  if (scannerTimer)
    clearInterval(scannerTimer);

  const seconds =
    Number(
      $("refreshSetting")?.value ||
      60
    );

  scannerTimer =
    setInterval(
      () => {

        if (
          document
            .getElementById(
              "section-scanner"
            )
            ?.classList.contains(
              "active"
            )
        ) {

          runScanner();

        }

      },
      Math.max(
        30,
        seconds
      ) * 1000
    );

}


/* =====================================================
   Init
===================================================== */

document.addEventListener(
  "DOMContentLoaded",
  async () => {

    loadTheme();

    renderRecentTrades();

    renderHistory();

    renderFavorites();

    updateFavoriteButton();

    await checkAuth();

    await loadSettings();

    await loadMarkets();

    startScannerTimer();

  }
);
