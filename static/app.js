/* =========================================================
   تحليل العملات الرقمية
   Compatible with current server.py
========================================================= */

let currentSymbol = "BTCUSDT";
let currentInterval = "15m";
let markets = [];
let favorites = JSON.parse(localStorage.getItem("favorites") || "[]");
let refreshTimer = null;
let chart = null;


/* =========================================================
   HELPERS
========================================================= */

const $ = (id) => document.getElementById(id);

function showStatus(message, type = "") {
    const box = $("status");
    if (!box) return;

    box.textContent = message;
    box.className = "status-box " + type;
}

function showError(message) {
    const box = $("errorBox");
    if (!box) return;

    box.textContent = message;
    box.style.display = "block";

    setTimeout(() => {
        box.style.display = "none";
    }, 5000);
}

async function api(url, options = {}) {
    const response = await fetch(url, {
        credentials: "same-origin",
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {})
        }
    });

    let data = {};

    try {
        data = await response.json();
    } catch (_) {}

    if (!response.ok || data.ok === false) {
        throw new Error(data.error || data.message || "حدث خطأ");
    }

    return data;
}

function formatNumber(value, decimals = 4) {
    if (value === null || value === undefined || value === "") {
        return "--";
    }

    const n = Number(value);

    if (!Number.isFinite(n)) {
        return "--";
    }

    if (Math.abs(n) >= 1000) {
        return n.toLocaleString("en-US", {
            maximumFractionDigits: 2
        });
    }

    return n.toLocaleString("en-US", {
        maximumFractionDigits: decimals
    });
}

function formatPrice(value) {
    const n = Number(value);

    if (!Number.isFinite(n)) return "--";

    if (n >= 1000) return n.toLocaleString("en-US", {maximumFractionDigits: 2});
    if (n >= 1) return n.toLocaleString("en-US", {maximumFractionDigits: 4});
    if (n >= 0.01) return n.toLocaleString("en-US", {maximumFractionDigits: 6});

    return n.toLocaleString("en-US", {maximumFractionDigits: 10});
}


/* =========================================================
   AUTH
========================================================= */

async function loadUser() {
    try {
        const data = await api("/api/auth/me");

        if (data.user) {
            setLoggedUser(data.user);
        } else {
            setLoggedOut();
        }
    } catch (_) {
        setLoggedOut();
    }
}

function setLoggedUser(user) {
    const usernameDisplay = $("usernameDisplay");
    const planDisplay = $("planDisplay");
    const loginBtn = $("loginBtn");
    const logoutBtn = $("logoutBtn");
    const adminLink = $("adminLink");

    if (usernameDisplay) {
        usernameDisplay.textContent = user.username || "";
    }

    if (planDisplay) {
        planDisplay.textContent =
            user.plan === "premium" ? "Premium 👑" : "مجاني";
    }

    if (loginBtn) loginBtn.style.display = "none";
    if (logoutBtn) logoutBtn.style.display = "inline-flex";

    if (adminLink) {
        adminLink.style.display = user.is_admin ? "flex" : "none";
    }
}

function setLoggedOut() {
    const usernameDisplay = $("usernameDisplay");
    const planDisplay = $("planDisplay");
    const loginBtn = $("loginBtn");
    const logoutBtn = $("logoutBtn");
    const adminLink = $("adminLink");

    if (usernameDisplay) usernameDisplay.textContent = "";
    if (planDisplay) planDisplay.textContent = "مجاني";

    if (loginBtn) loginBtn.style.display = "inline-flex";
    if (logoutBtn) logoutBtn.style.display = "none";
    if (adminLink) adminLink.style.display = "none";
}

async function login(username, password) {
    try {
        const data = await api("/api/auth/login", {
            method: "POST",
            body: JSON.stringify({
                username,
                password
            })
        });

        setLoggedUser(data.user);

        if ($("authModal")) {
            $("authModal").classList.remove("show");
        }

        showStatus("تم تسجيل الدخول بنجاح ✅", "success");

    } catch (error) {
        throw error;
    }
}

async function register(username, email, password) {
    return api("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({
            username,
            email,
            password
        })
    });
}

async function logout() {
    try {
        await api("/api/auth/logout", {
            method: "POST"
        });
    } catch (_) {}

    setLoggedOut();
    showStatus("تم تسجيل الخروج", "success");
}


/* =========================================================
   BINANCE MARKETS
========================================================= */

async function loadMarkets() {
    try {
        showStatus("جاري تحميل العملات...", "");

        const data = await api("/api/binance/markets");

        markets = data.markets || data.symbols || [];

        renderCoinList();

        const count = $("coinCount");

        if (count) {
            count.textContent = markets.length;
        }

        showStatus("Binance متصل 🟢", "success");

    } catch (error) {
        showError("تعذر تحميل العملات: " + error.message);
        showStatus("تعذر الاتصال بـ Binance", "error");
    }
}

function normalizeSymbol(item) {
    if (typeof item === "string") return item;

    return (
        item.symbol ||
        item.ticker ||
        item.code ||
        ""
    );
}

function renderCoinList(filter = "") {
    const list = $("coinList");

    if (!list) return;

    const search = filter.trim().toUpperCase();

    const filtered = markets
        .map(normalizeSymbol)
        .filter(symbol => symbol.endsWith("USDT"))
        .filter(symbol => !search || symbol.includes(search))
        .slice(0, 150);

    if (!filtered.length) {
        list.innerHTML = `
            <div class="empty-state">
                <div>🔎</div>
                <h3>لا توجد نتائج</h3>
                <p>جرّب البحث باسم عملة أخرى.</p>
            </div>
        `;
        return;
    }

    list.innerHTML = filtered.map(symbol => {
        const active = symbol === currentSymbol ? "active" : "";
        const fav = favorites.includes(symbol) ? "★" : "☆";

        return `
            <button
                type="button"
                class="coin-item ${active}"
                data-symbol="${symbol}"
            >
                <span class="coin-symbol-icon">₿</span>

                <span class="coin-item-name">
                    <strong>${symbol}</strong>
                    <small>Binance Spot</small>
                </span>

                <span class="coin-favorite">${fav}</span>
            </button>
        `;
    }).join("");

    list.querySelectorAll(".coin-item").forEach(button => {
        button.addEventListener("click", () => {
            currentSymbol = button.dataset.symbol;
            renderCoinList($("coinSearch")?.value || "");
            analyzeCurrent();
        });
    });
}


/* =========================================================
   PRICE
========================================================= */

async function loadPrice() {
    try {
        const data = await api(
            `/api/binance/price?symbol=${encodeURIComponent(currentSymbol)}`
        );

        const price =
            data.price ??
            data.current_price ??
            data.data?.price;

        if ($("currentPrice")) {
            $("currentPrice").textContent = formatPrice(price);
        }

    } catch (_) {}
}


/* =========================================================
   ANALYSIS
========================================================= */

async function analyzeCurrent() {
    try {
        showStatus(
            `جاري تحليل ${currentSymbol} على ${currentInterval}...`
        );

        const data = await api(
            `/api/binance/analysis?symbol=${encodeURIComponent(currentSymbol)}&interval=${encodeURIComponent(currentInterval)}`
        );

        const a = data.analysis || data;

        updateAnalysis(a);

        showStatus(
            `آخر تحديث: ${new Date().toLocaleTimeString("ar-SA")}`,
            "success"
        );

    } catch (error) {
        showError("فشل التحليل: " + error.message);
        showStatus("تعذر جلب التحليل", "error");
    }
}

function updateAnalysis(a) {
    const price = a.price ?? a.entry;

    setText("symbolName", a.symbol || currentSymbol);
    setText("currentPrice", formatPrice(price));

    setText("signal", a.signal || "حيادي");

    const score = Number(a.score ?? 0);

    setText(
        "score",
        Number.isFinite(score) ? Math.round(score) : "--"
    );

    if ($("signalProgress")) {
        const progress = Math.max(0, Math.min(100, score));
        $("signalProgress").style.width = progress + "%";
    }

    setText("entry", formatPrice(a.entry));
    setText("tp1", formatPrice(a.tp1));
    setText("tp2", formatPrice(a.tp2));
    setText("tp3", formatPrice(a.tp3));
    setText("sl", formatPrice(a.sl));

    setText(
        "rr",
        a.rr !== undefined && a.rr !== null
            ? a.rr
            : "--"
    );

    setText("rsi", formatNumber(a.rsi, 2));
    setText("ema20", formatPrice(a.ema20));
    setText("ema50", formatPrice(a.ema50));
    setText("ema200", formatPrice(a.ema200));
    setText("macd", formatNumber(a.macd, 6));
    setText("atr", formatPrice(a.atr));

    if (a.volume_ratio !== undefined) {
        setText(
            "volumeRatio",
            Number(a.volume_ratio).toFixed(2) + "x"
        );
    }

    const trend =
        a.direction ||
        (score >= 65 ? "صاعد" :
         score <= 35 ? "هابط" : "جانبي");

    setText("trend", trend);

    setText("support", formatPrice(a.support));
    setText("resistance", formatPrice(a.resistance));

    updateRSI(a.rsi);
    updateMACD(a.macd_histogram);
    renderReasons(a.reasons || []);

    renderChart(a.candles || []);

    setText("marketRegime", trend);
    setText("marketTrend", trend);
    setText("marketRegimeOverview", trend);

    setText(
        "marketStrength",
        Number.isFinite(score) ? `${Math.round(score)} / 100` : "--"
    );

    setText("chartTimeframe", intervalName(currentInterval));
}

function setText(id, value) {
    const element = $(id);
    if (element) {
        element.textContent = value ?? "--";
    }
}

function updateRSI(rsi) {
    const value = Number(rsi);

    if (!Number.isFinite(value)) {
        setText("rsiStatus", "--");
        return;
    }

    if (value >= 70) {
        setText("rsiStatus", "تشبع شرائي");
    } else if (value <= 30) {
        setText("rsiStatus", "تشبع بيعي");
    } else if (value >= 50) {
        setText("rsiStatus", "إيجابي");
    } else {
        setText("rsiStatus", "ضعيف");
    }
}

function updateMACD(histogram) {
    const value = Number(histogram);

    if (!Number.isFinite(value)) {
        setText("macdStatus", "--");
        return;
    }

    setText(
        "macdStatus",
        value > 0 ? "إيجابي 🟢" : "سلبي 🔴"
    );
}

function renderReasons(reasons) {
    const box = $("reasons");

    if (!box) return;

    if (!Array.isArray(reasons) || !reasons.length) {
        box.innerHTML = `
            <div class="reason-item">
                لا توجد أسباب إضافية.
            </div>
        `;
        return;
    }

    box.innerHTML = reasons.map(reason => `
        <div class="reason-item">
            ${escapeHtml(String(reason))}
        </div>
    `).join("");
}

function escapeHtml(value) {
    return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


/* =========================================================
   CHART
========================================================= */

function renderChart(candles) {
    const canvas = $("priceChart");

    if (!canvas || !Array.isArray(candles) || !candles.length) {
        return;
    }

    if (typeof Chart === "undefined") {
        return;
    }

    const labels = [];
    const prices = [];

    candles.forEach(c => {
        let time = c[0];
        let close = c[4];

        if (Array.isArray(c)) {
            time = c[0];
            close = c[4];
        } else if (typeof c === "object") {
            time = c.time ?? c.open_time ?? c.timestamp;
            close = c.close ?? c.c;
        }

        labels.push(
            time
                ? new Date(Number(time)).toLocaleTimeString("ar-SA", {
                    hour: "2-digit",
                    minute: "2-digit"
                })
                : ""
        );

        prices.push(Number(close));
    });

    if (chart) {
        chart.destroy();
    }

    chart = new Chart(canvas, {
        type: "line",
        data: {
            labels,
            datasets: [{
                label: currentSymbol,
                data: prices,
                tension: 0.25,
                pointRadius: 0,
                borderWidth: 2,
                fill: false
            }]
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
                    display: false
                },
                y: {
                    beginAtZero: false
                }
            }
        }
    });
}


/* =========================================================
   TIMEFRAME
========================================================= */

function intervalName(interval) {
    const names = {
        "5m": "5 دقائق",
        "15m": "15 دقيقة",
        "1h": "ساعة",
        "4h": "4 ساعات",
        "1d": "يومي",
        "1w": "أسبوعي"
    };

    return names[interval] || interval;
}

function setupTimeframes() {
    document.querySelectorAll("[data-interval]").forEach(button => {
        button.addEventListener("click", () => {

            currentInterval = button.dataset.interval;

            document
                .querySelectorAll(".timeframes button")
                .forEach(b => b.classList.remove("active"));

            button.classList.add("active");

            analyzeCurrent();
        });
    });
}


/* =========================================================
   FAVORITES
========================================================= */

function setupFavorites() {
    const btn = $("favoriteBtn");

    if (!btn) return;

    updateFavoriteButton();

    btn.addEventListener("click", () => {

        if (favorites.includes(currentSymbol)) {
            favorites = favorites.filter(
                s => s !== currentSymbol
            );
        } else {
            favorites.push(currentSymbol);
        }

        localStorage.setItem(
            "favorites",
            JSON.stringify(favorites)
        );

        updateFavoriteButton();
        renderCoinList($("coinSearch")?.value || "");
        renderFavorites();
    });
}

function updateFavoriteButton() {
    const btn = $("favoriteBtn");

    if (!btn) return;

    btn.textContent =
        favorites.includes(currentSymbol) ? "★" : "☆";
}

function renderFavorites() {
    const box = $("favoritesList");

    if (!box) return;

    if (!favorites.length) {
        box.innerHTML = `
            <div>⭐</div>
            <h3>لا توجد عملات مفضلة</h3>
            <p>أضف العملات للمفضلة من صفحة التحليل.</p>
        `;
        return;
    }

    box.className = "favorites-list";

    box.innerHTML = favorites.map(symbol => `
        <button
            type="button"
            class="coin-item"
            data-favorite="${symbol}"
        >
            ⭐ ${symbol}
        </button>
    `).join("");

    box.querySelectorAll("[data-favorite]").forEach(button => {
        button.addEventListener("click", () => {
            currentSymbol = button.dataset.favorite;
            analyzeCurrent();
        });
    });
}


/* =========================================================
   SEARCH
========================================================= */

function setupSearch() {
    const input = $("coinSearch");

    if (!input) return;

    input.addEventListener("input", () => {
        renderCoinList(input.value);
    });
}


/* =========================================================
   REFRESH
========================================================= */

function setupRefresh() {
    const btn = $("refreshBtn");

    if (!btn) return;

    btn.addEventListener("click", async () => {
        await loadMarkets();
        await analyzeCurrent();
    });
}

function startAutoRefresh(seconds = 30) {
    if (refreshTimer) {
        clearInterval(refreshTimer);
    }

    refreshTimer = setInterval(() => {
        analyzeCurrent();
    }, seconds * 1000);
}


/* =========================================================
   LOGIN / REGISTER FORMS
========================================================= */

function setupAuthForms() {

    const loginForm = $("loginForm");
    const registerForm = $("registerForm");

    if (loginForm) {
        loginForm.addEventListener("submit", async e => {
            e.preventDefault();

            const error = $("loginError");
            if (error) error.textContent = "";

            try {
                await login(
                    $("loginUsername").value.trim(),
                    $("loginPassword").value
                );
            } catch (err) {
                if (error) {
                    error.textContent = err.message;
                }
            }
        });
    }

    if (registerForm) {
        registerForm.addEventListener("submit", async e => {
            e.preventDefault();

            const error = $("registerError");
            if (error) error.textContent = "";

            const password = $("registerPassword").value;
            const password2 = $("registerPassword2").value;

            if (password !== password2) {
                if (error) {
                    error.textContent = "كلمتا المرور غير متطابقتين";
                }
                return;
            }

            try {
                await register(
                    $("registerUsername").value.trim(),
                    $("registerEmail").value.trim(),
                    password
                );

                await login(
                    $("registerUsername").value.trim(),
                    password
                );

            } catch (err) {
                if (error) {
                    error.textContent = err.message;
                }
            }
        });
    }

    const logoutBtn = $("logoutBtn");

    if (logoutBtn) {
        logoutBtn.addEventListener("click", logout);
    }
}


/* =========================================================
   ADMIN LINK
========================================================= */

function setupAdmin() {
    const adminLink = $("adminLink");

    if (!adminLink) return;

    adminLink.addEventListener("click", () => {
        window.location.href = "/admin";
    });
}


/* =========================================================
   SETTINGS
========================================================= */

async function loadSettings() {
    try {
        const data = await api("/api/settings");

        const settings = data.settings || data;

        if (settings.interval && $("intervalSetting")) {
            $("intervalSetting").value = settings.interval;
            currentInterval = settings.interval;
        }

        if (settings.refresh_seconds && $("refreshSetting")) {
            $("refreshSetting").value =
                String(settings.refresh_seconds);
        }

        if (
            settings.notifications !== undefined &&
            $("notificationsSetting")
        ) {
            $("notificationsSetting").checked =
                Boolean(settings.notifications);
        }

    } catch (_) {}
}

async function saveSettings() {
    const interval =
        $("intervalSetting")?.value || "15m";

    const refresh_seconds =
        Number($("refreshSetting")?.value || 30);

    const notifications =
        Boolean($("notificationsSetting")?.checked);

    try {
        await api("/api/settings", {
            method: "POST",
            body: JSON.stringify({
                interval,
                refresh_seconds,
                notifications
            })
        });

        currentInterval = interval;

        if ($("settingsMessage")) {
            $("settingsMessage").textContent =
                "تم حفظ الإعدادات ✅";
        }

        startAutoRefresh(refresh_seconds);

    } catch (error) {

        if ($("settingsMessage")) {
            $("settingsMessage").textContent =
                error.message;
        }
    }
}

function setupSettings() {
    const btn = $("saveSettingsBtn");

    if (btn) {
        btn.addEventListener("click", saveSettings);
    }
}


/* =========================================================
   PREMIUM
========================================================= */

function setupPremium() {
    const subscribeBtn = $("subscribeBtn");

    if (!subscribeBtn) return;

    subscribeBtn.addEventListener("click", () => {
        alert(
            "اشتراك Premium بقيمة $10 شهرياً.\n\n" +
            "طرق الدفع: Binance Pay أو USDT TRC20.\n" +
            "سيتم تفعيل الدفع الإلكتروني بعد ربط بوابة الدفع."
        );
    });
}


/* =========================================================
   SCANNER
========================================================= */

function setupScanner() {
    const button = $("runScannerBtn");

    if (!button) return;

    button.addEventListener("click", async () => {

        const box = $("scannerResults");

        if (box) {
            box.innerHTML = `
                <div class="loading">
                    جاري فحص السوق... ⏳
                </div>
            `;
        }

        try {

            const data = await api(
                "/api/binance/scan?interval=15m&limit=50"
            );

            const results = data.results || [];

            if (!results.length) {
                if (box) {
                    box.innerHTML = `
                        <div class="empty-state">
                            <div>🔎</div>
                            <h3>لا توجد نتائج</h3>
                            <p>لم تظهر فرص ضمن العملات المفحوصة.</p>
                        </div>
                    `;
                }
                return;
            }

            if (box) {
                box.innerHTML = results.map(item => {

                    const symbol =
                        item.symbol || "--";

                    const signal =
                        item.signal || "حيادي";

                    const score =
                        item.score ?? "--";

                    return `
                        <div class="scanner-item">
                            <strong>${escapeHtml(symbol)}</strong>
                            <span>${escapeHtml(signal)}</span>
                            <b>${score}/100</b>
                        </div>
                    `;
                }).join("");
            }

        } catch (error) {

            if (box) {
                box.innerHTML = `
                    <div class="empty-state">
                        <div>⚠️</div>
                        <h3>تعذر تشغيل الماسح</h3>
                        <p>${escapeHtml(error.message)}</p>
                    </div>
                `;
            }
        }
    });
}


/* =========================================================
   START
========================================================= */

document.addEventListener("DOMContentLoaded", async () => {

    setupTimeframes();
    setupFavorites();
    setupSearch();
    setupRefresh();
    setupAuthForms();
    setupAdmin();
    setupSettings();
    setupPremium();
    setupScanner();

    renderFavorites();

    await loadUser();
    await loadSettings();
    await loadMarkets();

    renderCoinList();

    await analyzeCurrent();
    await loadPrice();

    startAutoRefresh(30);
});
