"use strict";

/* =========================================================
   مضارب أبو سعود — app.js
   الاشتراك يظهر لجميع المستخدمين
   ========================================================= */

// Cross-browser DOM helpers
const $ = (id) => document.getElementById(id);
const qs = (selector) => document.querySelector(selector);
const qsa = (selector) => [...document.querySelectorAll(selector)];

const state = {
  user: null,
  admin: false,

  market: localStorage.getItem("mudarib_market") || "crypto",
  interval: "15m",
  symbol: "BTCUSDT",

  results: [],
  signals: new Set(),

  sort: "change",
  dir: -1,

  busy: false,
  chart: null,

  plan: null,

  recent: loadStoredRecent(),

  loaded: {
    saudi: false,
    usmarket: false,
    forex: false,
    futures: false,
    news: false
  }
};


/* =========================================================
   أدوات عامة
   ========================================================= */

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function loadStoredRecent() {
  try {
    const raw = localStorage.getItem("mudarib_recent");
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.slice(0, 30) : [];
  } catch (error) {
    console.warn("Recent storage:", error);
    return [];
  }
}

function normalizePayload(data) {
  if (!data || typeof data !== "object") return {};
  const nested = data.data;
  if (
    nested &&
    typeof nested === "object" &&
    !Array.isArray(nested)
  ) {
    return nested;
  }
  return data;
}

function extractRows(data) {
  const payload = normalizePayload(data);
  if (Array.isArray(payload.results)) return payload.results;
  if (Array.isArray(payload.signals)) return payload.signals;
  if (Array.isArray(payload.items)) return payload.items;
  if (Array.isArray(payload.data)) return payload.data;
  return [];
}

function formatNumber(value, digits = 6) {
  if (
    value === null ||
    value === undefined ||
    value === "" ||
    Number.isNaN(Number(value))
  ) {
    return "-";
  }

  const n = Number(value);

  if (!Number.isFinite(n)) {
    return "-";
  }

  if (Math.abs(n) >= 1000) {
    return n.toLocaleString("en-US", {
      maximumFractionDigits: 2
    });
  }

  return n.toLocaleString("en-US", {
    maximumFractionDigits: digits
  });
}

function formatPercent(value) {
  if (
    value === null ||
    value === undefined ||
    value === "" ||
    Number.isNaN(Number(value))
  ) {
    return "-";
  }

  const n = Number(value);

  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function signalClass(signal) {
  const s = String(signal || "").toLowerCase();

  if (
    s.includes("شراء قوي") ||
    s.includes("strong buy") ||
    s.includes("strong_buy")
  ) {
    return "strong-buy";
  }

  if (
    s === "شراء" ||
    s.includes("buy")
  ) {
    return "buy";
  }

  if (
    s.includes("بيع قوي") ||
    s.includes("strong sell") ||
    s.includes("strong_sell")
  ) {
    return "strong-sell";
  }

  if (
    s === "بيع" ||
    s.includes("sell")
  ) {
    return "sell";
  }

  return "neutral";
}

function setText(id, value) {
  const el = $(id);

  if (el) {
    el.textContent = value ?? "-";
  }
}

function setHtml(id, value) {
  const el = $(id);

  if (el) {
    el.innerHTML = value ?? "";
  }
}

function show(el) {
  if (el) {
    el.hidden = false;
  }
}

function hide(el) {
  if (el) {
    el.hidden = true;
  }
}


/* =========================================================
   API
   ========================================================= */

async function api(url, options = {}) {

  const headers = {
    Accept: "application/json",
    ...(options.headers || {})
  };

  if (
    options.body &&
    !headers["Content-Type"]
  ) {
    headers["Content-Type"] =
      "application/json";
  }

  const response =
    await fetch(
      url,
      {
        ...options,
        headers,
        credentials: "same-origin",
        cache: "no-store"
      }
    );

  let data = null;

  const contentType =
    response.headers.get(
      "content-type"
    ) || "";

  if (
    contentType.includes(
      "application/json"
    )
  ) {

    data =
      await response
        .json()
        .catch(() => ({}));

  } else {

    const text =
      await response
        .text()
        .catch(() => "");

    try {

      data =
        JSON.parse(text);

    } catch {

      data = {
        ok: response.ok,
        message:
          text ||
          response.statusText
      };
    }
  }

  if (!response.ok) {

    throw new Error(
      data?.message ||
      data?.error ||
      `HTTP ${response.status}`
    );
  }

  if (
    data &&
    data.ok === false
  ) {

    throw new Error(
      data.message ||
      data.error ||
      "تعذر تنفيذ الطلب"
    );
  }

  return data;
}


/* =========================================================
   التنقل — نظام موحد للصفحات المستقلة
   ========================================================= */

const ROUTES = Object.freeze({
  dashboard: "/",
  scanner: "/scanner",
  recent: "/recent",
  saudi: "/saudi",
  usmarket: "/usmarket",
  forex: "/forex",
  futures: "/futures",
  news: "/news",
  subscription: "/subscription"
});

const MARKET_ROUTES = Object.freeze({
  crypto: "dashboard",
  saudi: "saudi",
  usmarket: "usmarket",
  forex: "forex",
  futures: "futures"
});

const MARKET_TITLES = Object.freeze({
  crypto: "🪙 العملات الرقمية",
  saudi: "🇸🇦 السوق السعودي",
  usmarket: "🇺🇸 السوق الأمريكي",
  forex: "💱 الفوركس",
  futures: "📈 الفيوتشر"
});

function closeMobileNav() {
  const sidebar = qs(".sidebar");
  if (sidebar) sidebar.classList.remove("open");
  document.body.classList.remove("sidebar-open");
  const menuBtn = $("menuBtn");
  if (menuBtn) menuBtn.setAttribute("aria-expanded", "false");
}

function openMobileNav() {
  const sidebar = qs(".sidebar");
  if (!sidebar) return;
  const open = sidebar.classList.toggle("open");
  document.body.classList.toggle("sidebar-open", open);
  const menuBtn = $("menuBtn");
  if (menuBtn) menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
}

function navigateToSection(section) {
  const target = ROUTES[section] || ROUTES.dashboard;
  if (window.location.pathname !== target) {
    window.location.assign(target);
  }
}

function applyMarket(market, navigate = true) {
  const selected = Object.prototype.hasOwnProperty.call(MARKET_ROUTES, market)
    ? market
    : "crypto";

  state.market = selected;
  localStorage.setItem("mudarib_market", selected);
  document.body.dataset.market = selected;

  const selector = $("marketSelect");
  if (selector) selector.value = selected;

  qsa(".market-card[data-market], [data-market]").forEach(el => {
    el.classList.toggle("active", el.dataset.market === selected);
    if (el.dataset.market) el.setAttribute("aria-current", el.dataset.market === selected ? "page" : "false");
  });

  setText("marketTitle", MARKET_TITLES[selected]);

  if (navigate) navigateToSection(MARKET_ROUTES[selected]);
}

function setupMarketSelector() {
  const selector = $("marketSelect");
  if (selector) {
    selector.value = state.market;
    selector.addEventListener("change", () => applyMarket(selector.value, true));
  }

  qsa(".market-card[data-market]").forEach(el => {
    el.addEventListener("click", event => {
      const market = el.dataset.market;
      if (!market || !MARKET_ROUTES[market]) return;

      state.market = market;
      localStorage.setItem("mudarib_market", market);
      document.body.dataset.market = market;

      // نخلي الرابط الحقيقي يعمل حتى مع تعطيل JavaScript.
      // فقط نمنع الانتقال إذا كنا أصلًا في الصفحة المطلوبة.
      const target = ROUTES[MARKET_ROUTES[market]];
      if (window.location.pathname === target) {
        event.preventDefault();
      }
      closeMobileNav();
    });
  });
}

function setupNavigation() {
  const page = document.body.dataset.page || "dashboard";
  const currentRoute = ROUTES[page] || window.location.pathname;

  qsa("[data-section]").forEach(link => {
    const section = link.dataset.section;
    if (!section || !ROUTES[section]) return;

    link.classList.toggle("active", section === page);
    link.setAttribute("aria-current", section === page ? "page" : "false");

    link.addEventListener("click", event => {
      closeMobileNav();
      const target = ROUTES[section];

      // الروابط الحقيقية هي المصدر الأساسي للتنقل.
      // إذا كان العنصر رابطًا، نترك المتصفح ينتقل مباشرة.
      if (link.tagName !== "A") {
        event.preventDefault();
        window.location.assign(target);
      }
    });
  });

  const menuBtn = $("menuBtn");
  if (menuBtn) {
    menuBtn.type = "button";
    menuBtn.setAttribute("aria-controls", "sidebar");
    menuBtn.setAttribute("aria-expanded", "false");
    menuBtn.addEventListener("click", event => {
      event.preventDefault();
      openMobileNav();
    });
  }

  const sidebar = $("sidebar");
  if (sidebar) {
    sidebar.addEventListener("click", event => {
      const link = event.target.closest("a");
      if (link && link.dataset.section) closeMobileNav();
    });
  }

  document.addEventListener("click", event => {
    if (!sidebar?.classList.contains("open")) return;
    if (sidebar.contains(event.target) || menuBtn?.contains(event.target)) return;
    closeMobileNav();
  });

  document.addEventListener("keydown", event => {
    if (event.key === "Escape") closeMobileNav();
  });

  window.addEventListener("resize", () => {
    if (window.innerWidth > 1000) closeMobileNav();
  });

  if (currentRoute === window.location.pathname) {
    qsa("[data-section]").forEach(link => {
      const active = link.dataset.section === page;
      link.classList.toggle("active", active);
      link.setAttribute("aria-current", active ? "page" : "false");
    });
  }
}

function showSection(sectionId) {
  const sections = qsa(".section");
  if (!sections.length) {
    navigateToSection(sectionId);
    return;
  }

  sections.forEach(section => {
    const active = section.id === sectionId;
    section.classList.toggle("active", active);
    section.hidden = !active;
  });

  const titles = {
    dashboard: "الرئيسية",
    scanner: "ماسح الفرص",
    recent: "صفقات سبوت",
    saudi: "🇸🇦 السوق السعودي",
    usmarket: "🇺🇸 صفقات الأمريكي",
    forex: "💱 صفقات الفوركس",
    futures: "📈 صفقات الفيوتشر",
    news: "الأخبار",
    subscription: "الاشتراك"
  };

  setText("pageTitle", titles[sectionId] || "مضارب أبو سعود");
}


/* =========================================================
   الوضع الليلي
   ========================================================= */

function setupTheme() {

  const btn =
    $("themeBtn");

  const saved =
    localStorage.getItem(
      "mudarib_theme"
    );

  if (
    saved === "light"
  ) {

    document.body.classList.add(
      "light"
    );
  }

  if (btn) {

    btn.addEventListener(
      "click",
      () => {

        document.body.classList.toggle(
          "light"
        );

        localStorage.setItem(
          "mudarib_theme",
          document.body.classList.contains(
            "light"
          )
            ? "light"
            : "dark"
        );
      }
    );
  }
}


/* =========================================================
   تسجيل الدخول / التسجيل
   ========================================================= */

function openAuth(
  type = "login"
) {

  const modal =
    $("authModal");

  if (!modal) return;

  show(modal);

  modal.classList.add(
    "show"
  );

  switchAuth(type);

  const msg =
    $("authMsg");

  if (msg) {

    msg.textContent = "";

    msg.className = "";
  }
}


function closeAuth() {

  const modal =
    $("authModal");

  if (!modal) return;

  modal.classList.remove(
    "show"
  );

  modal.hidden = true;
}


function switchAuth(type) {

  const loginForm =
    $("loginForm");

  const registerForm =
    $("registerForm");

  const loginTab =
    $("loginTab");

  const registerTab =
    $("registerTab");

  const isLogin =
    type === "login";

  if (loginForm) {
    loginForm.hidden =
      !isLogin;
  }

  if (registerForm) {
    registerForm.hidden =
      isLogin;
  }

  if (loginTab) {

    loginTab.classList.toggle(
      "active",
      isLogin
    );
  }

  if (registerTab) {

    registerTab.classList.toggle(
      "active",
      !isLogin
    );
  }

  const msg =
    $("authMsg");

  if (msg) {

    msg.textContent = "";

    msg.className = "";
  }
}


function setAuthMessage(
  message,
  type = ""
) {

  const el =
    $("authMsg");

  if (!el) return;

  el.textContent =
    message || "";

  el.className =
    type
      ? `auth-message ${type}`
      : "";
}


async function login(
  email,
  password
) {

  try {

    setAuthMessage(
      "جاري تسجيل الدخول..."
    );

    const data =
      await api(
        "/api/auth/login",
        {
          method: "POST",

          body:
            JSON.stringify({
              email,
              password
            })
        }
      );

    state.user =
      data.user ||
      data.account ||
      null;

    state.admin =
      !!(
        data.admin ||
        data.is_admin ||
        data.user?.admin ||
        data.user?.is_admin
      );

    setAuthMessage(
      "تم تسجيل الدخول بنجاح",
      "success"
    );

    closeAuth();

    await checkAuth();

    /*
     * الاشتراك يظهر للجميع.
     * إذا المستخدم مسجل، نقدر
     * نحدث بيانات الاشتراك.
     */

    if (state.user) {
      loadSubscription();
    }

  } catch (error) {

    setAuthMessage(
      error.message ||
      "فشل تسجيل الدخول",
      "error"
    );
  }
}


async function register(
  name,
  email,
  password
) {

  try {

    setAuthMessage(
      "جاري إنشاء الحساب..."
    );

    const data =
      await api(
        "/api/auth/register",
        {
          method: "POST",

          body:
            JSON.stringify({
              name,
              email,
              password
            })
        }
      );

    if (
      data.user ||
      data.account
    ) {

      state.user =
        data.user ||
        data.account;
    }

    setAuthMessage(
      "تم إنشاء الحساب بنجاح",
      "success"
    );

    setTimeout(
      () => {

        switchAuth(
          "login"
        );

        const loginEmail =
          $("loginEmail");

        if (loginEmail) {
          loginEmail.value =
            email;
        }

      },
      700
    );

  } catch (error) {

    setAuthMessage(
      error.message ||
      "تعذر إنشاء الحساب",
      "error"
    );
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
  state.admin = false;
  state.plan = null;

  updateAuthUI();
}


/* =========================================================
   فحص تسجيل الدخول
   ========================================================= */

async function checkAuth() {

  try {

    const data =
      await api(
        "/api/auth/me"
      );

    state.user =
      data.user ||
      data.account ||
      (
        data.logged_in
          ? data
          : null
      );

  } catch {

    state.user = null;
  }


  try {

    const adminData =
      await api(
        "/api/admin/me"
      );

    state.admin =
      !!(
        adminData.admin ||
        adminData.is_admin
      );

  } catch {

    state.admin = false;
  }

  updateAuthUI();
}


/* =========================================================
   تحديث واجهة المستخدم
   ========================================================= */

function updateAuthUI() {

  const loginBtn =
    $("loginBtn");

  const registerBtn =
    $("registerBtn");

  const logoutBtn =
    $("logoutBtn");

  const userBadge =
    $("userBadge");


  if (state.user) {

    hide(loginBtn);

    hide(registerBtn);

    show(logoutBtn);

    show(userBadge);

    if (userBadge) {

      const name =
        state.user.name ||
        state.user.email ||
        "مستخدم";

      userBadge.textContent =
        name;
    }

  } else {

    show(loginBtn);

    show(registerBtn);

    hide(logoutBtn);

    hide(userBadge);

    if (userBadge) {
      userBadge.textContent =
        "";
    }
  }


  const adminLink =
    $("adminLink");

  if (adminLink) {

    adminLink.hidden =
      !state.admin;
  }


  /*
   * =====================================================
   * الاشتراك يظهر لجميع المستخدمين
   * =====================================================
   */

  const subscriptionNav =
    $("subscriptionNav");

  if (subscriptionNav) {

    subscriptionNav.hidden =
      false;

    subscriptionNav.style.display =
      "";
  }
}


/* =========================================================
   ربط نماذج الدخول
   ========================================================= */

function setupAuth() {

  const loginBtn =
    $("loginBtn");

  const registerBtn =
    $("registerBtn");

  const logoutBtn =
    $("logoutBtn");


  if (loginBtn) {

    loginBtn.addEventListener(
      "click",
      () =>
        openAuth("login")
    );
  }


  if (registerBtn) {

    registerBtn.addEventListener(
      "click",
      () =>
        openAuth("register")
    );
  }


  if (logoutBtn) {

    logoutBtn.addEventListener(
      "click",
      logout
    );
  }


  const loginTab =
    $("loginTab");

  if (loginTab) {

    loginTab.addEventListener(
      "click",
      () =>
        switchAuth("login")
    );
  }


  const registerTab =
    $("registerTab");

  if (registerTab) {

    registerTab.addEventListener(
      "click",
      () =>
        switchAuth("register")
    );
  }


  const loginForm =
    $("loginForm");

  if (loginForm) {

    loginForm.addEventListener(
      "submit",
      async event => {

        event.preventDefault();

        const email =
          $("loginEmail")
            ?.value
            .trim();

        const password =
          $("loginPassword")
            ?.value || "";

        if (
          !email ||
          !password
        ) {

          setAuthMessage(
            "أدخل البريد وكلمة المرور",
            "error"
          );

          return;
        }

        await login(
          email,
          password
        );
      }
    );
  }


  const registerForm =
    $("registerForm");

  if (registerForm) {

    registerForm.addEventListener(
      "submit",
      async event => {

        event.preventDefault();

        const name =
          $("regName")
            ?.value
            .trim();

        const email =
          $("regEmail")
            ?.value
            .trim();

        const password =
          $("regPassword")
            ?.value || "";

        if (
          !name ||
          !email ||
          !password
        ) {

          setAuthMessage(
            "أكمل جميع البيانات",
            "error"
          );

          return;
        }

        await register(
          name,
          email,
          password
        );
      }
    );
  }


  qsa("[data-close]")
    .forEach(btn => {

      btn.addEventListener(
        "click",
        () => {

          const id =
            btn.dataset.close;

          if (
            id === "authModal"
          ) {

            closeAuth();
          }
        }
      );
    });


  const modal =
    $("authModal");

  if (modal) {

    modal.hidden = true;

    modal.addEventListener(
      "click",
      event => {

        if (
          event.target === modal
        ) {

          closeAuth();
        }
      }
    );
  }
}


/* =========================================================
   الرسم البياني
   ========================================================= */

function drawChart(
  candles
) {

  const canvas =
    $("priceChart");

  if (!canvas) return;

  if (
    typeof Chart ===
    "undefined"
  ) {
    return;
  }

  if (
    !Array.isArray(candles) ||
    !candles.length
  ) {
    return;
  }


  const labels =
    candles.map(
      candle => {

        const time =
          candle.t ||
          candle.time ||
          candle.timestamp;

        if (!time) {
          return "";
        }

        try {
          const numericTime = Number(time);
          const timestamp =
            numericTime > 100000000000
              ? numericTime
              : numericTime * 1000;

          return new Date(
            timestamp
          ).toLocaleTimeString(
            "ar-SA",
            {
              hour:
                "2-digit",

              minute:
                "2-digit"
            }
          );

        } catch {

          return "";
        }
      }
    );


  const prices =
    candles.map(
      candle =>
        Number(
          candle.c ??
          candle.close ??
          0
        )
    );


  if (state.chart) {

    state.chart.destroy();
  }


  state.chart =
    new Chart(
      canvas.getContext("2d"),
      {
        type: "line",

        data: {

          labels,

          datasets: [
            {
              label:
                state.symbol,

              data:
                prices,

              tension:
                0.25,

              pointRadius:
                0,

              borderWidth:
                2,

              fill:
                false
            }
          ]
        },

        options: {

          responsive:
            true,

          maintainAspectRatio:
            false,

          plugins: {

            legend: {
              display:
                false
            }
          },

          scales: {

            x: {
              ticks: {
                maxTicksLimit:
                  8
              }
            },

            y: {
              beginAtZero:
                false
            }
          }
        }
      }
    );
}


/* =========================================================
   تحليل العملة
   ========================================================= */

async function loadAnalysis(
  symbol = state.symbol,
  interval = state.interval
) {

  state.symbol =
    symbol;

  state.interval =
    interval;


  try {

    let data;


    try {

      data =
        await api(
          `/api/spot/analysis?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}`
        );

    } catch {

      data =
        await api(
          `/api/binance/analysis?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}`
        );
    }


    const analysis =
      data?.result ||
      data?.data ||
      data;

    const price =
      analysis.price ??
      analysis.close ??
      "-";


    const change =
      analysis.change ??
      analysis.change_percent ??
      analysis.changePct ??
      0;


    const signal =
      analysis.signal ||
      analysis.direction ||
      "حيادي";


    setText(
      "dashSymbol",
      symbol
    );

    setText(
      "dashPrice",
      formatNumber(price)
    );

    setText(
      "dashChange",
      formatPercent(change)
    );

    setText(
      "dashSignal",
      signal
    );

    setText(
      "bigSignal",
      signal
    );

    setText(
      "scoreText",
      analysis.score10 ??
      analysis.score ??
      "-"
    );


    const rawScore10 = Number(analysis.score10);
    const rawScore = Number(analysis.score);
    const score = Number.isFinite(rawScore10)
      ? rawScore10
      : (Number.isFinite(rawScore) ? rawScore / 10 : 0);


    const scoreBar =
      $("scoreBar");

    if (scoreBar) {

      const width =
        Math.max(
          0,
          Math.min(
            100,
            Number(score) * 10
          )
        );

      scoreBar.style.width =
        `${width}%`;
    }


    setText(
      "entry",
      formatNumber(
        analysis.entry
      )
    );

    setText(
      "tp1",
      formatNumber(
        analysis.tp1
      )
    );

    setText(
      "tp2",
      formatNumber(
        analysis.tp2
      )
    );

    setText(
      "tp3",
      formatNumber(
        analysis.tp3
      )
    );

    setText(
      "sl",
      formatNumber(
        analysis.sl
      )
    );

    setText(
      "rsi",
      formatNumber(
        analysis.rsi,
        2
      )
    );

    setText(
      "ema20",
      formatNumber(
        analysis.ema20
      )
    );

    setText(
      "ema50",
      formatNumber(
        analysis.ema50
      )
    );

    setText(
      "ema200",
      formatNumber(
        analysis.ema200
      )
    );


    const reasons =
      analysis.reasons ||
      [];

    const reasonsEl =
      $("reasons");

    if (reasonsEl) {

      if (
        Array.isArray(
          reasons
        ) &&
        reasons.length
      ) {

        reasonsEl.innerHTML =
          reasons
            .map(
              reason =>
                `<li>${escapeHtml(reason)}</li>`
            )
            .join("");

      } else {

        reasonsEl.innerHTML =
          "<li>لا توجد أسباب إضافية</li>";
      }
    }


    setText(
      "analysisMeta",
      `${symbol} • ${interval}`
    );


    drawChart(
      analysis.candles ||
      analysis.klines ||
      []
    );


    addRecent({
      symbol,
      price,
      signal,
      change,
      interval
    });


  } catch (error) {

    console.error(
      "Analysis:",
      error
    );

    setText(
      "analysisMeta",
      "تعذر تحميل التحليل"
    );
  }
}


/* =========================================================
   فواصل التحليل
   ========================================================= */

function setupDashboardIntervals() {

  qsa(
    "#dashIntervals button"
  ).forEach(btn => {

    btn.addEventListener(
      "click",
      () => {

        const interval =
          btn.dataset.interval ||
          btn.getAttribute(
            "data-value"
          ) ||
          btn.textContent
            .trim()
            .toLowerCase();

        if (!interval) {
          return;
        }

        qsa(
          "#dashIntervals button"
        ).forEach(x =>
          x.classList.remove(
            "active"
          )
        );

        btn.classList.add(
          "active"
        );

        state.interval =
          interval;

        loadAnalysis(
          state.symbol,
          state.interval
        );
      }
    );
  });
}


/* =========================================================
   الماسح
   ========================================================= */

async function runScanner() {

  if (state.busy) {
    return;
  }

  state.busy =
    true;

  const status =
    $("scannerStatus");

  const body =
    $("scannerBody");


  if (status) {
    status.textContent =
      "جاري الفحص...";
  }


  if (body) {

    body.innerHTML = `
      <tr>
        <td colspan="11">
          جاري فحص السوق...
        </td>
      </tr>
    `;
  }


  try {

    let data;


    try {

      data =
        await api(
          `/api/spot/scan?interval=${encodeURIComponent(state.interval)}`
        );

    } catch {

      data =
        await api(
          `/api/binance/scan?interval=${encodeURIComponent(state.interval)}`
        );
    }


    const payload = data?.data && typeof data.data === "object" && !Array.isArray(data.data) ? data.data : data;
    const rows =
      payload?.results ||
      payload?.signals ||
      payload?.items ||
      (Array.isArray(payload?.data) ? payload.data : []) ||
      [];


    state.results =
      Array.isArray(rows)
        ? rows
        : [];


    renderScanner();


    if (status) {

      status.textContent =
        `تم فحص ${state.results.length} عملة`;
    }


  } catch (error) {

    console.error(
      "Scanner:",
      error
    );


    if (body) {

      body.innerHTML = `
        <tr>
          <td colspan="11">
            تعذر تحميل الماسح:
            ${escapeHtml(error.message)}
          </td>
        </tr>
      `;
    }


    if (status) {

      status.textContent =
        "تعذر الاتصال";
    }


  } finally {

    state.busy =
      false;
  }
}


function renderScanner() {

  const body = $("scannerBody");
  if (!body) return;

  let rows = [...state.results];

  const search = $("scannerSearch")?.value.trim().toUpperCase();
  if (search) {
    rows = rows.filter(row =>
      String(row.symbol || row.instId || "")
        .toUpperCase()
        .includes(search)
    );
  }

  const signalFilter = [...state.signals];
  if (signalFilter.length) {
    rows = rows.filter(row => {
      const signal = row.signal || row.direction || "";
      return signalFilter.some(filter =>
        signal.toLowerCase().includes(filter.toLowerCase())
      );
    });
  }

  const sortField = $("sortField")?.value || state.sort;
  const sortValue = (row, field) => {
    if (field === "change") return Number(row.change ?? row.change_percent ?? row.pct_change ?? 0);
    if (field === "volume") return Number(row.volume ?? row.quoteVolume ?? row.volume24h ?? row.quote_volume ?? 0);
    if (field === "price") return Number(row.price ?? row.last ?? row.close ?? 0);
    if (field === "score") return Number(row.score ?? row.score10 ?? 0);
    return row[field] ?? "";
  };
  rows.sort((a,b) => {
    const av = sortValue(a, sortField);
    const bv = sortValue(b, sortField);
    const an = Number(av), bn = Number(bv);
    if (Number.isFinite(an) && Number.isFinite(bn)) return (an-bn)*state.dir;
    return String(av).localeCompare(String(bv), "ar") * state.dir;
  });

  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="11">لا توجد فرص مطابقة حالياً</td></tr>';
    return;
  }

  const volume = v => {
    const n = Number(v || 0);
    if (n >= 1e9) return (n/1e9).toFixed(2) + "B";
    if (n >= 1e6) return (n/1e6).toFixed(2) + "M";
    if (n >= 1e3) return (n/1e3).toFixed(1) + "K";
    return formatNumber(n, 0);
  };

  body.innerHTML = rows.map(row => {
    const symbol = row.symbol || row.instId || "-";
    const price = row.price ?? row.last ?? row.close ?? 0;
    const change = row.change ?? row.change_percent ?? 0;
    const signal = row.signal || row.direction || "حيادي";
    const score = row.score10 ?? row.score ?? "-";
    const rsi = row.rsi ?? "-";
    const entry = row.entry ?? price;
    const tp = row.tp1 ?? row.tp ?? row.target ?? "-";
    const sl = row.sl ?? row.stop ?? "-";
    const vol = row.volume24h ?? row.volume ?? 0;

    return `
      <tr data-symbol="${escapeAttr(symbol)}">
        <td><strong>${escapeHtml(symbol)}</strong></td>
        <td>${formatNumber(price)}</td>
        <td>${formatNumber(change, 2)}%</td>
        <td><span class="signal-badge ${signalClass(signal)}">${escapeHtml(signal)}</span></td>
        <td>${formatNumber(score, 1)}</td>
        <td>${formatNumber(rsi, 1)}</td>
        <td>${volume(vol)}</td>
        <td>${formatNumber(entry)}</td>
        <td>${formatNumber(tp)}</td>
        <td>${formatNumber(sl)}</td>
        <td>${escapeHtml(row.interval || state.interval)}</td>
      </tr>`;
  }).join("");

  qsa("#scannerBody tr[data-symbol]").forEach(row => {
    row.addEventListener("click", () => {
      const symbol = row.dataset.symbol;
      if (!symbol) return;
      state.symbol = symbol;
      showSection("dashboard");
      loadAnalysis(symbol, state.interval);
    });
  });
}

function setupScanner() {

  qsa(
    "#intervalChips button"
  ).forEach(btn => {

    btn.addEventListener(
      "click",
      () => {

        const interval =
          btn.dataset.interval ||
          btn.dataset.value ||
          btn.textContent
            .trim()
            .toLowerCase();

        if (!interval) {
          return;
        }

        state.interval =
          interval;

        qsa(
          "#intervalChips button"
        ).forEach(x =>
          x.classList.remove(
            "active"
          )
        );

        btn.classList.add(
          "active"
        );

        runScanner();
      }
    );
  });


  qsa(
    ".signal-chips button"
  ).forEach(btn => {

    btn.addEventListener(
      "click",
      () => {

        const signal =
          btn.dataset.signal ||
          btn.dataset.value ||
          btn.textContent
            .trim();


        btn.classList.toggle(
          "active"
        );


        if (
          state.signals.has(
            signal
          )
        ) {

          state.signals.delete(
            signal
          );

        } else {

          state.signals.add(
            signal
          );
        }


        renderScanner();
      }
    );
  });


  const search =
    $("scannerSearch");

  if (search) {

    search.addEventListener(
      "input",
      renderScanner
    );
  }


  const sort =
    $("sortField");

  if (sort) {

    sort.addEventListener(
      "change",
      () => {

        state.sort =
          sort.value;

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

        state.dir *= -1;

        renderScanner();
      }
    );
  }


  const scanBtn =
    $("scanBtn");

  if (scanBtn) {

    scanBtn.addEventListener(
      "click",
      runScanner
    );
  }
}


/* =========================================================
   الصفقات الحديثة
   ========================================================= */

function addRecent(item) {

  if (!item?.symbol) {
    return;
  }


  const clean = {

    symbol:
      item.symbol,

    price:
      item.price,

    signal:
      item.signal,

    change:
      item.change,

    interval:
      item.interval,

    time:
      Date.now()
  };


  state.recent =
    state.recent.filter(
      x =>
        !(
          x.symbol ===
            clean.symbol &&
          x.interval ===
            clean.interval
        )
    );


  state.recent.unshift(
    clean
  );


  state.recent =
    state.recent.slice(
      0,
      30
    );


  localStorage.setItem(
    "mudarib_recent",
    JSON.stringify(
      state.recent
    )
  );
}


function renderRecent() {

  const list =
    $("recentList");

  if (!list) {
    return;
  }


  if (!state.recent.length) {

    list.innerHTML =
      "<div>لا توجد صفقات حديثة</div>";

    return;
  }


  list.innerHTML =
    state.recent
      .map(item => `

        <div
          class="recent-item"
          data-symbol="${escapeAttr(item.symbol)}"
          data-interval="${escapeAttr(item.interval || "15m")}"
        >

          <strong>
            ${escapeHtml(item.symbol)}
          </strong>

          <span>
            ${formatNumber(item.price)}
          </span>

          <span class="signal-badge ${signalClass(item.signal)}">
            ${escapeHtml(item.signal || "حيادي")}
          </span>

          <span>
            ${formatPercent(item.change)}
          </span>

        </div>

      `)
      .join("");


  qsa(
    "#recentList .recent-item"
  ).forEach(item => {

    item.addEventListener(
      "click",
      () => {

        showSection(
          "dashboard"
        );

        loadAnalysis(
          item.dataset.symbol,
          item.dataset.interval ||
            "15m"
        );
      }
    );
  });
}


function setupRecent() {

  const clear =
    $("clearRecent");

  if (clear) {

    clear.addEventListener(
      "click",
      () => {

        state.recent =
          [];

        localStorage.removeItem(
          "mudarib_recent"
        );

        renderRecent();
      }
    );
  }
}


/* =========================================================
   جدول الأسواق
   ========================================================= */

function renderMarketTable(
  body,
  rows
) {

  if (!body) {
    return;
  }


  if (
    !Array.isArray(rows) ||
    !rows.length
  ) {

    body.innerHTML = `
      <tr>
        <td colspan="8">
          لا توجد بيانات كافية حالياً
        </td>
      </tr>
    `;

    return;
  }


  body.innerHTML =
    rows
      .map(row => {

        const symbol =
          row.symbol ||
          row.ticker ||
          row.code ||
          row.instId ||
          "-";


        const price =
          row.price ??
          row.last ??
          row.close ??
          0;


        const change =
          row.change ??
          row.change_percent ??
          0;


        const signal =
          row.signal ||
          row.direction ||
          "حيادي";


        const score =
          row.score10 ??
          row.score ??
          "-";


        const rsi =
          row.rsi ??
          "-";


        const entry =
          row.entry ??
          "-";


        const target =
          row.tp1 ??
          row.tp ??
          row.target ??
          "-";


        const sl =
          row.sl ??
          row.stop ??
          "-";


        return `
          <tr>

            <td>
              <strong>
                ${escapeHtml(symbol)}
              </strong>
            </td>

            <td>
              ${formatNumber(price)}
            </td>

            <td>
              <span class="signal-badge ${signalClass(signal)}">
                ${escapeHtml(signal)}
              </span>
            </td>

            <td>
              ${formatNumber(score, 2)}
            </td>

            <td>
              ${formatNumber(rsi, 2)}
            </td>

            <td>
              ${formatNumber(entry)}
            </td>

            <td>
              ${formatNumber(target)}
            </td>

            <td>
              ${formatNumber(sl)}
            </td>

          </tr>
        `;
      })
      .join("");
}


/* =========================================================
   السوق السعودي
   ========================================================= */

async function loadSaudi() {

  const body =
    $("saudiBody");

  const status =
    $("saudiStatus");

  if (!body) {
    return;
  }


  body.innerHTML = `
    <tr>
      <td colspan="8">
        جاري تحميل السوق السعودي...
      </td>
    </tr>
  `;


  if (status) {
    status.textContent =
      "جاري الفحص...";
  }


  try {

    let data;


    try {

      data =
        await api(
          "/api/saudi/scan?interval=15m&limit=10"
        );

    } catch {

      data =
        await api(
          "/api/saudi/signals?interval=15m&limit=10"
        );
    }


    const payload = data?.data && typeof data.data === "object" && !Array.isArray(data.data) ? data.data : data;
    const rows =
      payload?.results ||
      payload?.signals ||
      payload?.items ||
      (Array.isArray(payload?.data) ? payload.data : []) ||
      [];


    renderMarketTable(
      body,
      rows
    );


    state.loaded.saudi =
      true;


    if (status) {

      status.textContent =
        `تم تحديث السوق السعودي — ${rows.length} فرصة`;
    }


  } catch (error) {

    console.error(
      "Saudi:",
      error
    );


    body.innerHTML = `
      <tr>
        <td colspan="8">
          تعذر تحميل السوق السعودي:
          ${escapeHtml(error.message)}
        </td>
      </tr>
    `;


    if (status) {

      status.textContent =
        "تعذر الاتصال";
    }
  }
}


/* =========================================================
   السوق الأمريكي
   ========================================================= */

async function loadUSMarket() {

  const body =
    $("usMarketBody");

  const status =
    $("usStatus");

  if (!body) {
    return;
  }


  body.innerHTML = `
    <tr>
      <td colspan="8">
        جاري تحميل السوق الأمريكي...
      </td>
    </tr>
  `;


  if (status) {

    status.textContent =
      "جاري الفحص...";
  }


  try {

    let data;


    try {

      data =
        await api(
          "/api/usmarket/scan?interval=1d&limit=40"
        );

    } catch {

      data =
        await api(
          "/api/usmarket/signals?interval=1d&limit=40"
        );
    }


    const payload = data?.data && typeof data.data === "object" && !Array.isArray(data.data) ? data.data : data;
    const rows =
      payload?.results ||
      payload?.signals ||
      payload?.items ||
      (Array.isArray(payload?.data) ? payload.data : []) ||
      [];


    renderMarketTable(
      body,
      rows
    );


    state.loaded.usmarket =
      true;


    if (status) {

      status.textContent =
        `تم تحديث السوق الأمريكي — ${rows.length} فرصة`;
    }


  } catch (error) {

    console.error(
      "US Market:",
      error
    );


    body.innerHTML = `
      <tr>
        <td colspan="8">
          تعذر تحميل السوق الأمريكي:
          ${escapeHtml(error.message)}
        </td>
      </tr>
    `;


    if (status) {

      status.textContent =
        "تعذر الاتصال";
    }
  }
}


/* =========================================================
   الفوركس
   ========================================================= */

async function loadForex() {

  const body =
    $("forexBody");

  const status =
    $("forexStatus");

  if (!body) {
    return;
  }


  body.innerHTML = `
    <tr>
      <td colspan="8">
        جاري تحميل صفقات الفوركس...
      </td>
    </tr>
  `;


  if (status) {

    status.textContent =
      "جاري الفحص...";
  }


  try {

    let data;


    try {

      data =
        await api(
          "/api/forex/scan?interval=1H&limit=10"
        );

    } catch {

      data =
        await api(
          "/api/forex/signals?interval=1H&limit=10"
        );
    }


    const payload = data?.data && typeof data.data === "object" && !Array.isArray(data.data) ? data.data : data;
    const rows =
      payload?.results ||
      payload?.signals ||
      payload?.items ||
      (Array.isArray(payload?.data) ? payload.data : []) ||
      [];


    renderMarketTable(
      body,
      rows
    );


    state.loaded.forex =
      true;


    if (status) {

      status.textContent =
        `تم تحديث الفوركس — ${rows.length} فرصة`;
    }


  } catch (error) {

    console.error(
      "Forex:",
      error
    );


    body.innerHTML = `
      <tr>
        <td colspan="8">
          تعذر تحميل الفوركس:
          ${escapeHtml(error.message)}
        </td>
      </tr>
    `;


    if (status) {

      status.textContent =
        "تعذر الاتصال";
    }
  }
}


/* =========================================================
   الفيوتشر
   ========================================================= */

async function loadFutures() {

  const body =
    $("futuresBody");

  const status =
    $("futuresStatus");

  if (!body) {
    return;
  }


  body.innerHTML = `
    <tr>
      <td colspan="8">
        جاري تحميل صفقات الفيوتشر...
      </td>
    </tr>
  `;


  if (status) {

    status.textContent =
      "جاري الفحص 15m...";
  }


  try {

    let data;


    try {

      data =
        await api(
          "/api/futures/scan?interval=15m&limit=40"
        );

    } catch {

      try {

        data =
          await api(
            "/api/futures/signals?interval=15m&limit=40"
          );

      } catch {

        data =
          await api(
            "/api/futures?interval=15m&limit=40"
          );
      }
    }


    const payload = data?.data && typeof data.data === "object" && !Array.isArray(data.data) ? data.data : data;
    const rows =
      payload?.results ||
      payload?.signals ||
      payload?.items ||
      (Array.isArray(payload?.data) ? payload.data : []) ||
      [];


    renderMarketTable(
      body,
      rows
    );


    state.loaded.futures =
      true;


    if (status) {

      status.textContent =
        `تم تحديث الفيوتشر 15m — ${rows.length} فرصة`;
    }


  } catch (error) {

    console.error(
      "Futures:",
      error
    );


    body.innerHTML = `
      <tr>
        <td colspan="8">
          تعذر تحميل صفقات الفيوتشر:
          ${escapeHtml(error.message)}
        </td>
      </tr>
    `;


    if (status) {

      status.textContent =
        "تعذر الاتصال";
    }
  }
}


/* =========================================================
   أزرار التحديث
   ========================================================= */

function setupMarketRefresh() {

  const saudi =
    $("refreshSaudi");

  if (saudi) {

    saudi.addEventListener(
      "click",
      loadSaudi
    );
  }


  const us =
    $("refreshUSMarket");

  if (us) {

    us.addEventListener(
      "click",
      loadUSMarket
    );
  }


  const forex =
    $("refreshForex");

  if (forex) {

    forex.addEventListener(
      "click",
      loadForex
    );
  }


  const futures =
    $("refreshFutures");

  if (futures) {

    futures.addEventListener(
      "click",
      loadFutures
    );
  }
}


/* =========================================================
   الأخبار
   ========================================================= */

async function loadNews() {

  const list =
    $("newsList");

  if (!list) {
    return;
  }


  list.innerHTML =
    "<div>جاري تحميل الأخبار...</div>";


  try {

    let data;


    try {

      data =
        await api(
          "/api/news"
        );

    } catch {

      data =
        await api(
          "/api/news/latest"
        );
    }


    const rows =
      data.news ||
      data.results ||
      data.items ||
      data.data ||
      [];


    if (
      !Array.isArray(rows) ||
      !rows.length
    ) {

      list.innerHTML =
        "<div>لا توجد أخبار حالياً</div>";

      return;
    }


    list.innerHTML =
      rows
        .map(item => {

          const title =
            item.title ||
            item.headline ||
            "خبر";


          const link =
            item.link ||
            item.url ||
            "#";


          const source =
            item.source ||
            item.publisher ||
            "";


          return `
            <a
              class="news-item"
              href="${escapeAttr(link)}"
              target="_blank"
              rel="noopener noreferrer"
            >

              <strong>
                ${escapeHtml(title)}
              </strong>

              ${
                source
                  ? `<small>${escapeHtml(source)}</small>`
                  : ""
              }

            </a>
          `;
        })
        .join("");


    state.loaded.news =
      true;


  } catch (error) {

    console.error(
      "News:",
      error
    );


    list.innerHTML = `
      <div>
        تعذر تحميل الأخبار
      </div>
    `;
  }
}


/* =========================================================
   الاشتراك
   ========================================================= */

async function loadSubscription() {

  /*
   * مهم:
   * لا يوجد هنا شرط state.user.
   *
   * الاشتراك متاح للزائر
   * والمسجل.
   */

  try {

    let data;

    /*
     * المسار الأساسي
     */
    try {

      data =
        await api(
          "/api/subscription/plans"
        );

    } catch {

      /*
       * المسار الموجود في server.py
       */
      data =
        await api(
          "/api/plans"
        );
    }


    const subscriptionPayload =
      data?.data && typeof data.data === "object" && !Array.isArray(data.data)
        ? data.data
        : data;

    let plans =
      subscriptionPayload?.plans ||
      subscriptionPayload?.results ||
      [];

    /*
     * server.py historically returned PLANS as an object
     * keyed by plan id. Normalize it so the UI always
     * receives an array.
     */
    if (
      plans &&
      !Array.isArray(plans) &&
      typeof plans === "object"
    ) {
      plans = Object.entries(plans).map(
        ([id, plan]) => ({
          id,
          ...plan
        })
      );
    }


    const plansEl =
      $("plans");


    if (
      plansEl &&
      Array.isArray(plans)
    ) {

      plansEl.innerHTML =
        plans
          .map(
            (plan, index) => {

              const planId =
                plan.id ??
                plan.plan_id ??
                plan.code ??
                index;

              const price =
                plan.price ??
                plan.amount ??
                "-";

              const days =
                plan.days ??
                plan.duration ??
                "";

              return `

                <div
                  class="plan-card"
                  data-plan-id="${escapeAttr(planId)}"
                >

                  <h3>
                    ${escapeHtml(
                      plan.name ||
                      plan.title ||
                      "خطة اشتراك"
                    )}
                  </h3>

                  <strong>
                    ${escapeHtml(price)}
                    USDT
                  </strong>

                  <div>
                    ${escapeHtml(days)}
                    يوم
                  </div>

                </div>

              `;
            }
          )
          .join("");


      qsa(
        "#plans .plan-card"
      ).forEach(
        planEl => {

          planEl.addEventListener(
            "click",
            () => {

              qsa(
                "#plans .plan-card"
              ).forEach(x =>
                x.classList.remove(
                  "active"
                )
              );


              planEl.classList.add(
                "active"
              );


              state.plan =
                planEl.dataset.planId;


              setText(
                "chosenPlan",
                state.plan
              );


              const paymentBox =
                $("paymentBox");


              if (paymentBox) {

                paymentBox.hidden =
                  false;
              }
            }
          );
        }
      );
    }


    const address =
      subscriptionPayload?.trc20Address ||
      subscriptionPayload?.address ||
      subscriptionPayload?.pay_address ||
      subscriptionPayload?.paymentAddress ||
      subscriptionPayload?.trc20 ||
      "";

    const binancePayId =
      subscriptionPayload?.binancePayId ||
      "";

    const payAddressEl = $("payAddress");
    if (payAddressEl) payAddressEl.value = address;

    const binancePayEl = $("binancePayId");
    if (binancePayEl) binancePayEl.value = binancePayId;

    setupQR(address);


  } catch (error) {

    console.error(
      "Subscription:",
      error
    );


    setText(
      "subscriptionStatus",
      "تعذر تحميل خطط الاشتراك"
    );
  }
}


/* =========================================================
   QR
   ========================================================= */

function setupQR(
  address
) {

  const box =
    $("qrBox");

  if (!box) {
    return;
  }


  box.innerHTML =
    "";


  if (
    !address ||
    typeof QRCode ===
      "undefined"
  ) {

    return;
  }


  const canvas =
    document.createElement(
      "canvas"
    );


  box.appendChild(
    canvas
  );


  try {

    QRCode.toCanvas(
      canvas,
      address,
      {
        width: 180
      }
    );

  } catch (error) {

    console.warn(
      "QR:",
      error
    );
  }
}


/* =========================================================
   إرسال الدفع
   ========================================================= */

function setupSubscription() {

  const copy =
    $("copyAddress");

  const copyBinance = $("copyBinancePay");
  if (copyBinance) {
    copyBinance.addEventListener("click", async () => {
      const value = $("binancePayId")?.value?.trim();
      if (!value) return;
      try {
        await navigator.clipboard.writeText(value);
        copyBinance.textContent = "تم النسخ ✓";
        setTimeout(() => { copyBinance.textContent = "نسخ ID"; }, 1500);
      } catch {
        alert("انسخ رقم Binance Pay يدوياً");
      }
    });
  }


  if (copy) {

    copy.addEventListener(
      "click",
      async () => {

        const address =
          $("payAddress")
            ?.value
            ?.trim();


        if (!address) {
          return;
        }


        try {

          await navigator
            .clipboard
            .writeText(
              address
            );


          copy.textContent =
            "تم النسخ ✓";


          setTimeout(
            () => {

              copy.textContent =
                "نسخ العنوان";

            },
            1500
          );


        } catch {

          alert(
            "انسخ العنوان يدوياً"
          );
        }
      }
    );
  }


  const send =
    $("sendPayment");


  if (send) {

    send.addEventListener(
      "click",
      async () => {

        /*
         * عرض الاشتراك للجميع،
         * لكن الدفع يحتاج تسجيل دخول.
         */

        if (!state.user) {

          openAuth(
            "login"
          );

          return;
        }


        if (!state.plan) {

          setText(
            "paymentMsg",
            "اختر خطة أولاً"
          );

          return;
        }


        const txid =
          $("txid")
            ?.value
            ?.trim();


        if (!txid) {

          setText(
            "paymentMsg",
            "أدخل رقم العملية"
          );

          return;
        }


        try {

          setText(
            "paymentMsg",
            "جاري إرسال العملية..."
          );


          await api(
            "/api/subscription/payment",
            {
              method:
                "POST",

              body:
                JSON.stringify({
                  plan_id:
                    state.plan,

                  txid
                })
            }
          );


          setText(
            "paymentMsg",
            "تم إرسال العملية للمراجعة ✓"
          );


        } catch (error) {

          setText(
            "paymentMsg",
            error.message ||
            "تعذر إرسال العملية"
          );
        }
      }
    );
  }
}


/* =========================================================
   حالة النظام
   ========================================================= */

function setSystemStatus(
  text,
  online = true
) {

  const el =
    $("systemStatus");

  if (!el) {
    return;
  }


  el.textContent =
    text;


  el.classList.toggle(
    "offline",
    !online
  );
}


/* =========================================================
   التحديث التلقائي
   ========================================================= */

function setupAutoRefresh() {
  if (refreshStarted) return;
  refreshStarted = true;

  setInterval(
    () => {

      if (
        state.loaded.futures
      ) {

        loadFutures();
      }

    },
    180000
  );


  setInterval(
    () => {

      if (
        state.loaded.saudi
      ) {

        loadSaudi();
      }

    },
    300000
  );


  setInterval(
    () => {

      if (
        state.loaded.usmarket
      ) {

        loadUSMarket();
      }

    },
    300000
  );


  setInterval(
    () => {

      if (
        state.loaded.forex
      ) {

        loadForex();
      }

    },
    300000
  );


  setInterval(
    () => {
      const page = document.body.dataset.page || "";
      if (page === "scanner" && !state.busy) {
        runScanner();
      }
    },
    120000
  );


  setInterval(
    () => {

      if (document.body.dataset.page === "news") {
        loadNews();
      }

    },
    600000
  );
}


/* =========================================================
   التشغيل
   ========================================================= */

let booted = false;
let refreshStarted = false;

async function boot() {
  if (booted) return;
  booted = true;
  try {
    console.log("مضارب أبو سعود — app.js started");
  const page=document.body.dataset.page||"dashboard";
  setSystemStatus("متصل",true);
  setupNavigation(); setupMarketSelector(); setupTheme(); setupAuth(); setupDashboardIntervals(); setupScanner(); setupRecent(); setupMarketRefresh(); setupSubscription();
  const subscriptionNav=$("subscriptionNav");
  if(subscriptionNav){subscriptionNav.hidden=false;subscriptionNav.style.display="";}
  renderRecent();
  await checkAuth();
  const subscriptionNavAfterAuth=$("subscriptionNav");
  if(subscriptionNavAfterAuth){subscriptionNavAfterAuth.hidden=false;subscriptionNavAfterAuth.style.display="";}
  if(page==="dashboard") await loadAnalysis(state.symbol,state.interval);
  else if(page==="scanner") await runScanner();
  else if(page==="recent") renderRecent();
  else if(page==="saudi") await loadSaudi();
  else if(page==="usmarket") await loadUSMarket();
  else if(page==="forex") await loadForex();
  else if(page==="futures") await loadFutures();
  else if(page==="news") await loadNews();
  else if(page==="subscription") await loadSubscription();
  setSystemStatus("متصل",true);
  setupAutoRefresh();
  } catch (error) {
    console.error("Boot:", error);
    setSystemStatus("تعذر تحميل النظام", false);
  }
}

/* =========================================================
   تشغيل آمن
   ========================================================= */

if (
  document.readyState ===
  "loading"
) {

  document.addEventListener(
    "DOMContentLoaded",
    boot,
    {
      once: true
    }
  );

} else {

  boot();
}