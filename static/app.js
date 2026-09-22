(() => {
  "use strict";

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

    if (
      config.body &&
      typeof config.body !== "string"
    ) {
      config.headers["Content-Type"] =
        "application/json";

      config.body =
        JSON.stringify(config.body);
    }

    const response =
      await fetch(url, config);

    let data = null;

    try {
      data = await response.json();
    } catch {
      try {
        data = await response.text();
      } catch {
        data = null;
      }
    }

    if (!response.ok) {
      let message = `خطأ HTTP ${response.status}`;

      if (data && typeof data === "object") {
        message =
          data.message ||
          data.error ||
          message;
      } else if (typeof data === "string" && data.trim()) {
        message = data;
      }

      throw new Error(message);
    }

    return data;
  }

  // ============================================================
  // أدوات عامة
  // ============================================================

  function setText(id, value) {
    const el = $(id);

    if (!el) return;

    el.textContent =
      value === null ||
      value === undefined ||
      value === ""
        ? "—"
        : String(value);
  }

  function num(value) {
    const n = Number(value);

    return Number.isFinite(n)
      ? n
      : null;
  }

  function formatNumber(value, digits = 4) {
    const n = num(value);

    if (n === null) return "—";

    return n.toLocaleString(
      "en-US",
      {
        maximumFractionDigits: digits
      }
    );
  }

  function formatPercent(value) {
    const n = num(value);

    if (n === null) return "—";

    return (
      (n > 0 ? "+" : "") +
      n.toFixed(2) +
      "%"
    );
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function getDataObject(data) {
    if (!data || typeof data !== "object") {
      return {};
    }

    return (
      data.analysis ||
      data.result ||
      data.data ||
      data.payload ||
      data
    );
  }

  function getUserFromResponse(data) {
    if (!data || typeof data !== "object") {
      return null;
    }

    return (
      data.user ||
      data.account ||
      data.data?.user ||
      data.data?.account ||
      null
    );
  }

  function getArray(data, key) {
    if (Array.isArray(data)) {
      return data;
    }

    if (!data || typeof data !== "object") {
      return [];
    }

    if (Array.isArray(data[key])) {
      return data[key];
    }

    if (Array.isArray(data.data?.[key])) {
      return data.data[key];
    }

    if (Array.isArray(data.result?.[key])) {
      return data.result[key];
    }

    if (Array.isArray(data.results)) {
      return data.results;
    }

    if (Array.isArray(data.data)) {
      return data.data;
    }

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

  function showSection(id) {
    const target =
      document.getElementById(id);

    if (!target) {
      id = "dashboard";
    }

    document
      .querySelectorAll(".section")
      .forEach((section) => {
        const active =
          section.id === id;

        section.classList.toggle(
          "active",
          active
        );

        section.hidden = !active;
      });

    document
      .querySelectorAll(".nav-item")
      .forEach((button) => {
        button.classList.toggle(
          "active",
          button.dataset.section === id
        );
      });

    setText(
      "pageTitle",
      sectionTitles[id] ||
        "الرئيسية"
    );

    const sidebar =
      $("sidebar");

    if (sidebar) {
      sidebar.classList.remove("open");
    }

    if (id === "alpha") {
      loadTradeSection(
        "alpha",
        "alphaList"
      );
    }

    if (id === "traditional") {
      loadTradeSection(
        "traditional",
        "traditionalList"
      );
    }

    if (id === "spot") {
      loadSpot();
    }

    if (id === "futures") {
      loadTradeSection(
        "futures",
        "futuresList"
      );
    }

    if (id === "news") {
      loadNews();
    }

    if (id === "subscription") {
      if (!state.user) {
        showSection("dashboard");
        openAuth("login");
        return;
      }

      loadSubscription();
    }
  }

  function bindNavigation() {
    document
      .querySelectorAll(".nav-item")
      .forEach((button) => {
        button.addEventListener(
          "click",
          (e) => {
            e.preventDefault();
            e.stopPropagation();

            const section =
              button.dataset.section;

            if (!section) return;

            if (
              section ===
              "subscription"
            ) {
              if (!state.user) {
                openAuth("login");
                return;
              }
            }

            showSection(section);
          }
        );
      });
  }

  // ============================================================
  // القائمة الجانبية
  // ============================================================

  function bindMenu() {
    const menu =
      $("menuBtn");

    const sidebar =
      $("sidebar");

    if (!menu || !sidebar) {
      return;
    }

    menu.addEventListener(
      "click",
      (e) => {
        e.preventDefault();
        e.stopPropagation();

        sidebar.classList.toggle(
          "open"
        );
      }
    );

    document.addEventListener(
      "click",
      (e) => {
        if (
          window.innerWidth > 900
        ) {
          return;
        }

        if (
          sidebar.classList.contains(
            "open"
          ) &&
          !sidebar.contains(e.target) &&
          e.target !== menu
        ) {
          sidebar.classList.remove(
            "open"
          );
        }
      }
    );
  }

  // ============================================================
  // تسجيل الدخول والتسجيل
  // ============================================================

  function openAuth(type = "login") {
    const modal =
      $("authModal");

    if (!modal) return;

    modal.style.display = "flex";
    modal.classList.add("show");

    switchAuth(type);
  }

  function closeAuth() {
    const modal =
      $("authModal");

    if (!modal) return;

    modal.classList.remove("show");
    modal.style.display = "none";

    setText(
      "authMsg",
      ""
    );
  }

  function switchAuth(type) {
    const loginTab =
      $("loginTab");

    const registerTab =
      $("registerTab");

    const loginForm =
      $("loginForm");

    const registerForm =
      $("registerForm");

    if (loginTab) {
      loginTab.classList.toggle(
        "active",
        type === "login"
      );
    }

    if (registerTab) {
      registerTab.classList.toggle(
        "active",
        type === "register"
      );
    }

    if (loginForm) {
      loginForm.hidden =
        type !== "login";
    }

    if (registerForm) {
      registerForm.hidden =
        type !== "register";
    }

    setText(
      "authMsg",
      ""
    );
  }

  function bindAuth() {
    $("loginBtn")?.addEventListener(
      "click",
      (e) => {
        e.preventDefault();
        openAuth("login");
      }
    );

    $("registerBtn")?.addEventListener(
      "click",
      (e) => {
        e.preventDefault();
        openAuth("register");
      }
    );

    $("loginTab")?.addEventListener(
      "click",
      (e) => {
        e.preventDefault();
        switchAuth("login");
      }
    );

    $("registerTab")?.addEventListener(
      "click",
      (e) => {
        e.preventDefault();
        switchAuth("register");
      }
    );

    document
      .querySelectorAll(
        "[data-close]"
      )
      .forEach((button) => {
        button.addEventListener(
          "click",
          (e) => {
            e.preventDefault();
            closeAuth();
          }
        );
      });

    $("authModal")?.addEventListener(
      "click",
      (e) => {
        if (
          e.target ===
          $("authModal")
        ) {
          closeAuth();
        }
      }
    );

    $("loginForm")?.addEventListener(
      "submit",
      login
    );

    $("registerForm")?.addEventListener(
      "submit",
      register
    );

    $("logoutBtn")?.addEventListener(
      "click",
      logout
    );
  }

  async function login(e) {
    e.preventDefault();

    const email =
      $("loginEmail")?.value
        .trim();

    const password =
      $("loginPassword")?.value ||
      "";

    if (!email || !password) {
      setText(
        "authMsg",
        "أدخل البريد وكلمة المرور"
      );
      return;
    }

    const button =
      e.submitter;

    if (button) {
      button.disabled = true;
      button.textContent =
        "جاري الدخول...";
    }

    setText(
      "authMsg",
      "جاري تسجيل الدخول..."
    );

    try {
      const data =
        await api(
          "/api/auth/login",
          {
            method: "POST",
            body: {
              email,
              password
            }
          }
        );

      const user =
        getUserFromResponse(data);

      if (user) {
        state.user = user;
      } else {
        try {
          const me =
            await api(
              "/api/auth/me"
            );

          state.user =
            getUserFromResponse(me);
        } catch {
          state.user = null;
        }
      }

      if (!state.user) {
        throw new Error(
          data?.message ||
          "تم الدخول لكن تعذر قراءة بيانات الحساب"
        );
      }

      await loadUser();

      updateUserUI();
      closeAuth();

      setText(
        "systemStatus",
        "تم تسجيل الدخول"
      );

    } catch (error) {
      console.error(
        "Login error:",
        error
      );

      setText(
        "authMsg",
        error.message ||
          "بيانات الدخول غير صحيحة"
      );
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent =
          "دخول";
      }
    }
  }

  async function register(e) {
    e.preventDefault();

    const name =
      $("regName")?.value
        .trim();

    const email =
      $("regEmail")?.value
        .trim();

    const password =
      $("regPassword")?.value ||
      "";

    if (
      !name ||
      !email ||
      !password
    ) {
      setText(
        "authMsg",
        "أكمل جميع البيانات"
      );
      return;
    }

    if (password.length < 6) {
      setText(
        "authMsg",
        "كلمة المرور 6 أحرف على الأقل"
      );
      return;
    }

    const button =
      e.submitter;

    if (button) {
      button.disabled = true;
      button.textContent =
        "جاري إنشاء الحساب...";
    }

    setText(
      "authMsg",
      "جاري إنشاء الحساب..."
    );

    try {
      const data =
        await api(
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

      const user =
        getUserFromResponse(data);

      if (user) {
        state.user = user;

        await loadUser();

        updateUserUI();
        closeAuth();

        setText(
          "systemStatus",
          "تم إنشاء الحساب بنجاح"
        );

        return;
      }

      /*
        بعض السيرفرات تنشئ الحساب فقط
        ولا تسجل الدخول مباشرة.
      */

      setText(
        "authMsg",
        data?.message ||
          "تم إنشاء الحساب، يمكنك تسجيل الدخول الآن"
      );

      switchAuth("login");

      if ($("loginEmail")) {
        $("loginEmail").value =
          email;
      }

    } catch (error) {
      console.error(
        "Register error:",
        error
      );

      setText(
        "authMsg",
        error.message ||
          "تعذر إنشاء الحساب"
      );
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent =
          "إنشاء الحساب";
      }
    }
  }

  async function logout(e) {
    e?.preventDefault();

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
    state.selectedPlan = null;

    updateUserUI();

    showSection(
      "dashboard"
    );

    setText(
      "systemStatus",
      "تم تسجيل الخروج"
    );
  }

  // ============================================================
  // المستخدم الحالي
  // ============================================================

  async function loadUser() {
    try {
      const data =
        await api(
          "/api/auth/me"
        );

      state.user =
        getUserFromResponse(data);

    } catch {
      state.user = null;
    }

    try {
      const data =
        await api(
          "/api/admin/me"
        );

      state.admin =
        data?.admin === true ||
        data?.data?.admin === true;

    } catch {
      state.admin = false;
    }

    updateUserUI();
  }

  function updateUserUI() {
    const logged =
      !!state.user;

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

    const admin =
      $("adminLink");

    if (badge) {
      badge.textContent =
        state.user?.name ||
        state.user?.email ||
        "زائر";
    }

    if (login) {
      login.hidden =
        logged;
    }

    if (register) {
      register.hidden =
        logged;
    }

    if (logout) {
      logout.hidden =
        !logged;
    }

    if (subscription) {
      subscription.hidden =
        !logged;
    }

    if (admin) {
      admin.hidden =
        !state.admin;
    }
  }

  // ============================================================
  // التحليل الفني
  // ============================================================

  async function loadAnalysis(
    symbol = state.symbol,
    interval = state.interval
  ) {
    if (state.loadingAnalysis) {
      return;
    }

    state.loadingAnalysis = true;

    state.symbol = symbol;
    state.interval = interval;

    setText(
      "systemStatus",
      "جاري تحميل التحليل..."
    );

    setText(
      "analysisMeta",
      interval
    );

    setText(
      "dashSymbol",
      symbol
    );

    try {
      const data =
        await api(
          `/api/binance/analysis?symbol=${encodeURIComponent(
            symbol
          )}&interval=${encodeURIComponent(
            interval
          )}`
        );

      /*
        السيرفر يرجع:
        {
          ok: true,
          analysis: {...}
        }
      */

      const a =
        getDataObject(data);

      renderAnalysis(a);

      setText(
        "systemStatus",
        "متصل"
      );

    } catch (error) {
      console.error(
        "Analysis error:",
        error
      );

      setText(
        "systemStatus",
        "تعذر تحميل التحليل"
      );

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
        "غير متاح"
      );

      setText(
        "bigSignal",
        "غير متاح"
      );

      setText(
        "scoreText",
        "—"
      );

      setText(
        "entry",
        "—"
      );

      setText(
        "tp1",
        "—"
      );

      setText(
        "tp2",
        "—"
      );

      setText(
        "tp3",
        "—"
      );

      setText(
        "sl",
        "—"
      );

      const reasons =
        $("reasons");

      if (reasons) {
        reasons.innerHTML = `
          <li>
            ${escapeHtml(
              error.message ||
                "تعذر جلب بيانات التحليل"
            )}
          </li>
        `;
      }
    } finally {
      state.loadingAnalysis =
        false;
    }
  }

  function renderAnalysis(a) {
    if (!a || typeof a !== "object") {
      return;
    }

    const indicators =
      a.indicators ||
      a.indicator ||
      {};

    const levels =
      a.levels ||
      {};

    const price =
      a.price ??
      a.current_price ??
      a.currentPrice;

    const change =
      a.change_24h ??
      a.change24h ??
      a.change ??
      a.price_change_percent;

    const signal =
      a.signal ||
      a.direction ||
      "حيادي";

    const score =
      num(
        a.score ??
        a.strength ??
        a.signal_score
      );

    setText(
      "dashSymbol",
      a.symbol ||
        state.symbol
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
      score === null
        ? "—"
        : `${score.toFixed(0)}%`
    );

    const bar =
      $("scoreBar");

    if (bar) {
      const safeScore =
        Math.max(
          0,
          Math.min(
            100,
            score || 0
          )
        );

      bar.style.width =
        `${safeScore}%`;
    }

    setText(
      "entry",
      formatNumber(
        a.entry ??
        levels.entry
      )
    );

    setText(
      "tp1",
      formatNumber(
        a.tp1 ??
        levels.tp1
      )
    );

    setText(
      "tp2",
      formatNumber(
        a.tp2 ??
        levels.tp2
      )
    );

    setText(
      "tp3",
      formatNumber(
        a.tp3 ??
        levels.tp3
      )
    );

    setText(
      "sl",
      formatNumber(
        a.sl ??
        levels.sl ??
        a.stop_loss
      )
    );

    setText(
      "rsi",
      indicators.rsi ??
      a.rsi === undefined
        ? "—"
        : Number(
            indicators.rsi ??
            a.rsi
          ).toFixed(2)
    );

    const ema20 =
      indicators.ema20 ??
      indicators.EMA20 ??
      a.ema20;

    const ema50 =
      indicators.ema50 ??
      indicators.EMA50 ??
      a.ema50;

    const ema200 =
      indicators.ema200 ??
      indicators.EMA200 ??
      a.ema200;

    setText(
      "ema20",
      formatNumber(ema20)
    );

    setText(
      "ema50",
      formatNumber(ema50)
    );

    setText(
      "ema200",
      formatNumber(ema200)
    );

    const reasons =
      $("reasons");

    if (reasons) {
      const list =
        Array.isArray(a.reasons)
          ? a.reasons
          : [];

      reasons.innerHTML =
        list.length
          ? list
              .map(
                (reason) =>
                  `<li>${escapeHtml(
                    reason
                  )}</li>`
              )
              .join("")
          : "";
    }

    const candles =
      a.candles ||
      a.chart ||
      a.klines;

    if (
      Array.isArray(candles)
    ) {
      renderChart(
        candles
      );
    }
  }

  // ============================================================
  // الرسم البياني
  // ============================================================

  function renderChart(candles) {
    const canvas =
      $("priceChart");

    if (
      !canvas ||
      typeof Chart ===
        "undefined"
    ) {
      return;
    }

    const labels = [];
    const values = [];

    candles.forEach(
      (candle) => {
        if (
          Array.isArray(candle)
        ) {
          const timestamp =
            Number(candle[0]);

          const close =
            Number(candle[4]);

          if (
            !Number.isFinite(
              close
            )
          ) {
            return;
          }

          labels.push(
            Number.isFinite(
              timestamp
            )
              ? new Date(
                  timestamp
                ).toLocaleTimeString(
                  "ar-SA",
                  {
                    hour: "2-digit",
                    minute: "2-digit"
                  }
                )
              : ""
          );

          values.push(close);

          return;
        }

        if (
          !candle ||
          typeof candle !==
            "object"
        ) {
          return;
        }

        const timestamp =
          Number(
            candle.t ??
            candle.time ??
            candle.openTime
          );

        const close =
          Number(
            candle.c ??
            candle.close
          );

        if (
          !Number.isFinite(
            close
          )
        ) {
          return;
        }

        labels.push(
          Number.isFinite(
            timestamp
          )
            ? new Date(
                timestamp
              ).toLocaleTimeString(
                "ar-SA",
                {
                  hour: "2-digit",
                  minute: "2-digit"
                }
              )
            : ""
        );

        values.push(close);
      }
    );

    if (!values.length) {
      return;
    }

    if (state.chart) {
      try {
        state.chart.destroy();
      } catch {}
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
        }
      );
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
        button.addEventListener(
          "click",
          (e) => {
            e.preventDefault();

            document
              .querySelectorAll(
                "#dashIntervals button"
              )
              .forEach(
                (b) =>
                  b.classList.remove(
                    "active"
                  )
              );

            button.classList.add(
              "active"
            );

            loadAnalysis(
              state.symbol,
              button.dataset
                .interval ||
                "15m"
            );
          }
        );
      });
  }

  // ============================================================
  // الماسح
  // ============================================================

  async function scan() {
    if (state.loadingScan) {
      return;
    }

    state.loadingScan = true;

    const button =
      $("scanBtn");

    if (button) {
      button.disabled = true;
      button.textContent =
        "جاري الفحص...";
    }

    setText(
      "scannerStatus",
      "جاري فحص العملات..."
    );

    try {
      const data =
        await api(
          `/api/binance/scan?interval=${encodeURIComponent(
            state.interval
          )}&limit=40`
        );

      state.results =
        getArray(
          data,
          "results"
        );

      renderScanner();

      setText(
        "scannerStatus",
        `تم العثور على ${state.results.length} نتيجة`
      );

    } catch (error) {
      console.error(
        "Scanner error:",
        error
      );

      setText(
        "scannerStatus",
        error.message ||
          "تعذر تشغيل الماسح"
      );
    } finally {
      state.loadingScan =
        false;

      if (button) {
        button.disabled =
          false;

        button.textContent =
          "🔄 تحديث";
      }
    }
  }

  function renderScanner() {
    const body =
      $("scannerBody");

    if (!body) return;

    let rows =
      [...state.results];

    const search =
      $("scannerSearch")
        ?.value
        .trim()
        .toUpperCase() ||
      "";

    if (search) {
      rows =
        rows.filter(
          (item) =>
            String(
              item.symbol ||
                ""
            )
              .toUpperCase()
              .includes(search)
        );
    }

    if (
      state.signals.length
    ) {
      rows =
        rows.filter(
          (item) =>
            state.signals.includes(
              item.signal
            )
        );
    }

    rows.sort(
      (a, b) => {
        let av =
          a[
            state.sortField
          ];

        let bv =
          b[
            state.sortField
          ];

        if (
          state.sortField ===
          "symbol" ||
          state.sortField ===
          "signal"
        ) {
          av = String(
            av || ""
          ).toUpperCase();

          bv = String(
            bv || ""
          ).toUpperCase();
        } else {
          av =
            Number(av) || 0;

          bv =
            Number(bv) || 0;
        }

        if (av < bv) {
          return state.sortDesc
            ? 1
            : -1;
        }

        if (av > bv) {
          return state.sortDesc
            ? -1
            : 1;
        }

        return 0;
      }
    );

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

    body.innerHTML =
      rows
        .map(
          (item) => `
            <tr
              data-symbol="${escapeHtml(
                item.symbol
              )}"
            >
              <td>
                <b>
                  ${escapeHtml(
                    item.symbol
                  )}
                </b>
              </td>

              <td>
                ${formatNumber(
                  item.price
                )}
              </td>

              <td>
                ${formatPercent(
                  item.change ??
                  item.change_24h
                )}
              </td>

              <td>
                ${escapeHtml(
                  item.signal ||
                    "حيادي"
                )}
              </td>

              <td>
                ${formatNumber(
                  item.score,
                  0
                )}
              </td>

              <td>
                ${formatNumber(
                  item.volume ??
                  item.quoteVolume,
                  0
                )}
              </td>

              <td>
                ${escapeHtml(
                  item.interval ||
                    state.interval
                )}
              </td>
            </tr>
          `
        )
        .join("");

    body
      .querySelectorAll(
        "tr[data-symbol]"
      )
      .forEach(
        (row) => {
          row.addEventListener(
            "click",
            () => {
              const symbol =
                row.dataset
                  .symbol;

              if (!symbol) {
                return;
              }

              showSection(
                "dashboard"
              );

              loadAnalysis(
                symbol,
                state.interval
              );
            }
          );
        }
      );
  }

  function bindScanner() {
    $("scanBtn")?.addEventListener(
      "click",
      (e) => {
        e.preventDefault();
        scan();
      }
    );

    $("scannerSearch")?.addEventListener(
      "input",
      renderScanner
    );

    $("sortField")?.addEventListener(
      "change",
      (e) => {
        state.sortField =
          e.target.value ||
          "change";

        renderScanner();
      }
    );

    $("sortDir")?.addEventListener(
      "click",
      (e) => {
        e.preventDefault();

        state.sortDesc =
          !state.sortDesc;

        e.currentTarget.textContent =
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
      .forEach(
        (button) => {
          button.addEventListener(
            "click",
            (e) => {
              e.preventDefault();

              document
                .querySelectorAll(
                  "#intervalChips button"
                )
                .forEach(
                  (b) =>
                    b.classList.remove(
                      "active"
                    )
                );

              button.classList.add(
                "active"
              );

              state.interval =
                button.dataset
                  .interval ||
                "15m";

              scan();
            }
          );
        }
      );

    document
      .querySelectorAll(
        ".signal-chips button"
      )
      .forEach(
        (button) => {
          button.addEventListener(
            "click",
            (e) => {
              e.preventDefault();

              const signal =
                button.dataset
                  .signal;

              if (!signal) {
                return;
              }

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
                    (x) =>
                      x !==
                      signal
                  );
              } else {
                state.signals.push(
                  signal
                );
              }

              renderScanner();
            }
          );
        }
      );
  }

  // ============================================================
  // صفقات الأقسام
  // ============================================================

  async function loadTradeSection(
    type,
    containerId
  ) {
    const container =
      $(containerId);

    if (!container) {
      return;
    }

    /*
      الـ server الحالي لا يحتوي
      APIs مستقلة لهذه الأقسام.
      لذلك لا نرسل طلبات 404.
    */

    container.innerHTML = `
      <div class="empty-card">
        لا توجد صفقات متاحة حالياً
      </div>
    `;
  }

  async function loadSpot() {
    const container =
      $("spotList");

    if (!container) {
      return;
    }

    if (!state.results.length) {
      container.innerHTML = `
        <div class="empty-card">
          جاري تحميل صفقات السبوت...
        </div>
      `;

      await scan();
    }

    if (!state.results.length) {
      container.innerHTML = `
        <div class="empty-card">
          لا توجد صفقات سبوت متاحة حالياً
        </div>
      `;

      return;
    }

    container.innerHTML =
      state.results
        .map(
          (item) => `
            <div class="trade-card">

              <div class="trade-card-head">
                <div>
                  <b>
                    ${escapeHtml(
                      item.symbol
                    )}
                  </b>

                  <small>
                    ${escapeHtml(
                      item.interval ||
                        state.interval
                    )}
                  </small>
                </div>

                <strong>
                  ${escapeHtml(
                    item.signal ||
                      "حيادي"
                  )}
                </strong>
              </div>

              <div class="trade-levels">

                <div>
                  <span>الدخول</span>
                  <b>
                    ${formatNumber(
                      item.entry
                    )}
                  </b>
                </div>

                <div>
                  <span>TP1</span>
                  <b>
                    ${formatNumber(
                      item.tp1
                    )}
                  </b>
                </div>

                <div>
                  <span>TP2</span>
                  <b>
                    ${formatNumber(
                      item.tp2
                    )}
                  </b>
                </div>

                <div>
                  <span>وقف</span>
                  <b>
                    ${formatNumber(
                      item.sl
                    )}
                  </b>
                </div>

              </div>

            </div>
          `
        )
        .join("");
  }

  function bindTradeButtons() {
    $("spotRefresh")?.addEventListener(
      "click",
      (e) => {
        e.preventDefault();
        loadSpot();
      }
    );

    $("futuresRefresh")?.addEventListener(
      "click",
      (e) => {
        e.preventDefault();

        loadTradeSection(
          "futures",
          "futuresList"
        );
      }
    );
  }

  // ============================================================
  // الأخبار
  // ============================================================

  async function loadNews() {
    const container =
      $("newsList");

    if (!container) {
      return;
    }

    container.innerHTML = `
      <div class="empty-card">
        جاري تحميل الأخبار...
      </div>
    `;

    try {
      const data =
        await api(
          "/api/news"
        );

      const items =
        getArray(
          data,
          "news"
        );

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
          .map(
            (item) => `
              <article class="news-card">

                <h3>
                  ${escapeHtml(
                    item.title
                  )}
                </h3>

                <p>
                  ${escapeHtml(
                    item.description ||
                      item.summary ||
                      ""
                  )}
                </p>

                ${
                  item.link
                    ? `
                      <a
                        href="${escapeHtml(
                          item.link
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
            `
          )
          .join("");

    } catch (error) {
      console.error(
        "News error:",
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
      (e) => {
        e.preventDefault();
        loadNews();
      }
    );
  }

  // ============================================================
  // USDT.D / BTC.D
  // ============================================================

  function setDominanceUnavailable(
    symbol,
    valueId,
    signalId,
    metaId
  ) {
    setText(
      valueId,
      "—"
    );

    setText(
      signalId,
      "غير متاح"
    );

    setText(
      metaId,
      `${symbol} — البيانات غير متوفرة`
    );
  }

  async function loadDominance() {
    /*
      لا توجد endpoints في server.py الحالي
      لـ USDT.D و BTC.D.
    */

    setDominanceUnavailable(
      "USDT.D",
      "usdtDominance",
      "usdtDominanceSignal",
      "usdtDominanceMeta"
    );

    setDominanceUnavailable(
      "BTC.D",
      "btcDominance",
      "btcDominanceSignal",
      "btcDominanceMeta"
    );
  }

  // ============================================================
  // الاشتراك
  // ============================================================

  async function loadSubscription() {
    if (!state.user) {
      return;
    }

    try {
      const data =
        await api(
          "/api/subscription/plans"
        );

      const plans =
        data.plans ||
        data.data?.plans ||
        {};

      renderPlans(
        plans
      );

      const address =
        data.address ||
        data.payment_address ||
        data.trc20_address ||
        data.data?.address ||
        data.data?.payment_address ||
        data.data?.trc20_address ||
        "";

      if ($("payAddress")) {
        $("payAddress").value =
          address;
      }

      generateQRCode(
        address
      );

    } catch (error) {
      console.warn(
        "Subscription plans:",
        error
      );
    }

    try {
      const data =
        await api(
          "/api/subscription/my"
        );

      renderSubscription(
        data
      );

    } catch (error) {
      console.warn(
        "Subscription my:",
        error
      );
    }
  }

  function renderPlans(plans) {
    const container =
      $("plans");

    if (!container) {
      return;
    }

    const entries =
      Array.isArray(plans)
        ? plans.map(
            (plan, index) => [
              plan.id ??
                plan.plan_id ??
                index,
              plan
            ]
          )
        : Object.entries(
            plans || {}
          );

    if (!entries.length) {
      container.innerHTML = `
        <div class="empty-card">
          لا توجد باقات حالياً
        </div>
      `;

      return;
    }

    container.innerHTML =
      entries
        .map(
          ([id, plan]) => `
            <div class="plan-card">

              <h3>
                ${escapeHtml(
                  plan?.name ||
                    `باقة ${id}`
                )}
              </h3>

              <strong>
                ${formatNumber(
                  plan?.amount ??
                  plan?.price,
                  2
                )} USDT
              </strong>

              <small>
                ${escapeHtml(
                  String(
                    plan?.days ??
                    plan?.duration ??
                    ""
                  )
                )} يوم
              </small>

              <button
                type="button"
                class="btn primary plan-select"
                data-plan="${escapeHtml(
                  String(id)
                )}"
              >
                اختيار الباقة
              </button>

            </div>
          `
        )
        .join("");

    container
      .querySelectorAll(
        ".plan-select"
      )
      .forEach(
        (button) => {
          button.addEventListener(
            "click",
            () => {
              selectPlan(
                button.dataset.plan
              );
            }
          );
        }
      );
  }

  function selectPlan(planId) {
    state.selectedPlan =
      planId;

    const payment =
      $("paymentBox");

    if (payment) {
      payment.hidden = false;

      payment.dataset.plan =
        planId;
    }

    const plans =
      $("plans");

    const buttons =
      plans?.querySelectorAll(
        ".plan-select"
      );

    buttons?.forEach(
      (button) => {
        button.classList.toggle(
          "active",
          button.dataset.plan ===
            String(planId)
        );
      }
    );

    const button =
      plans?.querySelector(
        `.plan-select[data-plan="${CSS.escape(
          String(planId)
        )}"]`
      );

    const card =
      button?.closest(
        ".plan-card"
      );

    const title =
      card?.querySelector(
        "h3"
      )?.textContent ||
      planId;

    const amount =
      card?.querySelector(
        "strong"
      )?.textContent ||
      "";

    setText(
      "chosenPlan",
      `الباقة: ${title} — ${amount}`
    );

    setText(
      "paymentMsg",
      ""
    );

    payment?.scrollIntoView({
      behavior: "smooth",
      block: "nearest"
    });
  }

  function renderSubscription(data) {
    if (!data) return;

    const info =
      data.data ||
      data.subscription ||
      data;

    let text =
      info.active
        ? `اشتراكك فعال — ${
            info.plan ||
            info.plan_name ||
            ""
          }`
        : "لا يوجد اشتراك فعال";

    const expires =
      info.expires ||
      info.expires_at ||
      info.expiry;

    if (expires) {
      text +=
        ` — ينتهي ${expires}`;
    }

    setText(
      "subscriptionStatus",
      text
    );
  }

  function generateQRCode(address) {
    const box =
      $("qrBox");

    if (!box) return;

    box.innerHTML = "";

    if (
      !address ||
      typeof QRCode ===
        "undefined"
    ) {
      return;
    }

    try {
      const canvas =
        document.createElement(
          "canvas"
        );

      box.appendChild(
        canvas
      );

      QRCode.toCanvas(
        canvas,
        address,
        {
          width: 180,
          margin: 2
        }
      );
    } catch (error) {
      console.warn(
        "QR error:",
        error
      );
    }
  }

  function bindSubscription() {
    $("copyAddress")?.addEventListener(
      "click",
      async (e) => {
        e.preventDefault();

        const input =
          $("payAddress");

        if (!input?.value) {
          setText(
            "paymentMsg",
            "عنوان الدفع غير متوفر"
          );
          return;
        }

        try {
          await navigator.clipboard.writeText(
            input.value
          );

          setText(
            "paymentMsg",
            "تم نسخ العنوان"
          );
        } catch {
          try {
            input.select();

            document.execCommand(
              "copy"
            );

            setText(
              "paymentMsg",
              "تم نسخ العنوان"
            );
          } catch {
            setText(
              "paymentMsg",
              "تعذر نسخ العنوان"
            );
          }
        }
      }
    );

    $("sendPayment")?.addEventListener(
      "click",
      async (e) => {
        e.preventDefault();

        const paymentBox =
          $("paymentBox");

        const plan =
          state.selectedPlan ||
          paymentBox?.dataset.plan;

        const txid =
          $("txid")?.value
            .trim();

        if (!plan) {
          setText(
            "paymentMsg",
            "اختر الباقة أولاً"
          );
          return;
        }

        if (!txid) {
          setText(
            "paymentMsg",
            "أدخل TXID أولاً"
          );
          return;
        }

        const button =
          $("sendPayment");

        if (button) {
          button.disabled = true;
          button.textContent =
            "جاري الإرسال...";
        }

        try {
          /*
            نرسل plan_id و plan
            لدعم اختلاف تسمية السيرفر.
          */

          const data =
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

          setText(
            "paymentMsg",
            data?.message ||
              data?.data?.message ||
              "تم إرسال طلب الاشتراك بنجاح"
          );

          if ($("txid")) {
            $("txid").value = "";
          }

        } catch (error) {
          console.error(
            "Payment error:",
            error
          );

          setText(
            "paymentMsg",
            error.message ||
              "تعذر إرسال الطلب"
          );
        } finally {
          if (button) {
            button.disabled =
              false;

            button.textContent =
              "إرسال طلب الاشتراك";
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

    if (!button) {
      return;
    }

    const saved =
      localStorage.getItem(
        "theme"
      );

    if (saved === "dark") {
      document.body.classList.add(
        "dark"
      );

      button.textContent =
        "☀️ الوضع النهاري";
    }

    button.addEventListener(
      "click",
      (e) => {
        e.preventDefault();

        document.body.classList.toggle(
          "dark"
        );

        const dark =
          document.body.classList.contains(
            "dark"
          );

        localStorage.setItem(
          "theme",
          dark
            ? "dark"
            : "light"
        );

        button.textContent =
          dark
            ? "☀️ الوضع النهاري"
            : "🌙 الوضع الليلي";
      }
    );
  }

  // ============================================================
  // تشغيل الموقع
  // ============================================================

  async function boot() {
    try {
      /*
        ربط الواجهة أولاً حتى تظل
        القوائم والدخول تعمل حتى لو
        API فيه مشكلة.
      */

      bindNavigation();
      bindMenu();
      bindAuth();
      bindDashboardIntervals();
      bindScanner();
      bindTradeButtons();
      bindNews();
      bindSubscription();
      bindTheme();

      /*
        نضمن أن الرئيسية هي الوحيدة
        الظاهرة عند بداية الموقع.
      */

      showSection(
        "dashboard"
      );

      setText(
        "systemStatus",
        "جاري الاتصال..."
      );

    } catch (error) {
      console.error(
        "UI binding error:",
        error
      );
    }

    // ----------------------------------------------------------
    // المستخدم
    // ----------------------------------------------------------

    try {
      await loadUser();
    } catch (error) {
      console.warn(
        "User error:",
        error
      );
    }

    // ----------------------------------------------------------
    // الخدمات بشكل مستقل
    // ----------------------------------------------------------

    loadAnalysis(
      "BTCUSDT",
      "15m"
    ).catch(
      (error) =>
        console.warn(
          "Analysis:",
          error
        )
    );

    scan().catch(
      (error) =>
        console.warn(
          "Scan:",
          error
        )
    );

    loadNews().catch(
      (error) =>
        console.warn(
          "News:",
          error
        )
    );

    loadDominance().catch(
      (error) =>
        console.warn(
          "Dominance:",
          error
        )
    );
  }

  // ============================================================
  // بدء التطبيق
  // ============================================================

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

})();
