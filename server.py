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
      throw new Error(
        data?.message ||
        data?.error ||
        `خطأ HTTP ${response.status}`
      );
    }

    return data;
  }

  // ============================================================
  // أدوات
  // ============================================================

  function setText(id, value) {
    const el = $(id);
    if (el) {
      el.textContent =
        value === null ||
        value === undefined ||
        value === ""
          ? "—"
          : String(value);
    }
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

  // ============================================================
  // الأقسام والقائمة
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
    document
      .querySelectorAll(".section")
      .forEach((section) => {
        section.classList.toggle(
          "active",
          section.id === id
        );
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
      sectionTitles[id] || "الرئيسية"
    );

    const sidebar = $("sidebar");

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
      loadSubscription();
    }
  }

  function bindNavigation() {
    document
      .querySelectorAll(".nav-item")
      .forEach((button) => {
        button.addEventListener(
          "click",
          function (e) {
            e.preventDefault();

            const section =
              this.dataset.section;

            if (section) {
              showSection(section);
            }
          }
        );
      });
  }

  // ============================================================
  // زر القائمة للجوال
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
      function (e) {
        e.preventDefault();
        e.stopPropagation();

        sidebar.classList.toggle(
          "open"
        );
      }
    );
  }

  // ============================================================
  // تسجيل الدخول
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
      $("loginPassword")?.value || "";

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

      if (data.user) {
        state.user =
          data.user;
      }

      updateUserUI();
      closeAuth();

      setText(
        "systemStatus",
        "متصل"
      );

    } catch (error) {
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

      if (data.user) {
        state.user =
          data.user;

        updateUserUI();
        closeAuth();

        setText(
          "systemStatus",
          "تم إنشاء الحساب"
        );
      }

    } catch (error) {
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
    e.preventDefault();

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
  // المستخدم الحالي
  // ============================================================

  async function loadUser() {
    try {
      const data =
        await api(
          "/api/auth/me"
        );

      state.user =
        data.user || null;
    } catch {
      state.user = null;
    }

    try {
      const data =
        await api(
          "/api/admin/me"
        );

      state.admin =
        data.admin === true;
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
        server.py يرجع:

        {
          ok: true,
          analysis: {...}
        }

        لذلك نأخذ data.analysis
      */

      const a =
        data.analysis || {};

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

      const reasons =
        $("reasons");

      if (reasons) {
        reasons.innerHTML =
          `<li>${escapeHtml(
            error.message ||
              "تعذر جلب بيانات التحليل"
          )}</li>`;
      }
    } finally {
      state.loadingAnalysis =
        false;
    }
  }

  function renderAnalysis(a) {
    setText(
      "dashSymbol",
      a.symbol ||
        state.symbol
    );

    setText(
      "dashPrice",
      formatNumber(
        a.price
      )
    );

    setText(
      "dashChange",
      "—"
    );

    setText(
      "dashSignal",
      a.signal ||
        "حيادي"
    );

    setText(
      "bigSignal",
      a.signal ||
        "حيادي"
    );

    setText(
      "scoreText",
      a.score === undefined
        ? "—"
        : `${Number(a.score).toFixed(0)}%`
    );

    const bar =
      $("scoreBar");

    if (bar) {
      const score =
        Math.max(
          0,
          Math.min(
            100,
            Number(a.score || 0)
          )
        );

      bar.style.width =
        `${score}%`;
    }

    setText(
      "entry",
      formatNumber(
        a.entry
      )
    );

    setText(
      "tp1",
      formatNumber(
        a.tp1
      )
    );

    setText(
      "tp2",
      formatNumber(
        a.tp2
      )
    );

    setText(
      "tp3",
      formatNumber(
        a.tp3
      )
    );

    setText(
      "sl",
      formatNumber(
        a.sl
      )
    );

    setText(
      "rsi",
      a.rsi === undefined
        ? "—"
        : Number(a.rsi).toFixed(2)
    );

    setText(
      "ema20",
      formatNumber(
        a.ema20
      )
    );

    setText(
      "ema50",
      formatNumber(
        a.ema50
      )
    );

    setText(
      "ema200",
      formatNumber(
        a.ema200
      )
    );

    const reasons =
      $("reasons");

    if (reasons) {
      reasons.innerHTML =
        Array.isArray(a.reasons)
          ? a.reasons
              .map(
                (r) =>
                  `<li>${escapeHtml(
                    r
                  )}</li>`
              )
              .join("")
          : "";
    }

    if (
      Array.isArray(
        a.candles
      )
    ) {
      renderChart(
        a.candles
      );
    }
  }

  // ============================================================
  // الرسم
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
          !candle ||
          typeof candle !==
            "object"
        ) {
          return;
        }

        const timestamp =
          Number(
            candle.t
          );

        const close =
          Number(
            candle.c
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
                  minute:
                    "2-digit"
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
        canvas.getContext(
          "2d"
        ),
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
            maintainAspectRatio:
              false,

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
        Array.isArray(
          data.results
        )
          ? data.results
          : [];

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
          "symbol"
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
                  item.change
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
                  item.volume,
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
      server.py الحالي لا يحتوي:
      /api/trades/alpha
      /api/trades/traditional
      /api/trades/futures

      لذلك لا نرسل طلبات غير موجودة
      ولا نخلي الصفحة تعلق.
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

      try {
        await scan();
      } catch {}
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
        Array.isArray(
          data.news
        )
          ? data.news
          : [];

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
      مهم:
      server.py المرسل لا يحتوي API لـ USDT.D أو BTC.D.

      لذلك لا نحاول طلب endpoint غير موجود
      ولا نخلي الصفحة تعلق.
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

      renderPlans(
        data.plans || {}
      );

      const address =
        data.address;

      if ($("payAddress")) {
        $("payAddress").value =
          address || "";
      }

    } catch (error) {
      console.warn(
        "subscription plans:",
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
        "subscription my:",
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
      Object.entries(
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
                  plan.name
                )}
              </h3>

              <strong>
                ${formatNumber(
                  plan.amount,
                  2
                )} USDT
              </strong>

              <small>
                ${escapeHtml(
                  String(
                    plan.days
                  )
                )} يوم
              </small>

              <button
                class="btn primary plan-select"
                data-plan="${escapeHtml(
                  id
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
                button.dataset
                  .plan
              );
            }
          );
        }
      );
  }

  function selectPlan(
    planId
  ) {
    const payment =
      $("paymentBox");

    if (payment) {
      payment.hidden = false;
    }

    const plans =
      $("plans");

    const button =
      plans?.querySelector(
        `[data-plan="${CSS.escape(
          planId
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

    payment?.setAttribute(
      "data-plan",
      planId
    );
  }

  function renderSubscription(
    data
  ) {
    if (!data) return;

    let text =
      data.active
        ? `اشتراكك فعال — ${data.plan || ""}`
        : "لا يوجد اشتراك فعال";

    if (
      data.expires
    ) {
      text +=
        ` — ينتهي ${data.expires}`;
    }

    setText(
      "subscriptionStatus",
      text
    );
  }

  function bindSubscription() {
    $("copyAddress")?.addEventListener(
      "click",
      async (e) => {
        e.preventDefault();

        const input =
          $("payAddress");

        if (!input?.value) {
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
          input.select();

          document.execCommand(
            "copy"
          );

          setText(
            "paymentMsg",
            "تم نسخ العنوان"
          );
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
          paymentBox?.dataset
            .plan;

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
          button.disabled =
            true;
        }

        try {
          const data =
            await api(
              "/api/subscription/request",
              {
                method: "POST",
                body: {
                  plan,
                  txid
                }
              }
            );

          setText(
            "paymentMsg",
            data.message ||
              "تم إرسال الطلب بنجاح"
          );

        } catch (error) {
          setText(
            "paymentMsg",
            error.message ||
              "تعذر إرسال الطلب"
          );
        } finally {
          if (button) {
            button.disabled =
              false;
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
  // التشغيل
  // ============================================================

  async function boot() {
    /*
      نربط الأزرار أول شيء.
      حتى لو Binance أو الأخبار أو قاعدة البيانات
      فيها مشكلة، القائمة تظل تعمل.
    */

    try {
      bindNavigation();
      bindMenu();
      bindAuth();
      bindDashboardIntervals();
      bindScanner();
      bindTradeButtons();
      bindNews();
      bindSubscription();
      bindTheme();

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

    // كل خدمة مستقلة
    try {
      await loadUser();
    } catch (error) {
      console.warn(
        "User error:",
        error
      );
    }

    loadAnalysis(
      "BTCUSDT",
      "15m"
    ).catch(
      (e) =>
        console.warn(
          "analysis:",
          e
        )
    );

    scan().catch(
      (e) =>
        console.warn(
          "scan:",
          e
        )
    );

    loadNews().catch(
      (e) =>
        console.warn(
          "news:",
          e
        )
    );

    loadDominance().catch(
      (e) =>
        console.warn(
          "dominance:",
          e
        )
    );
  }

  // ============================================================
  // ابدأ بعد تحميل HTML
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
