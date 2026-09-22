(() => {
  "use strict";

  // ============================================================
  // مضارب أبو سعود
  // app.js
  // إصلاح الأزرار + تسجيل الدخول + التسجيل + التحليلات
  // بدون تحويل المستخدم إلى /login أو /register
  // ============================================================

  const $ = (id) => document.getElementById(id);

  const state = {
    user: null,
    admin: false,
    interval: "15m",
    symbol: "BTCUSDT",
    results: [],
    signals: [],
    sortField: "change",
    sortDesc: true,
    chart: null,
    recent: [],
    loadingAnalysis: false,
    loadingScan: false
  };

  // ============================================================
  // API
  // ============================================================

  async function api(url, options = {}) {
    const config = {
      credentials: "same-origin",
      cache: "no-store",
      ...options,
      headers: {
        ...(options.headers || {})
      }
    };

    if (config.body && typeof config.body !== "string") {
      config.headers["Content-Type"] = "application/json";
      config.body = JSON.stringify(config.body);
    }

    const response = await fetch(url, config);

    let data = null;
    const type = response.headers.get("content-type") || "";

    try {
      if (type.includes("application/json")) {
        data = await response.json();
      } else {
        const text = await response.text();
        try {
          data = JSON.parse(text);
        } catch {
          data = text;
        }
      }
    } catch {
      data = null;
    }

    if (!response.ok) {
      const message =
        data?.message ||
        data?.error ||
        data?.detail ||
        `خطأ HTTP ${response.status}`;

      throw new Error(message);
    }

    return data;
  }

  // ============================================================
  // أدوات مساعدة
  // ============================================================

  function setText(id, value) {
    const el = $(id);
    if (el) el.textContent = value ?? "—";
  }

  function safeNumber(value, fallback = null) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  function formatNumber(value, digits = 4) {
    const n = safeNumber(value);

    if (n === null) return "—";

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
    const n = safeNumber(value);

    if (n === null) return "—";

    return `${n > 0 ? "+" : ""}${n.toFixed(2)}%`;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function firstValue(obj, keys, fallback = null) {
    if (!obj || typeof obj !== "object") return fallback;

    for (const key of keys) {
      if (
        obj[key] !== undefined &&
        obj[key] !== null &&
        obj[key] !== ""
      ) {
        return obj[key];
      }
    }

    return fallback;
  }

  function unwrap(data) {
    if (!data) return data;

    if (data.data !== undefined) return data.data;
    if (data.result !== undefined) return data.result;
    if (data.results !== undefined) return data.results;

    return data;
  }

  function arrayFrom(data) {
    const value = unwrap(data);

    if (Array.isArray(value)) return value;

    if (value && Array.isArray(value.items)) return value.items;
    if (value && Array.isArray(value.data)) return value.data;
    if (value && Array.isArray(value.results)) return value.results;

    return [];
  }

  // ============================================================
  // الأقسام
  // ============================================================

  const sectionTitles = {
    dashboard: "الرئيسية",
    scanner: "ماسح الفرص",
    alpha: "صفقات Alpha",
    traditional: "صفقات التمويل التقليدي",
    spot: "صفقات السبوت",
    futures: "صفقات الفيوتشر",
    news: "الأخبار",
    subscription: "الاشتراك"
  };

  function showSection(sectionId) {
    const sections = document.querySelectorAll(".section");

    sections.forEach((section) => {
      section.classList.toggle(
        "active",
        section.id === sectionId
      );

      if (section.id !== sectionId) {
        section.hidden = false;
      }
    });

    const navItems = document.querySelectorAll(".nav-item");

    navItems.forEach((item) => {
      item.classList.toggle(
        "active",
        item.dataset.section === sectionId
      );
    });

    setText(
      "pageTitle",
      sectionTitles[sectionId] || "مضارب أبو سعود"
    );

    const sidebar = $("sidebar");

    if (sidebar) {
      sidebar.classList.remove("open");
    }

    if (sectionId === "alpha") {
      loadTradeSection("alpha");
    }

    if (sectionId === "traditional") {
      loadTradeSection("traditional");
    }

    if (sectionId === "spot") {
      loadSpot();
    }

    if (sectionId === "futures") {
      loadTradeSection("futures");
    }

    if (sectionId === "news") {
      loadNews();
    }

    if (sectionId === "subscription") {
      loadSubscription();
    }
  }

  function bindNavigation() {
    document.querySelectorAll(".nav-item").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();

        const section = button.dataset.section;

        if (!section) return;

        showSection(section);
      });
    });
  }

  // ============================================================
  // القائمة الجانبية بالجوال
  // ============================================================

  function bindMenu() {
    const menuBtn = $("menuBtn");
    const sidebar = $("sidebar");

    if (!menuBtn || !sidebar) return;

    menuBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();

      sidebar.classList.toggle("open");
    });
  }

  // ============================================================
  // تسجيل الدخول والتسجيل
  // ============================================================

  function openAuth(tab = "login") {
    const modal = $("authModal");

    if (!modal) return;

    modal.classList.add("show");
    modal.style.display = "flex";

    switchAuthTab(tab);

    setTimeout(() => {
      if (tab === "login") {
        $("loginEmail")?.focus();
      } else {
        $("regName")?.focus();
      }
    }, 50);
  }

  function closeAuth() {
    const modal = $("authModal");

    if (!modal) return;

    modal.classList.remove("show");
    modal.style.display = "none";
  }

  function switchAuthTab(tab) {
    const loginTab = $("loginTab");
    const registerTab = $("registerTab");
    const loginForm = $("loginForm");
    const registerForm = $("registerForm");

    if (!loginTab || !registerTab) return;

    const login = tab === "login";

    loginTab.classList.toggle("active", login);
    registerTab.classList.toggle("active", !login);

    if (loginForm) loginForm.hidden = !login;
    if (registerForm) registerForm.hidden = login;

    setText("authMsg", "");
  }

  function bindAuth() {
    $("loginBtn")?.addEventListener("click", (event) => {
      event.preventDefault();
      openAuth("login");
    });

    $("registerBtn")?.addEventListener("click", (event) => {
      event.preventDefault();
      openAuth("register");
    });

    $("loginTab")?.addEventListener("click", (event) => {
      event.preventDefault();
      switchAuthTab("login");
    });

    $("registerTab")?.addEventListener("click", (event) => {
      event.preventDefault();
      switchAuthTab("register");
    });

    document.querySelectorAll("[data-close]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();

        const id = button.dataset.close;

        if (id === "authModal") {
          closeAuth();
        }
      });
    });

    $("authModal")?.addEventListener("click", (event) => {
      if (event.target === $("authModal")) {
        closeAuth();
      }
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeAuth();
      }
    });

    $("loginForm")?.addEventListener("submit", login);

    $("registerForm")?.addEventListener(
      "submit",
      register
    );

    $("logoutBtn")?.addEventListener("click", async (event) => {
      event.preventDefault();

      try {
        await api("/api/auth/logout", {
          method: "POST"
        });
      } catch (error) {
        console.warn("logout:", error);
      }

      state.user = null;
      state.admin = false;

      updateUserUI();

      setText("authMsg", "");

      showSection("dashboard");
    });
  }

  async function login(event) {
    event.preventDefault();

    const email = $("loginEmail")?.value.trim();
    const password = $("loginPassword")?.value || "";

    if (!email || !password) {
      setText("authMsg", "أدخل البريد وكلمة المرور.");
      return;
    }

    const button = event.submitter;

    if (button) {
      button.disabled = true;
      button.dataset.oldText = button.textContent;
      button.textContent = "جاري الدخول...";
    }

    setText("authMsg", "جاري تسجيل الدخول...");

    try {
      const data = await api("/api/auth/login", {
        method: "POST",
        body: {
          email,
          password
        }
      });

      state.user =
        data?.user ||
        data?.data?.user ||
        data?.account ||
        data ||
        null;

      state.admin = Boolean(
        data?.admin ||
        data?.is_admin ||
        state.user?.admin ||
        state.user?.is_admin
      );

      updateUserUI();

      closeAuth();

      setText(
        "systemStatus",
        "متصل"
      );

    } catch (error) {
      console.error("login:", error);

      setText(
        "authMsg",
        error.message || "تعذر تسجيل الدخول."
      );
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent =
          button.dataset.oldText || "دخول";
      }
    }
  }

  async function register(event) {
    event.preventDefault();

    const name = $("regName")?.value.trim();
    const email = $("regEmail")?.value.trim();
    const password = $("regPassword")?.value || "";

    if (!name || !email || !password) {
      setText(
        "authMsg",
        "أكمل جميع البيانات."
      );
      return;
    }

    if (password.length < 6) {
      setText(
        "authMsg",
        "كلمة المرور يجب أن تكون 6 أحرف على الأقل."
      );
      return;
    }

    const button = event.submitter;

    if (button) {
      button.disabled = true;
      button.dataset.oldText = button.textContent;
      button.textContent = "جاري إنشاء الحساب...";
    }

    setText(
      "authMsg",
      "جاري إنشاء الحساب..."
    );

    try {
      const data = await api("/api/auth/register", {
        method: "POST",
        body: {
          name,
          email,
          password
        }
      });

      state.user =
        data?.user ||
        data?.data?.user ||
        null;

      if (state.user) {
        state.admin = Boolean(
          data?.admin ||
          data?.is_admin ||
          state.user?.admin ||
          state.user?.is_admin
        );

        updateUserUI();
        closeAuth();

        setText(
          "systemStatus",
          "تم إنشاء الحساب"
        );
      } else {
        setText(
          "authMsg",
          data?.message ||
          "تم إنشاء الحساب، سجل الدخول الآن."
        );

        switchAuthTab("login");

        if ($("loginEmail")) {
          $("loginEmail").value = email;
        }
      }

    } catch (error) {
      console.error("register:", error);

      setText(
        "authMsg",
        error.message || "تعذر إنشاء الحساب."
      );
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent =
          button.dataset.oldText ||
          "إنشاء الحساب";
      }
    }
  }

  // ============================================================
  // التحقق من الجلسة
  // ============================================================

  async function loadCurrentUser() {
    try {
      const data = await api("/api/auth/me");

      const value = unwrap(data);

      if (value?.user) {
        state.user = value.user;
      } else if (value?.authenticated === false) {
        state.user = null;
      } else if (
        value &&
        typeof value === "object" &&
        (
          value.email ||
          value.name ||
          value.id ||
          value.user_id
        )
      ) {
        state.user = value;
      }

    } catch (error) {
      console.warn("auth/me:", error);
      state.user = null;
    }

    try {
      const data = await api("/api/admin/me");

      state.admin = Boolean(
        data?.admin ||
        data?.is_admin ||
        data?.authenticated ||
        data?.user?.admin
      );
    } catch {
      state.admin = false;
    }

    updateUserUI();
  }

  function updateUserUI() {
    const user = state.user;

    const badge = $("userBadge");
    const loginBtn = $("loginBtn");
    const registerBtn = $("registerBtn");
    const logoutBtn = $("logoutBtn");
    const subscriptionNav = $("subscriptionNav");
    const adminLink = $("adminLink");

    if (badge) {
      badge.textContent =
        user?.name ||
        user?.email ||
        "زائر";
    }

    if (loginBtn) {
      loginBtn.hidden = Boolean(user);
    }

    if (registerBtn) {
      registerBtn.hidden = Boolean(user);
    }

    if (logoutBtn) {
      logoutBtn.hidden = !user;
    }

    if (subscriptionNav) {
      subscriptionNav.hidden = !user;
    }

    if (adminLink) {
      adminLink.hidden = !state.admin;
    }
  }

  // ============================================================
  // تحليل BTCUSDT
  // ============================================================

  async function loadAnalysis(
    symbol = state.symbol,
    interval = state.interval
  ) {
    if (state.loadingAnalysis) return;

    state.loadingAnalysis = true;

    state.symbol = symbol;
    state.interval = interval;

    setText("systemStatus", "جاري تحميل التحليل...");

    setText("dashSymbol", symbol);
    setText("analysisMeta", interval);

    try {
      const data = await api(
        `/api/binance/analysis?symbol=${encodeURIComponent(
          symbol
        )}&interval=${encodeURIComponent(interval)}`
      );

      renderAnalysis(data);

      setText(
        "systemStatus",
        "متصل"
      );

    } catch (error) {
      console.error("analysis:", error);

      setText(
        "systemStatus",
        "تعذر تحميل التحليل"
      );

      showAnalysisError(error.message);
    } finally {
      state.loadingAnalysis = false;
    }
  }

  function showAnalysisError(message) {
    setText(
      "dashPrice",
      "—"
    );

    setText(
      "dashChange",
      "—"
    );

    setText(
      "dashSignal",
      "تعذر التحليل"
    );

    setText(
      "bigSignal",
      "تعذر التحليل"
    );

    setText(
      "scoreText",
      "—"
    );

    const reasons = $("reasons");

    if (reasons) {
      reasons.innerHTML = `
        <li>${escapeHtml(
          message || "تعذر جلب بيانات التحليل."
        )}</li>
      `;
    }
  }

  function renderAnalysis(data) {
    const root = unwrap(data) || {};

    const price = firstValue(
      root,
      [
        "price",
        "current_price",
        "currentPrice",
        "lastPrice",
        "close"
      ]
    );

    const change = firstValue(
      root,
      [
        "change",
        "change_percent",
        "changePercent",
        "priceChangePercent",
        "percent"
      ]
    );

    const signal = firstValue(
      root,
      [
        "signal",
        "recommendation",
        "label",
        "action"
      ],
      "حيادي"
    );

    const score = firstValue(
      root,
      [
        "score",
        "strength",
        "signal_strength",
        "confidence"
      ]
    );

    const entry = firstValue(
      root,
      [
        "entry",
        "entry_price",
        "entryPrice"
      ]
    );

    const tp1 = firstValue(
      root,
      [
        "tp1",
        "TP1",
        "take_profit_1",
        "target1"
      ]
    );

    const tp2 = firstValue(
      root,
      [
        "tp2",
        "TP2",
        "take_profit_2",
        "target2"
      ]
    );

    const tp3 = firstValue(
      root,
      [
        "tp3",
        "TP3",
        "take_profit_3",
        "target3"
      ]
    );

    const sl = firstValue(
      root,
      [
        "sl",
        "stop_loss",
        "stopLoss",
        "stop"
      ]
    );

    const rsi = firstValue(
      root,
      ["rsi", "RSI"]
    );

    const ema20 = firstValue(
      root,
      ["ema20", "EMA20"]
    );

    const ema50 = firstValue(
      root,
      ["ema50", "EMA50"]
    );

    const ema200 = firstValue(
      root,
      ["ema200", "EMA200"]
    );

    setText(
      "dashPrice",
      price === null
        ? "—"
        : formatNumber(price)
    );

    setText(
      "dashChange",
      change === null
        ? "—"
        : formatPercent(change)
    );

    setText("dashSignal", signal);
    setText("bigSignal", signal);

    setText(
      "entry",
      entry === null
        ? "—"
        : formatNumber(entry)
    );

    setText(
      "tp1",
      tp1 === null
        ? "—"
        : formatNumber(tp1)
    );

    setText(
      "tp2",
      tp2 === null
        ? "—"
        : formatNumber(tp2)
    );

    setText(
      "tp3",
      tp3 === null
        ? "—"
        : formatNumber(tp3)
    );

    setText(
      "sl",
      sl === null
        ? "—"
        : formatNumber(sl)
    );

    setText(
      "rsi",
      rsi === null
        ? "—"
        : formatNumber(rsi, 2)
    );

    setText(
      "ema20",
      ema20 === null
        ? "—"
        : formatNumber(ema20)
    );

    setText(
      "ema50",
      ema50 === null
        ? "—"
        : formatNumber(ema50)
    );

    setText(
      "ema200",
      ema200 === null
        ? "—"
        : formatNumber(ema200)
    );

    if (score !== null) {
      let scoreNumber = safeNumber(score);

      if (scoreNumber !== null) {
        if (scoreNumber <= 1) {
          scoreNumber *= 100;
        }

        scoreNumber = Math.max(
          0,
          Math.min(100, scoreNumber)
        );

        setText(
          "scoreText",
          `${scoreNumber.toFixed(0)}%`
        );

        const bar = $("scoreBar");

        if (bar) {
          bar.style.width =
            `${scoreNumber}%`;
        }
      }
    }

    const reasons = $("reasons");

    if (reasons) {
      const list = firstValue(
        root,
        [
          "reasons",
          "reason",
          "analysis_reasons"
        ],
        []
      );

      let items = [];

      if (Array.isArray(list)) {
        items = list;
      } else if (list) {
        items = [list];
      }

      reasons.innerHTML =
        items.length
          ? items
              .map(
                (item) =>
                  `<li>${escapeHtml(
                    typeof item === "object"
                      ? firstValue(
                          item,
                          ["text", "reason", "message"],
                          JSON.stringify(item)
                        )
                      : item
                  )}</li>`
              )
              .join("")
          : "";
    }

    const candles = firstValue(
      root,
      [
        "candles",
        "klines",
        "chart",
        "prices"
      ],
      []
    );

    if (Array.isArray(candles)) {
      renderChart(candles);
    }
  }

  // ============================================================
  // الرسم البياني
  // ============================================================

  function renderChart(candles) {
    const canvas = $("priceChart");

    if (!canvas) return;

    if (typeof Chart === "undefined") {
      console.warn("Chart.js غير متوفر");
      return;
    }

    const labels = [];
    const values = [];

    candles.forEach((candle, index) => {
      if (Array.isArray(candle)) {
        const time = candle[0];
        const close = safeNumber(candle[4]);

        if (close !== null) {
          labels.push(
            time
              ? new Date(Number(time)).toLocaleTimeString(
                  "ar-SA",
                  {
                    hour: "2-digit",
                    minute: "2-digit"
                  }
                )
              : index + 1
          );

          values.push(close);
        }

        return;
      }

      if (typeof candle === "object") {
        const time = firstValue(
          candle,
          ["time", "timestamp", "openTime", "date"],
          index
        );

        const close = safeNumber(
          firstValue(
            candle,
            ["close", "price", "c"],
            null
          )
        );

        if (close !== null) {
          labels.push(
            Number.isFinite(Number(time))
              ? new Date(
                  Number(time)
                ).toLocaleTimeString(
                  "ar-SA",
                  {
                    hour: "2-digit",
                    minute: "2-digit"
                  }
                )
              : String(time)
          );

          values.push(close);
        }
      }
    });

    if (!values.length) return;

    const ctx = canvas.getContext("2d");

    if (state.chart) {
      try {
        state.chart.destroy();
      } catch {}
    }

    state.chart = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: state.symbol,
            data: values,
            tension: 0.25,
            pointRadius: 0,
            borderWidth: 2,
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

  // ============================================================
  // فريمات الرئيسية
  // ============================================================

  function bindDashboardIntervals() {
    document
      .querySelectorAll(
        "#dashIntervals button"
      )
      .forEach((button) => {
        button.addEventListener("click", (event) => {
          event.preventDefault();

          document
            .querySelectorAll(
              "#dashIntervals button"
            )
            .forEach((item) =>
              item.classList.remove("active")
            );

          button.classList.add("active");

          const interval =
            button.dataset.interval ||
            "15m";

          loadAnalysis(
            state.symbol,
            interval
          );
        });
      });
  }

  // ============================================================
  // الماسح
  // ============================================================

  async function scan() {
    if (state.loadingScan) return;

    state.loadingScan = true;

    const button = $("scanBtn");

    if (button) {
      button.disabled = true;
      button.dataset.oldText = button.textContent;
      button.textContent = "جاري الفحص...";
    }

    setText(
      "scannerStatus",
      "جاري فحص العملات..."
    );

    try {
      const data = await api(
        `/api/binance/scan?interval=${encodeURIComponent(
          state.interval
        )}&limit=40`
      );

      state.results = arrayFrom(data);

      renderScanner();

      setText(
        "scannerStatus",
        `تم العثور على ${state.results.length} نتيجة`
      );

    } catch (error) {
      console.error("scan:", error);

      setText(
        "scannerStatus",
        error.message ||
          "تعذر تشغيل الماسح."
      );
    } finally {
      state.loadingScan = false;

      if (button) {
        button.disabled = false;
        button.textContent =
          button.dataset.oldText ||
          "🔄 تحديث";
      }
    }
  }

  function normalizeSignal(value) {
    const signal = String(
      value || "حيادي"
    ).trim();

    return signal;
  }

  function renderScanner() {
    const body = $("scannerBody");

    if (!body) return;

    let rows = [...state.results];

    const search =
      $("scannerSearch")?.value
        .trim()
        .toUpperCase() || "";

    if (search) {
      rows = rows.filter((item) => {
        const symbol = String(
          firstValue(
            item,
            ["symbol", "ticker", "pair"],
            ""
          )
        ).toUpperCase();

        return symbol.includes(search);
      });
    }

    const activeSignals =
      state.signals || [];

    if (activeSignals.length) {
      rows = rows.filter((item) => {
        const signal =
          normalizeSignal(
            firstValue(
              item,
              [
                "signal",
                "recommendation",
                "action"
              ],
              "حيادي"
            )
          );

        return activeSignals.includes(signal);
      });
    }

    rows.sort((a, b) => {
      const field = state.sortField;

      let av = firstValue(
        a,
        [field],
        ""
      );

      let bv = firstValue(
        b,
        [field],
        ""
      );

      if (field === "symbol") {
        av = String(av);
        bv = String(bv);
      } else {
        av = safeNumber(av, 0);
        bv = safeNumber(bv, 0);
      }

      if (av < bv) {
        return state.sortDesc ? 1 : -1;
      }

      if (av > bv) {
        return state.sortDesc ? -1 : 1;
      }

      return 0;
    });

    if (!rows.length) {
      body.innerHTML = `
        <tr>
          <td colspan="7">
            لا توجد نتائج حالياً
          </td>
        </tr>
      `;

      return;
    }

    body.innerHTML = rows
      .map((item) => {
        const symbol = firstValue(
          item,
          ["symbol", "ticker", "pair"],
          "—"
        );

        const price = firstValue(
          item,
          ["price", "current_price", "lastPrice"],
          null
        );

        const change = firstValue(
          item,
          [
            "change",
            "change_percent",
            "priceChangePercent",
            "percent"
          ],
          null
        );

        const signal = normalizeSignal(
          firstValue(
            item,
            [
              "signal",
              "recommendation",
              "action"
            ],
            "حيادي"
          )
        );

        const score = firstValue(
          item,
          [
            "score",
            "strength",
            "confidence"
          ],
          null
        );

        const volume = firstValue(
          item,
          [
            "volume",
            "quoteVolume",
            "volume24h"
          ],
          null
        );

        return `
          <tr data-symbol="${escapeHtml(symbol)}">
            <td><b>${escapeHtml(symbol)}</b></td>
            <td>${formatNumber(price)}</td>
            <td>${formatPercent(change)}</td>
            <td>${escapeHtml(signal)}</td>
            <td>${score === null ? "—" : formatNumber(score, 0)}</td>
            <td>${formatNumber(volume, 0)}</td>
            <td>${escapeHtml(state.interval)}</td>
          </tr>
        `;
      })
      .join("");

    body
      .querySelectorAll("tr[data-symbol]")
      .forEach((row) => {
        row.addEventListener("click", () => {
          const symbol =
            row.dataset.symbol;

          if (!symbol) return;

          state.symbol = symbol;

          showSection("dashboard");

          loadAnalysis(
            symbol,
            state.interval
          );
        });
      });
  }

  function bindScanner() {
    $("scanBtn")?.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        scan();
      }
    );

    $("scannerSearch")?.addEventListener(
      "input",
      renderScanner
    );

    $("sortField")?.addEventListener(
      "change",
      (event) => {
        state.sortField =
          event.target.value ||
          "change";

        renderScanner();
      }
    );

    $("sortDir")?.addEventListener(
      "click",
      (event) => {
        event.preventDefault();

        state.sortDesc =
          !state.sortDesc;

        event.currentTarget.textContent =
          state.sortDesc
            ? "↓ تنازلي"
            : "↑ تصاعدي";

        renderScanner();
      }
    );

    document
      .querySelectorAll(
        "#intervalChips button"
      )
      .forEach((button) => {
        button.addEventListener(
          "click",
          (event) => {
            event.preventDefault();

            document
              .querySelectorAll(
                "#intervalChips button"
              )
              .forEach((item) =>
                item.classList.remove("active")
              );

            button.classList.add("active");

            state.interval =
              button.dataset.interval ||
              "15m";

            scan();
          }
        );
      });

    document
      .querySelectorAll(
        ".signal-chips button"
      )
      .forEach((button) => {
        button.addEventListener(
          "click",
          (event) => {
            event.preventDefault();

            const signal =
              button.dataset.signal;

            if (!signal) return;

            button.classList.toggle(
              "active"
            );

            if (
              state.signals.includes(
                signal
              )
            ) {
              state.signals =
                state.signals.filter(
                  (item) =>
                    item !== signal
                );
            } else {
              state.signals.push(
                signal
              );
            }

            renderScanner();
          }
        );
      });
  }

  // ============================================================
  // صفقات الأقسام
  // ============================================================

  function tradeEndpoint(type) {
    const endpoints = {
      alpha: "/api/trades/alpha",
      traditional:
        "/api/trades/traditional",
      spot: "/api/trades/spot",
      futures:
        "/api/trades/futures"
    };

    return endpoints[type];
  }

  async function loadTradeSection(type) {
    const map = {
      alpha: "alphaList",
      traditional:
        "traditionalList",
      futures: "futuresList"
    };

    const container = $(map[type]);

    if (!container) return;

    container.innerHTML = `
      <div class="empty-card">
        جاري تحميل الصفقات...
      </div>
    `;

    try {
      const endpoint =
        tradeEndpoint(type);

      const data = await api(endpoint);

      renderTradeList(
        container,
        arrayFrom(data),
        type
      );

    } catch (error) {
      console.warn(
        `${type} trades:`,
        error
      );

      container.innerHTML = `
        <div class="empty-card">
          لا توجد صفقات متاحة حالياً
        </div>
      `;
    }
  }

  async function loadSpot() {
    const container =
      $("spotList");

    if (!container) return;

    container.innerHTML = `
      <div class="empty-card">
        جاري تحميل صفقات السبوت...
      </div>
    `;

    try {
      let data;

      try {
        data = await api(
          "/api/trades/spot"
        );
      } catch {
        // إذا ما كان endpoint موجود،
        // نستخدم نتائج الماسح بدون تعطيل الصفحة.
        if (!state.results.length) {
          await scan();
        }

        renderTradeList(
          container,
          state.results,
          "spot"
        );

        return;
      }

      renderTradeList(
        container,
        arrayFrom(data),
        "spot"
      );

    } catch (error) {
      console.warn(
        "spot:",
        error
      );

      container.innerHTML = `
        <div class="empty-card">
          لا توجد صفقات سبوت متاحة حالياً
        </div>
      `;
    }
  }

  function renderTradeList(
    container,
    items,
    type
  ) {
    if (!items.length) {
      container.innerHTML = `
        <div class="empty-card">
          لا توجد صفقات متاحة حالياً
        </div>
      `;

      return;
    }

    container.innerHTML = items
      .map((item) => {
        const symbol =
          firstValue(
            item,
            [
              "symbol",
              "ticker",
              "pair"
            ],
            "—"
          );

        const side =
          firstValue(
            item,
            [
              "side",
              "signal",
              "action"
            ],
            "—"
          );

        const entry =
          firstValue(
            item,
            [
              "entry",
              "entry_price",
              "entryPrice"
            ],
            null
          );

        const target =
          firstValue(
            item,
            [
              "target",
              "tp",
              "take_profit",
              "tp1"
            ],
            null
          );

        const stop =
          firstValue(
            item,
            [
              "sl",
              "stop_loss",
              "stopLoss"
            ],
            null
          );

        const leverage =
          firstValue(
            item,
            [
              "leverage",
              "lev",
              "margin_leverage"
            ],
            null
          );

        const timeframe =
          firstValue(
            item,
            [
              "timeframe",
              "interval"
            ],
            ""
          );

        const date =
          firstValue(
            item,
            [
              "created_at",
              "createdAt",
              "date",
              "time"
            ],
            ""
          );

        return `
          <div class="trade-card">

            <div class="trade-card-head">
              <div>
                <b>${escapeHtml(symbol)}</b>
                <small>
                  ${escapeHtml(timeframe)}
                </small>
              </div>

              <strong>
                ${escapeHtml(side)}
              </strong>
            </div>

            <div class="trade-levels">

              <div>
                <span>الدخول</span>
                <b>${formatNumber(entry)}</b>
              </div>

              <div>
                <span>الهدف</span>
                <b>${formatNumber(target)}</b>
              </div>

              <div>
                <span>الوقف</span>
                <b>${formatNumber(stop)}</b>
              </div>

              ${
                type === "futures"
                  ? `
                    <div>
                      <span>الرافعة</span>
                      <b>
                        ${leverage === null
                          ? "—"
                          : escapeHtml(
                              leverage
                            )}
                      </b>
                    </div>
                  `
                  : ""
              }

            </div>

            ${
              date
                ? `
                  <small class="trade-date">
                    ${escapeHtml(date)}
                  </small>
                `
                : ""
            }

          </div>
        `;
      })
      .join("");
  }

  function bindTradeRefresh() {
    $("spotRefresh")?.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        loadSpot();
      }
    );

    $("futuresRefresh")?.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        loadTradeSection("futures");
      }
    );
  }

  // ============================================================
  // الأخبار
  // ============================================================

  async function loadNews() {
    const container =
      $("newsList");

    if (!container) return;

    container.innerHTML = `
      <div class="empty-card">
        جاري تحميل الأخبار...
      </div>
    `;

    try {
      const data =
        await api("/api/news");

      const items =
        arrayFrom(data);

      if (!items.length) {
        container.innerHTML = `
          <div class="empty-card">
            لا توجد أخبار حالياً
          </div>
        `;

        return;
      }

      container.innerHTML =
        items
          .map((item) => {
            const title =
              firstValue(
                item,
                [
                  "title",
                  "headline",
                  "name"
                ],
                "خبر"
              );

            const description =
              firstValue(
                item,
                [
                  "description",
                  "summary",
                  "content"
                ],
                ""
              );

            const url =
              firstValue(
                item,
                [
                  "url",
                  "link"
                ],
                ""
              );

            return `
              <article class="news-card">
                <h3>
                  ${escapeHtml(title)}
                </h3>

                <p>
                  ${escapeHtml(
                    description
                  )}
                </p>

                ${
                  url
                    ? `
                      <a
                        href="${escapeHtml(
                          url
                        )}"
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

    } catch (error) {
      console.warn(
        "news:",
        error
      );

      container.innerHTML = `
        <div class="empty-card">
          تعذر تحميل الأخبار حالياً
        </div>
      `;
    }
  }

  function bindNews() {
    $("newsBtn")?.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        loadNews();
      }
    );
  }

  // ============================================================
  // USDT.D و BTC.D
  // ============================================================

  async function loadDominance() {
    // لا نستخدم endpoint التحليل العادي
    // إذا كان backend لا يدعم رموز الهيمنة.
    // نحاول أولاً endpoints المخصصة إن كانت موجودة.

    const requests = [
      {
        symbol: "USDT.D",
        valueId: "usdtDominance",
        signalId:
          "usdtDominanceSignal",
        metaId:
          "usdtDominanceMeta"
      },
      {
        symbol: "BTC.D",
        valueId: "btcDominance",
        signalId:
          "btcDominanceSignal",
        metaId:
          "btcDominanceMeta"
      }
    ];

    await Promise.all(
      requests.map(
        async (item) => {
          try {
            const data =
              await api(
                `/api/dominance/${encodeURIComponent(
                  item.symbol
                )}`
              );

            renderDominance(
              item,
              data
            );

          } catch {
            // إذا لم يوجد endpoint
            // لا نوقف بقية الصفحة.
            setText(
              item.valueId,
              "—"
            );

            setText(
              item.signalId,
              "غير متاح"
            );

            setText(
              item.metaId,
              item.symbol
            );
          }
        }
      )
    );
  }

  function renderDominance(
    item,
    data
  ) {
    const root =
      unwrap(data) || {};

    const value =
      firstValue(
        root,
        [
          "value",
          "dominance",
          "price",
          "current",
          "percent"
        ],
        null
      );

    const signal =
      firstValue(
        root,
        [
          "signal",
          "recommendation",
          "action"
        ],
        "حيادي"
      );

    const change =
      firstValue(
        root,
        [
          "change",
          "change_percent",
          "changePercent"
        ],
        null
      );

    setText(
      item.valueId,
      value === null
        ? "—"
        : `${formatNumber(value, 2)}%`
    );

    setText(
      item.signalId,
      signal
    );

    setText(
      item.metaId,
      change === null
        ? item.symbol
        : `${item.symbol} | ${formatPercent(
            change
          )}`
    );
  }

  // ============================================================
  // الاشتراك
  // ============================================================

  async function loadSubscription() {
    if (!state.user) return;

    try {
      const plans =
        await api(
          "/api/subscription/plans"
        );

      renderPlans(
        arrayFrom(plans)
      );
    } catch (error) {
      console.warn(
        "plans:",
        error
      );
    }

    try {
      const data =
        await api(
          "/api/subscription/my"
        );

      renderSubscriptionStatus(
        data
      );
    } catch (error) {
      console.warn(
        "subscription/my:",
        error
      );
    }
  }

  function renderPlans(plans) {
    const container =
      $("plans");

    if (!container) return;

    if (!plans.length) {
      container.innerHTML = `
        <div class="empty-card">
          لا توجد باقات متاحة حالياً
        </div>
      `;

      return;
    }

    container.innerHTML =
      plans
        .map((plan, index) => {
          const id =
            firstValue(
              plan,
              ["id", "plan_id"],
              index
            );

          const name =
            firstValue(
              plan,
              [
                "name",
                "title"
              ],
              "باقة"
            );

          const price =
            firstValue(
              plan,
              [
                "price",
                "amount"
              ],
              ""
            );

          const days =
            firstValue(
              plan,
              [
                "days",
                "duration"
              ],
              ""
            );

          return `
            <div class="plan-card">

              <h3>
                ${escapeHtml(name)}
              </h3>

              <strong>
                ${escapeHtml(price)}
              </strong>

              <small>
                ${escapeHtml(days)}
              </small>

              <button
                class="btn primary plan-select"
                data-plan-id="${escapeHtml(id)}"
              >
                اختيار الباقة
              </button>

            </div>
          `;
        })
        .join("");

    container
      .querySelectorAll(
        ".plan-select"
      )
      .forEach((button) => {
        button.addEventListener(
          "click",
          () => {
            selectPlan(
              button.dataset.planId
            );
          }
        );
      });
  }

  async function renderSubscriptionStatus(
    data
  ) {
    const root =
      unwrap(data) || {};

    const status =
      firstValue(
        root,
        [
          "status",
          "subscription_status"
        ],
        "لا يوجد اشتراك"
      );

    setText(
      "subscriptionStatus",
      status
    );
  }

  async function selectPlan(planId) {
    if (!planId) return;

    const paymentBox =
      $("paymentBox");

    if (paymentBox) {
      paymentBox.hidden = false;
    }

    setText(
      "chosenPlan",
      `الباقة المختارة: ${planId}`
    );

    try {
      const data =
        await api(
          "/api/subscription/plans"
        );

      const plans =
        arrayFrom(data);

      const plan =
        plans.find(
          (item) =>
            String(
              firstValue(
                item,
                ["id", "plan_id"],
                ""
              )
            ) ===
            String(planId)
        );

      if (plan) {
        const price =
          firstValue(
            plan,
            ["price", "amount"],
            ""
          );

        setText(
          "chosenPlan",
          `الباقة: ${firstValue(
            plan,
            ["name", "title"],
            "باقة"
          )} — ${price}`
        );
      }
    } catch (error) {
      console.warn(
        "selectPlan:",
        error
      );
    }
  }

  function bindSubscription() {
    $("copyAddress")?.addEventListener(
      "click",
      async (event) => {
        event.preventDefault();

        const input =
          $("payAddress");

        if (!input?.value) return;

        try {
          await navigator.clipboard.writeText(
            input.value
          );

          setText(
            "paymentMsg",
            "تم نسخ العنوان."
          );
        } catch {
          input.select();
          document.execCommand(
            "copy"
          );

          setText(
            "paymentMsg",
            "تم نسخ العنوان."
          );
        }
      }
    );

    $("sendPayment")?.addEventListener(
      "click",
      async (event) => {
        event.preventDefault();

        const txid =
          $("txid")?.value.trim();

        if (!txid) {
          setText(
            "paymentMsg",
            "أدخل TXID أولاً."
          );
          return;
        }

        const button =
          $("sendPayment");

        if (button) {
          button.disabled = true;
        }

        try {
          await api(
            "/api/subscription/request",
            {
              method: "POST",
              body: {
                txid
              }
            }
          );

          setText(
            "paymentMsg",
            "تم إرسال طلب الاشتراك بنجاح."
          );

        } catch (error) {
          setText(
            "paymentMsg",
            error.message ||
              "تعذر إرسال الطلب."
          );
        } finally {
          if (button) {
            button.disabled = false;
          }
        }
      }
    );
  }

  // ============================================================
  // الوضع الليلي
  // ============================================================

  function bindTheme() {
    const button =
      $("themeBtn");

    if (!button) return;

    const saved =
      localStorage.getItem(
        "theme"
      );

    if (saved === "dark") {
      document.body.classList.add(
        "dark"
      );
    }

    button.addEventListener(
      "click",
      (event) => {
        event.preventDefault();

        document.body.classList.toggle(
          "dark"
        );

        const dark =
          document.body.classList.contains(
            "dark"
          );

        localStorage.setItem(
          "theme",
          dark ? "dark" : "light"
        );

        button.textContent =
          dark
            ? "☀️ الوضع النهاري"
            : "🌙 الوضع الليلي";
      }
    );
  }

  // ============================================================
  // التشغيل
  // ============================================================

  async function boot() {
    try {
      setText(
        "systemStatus",
        "جاري الاتصال..."
      );

      bindNavigation();
      bindMenu();
      bindAuth();
      bindDashboardIntervals();
      bindScanner();
      bindTradeRefresh();
      bindNews();
      bindSubscription();
      bindTheme();

      // هذه كلها منفصلة؛ فشل واحدة ما يوقف الثانية
      await loadCurrentUser();

      await Promise.allSettled([
        loadAnalysis(
          "BTCUSDT",
          "15m"
        ),
        scan(),
        loadNews(),
        loadDominance()
      ]);

      setText(
        "systemStatus",
        "متصل"
      );

    } catch (error) {
      console.error(
        "BOOT ERROR:",
        error
      );

      setText(
        "systemStatus",
        "متصل - بعض البيانات غير متاحة"
      );
    }
  }

  // نضمن أن DOM جاهز
  if (
    document.readyState ===
    "loading"
  ) {
    document.addEventListener(
      "DOMContentLoaded",
      boot,
      { once: true }
    );
  } else {
    boot();
  }

})();
