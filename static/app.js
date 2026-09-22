(() => {
  "use strict";

  // ============================================================
  // مضارب أبو سعود
  // app.js
  // تسجيل الدخول + إنشاء الحساب + التحليلات + الماسح
  // بدون تحويل المستخدم إلى /login أو /register
  // ============================================================

  const $ = (id) => document.getElementById(id);

  const state = {
    user: null,
    admin: false,

    symbol: "BTCUSDT",
    interval: "15m",

    results: [],
    signals: [],

    sortField: "change",
    sortDesc: true,

    chart: null,

    loadingAnalysis: false,
    loadingScan: false,

    selectedPlan: null
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

    const text = await response.text();

    let data = {};

    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      data = {
        ok: response.ok,
        raw: text
      };
    }

    if (!response.ok) {
      const message =
        data?.message ||
        data?.error ||
        data?.detail ||
        `HTTP ${response.status}`;

      throw new Error(message);
    }

    return data;
  }

  // ============================================================
  // HELPERS
  // ============================================================

  function getAnalysisFromResponse(data) {
    if (!data || typeof data !== "object") {
      return {};
    }

    if (data.analysis && typeof data.analysis === "object") {
      return data.analysis;
    }

    if (
      data.data &&
      typeof data.data === "object" &&
      data.data.analysis &&
      typeof data.data.analysis === "object"
    ) {
      return data.data.analysis;
    }

    if (
      data.result &&
      typeof data.result === "object" &&
      data.result.analysis &&
      typeof data.result.analysis === "object"
    ) {
      return data.result.analysis;
    }

    if (data.result && typeof data.result === "object") {
      return data.result;
    }

    if (data.data && typeof data.data === "object") {
      return data.data;
    }

    return data;
  }

  function getUserFromResponse(data) {
    if (!data || typeof data !== "object") {
      return null;
    }

    if (data.user) {
      return data.user;
    }

    if (data.account) {
      return data.account;
    }

    if (data.data?.user) {
      return data.data.user;
    }

    if (data.data?.account) {
      return data.data.account;
    }

    return null;
  }

  function getArray(data, key) {
    if (Array.isArray(data)) {
      return data;
    }

    if (Array.isArray(data?.[key])) {
      return data[key];
    }

    if (Array.isArray(data?.data?.[key])) {
      return data.data[key];
    }

    if (Array.isArray(data?.result?.[key])) {
      return data.result[key];
    }

    if (Array.isArray(data?.results)) {
      return data.results;
    }

    if (Array.isArray(data?.data)) {
      return data.data;
    }

    return [];
  }

  function setText(id, value) {
    const el = $(id);

    if (el) {
      el.textContent =
        value === undefined ||
        value === null ||
        value === ""
          ? "—"
          : String(value);
    }
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function numberValue(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function formatNumber(value, digits = 2) {
    const n = numberValue(value);

    if (n === null) {
      return "—";
    }

    return n.toLocaleString("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits
    });
  }

  function formatPercent(value, digits = 2) {
    const n = numberValue(value);

    if (n === null) {
      return "—";
    }

    return `${n >= 0 ? "+" : ""}${n.toFixed(digits)}%`;
  }

  function signalClass(signal) {
    const s = String(signal || "").toLowerCase();

    if (
      s.includes("strong buy") ||
      s.includes("شراء قوي") ||
      s.includes("strong_buy")
    ) {
      return "strong-buy";
    }

    if (
      s.includes("buy") ||
      s.includes("شراء")
    ) {
      return "buy";
    }

    if (
      s.includes("strong sell") ||
      s.includes("بيع قوي") ||
      s.includes("strong_sell")
    ) {
      return "strong-sell";
    }

    if (
      s.includes("sell") ||
      s.includes("بيع")
    ) {
      return "sell";
    }

    return "neutral";
  }

  function signalText(signal) {
    if (!signal) {
      return "محايد";
    }

    const s = String(signal).toLowerCase();

    if (
      s.includes("strong buy") ||
      s.includes("شراء قوي") ||
      s.includes("strong_buy")
    ) {
      return "شراء قوي";
    }

    if (
      s.includes("buy") ||
      s.includes("شراء")
    ) {
      return "شراء";
    }

    if (
      s.includes("strong sell") ||
      s.includes("بيع قوي") ||
      s.includes("strong_sell")
    ) {
      return "بيع قوي";
    }

    if (
      s.includes("sell") ||
      s.includes("بيع")
    ) {
      return "بيع";
    }

    return "محايد";
  }

  function showMessage(element, message, type = "") {
    if (!element) {
      return;
    }

    element.textContent = message || "";

    element.classList.remove(
      "success",
      "error",
      "warning"
    );

    if (type) {
      element.classList.add(type);
    }
  }

  // ============================================================
  // SECTIONS / NAVIGATION
  // ============================================================

  function showSection(id) {
    const sections = document.querySelectorAll(".section");

    sections.forEach((section) => {
      const active = section.id === id;

      section.classList.toggle("active", active);
      section.hidden = !active;
    });

    document
      .querySelectorAll(".nav-btn")
      .forEach((button) => {
        button.classList.toggle(
          "active",
          button.dataset.section === id
        );
      });

    const sidebar = $("sidebar");

    if (sidebar) {
      sidebar.classList.remove("open");
    }

    if (id === "dashboard") {
      loadAnalysis();
      loadDominance();
    }

    if (id === "scanner") {
      scan();
    }

    if (id === "spot") {
      loadSpot();
    }

    if (id === "futures") {
      loadFutures();
    }

    if (id === "alpha") {
      loadTradeSection("alpha");
    }

    if (id === "traditional") {
      loadTradeSection("traditional");
    }

    if (id === "news") {
      loadNews();
    }

    if (id === "subscription") {
      if (!state.user) {
        openAuth("login");
        showSection("dashboard");
        return;
      }

      loadSubscription();
    }
  }

  function bindNavigation() {
    document
      .querySelectorAll(".nav-btn")
      .forEach((button) => {
        button.addEventListener("click", () => {
          const section = button.dataset.section;

          if (!section) {
            return;
          }

          if (section === "subscription" && !state.user) {
            openAuth("login");
            return;
          }

          showSection(section);
        });
      });
  }

  // ============================================================
  // SIDEBAR
  // ============================================================

  function bindSidebar() {
    const menuBtn = $("menuBtn");
    const sidebar = $("sidebar");

    if (menuBtn && sidebar) {
      menuBtn.addEventListener("click", (event) => {
        event.stopPropagation();
        sidebar.classList.toggle("open");
      });
    }

    document.addEventListener("click", (event) => {
      if (!sidebar) {
        return;
      }

      if (
        sidebar.classList.contains("open") &&
        !sidebar.contains(event.target) &&
        event.target !== menuBtn
      ) {
        sidebar.classList.remove("open");
      }
    });
  }

  // ============================================================
  // AUTH MODAL
  // ============================================================

  function openAuth(tab = "login") {
    const modal = $("authModal");

    if (!modal) {
      return;
    }

    modal.classList.add("open");
    modal.hidden = false;

    switchAuth(tab);
  }

  function closeAuth() {
    const modal = $("authModal");

    if (!modal) {
      return;
    }

    modal.classList.remove("open");
    modal.hidden = true;

    showMessage($("authMsg"), "");
  }

  function switchAuth(tab) {
    const loginTab = $("loginTab");
    const registerTab = $("registerTab");

    const loginForm = $("loginForm");
    const registerForm = $("registerForm");

    if (loginTab) {
      loginTab.classList.toggle(
        "active",
        tab === "login"
      );
    }

    if (registerTab) {
      registerTab.classList.toggle(
        "active",
        tab === "register"
      );
    }

    if (loginForm) {
      loginForm.hidden = tab !== "login";
    }

    if (registerForm) {
      registerForm.hidden = tab !== "register";
    }

    showMessage($("authMsg"), "");
  }

  function bindAuth() {
    const loginBtn = $("loginBtn");
    const registerBtn = $("registerBtn");
    const logoutBtn = $("logoutBtn");

    const closeBtn = $("authClose");
    const modal = $("authModal");

    const loginTab = $("loginTab");
    const registerTab = $("registerTab");

    const loginForm = $("loginForm");
    const registerForm = $("registerForm");

    if (loginBtn) {
      loginBtn.addEventListener("click", () => {
        openAuth("login");
      });
    }

    if (registerBtn) {
      registerBtn.addEventListener("click", () => {
        openAuth("register");
      });
    }

    if (logoutBtn) {
      logoutBtn.addEventListener("click", logout);
    }

    if (closeBtn) {
      closeBtn.addEventListener("click", closeAuth);
    }

    if (loginTab) {
      loginTab.addEventListener("click", () => {
        switchAuth("login");
      });
    }

    if (registerTab) {
      registerTab.addEventListener("click", () => {
        switchAuth("register");
      });
    }

    if (modal) {
      modal.addEventListener("click", (event) => {
        if (event.target === modal) {
          closeAuth();
        }
      });
    }

    if (loginForm) {
      loginForm.addEventListener("submit", async (event) => {
        event.preventDefault();

        const email = $("loginEmail")?.value.trim();
        const password = $("loginPassword")?.value;

        if (!email || !password) {
          showMessage(
            $("authMsg"),
            "اكتب البريد وكلمة المرور",
            "error"
          );
          return;
        }

        const submit =
          loginForm.querySelector(
            'button[type="submit"]'
          );

        if (submit) {
          submit.disabled = true;
        }

        showMessage(
          $("authMsg"),
          "جاري تسجيل الدخول..."
        );

        try {
          const data = await api(
            "/api/auth/login",
            {
              method: "POST",
              body: {
                email,
                password
              }
            }
          );

          let user = getUserFromResponse(data);

          if (!user) {
            try {
              const me = await api(
                "/api/auth/me"
              );

              user = getUserFromResponse(me);
            } catch {}
          }

          if (!user) {
            throw new Error(
              data?.message ||
              "تعذر تسجيل الدخول"
            );
          }

          state.user = user;

          await loadUser();

          closeAuth();

          showSection("dashboard");
        } catch (error) {
          showMessage(
            $("authMsg"),
            error.message ||
              "فشل تسجيل الدخول",
            "error"
          );
        } finally {
          if (submit) {
            submit.disabled = false;
          }
        }
      });
    }

    if (registerForm) {
      registerForm.addEventListener(
        "submit",
        async (event) => {
          event.preventDefault();

          const name =
            $("regName")?.value.trim();

          const email =
            $("regEmail")?.value.trim();

          const password =
            $("regPassword")?.value;

          if (!name || !email || !password) {
            showMessage(
              $("authMsg"),
              "عبّي جميع البيانات",
              "error"
            );
            return;
          }

          const submit =
            registerForm.querySelector(
              'button[type="submit"]'
            );

          if (submit) {
            submit.disabled = true;
          }

          showMessage(
            $("authMsg"),
            "جاري إنشاء الحساب..."
          );

          try {
            const data = await api(
              "/api/auth/register",
              {
                method: "POST",
                body: {
                  name,
                  email,
                  password
                }
              }
            );

            let user = getUserFromResponse(data);

            if (!user) {
              try {
                const loginData = await api(
                  "/api/auth/login",
                  {
                    method: "POST",
                    body: {
                      email,
                      password
                    }
                  }
                );

                user =
                  getUserFromResponse(
                    loginData
                  );
              } catch {}
            }

            if (user) {
              state.user = user;

              await loadUser();

              closeAuth();

              showSection("dashboard");
            } else {
              showMessage(
                $("authMsg"),
                data?.message ||
                  "تم إنشاء الحساب، سجّل الدخول الآن",
                "success"
              );

              switchAuth("login");

              if ($("loginEmail")) {
                $("loginEmail").value =
                  email;
              }
            }
          } catch (error) {
            showMessage(
              $("authMsg"),
              error.message ||
                "فشل إنشاء الحساب",
              "error"
            );
          } finally {
            if (submit) {
              submit.disabled = false;
            }
          }
        }
      );
    }
  }

  // ============================================================
  // USER
  // ============================================================

  async function loadUser() {
    try {
      const data = await api(
        "/api/auth/me"
      );

      const user =
        getUserFromResponse(data);

      if (user) {
        state.user = user;
      }
    } catch {
      state.user = null;
    }

    try {
      const adminData = await api(
        "/api/admin/me"
      );

      state.admin =
        !!(
          adminData?.admin ||
          adminData?.is_admin ||
          adminData?.user?.is_admin
        );
    } catch {
      state.admin = false;
    }

    updateUserUI();
  }

  function updateUserUI() {
    const loginBtn = $("loginBtn");
    const registerBtn = $("registerBtn");
    const logoutBtn = $("logoutBtn");

    const userBadge = $("userBadge");
    const subscriptionNav =
      $("subscriptionNav");

    if (state.user) {
      if (loginBtn) {
        loginBtn.hidden = true;
      }

      if (registerBtn) {
        registerBtn.hidden = true;
      }

      if (logoutBtn) {
        logoutBtn.hidden = false;
      }

      if (subscriptionNav) {
        subscriptionNav.hidden = false;
      }

      if (userBadge) {
        const name =
          state.user.name ||
          state.user.email ||
          "المستخدم";

        userBadge.textContent = name;
        userBadge.hidden = false;
      }
    } else {
      if (loginBtn) {
        loginBtn.hidden = false;
      }

      if (registerBtn) {
        registerBtn.hidden = false;
      }

      if (logoutBtn) {
        logoutBtn.hidden = true;
      }

      if (subscriptionNav) {
        subscriptionNav.hidden = true;
      }

      if (userBadge) {
        userBadge.textContent = "";
        userBadge.hidden = true;
      }
    }

    const adminBtn =
      document.querySelector(
        '[data-section="admin"]'
      );

    if (adminBtn) {
      adminBtn.hidden =
        !state.admin;
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
    } catch {}

    state.user = null;
    state.admin = false;

    updateUserUI();

    showSection("dashboard");
  }

  // ============================================================
  // ANALYSIS
  // ============================================================

  async function loadAnalysis() {
    if (state.loadingAnalysis) {
      return;
    }

    state.loadingAnalysis = true;

    try {
      const url =
        `/api/binance/analysis` +
        `?symbol=${encodeURIComponent(
          state.symbol
        )}` +
        `&interval=${encodeURIComponent(
          state.interval
        )}`;

      const data = await api(url);

      const analysis =
        getAnalysisFromResponse(data);

      renderAnalysis(analysis);
    } catch (error) {
      setText(
        "dashSignal",
        "غير متاح"
      );

      setText(
        "bigSignal",
        "تعذر جلب التحليل"
      );

      setText(
        "reasons",
        error.message ||
          "تعذر تحميل التحليل"
      );
    } finally {
      state.loadingAnalysis = false;
    }
  }

  function renderAnalysis(a) {
    if (!a || typeof a !== "object") {
      return;
    }

    const indicators =
      a.indicators &&
      typeof a.indicators === "object"
        ? a.indicators
        : {};

    const levels =
      a.levels &&
      typeof a.levels === "object"
        ? a.levels
        : {};

    const symbol =
      a.symbol ||
      state.symbol;

    const price =
      a.price ??
      a.current_price ??
      a.last_price ??
      a.close;

    const change =
      a.change_24h ??
      a.change24h ??
      a.price_change_24h ??
      a.change;

    const signal =
      a.signal ??
      a.final_signal ??
      a.trade_signal ??
      a.recommendation;

    setText(
      "dashSymbol",
      symbol
    );

    setText(
      "dashPrice",
      price !== undefined &&
        price !== null
        ? formatNumber(price, 4)
        : "—"
    );

    setText(
      "dashChange",
      formatPercent(change)
    );

    setText(
      "dashSignal",
      signalText(signal)
    );

    setText(
      "bigSignal",
      signalText(signal)
    );

    const entry =
      levels.entry ??
      a.entry;

    const tp1 =
      levels.tp1 ??
      levels.target1 ??
      a.tp1 ??
      a.target1;

    const tp2 =
      levels.tp2 ??
      levels.target2 ??
      a.tp2 ??
      a.target2;

    const tp3 =
      levels.tp3 ??
      levels.target3 ??
      a.tp3 ??
      a.target3;

    const sl =
      levels.sl ??
      levels.stop_loss ??
      levels.stopLoss ??
      a.sl ??
      a.stop_loss;

    setText(
      "entry",
      entry !== undefined &&
        entry !== null
        ? formatNumber(entry, 4)
        : "—"
    );

    setText(
      "tp1",
      tp1 !== undefined &&
        tp1 !== null
        ? formatNumber(tp1, 4)
        : "—"
    );

    setText(
      "tp2",
      tp2 !== undefined &&
        tp2 !== null
        ? formatNumber(tp2, 4)
        : "—"
    );

    setText(
      "tp3",
      tp3 !== undefined &&
        tp3 !== null
        ? formatNumber(tp3, 4)
        : "—"
    );

    setText(
      "sl",
      sl !== undefined &&
        sl !== null
        ? formatNumber(sl, 4)
        : "—"
    );

    const rsiValue =
      indicators.rsi ??
      a.rsi;

    setText(
      "rsi",
      rsiValue === null ||
        rsiValue === undefined ||
        rsiValue === ""
        ? "—"
        : Number.isFinite(
            Number(rsiValue)
          )
          ? Number(rsiValue).toFixed(2)
          : "—"
    );

    const ema20 =
      indicators.ema20 ??
      indicators.EMA20 ??
      a.ema20 ??
      a.EMA20;

    const ema50 =
      indicators.ema50 ??
      indicators.EMA50 ??
      a.ema50 ??
      a.EMA50;

    const ema200 =
      indicators.ema200 ??
      indicators.EMA200 ??
      a.ema200 ??
      a.EMA200;

    setText(
      "ema20",
      ema20 !== undefined &&
        ema20 !== null
        ? formatNumber(ema20, 4)
        : "—"
    );

    setText(
      "ema50",
      ema50 !== undefined &&
        ema50 !== null
        ? formatNumber(ema50, 4)
        : "—"
    );

    setText(
      "ema200",
      ema200 !== undefined &&
        ema200 !== null
        ? formatNumber(ema200, 4)
        : "—"
    );

    const score =
      a.score ??
      a.confidence ??
      a.signal_score;

    if (
      score !== undefined &&
      score !== null
    ) {
      const n = Number(score);

      if (Number.isFinite(n)) {
        setText(
          "scoreText",
          `${n.toFixed(0)}%`
        );

        const bar =
          $("scoreBar");

        if (bar) {
          bar.style.width =
            `${Math.max(
              0,
              Math.min(100, n)
            )}%`;
        }
      }
    }

    const reasons =
      a.reasons ??
      a.reason ??
      a.explanation ??
      [];

    const reasonsEl =
      $("reasons");

    if (reasonsEl) {
      if (Array.isArray(reasons)) {
        reasonsEl.innerHTML =
          reasons.length
            ? reasons
                .map(
                  (item) =>
                    `<div>${escapeHtml(
                      item
                    )}</div>`
                )
                .join("")
            : "—";
      } else {
        reasonsEl.textContent =
          reasons || "—";
      }
    }

    renderChart(a);
  }

  // ============================================================
  // CHART
  // ============================================================

  function renderChart(a) {
    const canvas =
      $("priceChart");

    if (
      !canvas ||
      typeof Chart === "undefined"
    ) {
      return;
    }

    let candles =
      a.klines ??
      a.candles ??
      a.chart ??
      [];

    if (
      candles &&
      !Array.isArray(candles) &&
      Array.isArray(candles.data)
    ) {
      candles = candles.data;
    }

    if (!Array.isArray(candles)) {
      candles = [];
    }

    const labels = [];
    const prices = [];

    candles.forEach((candle) => {
      if (Array.isArray(candle)) {
        const time =
          Number(candle[0]);

        const close =
          Number(candle[4]);

        if (
          Number.isFinite(time) &&
          Number.isFinite(close)
        ) {
          labels.push(
            new Date(
              time
            ).toLocaleTimeString(
              "ar-SA",
              {
                hour: "2-digit",
                minute: "2-digit"
              }
            )
          );

          prices.push(close);
        }

        return;
      }

      if (
        candle &&
        typeof candle === "object"
      ) {
        const time =
          candle.time ??
          candle.timestamp ??
          candle.open_time;

        const close =
          candle.close ??
          candle.c;

        const t =
          Number(time);

        const p =
          Number(close);

        if (
          Number.isFinite(t) &&
          Number.isFinite(p)
        ) {
          labels.push(
            new Date(
              t
            ).toLocaleTimeString(
              "ar-SA",
              {
                hour: "2-digit",
                minute: "2-digit"
              }
            )
          );

          prices.push(p);
        }
      }
    });

    if (!labels.length) {
      return;
    }

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

                data: prices,

                tension: 0.25,

                pointRadius: 0
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
              }
            }
          }
        }
      );
  }

  // ============================================================
  // DASHBOARD INTERVAL
  // ============================================================

  function bindDashboardIntervals() {
    document
      .querySelectorAll(
        "[data-interval]"
      )
      .forEach((button) => {
        button.addEventListener(
          "click",
          () => {
            state.interval =
              button.dataset.interval ||
              "15m";

            document
              .querySelectorAll(
                "[data-interval]"
              )
              .forEach((btn) => {
                btn.classList.toggle(
                  "active",
                  btn.dataset.interval ===
                    state.interval
                );
              });

            loadAnalysis();
          }
        );
      });
  }

  // ============================================================
  // SCANNER
  // ============================================================

  async function scan() {
    if (state.loadingScan) {
      return;
    }

    state.loadingScan = true;

    const status =
      $("scannerStatus");

    const body =
      $("scannerBody");

    if (status) {
      status.textContent =
        "جاري فحص السوق...";
    }

    if (body) {
      body.innerHTML =
        `<tr>
          <td colspan="10">
            جاري الفحص...
          </td>
        </tr>`;
    }

    try {
      const url =
        `/api/binance/scan` +
        `?interval=${encodeURIComponent(
          state.interval
        )}`;

      const data = await api(url);

      const rows =
        getArray(data, "results");

      state.results = rows;

      renderScanner();
    } catch (error) {
      if (status) {
        status.textContent =
          error.message ||
          "تعذر فحص السوق";
      }

      if (body) {
        body.innerHTML =
          `<tr>
            <td colspan="10">
              ${escapeHtml(
                error.message ||
                  "تعذر فحص السوق"
              )}
            </td>
          </tr>`;
      }
    } finally {
      state.loadingScan = false;
    }
  }

  function renderScanner() {
    const body =
      $("scannerBody");

    if (!body) {
      return;
    }

    let rows =
      Array.isArray(state.results)
        ? [...state.results]
        : [];

    const search =
      $("scannerSearch")
        ?.value
        ?.trim()
        ?.toUpperCase() || "";

    if (search) {
      rows = rows.filter(
        (row) =>
          String(
            row.symbol ||
              row.ticker ||
              ""
          )
            .toUpperCase()
            .includes(search)
      );
    }

    const signalFilter =
      document.querySelector(
        ".signal-chips .active"
      )?.dataset?.signal || "";

    if (signalFilter) {
      rows = rows.filter(
        (row) => {
          const signal =
            signalText(
              row.signal
            );

          return (
            signal ===
            signalFilter
          );
        }
      );
    }

    rows.sort(
      (a, b) => {
        const av =
          Number(
            a[state.sortField] ??
              a.change ??
              a.change_24h ??
              0
          );

        const bv =
          Number(
            b[state.sortField] ??
              b.change ??
              b.change_24h ??
              0
          );

        if (
          Number.isNaN(av) ||
          Number.isNaN(bv)
        ) {
          return 0;
        }

        return state.sortDesc
          ? bv - av
          : av - bv;
      }
    );

    if (!rows.length) {
      body.innerHTML =
        `<tr>
          <td colspan="10">
            لا توجد نتائج
          </td>
        </tr>`;

      return;
    }

    body.innerHTML =
      rows
        .map(
          (row) => {
            const symbol =
              row.symbol ||
              row.ticker ||
              "—";

            const price =
              row.price ??
              row.last_price ??
              row.close;

            const change =
              row.change ??
              row.change_24h ??
              row.change24h;

            const signal =
              signalText(
                row.signal
              );

            const cls =
              signalClass(
                row.signal
              );

            return `
              <tr
                class="scanner-row"
                data-symbol="${escapeHtml(
                  symbol
                )}"
              >
                <td>
                  <strong>
                    ${escapeHtml(
                      symbol
                    )}
                  </strong>
                </td>

                <td>
                  ${
                    price !==
                    undefined
                      ? formatNumber(
                          price,
                          6
                        )
                      : "—"
                  }
                </td>

                <td>
                  ${formatPercent(
                    change
                  )}
                </td>

                <td>
                  <span
                    class="signal ${cls}"
                  >
                    ${escapeHtml(
                      signal
                    )}
                  </span>
                </td>

                <td>
                  ${escapeHtml(
                    row.volume ??
                      row.quoteVolume ??
                      "—"
                  )}
                </td>

                <td>
                  ${escapeHtml(
                    row.rsi ??
                      row.indicators?.rsi ??
                      "—"
                  )}
                </td>

                <td>
                  ${escapeHtml(
                    row.score ??
                      row.confidence ??
                      "—"
                  )}
                </td>
              </tr>
            `;
          }
        )
        .join("");

    document
      .querySelectorAll(
        ".scanner-row"
      )
      .forEach((row) => {
        row.addEventListener(
          "click",
          () => {
            const symbol =
              row.dataset.symbol;

            if (!symbol) {
              return;
            }

            state.symbol =
              symbol.toUpperCase();

            showSection(
              "dashboard"
            );

            loadAnalysis();
          }
        );
      });

    const status =
      $("scannerStatus");

    if (status) {
      status.textContent =
        `تم العثور على ${rows.length} فرصة`;
    }
  }

  function bindScanner() {
    const scanBtn =
      $("scanBtn");

    if (scanBtn) {
      scanBtn.addEventListener(
        "click",
        scan
      );
    }

    const search =
      $("scannerSearch");

    if (search) {
      search.addEventListener(
        "input",
        renderScanner
      );
    }

    document
      .querySelectorAll(
        ".signal-chips button"
      )
      .forEach((button) => {
        button.addEventListener(
          "click",
          () => {
            document
              .querySelectorAll(
                ".signal-chips button"
              )
              .forEach(
                (btn) =>
                  btn.classList.remove(
                    "active"
                  )
              );

            button.classList.add(
              "active"
            );

            renderScanner();
          }
        );
      });

    document
      .querySelectorAll(
        ".intervalChips button"
      )
      .forEach((button) => {
        button.addEventListener(
          "click",
          () => {
            const interval =
              button.dataset.interval;

            if (interval) {
              state.interval =
                interval;
            }

            document
              .querySelectorAll(
                ".intervalChips button"
              )
              .forEach(
                (btn) =>
                  btn.classList.toggle(
                    "active",
                    btn === button
                  )
              );

            scan();
          }
        );
      });

    const sortField =
      $("sortField");

    const sortDir =
      $("sortDir");

    if (sortField) {
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

    if (sortDir) {
      sortDir.addEventListener(
        "click",
        () => {
          state.sortDesc =
            !state.sortDesc;

          sortDir.textContent =
            state.sortDesc
              ? "↓"
              : "↑";

          renderScanner();
        }
      );
    }
  }

  // ============================================================
  // SPOT
  // ============================================================

  async function loadSpot() {
    const list =
      $("spotList");

    if (!list) {
      return;
    }

    if (
      state.results &&
      state.results.length
    ) {
      renderTradeList(
        list,
        state.results,
        "spot"
      );

      return;
    }

    try {
      await scan();

      renderTradeList(
        list,
        state.results,
        "spot"
      );
    } catch {
      list.innerHTML =
        `<div class="empty-state">
          لا توجد صفقات سبوت حالياً
        </div>`;
    }
  }

  // ============================================================
  // FUTURES
  // ============================================================

  async function loadFutures() {
    const list =
      $("futuresList");

    if (!list) {
      return;
    }

    try {
      const data =
        await api(
          "/api/trades/futures"
        );

      const rows =
        getArray(
          data,
          "trades"
        );

      renderTradeList(
        list,
        rows,
        "futures"
      );
    } catch {
      list.innerHTML =
        `<div class="empty-state">
          لا توجد صفقات فيوتشر حالياً
        </div>`;
    }
  }

  // ============================================================
  // TRADE SECTIONS
  // ============================================================

  async function loadTradeSection(
    type
  ) {
    const list =
      $(`${type}List`);

    if (!list) {
      return;
    }

    list.innerHTML =
      `<div class="empty-state">
        جاري تحميل الصفقات...
      </div>`;

    try {
      const data =
        await api(
          `/api/trades/${encodeURIComponent(
            type
          )}`
        );

      const rows =
        getArray(
          data,
          "trades"
        );

      renderTradeList(
        list,
        rows,
        type
      );
    } catch {
      list.innerHTML =
        `<div class="empty-state">
          لا توجد صفقات ${escapeHtml(
            type
          )} حالياً
        </div>`;
    }
  }

  function renderTradeList(
    list,
    rows,
    type
  ) {
    if (!list) {
      return;
    }

    if (
      !Array.isArray(rows) ||
      !rows.length
    ) {
      list.innerHTML =
        `<div class="empty-state">
          لا توجد صفقات حالياً
        </div>`;

      return;
    }

    list.innerHTML =
      rows
        .map(
          (trade) => {
            const symbol =
              trade.symbol ||
              trade.ticker ||
              "—";

            const signal =
              signalText(
                trade.signal
              );

            const leverage =
              trade.leverage ??
              trade.lev;

            const entry =
              trade.entry ??
              trade.entry_price;

            const target =
              trade.target ??
              trade.tp ??
              trade.take_profit;

            const stop =
              trade.sl ??
              trade.stop_loss;

            return `
              <div class="trade-card">

                <div class="trade-head">
                  <strong>
                    ${escapeHtml(
                      symbol
                    )}
                  </strong>

                  <span
                    class="signal ${signalClass(
                      trade.signal
                    )}"
                  >
                    ${escapeHtml(
                      signal
                    )}
                  </span>
                </div>

                ${
                  type ===
                    "futures" &&
                  leverage
                    ? `
                      <div>
                        الرافعة:
                        ${escapeHtml(
                          leverage
                        )}x
                      </div>
                    `
                    : ""
                }

                <div>
                  الدخول:
                  ${formatNumber(
                    entry,
                    6
                  )}
                </div>

                <div>
                  الهدف:
                  ${formatNumber(
                    target,
                    6
                  )}
                </div>

                <div>
                  الوقف:
                  ${formatNumber(
                    stop,
                    6
                  )}
                </div>

              </div>
            `;
          }
        )
        .join("");
  }

  // ============================================================
  // NEWS
  // ============================================================

  async function loadNews() {
    const list =
      $("newsList");

    if (!list) {
      return;
    }

    list.innerHTML =
      `<div class="empty-state">
        جاري تحميل الأخبار...
      </div>`;

    try {
      const data =
        await api("/api/news");

      const rows =
        getArray(data, "news");

      if (!rows.length) {
        list.innerHTML =
          `<div class="empty-state">
            لا توجد أخبار حالياً
          </div>`;

        return;
      }

      list.innerHTML =
        rows
          .map(
            (item) => {
              const title =
                item.title ||
                item.name ||
                "خبر";

              const description =
                item.description ||
                item.summary ||
                "";

              const link =
                item.link ||
                item.url ||
                "#";

              return `
                <article class="news-card">

                  <h3>
                    ${escapeHtml(
                      title
                    )}
                  </h3>

                  ${
                    description
                      ? `
                        <p>
                          ${escapeHtml(
                            description
                          )}
                        </p>
                      `
                      : ""
                  }

                  ${
                    link !== "#"
                      ? `
                        <a
                          href="${escapeHtml(
                            link
                          )}"
                          target="_blank"
                          rel="noopener noreferrer"
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
      list.innerHTML =
        `<div class="empty-state">
          ${escapeHtml(
            error.message ||
              "تعذر تحميل الأخبار"
          )}
        </div>`;
    }
  }

  function bindNews() {
    const button =
      $("newsBtn");

    if (button) {
      button.addEventListener(
        "click",
        loadNews
      );
    }
  }

  // ============================================================
  // DOMINANCE
  // ============================================================

  async function loadDominance() {
    const usdtSignal =
      $("usdtDominanceSignal");

    const btcSignal =
      $("btcDominanceSignal");

    try {
      const data =
        await api(
          "/api/dominance/USDT.D"
        );

      const a =
        getAnalysisFromResponse(
          data
        );

      setText(
        "usdtDominance",
        a.value ??
          a.price ??
          a.dominance ??
          "—"
      );

      setText(
        "usdtDominanceSignal",
        signalText(
          a.signal
        )
      );

      setText(
        "usdtDominanceMeta",
        a.change ??
          a.change_24h ??
          ""
      );
    } catch {
      setText(
        "usdtDominance",
        "غير متاح"
      );

      if (usdtSignal) {
        usdtSignal.textContent =
          "غير متاح";
      }

      setText(
        "usdtDominanceMeta",
        "بيانات الهيمنة غير متوفرة"
      );
    }

    try {
      const data =
        await api(
          "/api/dominance/BTC.D"
        );

      const a =
        getAnalysisFromResponse(
          data
        );

      setText(
        "btcDominance",
        a.value ??
          a.price ??
          a.dominance ??
          "—"
      );

      setText(
        "btcDominanceSignal",
        signalText(
          a.signal
        )
      );

      setText(
        "btcDominanceMeta",
        a.change ??
          a.change_24h ??
          ""
      );
    } catch {
      setText(
        "btcDominance",
        "غير متاح"
      );

      if (btcSignal) {
        btcSignal.textContent =
          "غير متاح";
      }

      setText(
        "btcDominanceMeta",
        "بيانات الهيمنة غير متوفرة"
      );
    }
  }

  // ============================================================
  // SUBSCRIPTION
  // ============================================================

  async function loadSubscription() {
    if (!state.user) {
      return;
    }

    const plans =
      $("plans");

    const status =
      $("subscriptionStatus");

    try {
      const data =
        await api(
          "/api/subscription/plans"
        );

      const rows =
        getArray(
          data,
          "plans"
        );

      renderPlans(rows);
    } catch {
      if (plans) {
        plans.innerHTML =
          `<div class="empty-state">
            تعذر تحميل الباقات
          </div>`;
      }
    }

    try {
      const data =
        await api(
          "/api/subscription/my"
        );

      renderSubscriptionStatus(
        data
      );
    } catch {
      if (status) {
        status.textContent =
          "لا يوجد اشتراك فعال";
      }
    }

    loadPaymentHistory();
  }

  function renderPlans(rows) {
    const container =
      $("plans");

    if (!container) {
      return;
    }

    if (
      !Array.isArray(rows) ||
      !rows.length
    ) {
      container.innerHTML =
        `<div class="empty-state">
          لا توجد باقات حالياً
        </div>`;

      return;
    }

    container.innerHTML =
      rows
        .map(
          (plan, index) => {
            const id =
              plan.id ??
              plan.plan_id ??
              plan.name ??
              index;

            const name =
              plan.name_ar ??
              plan.name ??
              `الباقة ${index + 1}`;

            const days =
              plan.days ??
              plan.duration_days ??
              "";

            const price =
              plan.price ??
              plan.amount ??
              "";

            return `
              <button
                class="plan-card"
                type="button"
                data-plan="${escapeHtml(
                  id
                )}"
              >
                <strong>
                  ${escapeHtml(
                    name
                  )}
                </strong>

                ${
                  days
                    ? `<span>
                        ${escapeHtml(
                          days
                        )} يوم
                      </span>`
                    : ""
                }

                ${
                  price !== ""
                    ? `<span>
                        ${escapeHtml(
                          price
                        )} USDT
                      </span>`
                    : ""
                }
              </button>
            `;
          }
        )
        .join("");

    container
      .querySelectorAll(
        "[data-plan]"
      )
      .forEach((button) => {
        button.addEventListener(
          "click",
          () => {
            state.selectedPlan =
              button.dataset.plan;

            container
              .querySelectorAll(
                "[data-plan]"
              )
              .forEach(
                (btn) =>
                  btn.classList.toggle(
                    "active",
                    btn === button
                  )
              );

            const chosen =
              $("chosenPlan");

            if (chosen) {
              chosen.value =
                state.selectedPlan;
            }

            const paymentBox =
              $("paymentBox");

            if (paymentBox) {
              paymentBox.hidden =
                false;
            }
          }
        );
      });
  }

  function renderSubscriptionStatus(
    data
  ) {
    const status =
      $("subscriptionStatus");

    if (!status) {
      return;
    }

    const sub =
      data?.subscription ??
      data?.data?.subscription ??
      data?.subscription_data;

    if (!sub) {
      status.textContent =
        "لا يوجد اشتراك فعال";

      return;
    }

    const active =
      sub.active ??
      sub.is_active ??
      true;

    if (!active) {
      status.textContent =
        "الاشتراك غير فعال";

      return;
    }

    const expires =
      sub.expires_at ??
      sub.end_date ??
      sub.expiry;

    status.textContent =
      expires
        ? `الاشتراك فعال حتى ${expires}`
        : "الاشتراك فعال";
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

      const rows =
        getArray(
          data,
          "history"
        );

      if (!rows.length) {
        box.innerHTML =
          `<div class="empty-state">
            لا توجد طلبات دفع
          </div>`;

        return;
      }

      box.innerHTML =
        rows
          .map(
            (row) => `
              <div class="payment-row">
                <strong>
                  ${escapeHtml(
                    row.plan_name ||
                      row.plan ||
                      "اشتراك"
                  )}
                </strong>

                <span>
                  ${escapeHtml(
                    row.status ||
                      "قيد المراجعة"
                  )}
                </span>
              </div>
            `
          )
          .join("");
    } catch {
      box.innerHTML =
        `<div class="empty-state">
          لا توجد بيانات دفع
        </div>`;
    }
  }

  function bindSubscription() {
    const copyBtn =
      $("copyAddress");

    const address =
      $("payAddress");

    if (copyBtn) {
      copyBtn.addEventListener(
        "click",
        async () => {
          const value =
            address?.textContent?.trim();

          if (!value) {
            return;
          }

          try {
            await navigator.clipboard.writeText(
              value
            );
          } catch {
            const area =
              document.createElement(
                "textarea"
              );

            area.value = value;

            document.body.appendChild(
              area
            );

            area.select();

            document.execCommand(
              "copy"
            );

            area.remove();
          }

          copyBtn.textContent =
            "تم النسخ";

          setTimeout(() => {
            copyBtn.textContent =
              "نسخ";
          }, 1500);
        }
      );
    }

    const sendPayment =
      $("sendPayment");

    if (sendPayment) {
      sendPayment.addEventListener(
        "click",
        async () => {
          if (!state.user) {
            openAuth("login");
            return;
          }

          const plan =
            state.selectedPlan ||
            $("chosenPlan")?.value;

          const txid =
            $("txid")?.value?.trim();

          const msg =
            $("paymentMsg");

          if (!plan) {
            showMessage(
              msg,
              "اختر الباقة أولاً",
              "error"
            );

            return;
          }

          if (!txid) {
            showMessage(
              msg,
              "أدخل TXID العملية",
              "error"
            );

            return;
          }

          sendPayment.disabled =
            true;

          showMessage(
            msg,
            "جاري إرسال الطلب..."
          );

          try {
            await api(
              "/api/subscription/request",
              {
                method: "POST",

                body: {
                  plan,
                  plan_id: plan,
                  txid
                }
              }
            );

            showMessage(
              msg,
              "تم إرسال طلب الاشتراك بنجاح",
              "success"
            );

            if ($("txid")) {
              $("txid").value = "";
            }

            await loadSubscription();
          } catch (error) {
            showMessage(
              msg,
              error.message ||
                "تعذر إرسال الطلب",
              "error"
            );
          } finally {
            sendPayment.disabled =
              false;
          }
        }
      );
    }
  }

  // ============================================================
  // THEME
  // ============================================================

  function bindTheme() {
    const themeBtn =
      $("themeBtn");

    if (!themeBtn) {
      return;
    }

    const saved =
      localStorage.getItem(
        "theme"
      );

    if (saved) {
      document.documentElement.dataset.theme =
        saved;
    }

    themeBtn.addEventListener(
      "click",
      () => {
        const current =
          document.documentElement
            .dataset.theme;

        const next =
          current === "light"
            ? "dark"
            : "light";

        document.documentElement.dataset.theme =
          next;

        localStorage.setItem(
          "theme",
          next
        );
      }
    );
  }

  // ============================================================
  // REFRESH BUTTONS
  // ============================================================

  function bindRefreshButtons() {
    const spotRefresh =
      $("spotRefresh");

    const futuresRefresh =
      $("futuresRefresh");

    if (spotRefresh) {
      spotRefresh.addEventListener(
        "click",
        loadSpot
      );
    }

    if (futuresRefresh) {
      futuresRefresh.addEventListener(
        "click",
        loadFutures
      );
    }
  }

  // ============================================================
  // BOOT
  // ============================================================

  async function boot() {
    // مهم:
    // نربط الواجهة أولاً حتى ما يصير أي تحويل
    // إلى /login أو /register.

    bindNavigation();
    bindSidebar();
    bindAuth();
    bindDashboardIntervals();
    bindScanner();
    bindNews();
    bindSubscription();
    bindTheme();
    bindRefreshButtons();

    // إظهار الرئيسية فقط عند البداية
    showSection("dashboard");

    // تحميل المستخدم بشكل مستقل
    try {
      await loadUser();
    } catch {
      state.user = null;
      state.admin = false;
      updateUserUI();
    }

    // تحميل البيانات بشكل مستقل
    loadAnalysis().catch(() => {});
    scan().catch(() => {});
    loadNews().catch(() => {});
    loadDominance().catch(() => {});
  }

  // ============================================================
  // START
  // ============================================================

  if (
    document.readyState ===
    "loading"
  ) {
    document.addEventListener(
      "DOMContentLoaded",
      boot
    );
  } else {
    boot();
  }

})();
