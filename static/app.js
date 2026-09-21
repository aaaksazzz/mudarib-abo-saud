"use strict";

const state = {
    user: null,
    admin: false,
    interval: "15m",
    symbol: "BTCUSDT",
    results: [],
    futuresResults: [],
    scannerBusy: false,
    futuresBusy: false,
    futuresFilter: "all",
    chart: null,
    recent: JSON.parse(
        localStorage.getItem("mudarib_recent") || "[]"
    ),
    news: [],
    selectedPlan: null,
    paymentMethod: "TRC20"
};


const $ = id => document.getElementById(id);


function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


function number(value, digits = 2) {
    const n = Number(value);

    if (!Number.isFinite(n)) {
        return "-";
    }

    return n.toLocaleString("en-US", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits
    });
}


function price(value) {
    const n = Number(value);

    if (!Number.isFinite(n) || n <= 0) {
        return "-";
    }

    if (n >= 1000) {
        return n.toLocaleString("en-US", {
            maximumFractionDigits: 2
        });
    }

    if (n >= 1) {
        return n.toLocaleString("en-US", {
            maximumFractionDigits: 4
        });
    }

    return n.toLocaleString("en-US", {
        maximumFractionDigits: 8
    });
}


async function api(url, options = {}) {

    const config = {
        credentials: "same-origin",
        ...options
    };

    config.headers = {
        "Content-Type": "application/json",
        ...(options.headers || {})
    };

    const response = await fetch(url, config);

    const data =
        await response.json().catch(() => ({}));

    if (!response.ok) {

        const error =
            new Error(
                data.message ||
                data.error ||
                "حدث خطأ في الطلب."
            );

        error.status = response.status;

        throw error;
    }

    return data;
}


function toast(message, type = "info") {

    const container = $("toastContainer");

    if (!container) {
        return;
    }

    const item =
        document.createElement("div");

    item.className = `toast ${type}`;
    item.textContent = message;

    container.appendChild(item);

    setTimeout(() => {
        item.remove();
    }, 3500);
}


function setLoading(button, loading, text) {

    if (!button) {
        return;
    }

    if (loading) {
        button.dataset.originalText =
            button.textContent;

        button.disabled = true;
        button.textContent =
            text || "⏳ جاري التحميل...";
    } else {
        button.disabled = false;

        button.textContent =
            button.dataset.originalText ||
            button.textContent;
    }
}


/* ============================================================
   NAVIGATION
   ============================================================ */

const sectionTitles = {
    dashboard: "الرئيسية",
    scanner: "ماسح العملات",
    futures: "Futures",
    recent: "السجل",
    news: "الأخبار",
    subscription: "الاشتراك"
};


function showSection(name) {

    const sections =
        document.querySelectorAll(
            ".section"
        );

    sections.forEach(section => {

        section.classList.toggle(
            "active",
            section.dataset.sectionContent === name
        );

    });


    document.querySelectorAll(
        "[data-section]"
    ).forEach(item => {

        item.classList.toggle(
            "active",
            item.dataset.section === name
        );

    });


    const title = $("pageTitle");

    if (title) {
        title.textContent =
            sectionTitles[name] || name;
    }


    if (history.replaceState) {
        history.replaceState(
            null,
            "",
            `#${name}`
        );
    }


    document.body.classList.remove(
        "sidebar-open"
    );


    if (name === "futures") {
        runFuturesScan(false);
    }

    if (name === "news") {
        loadNews();
    }

    if (name === "subscription") {
        loadSubscription();
    }


    window.scrollTo({
        top: 0,
        behavior: "smooth"
    });
}


window.showSection = showSection;


function setupNavigation() {

    document.querySelectorAll(
        "[data-section]"
    ).forEach(item => {

        item.addEventListener(
            "click",
            event => {

                if (
                    item.tagName === "A" &&
                    item.getAttribute("href") !== "#"
                ) {
                    return;
                }

                event.preventDefault();

                showSection(
                    item.dataset.section
                );
            }
        );

    });


    const initial =
        window.location.hash
            .replace("#", "")
            .trim();

    if (
        initial &&
        sectionTitles[initial]
    ) {
        showSection(initial);
    } else {
        showSection("dashboard");
    }
}


/* ============================================================
   MOBILE MENU
   ============================================================ */

function setupMobileMenu() {

    const button =
        $("mobileMenuBtn");

    const overlay =
        $("mobileOverlay");

    if (!button) {
        return;
    }

    const close = () => {
        document.body.classList.remove(
            "sidebar-open"
        );
    };


    button.addEventListener(
        "click",
        () => {
            document.body.classList.toggle(
                "sidebar-open"
            );
        }
    );


    if (overlay) {
        overlay.addEventListener(
            "click",
            close
        );
    }


    document.querySelectorAll(
        ".sidebar .nav-item"
    ).forEach(item => {

        item.addEventListener(
            "click",
            close
        );

    });

}


/* ============================================================
   AUTH
   ============================================================ */

async function checkAuth() {

    try {

        const data =
            await api(
                "/api/auth/me"
            );

        state.user =
            data.user || null;

    } catch (error) {

        console.error(
            "AUTH:",
            error
        );

        state.user = null;
    }


    try {

        const data =
            await api(
                "/api/admin/me"
            );

        state.admin =
            data.authenticated === true ||
            data.admin === true;

    } catch (_) {

        state.admin = false;
    }


    updateAuthUI();
}


function updateAuthUI() {

    const userBadge =
        $("userBadge");

    const loginBtn =
        $("loginBtn");

    const registerBtn =
        $("registerBtn");

    const logoutBtn =
        $("logoutBtn");

    const adminLink =
        $("adminLink");

    const subscriptionLink =
        $("subscriptionLink");

    const mobileSubscriptionLink =
        $("mobileSubscriptionLink");

    const mobileBottomSubscription =
        $("mobileBottomSubscription");


    if (state.user) {

        if (userBadge) {

            userBadge.innerHTML = `
                <span>👤</span>
                <span>${escapeHtml(
                    state.user.name || "المستخدم"
                )}</span>
            `;
        }

        if (loginBtn) {
            loginBtn.style.display = "none";
        }

        if (registerBtn) {
            registerBtn.style.display = "none";
        }

        if (logoutBtn) {
            logoutBtn.style.display = "inline-flex";
        }

    } else {

        if (userBadge) {

            userBadge.innerHTML = `
                <span>👤</span>
                <span>زائر</span>
            `;
        }

        if (loginBtn) {
            loginBtn.style.display = "inline-flex";
        }

        if (registerBtn) {
            registerBtn.style.display = "inline-flex";
        }

        if (logoutBtn) {
            logoutBtn.style.display = "none";
        }
    }


    if (subscriptionLink) {
        subscriptionLink.style.display =
            state.user
            ? "flex"
            : "none";
    }

    if (mobileSubscriptionLink) {
        mobileSubscriptionLink.style.display =
            state.user
            ? "flex"
            : "none";
    }

    if (mobileBottomSubscription) {
        mobileBottomSubscription.style.display =
            state.user
            ? "flex"
            : "none";
    }

    if (adminLink) {
        adminLink.style.display =
            state.admin
            ? "flex"
            : "none";
    }
}


async function logoutUser() {

    try {
        await api(
            "/api/auth/logout",
            {
                method: "POST",
                body: "{}"
            }
        );
    } catch (error) {
        console.error(error);
    }

    state.user = null;

    updateAuthUI();

    toast(
        "تم تسجيل الخروج.",
        "success"
    );

    showSection("dashboard");
}


function setupAuth() {

    const logout =
        $("logoutBtn");

    if (logout) {

        logout.addEventListener(
            "click",
            logoutUser
        );
    }
}


/* ============================================================
   SCANNER
   ============================================================ */

async function runScanner() {

    if (state.scannerBusy) {
        return;
    }

    const button =
        $("scanBtn");

    state.scannerBusy = true;

    setLoading(
        button,
        true,
        "⏳ جاري الفحص..."
    );

    const status =
        $("scannerStatus");

    if (status) {
        status.textContent =
            `جاري فحص العملات على ${state.interval}...`;
    }

    try {

        const data =
            await api(
                `/api/binance/scan?interval=${encodeURIComponent(
                    state.interval
                )}`
            );

        state.results =
            Array.isArray(data.data)
            ? data.data
            : [];

        renderScanner();

        if (status) {

            status.textContent =
                data.scanned
                ? `تم فحص ${data.scanned} عملة وظهرت ${state.results.length} نتيجة.`
                : `ظهرت ${state.results.length} نتيجة.`;
        }

        if ($("statSpot")) {
            $("statSpot").textContent =
                state.results.length;
        }

    } catch (error) {

        console.error(error);

        if (status) {
            status.textContent =
                error.message ||
                "تعذر فحص العملات.";
        }

        toast(
            error.message ||
            "تعذر فحص العملات.",
            "error"
        );

    } finally {

        state.scannerBusy = false;

        setLoading(
            button,
            false
        );
    }
}


function signalClass(signal) {

    if (signal === "شراء قوي") {
        return "strong-buy";
    }

    if (signal === "شراء") {
        return "buy";
    }

    if (signal === "بيع قوي") {
        return "strong-sell";
    }

    if (signal === "بيع") {
        return "sell";
    }

    return "neutral";
}


function renderScanner() {

    const grid =
        $("scannerGrid");

    if (!grid) {
        return;
    }

    const search =
        (
            $("scannerSearch")?.value ||
            ""
        )
        .trim()
        .toUpperCase();

    const filter =
        $("scannerFilter")?.value ||
        "all";


    let items =
        state.results.filter(item => {

            const symbol =
                String(
                    item.symbol || ""
                ).toUpperCase();

            if (
                search &&
                !symbol.includes(search)
            ) {
                return false;
            }

            const signal =
                item.signal || "";

            if (
                filter === "buy" &&
                signal !== "شراء"
            ) {
                return false;
            }

            if (
                filter === "strong-buy" &&
                signal !== "شراء قوي"
            ) {
                return false;
            }

            if (
                filter === "sell" &&
                signal !== "بيع"
            ) {
                return false;
            }

            if (
                filter === "strong-sell" &&
                signal !== "بيع قوي"
            ) {
                return false;
            }

            return true;
        });


    if (!items.length) {

        grid.innerHTML = `
            <div class="empty-state full-grid">
                لا توجد نتائج مطابقة حالياً.
            </div>
        `;

        return;
    }


    grid.innerHTML =
        items.map(item => {

            const cls =
                signalClass(
                    item.signal
                );

            return `
                <article
                    class="coin-card ${cls}"
                    data-symbol="${escapeHtml(
                        item.symbol
                    )}"
                >

                    <div class="coin-card-top">

                        <div>
                            <strong>
                                ${escapeHtml(
                                    item.symbol
                                )}
                            </strong>

                            <small>
                                15m / Spot
                            </small>
                        </div>

                        <span
                            class="signal-badge ${cls}"
                        >
                            ${escapeHtml(
                                item.signal
                            )}
                        </span>

                    </div>


                    <div class="coin-price">
                        ${price(item.price)}
                    </div>


                    <div class="coin-metrics">

                        <div>
                            <span>القوة</span>
                            <strong>
                                ${number(
                                    item.score,
                                    0
                                )}%
                            </strong>
                        </div>

                        <div>
                            <span>RSI</span>
                            <strong>
                                ${number(
                                    item.rsi,
                                    1
                                )}
                            </strong>
                        </div>

                    </div>


                    <div class="coin-levels">

                        <div>
                            <span>EMA20</span>
                            <b>
                                ${price(item.ema20)}
                            </b>
                        </div>

                        <div>
                            <span>EMA50</span>
                            <b>
                                ${price(item.ema50)}
                            </b>
                        </div>

                        <div>
                            <span>EMA200</span>
                            <b>
                                ${price(item.ema200)}
                            </b>
                        </div>

                    </div>


                    <button
                        class="btn btn-outline full-width analyze-card-btn"
                        data-symbol="${escapeHtml(
                            item.symbol
                        )}"
                        type="button"
                    >
                        فتح التحليل
                    </button>

                </article>
            `;

        }).join("");


    grid.querySelectorAll(
        ".analyze-card-btn"
    ).forEach(button => {

        button.addEventListener(
            "click",
            () => {

                const symbol =
                    button.dataset.symbol;

                openAnalysis(
                    symbol,
                    state.interval
                );
            }
        );

    });
}


function setupScanner() {

    $("scanBtn")?.addEventListener(
        "click",
        runScanner
    );


    document.querySelectorAll(
        ".interval-btn"
    ).forEach(button => {

        button.addEventListener(
            "click",
            () => {

                document.querySelectorAll(
                    ".interval-btn"
                ).forEach(x => {
                    x.classList.remove("active");
                });

                button.classList.add("active");

                state.interval =
                    button.dataset.interval;

                runScanner();
            }
        );

    });


    $("scannerSearch")?.addEventListener(
        "input",
        renderScanner
    );


    $("scannerFilter")?.addEventListener(
        "change",
        renderScanner
    );
}


/* ============================================================
   ANALYSIS
   ============================================================ */

async function openAnalysis(symbol, interval = "15m") {

    state.symbol = symbol;
    state.interval = interval;

    const input =
        $("analysisSymbol");

    const intervalInput =
        $("analysisInterval");

    if (input) {
        input.value = symbol;
    }

    if (intervalInput) {
        intervalInput.value = interval;
    }

    showSection("dashboard");

    await loadAnalysis();
}


async function loadAnalysis() {

    const symbol =
        (
            $("analysisSymbol")?.value ||
            "BTCUSDT"
        )
        .trim()
        .toUpperCase();

    const interval =
        $("analysisInterval")?.value ||
        "15m";

    if (!symbol) {
        return;
    }

    const loading =
        $("analysisLoading");

    const empty =
        $("analysisEmpty");

    const content =
        $("analysisContent");

    if (loading) {
        loading.style.display = "block";
    }

    if (empty) {
        empty.style.display = "none";
    }

    if (content) {
        content.style.display = "none";
    }

    try {

        const data =
            await api(
                `/api/binance/analysis?symbol=${encodeURIComponent(
                    symbol
                )}&interval=${encodeURIComponent(
                    interval
                )}`
            );

        const result =
            data.data || {};

        renderAnalysis(
            symbol,
            interval,
            result
        );

        addRecent(
            symbol,
            interval,
            result
        );

    } catch (error) {

        console.error(error);

        if (empty) {
            empty.textContent =
                error.message ||
                "تعذر تحميل التحليل.";

            empty.style.display = "block";
        }

        toast(
            error.message ||
            "تعذر تحميل التحليل.",
            "error"
        );

    } finally {

        if (loading) {
            loading.style.display = "none";
        }
    }
}


function renderAnalysis(
    symbol,
    interval,
    result
) {

    const content =
        $("analysisContent");

    const signal =
        $("analysisSignal");

    const metrics =
        $("analysisMetrics");

    if (!content || !signal || !metrics) {
        return;
    }

    content.style.display = "block";


    const cls =
        signalClass(
            result.signal
        );


    signal.className =
        `analysis-signal ${cls}`;

    signal.innerHTML = `
        <div>
            <span>الإشارة</span>
            <strong>
                ${escapeHtml(
                    result.signal || "محايد"
                )}
            </strong>
        </div>

        <div>
            <span>القوة</span>
            <strong>
                ${number(
                    result.score,
                    0
                )}%
            </strong>
        </div>

        <div>
            <span>العملة</span>
            <strong>
                ${escapeHtml(symbol)}
            </strong>
        </div>

        <div>
            <span>الفاصل</span>
            <strong>
                ${escapeHtml(interval)}
            </strong>
        </div>
    `;


    metrics.innerHTML = `

        <div class="metric-card">
            <span>السعر</span>
            <strong>${price(result.price)}</strong>
        </div>

        <div class="metric-card">
            <span>RSI</span>
            <strong>${number(result.rsi, 2)}</strong>
        </div>

        <div class="metric-card">
            <span>EMA20</span>
            <strong>${price(result.ema20)}</strong>
        </div>

        <div class="metric-card">
            <span>EMA50</span>
            <strong>${price(result.ema50)}</strong>
        </div>

        <div class="metric-card">
            <span>EMA200</span>
            <strong>${price(result.ema200)}</strong>
        </div>

        <div class="metric-card">
            <span>ATR</span>
            <strong>${price(result.atr)}</strong>
        </div>

    `;


    renderChart(
        result.chart || []
    );
}


function renderChart(data) {

    const canvas =
        $("analysisChart");

    if (!canvas || typeof Chart === "undefined") {
        return;
    }

    const labels =
        data.map(item => {
            const date =
                new Date(
                    Number(item.time) * 1000
                );

            return date.toLocaleTimeString(
                "ar-SA",
                {
                    hour: "2-digit",
                    minute: "2-digit"
                }
            );
        });

    const values =
        data.map(item => Number(item.price));


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
                            label: "السعر",
                            data: values,
                            tension: 0.25,
                            borderWidth: 2,
                            pointRadius: 0
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


function setupAnalysis() {

    $("analysisForm")?.addEventListener(
        "submit",
        event => {

            event.preventDefault();

            loadAnalysis();
        }
    );
}


/* ============================================================
   RECENT
   ============================================================ */

function addRecent(
    symbol,
    interval,
    result
) {

    state.recent =
        state.recent.filter(
            item =>
                item.symbol !== symbol
        );

    state.recent.unshift({
        symbol,
        interval,
        signal: result.signal || "محايد",
        score: result.score || 50,
        time: Date.now()
    });

    state.recent =
        state.recent.slice(0, 20);

    localStorage.setItem(
        "mudarib_recent",
        JSON.stringify(state.recent)
    );

    renderRecent();
}


function renderRecent() {

    const grid =
        $("recentGrid");

    if (!grid) {
        return;
    }

    if (!state.recent.length) {

        grid.innerHTML = `
            <div class="empty-state full-grid">
                لا يوجد سجل حتى الآن.
            </div>
        `;

        return;
    }


    grid.innerHTML =
        state.recent.map(item => {

            const cls =
                signalClass(
                    item.signal
                );

            return `
                <article
                    class="coin-card ${cls}"
                >

                    <div class="coin-card-top">

                        <div>
                            <strong>
                                ${escapeHtml(
                                    item.symbol
                                )}
                            </strong>

                            <small>
                                ${escapeHtml(
                                    item.interval
                                )}
                            </small>
                        </div>

                        <span
                            class="signal-badge ${cls}"
                        >
                            ${escapeHtml(
                                item.signal
                            )}
                        </span>

                    </div>

                    <div class="recent-score">
                        القوة ${number(item.score, 0)}%
                    </div>

                    <button
                        class="btn btn-outline full-width recent-open"
                        data-symbol="${escapeHtml(
                            item.symbol
                        )}"
                        data-interval="${escapeHtml(
                            item.interval
                        )}"
                        type="button"
                    >
                        فتح التحليل
                    </button>

                </article>
            `;

        }).join("");


    grid.querySelectorAll(
        ".recent-open"
    ).forEach(button => {

        button.addEventListener(
            "click",
            () => {

                openAnalysis(
                    button.dataset.symbol,
                    button.dataset.interval
                );
            }
        );
    });
}


function setupRecent() {

    $("clearRecentBtn")?.addEventListener(
        "click",
        () => {

            state.recent = [];

            localStorage.removeItem(
                "mudarib_recent"
            );

            renderRecent();

            toast(
                "تم مسح السجل.",
                "success"
            );
        }
    );
}


/* ============================================================
   FUTURES
   ============================================================ */

async function runFuturesScan(force = false) {

    if (state.futuresBusy) {
        return;
    }

    state.futuresBusy = true;

    const button =
        $("futuresScanBtn");

    const status =
        $("futuresStatus");

    setLoading(
        button,
        true,
        "⏳ جاري فحص Futures..."
    );

    if (status) {
        status.textContent =
            "جاري فحص عقود Futures...";
    }

    try {

        const data =
            await api(
                `/api/futures/scan?force=${force ? "1" : "0"}`
            );

        state.futuresResults =
            Array.isArray(data.data)
            ? data.data
            : [];

        renderFutures();

        if (status) {

            status.textContent =
                data.message ||
                `ظهرت ${state.futuresResults.length} فرصة.`;
        }

        if ($("statFutures")) {
            $("statFutures").textContent =
                state.futuresResults.length;
        }

    } catch (error) {

        console.error(error);

        if (status) {
            status.textContent =
                error.message ||
                "تعذر فحص Futures.";
        }

        toast(
            error.message ||
            "تعذر فحص Futures.",
            "error"
        );

    } finally {

        state.futuresBusy = false;

        setLoading(
            button,
            false
        );
    }
}


function renderFutures() {

    const grid =
        $("futuresGrid");

    if (!grid) {
        return;
    }


    const search =
        (
            $("futuresSearch")?.value ||
            ""
        )
        .trim()
        .toUpperCase();


    let items =
        state.futuresResults.filter(item => {

            if (
                search &&
                !String(
                    item.symbol || ""
                )
                .toUpperCase()
                .includes(search)
            ) {
                return false;
            }

            if (
                state.futuresFilter !== "all" &&
                item.direction !==
                state.futuresFilter
            ) {
                return false;
            }

            return true;
        });


    if (!items.length) {

        grid.innerHTML = `
            <div class="empty-state full-grid">
                ما ظهرت فرص مطابقة حالياً.
                اضغط فحص Futures لإعادة الفحص.
            </div>
        `;

        return;
    }


    grid.innerHTML =
        items.map(item => {

            const long =
                item.direction === "LONG";

            const cls =
                long
                ? "futures-long"
                : "futures-short";


            return `
                <article
                    class="futures-card ${cls}"
                >

                    <div class="futures-card-header">

                        <div>

                            <strong>
                                ${escapeHtml(
                                    item.symbol
                                )}
                            </strong>

                            <span>
                                ${escapeHtml(
                                    item.timeframe || "15m"
                                )}
                            </span>

                        </div>

                        <span
                            class="direction-badge"
                        >
                            ${long ? "🟢 LONG شراء" : "🔴 SHORT بيع"}
                        </span>

                    </div>


                    <div class="futures-score">

                        <div>

                            <span>الثقة</span>

                            <strong>
                                ${number(
                                    item.confidence,
                                    0
                                )}%
                            </strong>

                        </div>

                        <div>

                            <span>RSI</span>

                            <strong>
                                ${number(
                                    item.rsi,
                                    1
                                )}
                            </strong>

                        </div>

                        <div>

                            <span>24H</span>

                            <strong>
                                ${number(
                                    item.change24h,
                                    2
                                )}%
                            </strong>

                        </div>

                    </div>


                    <div class="trade-levels">

                        <div class="entry">
                            <span>الدخول</span>
                            <strong>
                                ${price(item.entry)}
                            </strong>
                        </div>

                        <div class="target">
                            <span>الهدف</span>
                            <strong>
                                ${price(item.target)}
                            </strong>
                        </div>

                        <div class="stop">
                            <span>وقف الخسارة</span>
                            <strong>
                                ${price(item.stop)}
                            </strong>
                        </div>

                    </div>


                    <div class="futures-info">

                        <span>
                            مخاطرة ${number(
                                item.risk_percent,
                                2
                            )}%
                        </span>

                        <span>
                            عائد ${number(
                                item.reward_percent,
                                2
                            )}%
                        </span>

                        <span>
                            رافعة ${number(
                                item.leverage,
                                0
                            )}x
                        </span>

                    </div>


                    <div class="futures-reason">
                        ${escapeHtml(
                            item.reason || ""
                        )}
                    </div>

                </article>
            `;

        }).join("");
}


function setupFutures() {

    $("futuresScanBtn")?.addEventListener(
        "click",
        () => runFuturesScan(true)
    );


    document.querySelectorAll(
        ".futures-filter"
    ).forEach(button => {

        button.addEventListener(
            "click",
            () => {

                document.querySelectorAll(
                    ".futures-filter"
                ).forEach(x => {
                    x.classList.remove(
                        "active"
                    );
                });

                button.classList.add(
                    "active"
                );

                state.futuresFilter =
                    button.dataset.futuresFilter;

                renderFutures();
            }
        );

    });


    $("futuresSearch")?.addEventListener(
        "input",
        renderFutures
    );
}


/* ============================================================
   NEWS
   ============================================================ */

async function loadNews() {

    const status =
        $("newsStatus");

    if (status) {
        status.textContent =
            "جاري تحميل الأخبار...";
    }

    try {

        const data =
            await api("/api/news");

        state.news =
            Array.isArray(data.data)
            ? data.data
            : [];

        renderNews();

        if (status) {
            status.textContent =
                `تم تحميل ${state.news.length} خبر.`;
        }

    } catch (error) {

        console.error(error);

        if (status) {
            status.textContent =
                error.message ||
                "تعذر تحميل الأخبار.";
        }
    }
}


function renderNews() {

    const grid =
        $("newsGrid");

    if (!grid) {
        return;
    }


    if (!state.news.length) {

        grid.innerHTML = `
            <div class="empty-state full-grid">
                لا توجد أخبار متاحة حالياً.
            </div>
        `;

        return;
    }


    grid.innerHTML =
        state.news.map(
            (item, index) => {

                return `
                    <article
                        class="news-card"
                        data-news-index="${index}"
                    >

                        <div class="news-card-top">

                            <span class="news-source">
                                ${escapeHtml(
                                    item.source || "أخبار"
                                )}
                            </span>

                            <span class="news-date">
                                ${escapeHtml(
                                    item.published || ""
                                )}
                            </span>

                        </div>


                        <h3>
                            ${escapeHtml(
                                item.title || ""
                            )}
                        </h3>


                        <p>
                            ${escapeHtml(
                                item.description || ""
                            )}
                        </p>


                        <button
                            class="btn btn-outline news-open-btn"
                            type="button"
                        >
                            قراءة الخبر
                        </button>

                    </article>
                `;
            }
        ).join("");


    grid.querySelectorAll(
        ".news-card"
    ).forEach(card => {

        const index =
            Number(
                card.dataset.newsIndex
            );

        card.querySelector(
            ".news-open-btn"
        )?.addEventListener(
            "click",
            () => openNewsArticle(
                state.news[index]
            )
        );

    });
}


function openNewsArticle(item) {

    if (!item) {
        return;
    }

    const modal =
        $("newsModal");

    if (!modal) {
        return;
    }

    $("modalNewsSource").textContent =
        item.source || "";

    $("modalNewsTitle").textContent =
        item.title || "";

    $("modalNewsDate").textContent =
        item.published || "";

    $("modalNewsDescription").textContent =
        item.description || "";

    modal.classList.add("active");
    modal.setAttribute(
        "aria-hidden",
        "false"
    );

    document.body.classList.add(
        "modal-open"
    );
}


function closeNewsModal() {

    const modal =
        $("newsModal");

    if (!modal) {
        return;
    }

    modal.classList.remove("active");
    modal.setAttribute(
        "aria-hidden",
        "true"
    );

    document.body.classList.remove(
        "modal-open"
    );
}


function setupNews() {

    $("refreshNewsBtn")?.addEventListener(
        "click",
        loadNews
    );

    $("closeNewsModal")?.addEventListener(
        "click",
        closeNewsModal
    );

    document.querySelector(
        ".modal-backdrop"
    )?.addEventListener(
        "click",
        closeNewsModal
    );
}


/* ============================================================
   SUBSCRIPTION
   ============================================================ */

async function loadSubscription() {

    if (!state.user) {

        const status =
            $("subscriptionStatus");

        if (status) {
            status.innerHTML = `
                <strong>
                    🔐 يجب تسجيل الدخول أولاً
                </strong>

                <a
                    href="/login"
                    class="btn btn-primary"
                >
                    تسجيل الدخول
                </a>
            `;
        }

        return;
    }


    try {

        const data =
            await api(
                "/api/subscription/my"
            );

        const subscription =
            data.data || {};

        const status =
            $("subscriptionStatus");


        if (
            subscription.is_premium
        ) {

            const until =
                subscription.premium_until
                ? new Date(
                    subscription.premium_until
                ).toLocaleDateString(
                    "ar-SA"
                )
                : "غير محدد";


            status.innerHTML = `
                <div>
                    <span class="status-dot"></span>
                    <strong>اشتراكك فعال</strong>
                </div>

                <small>
                    ينتهي في ${escapeHtml(until)}
                </small>
            `;

        } else {

            status.innerHTML = `
                <div>
                    <span class="status-dot danger"></span>
                    <strong>لا يوجد اشتراك فعال</strong>
                </div>

                <small>
                    اختر باقة بالأسفل.
                </small>
            `;
        }


        await loadPlans();
        await loadPaymentSettings();

    } catch (error) {

        console.error(error);

        toast(
            "تعذر تحميل بيانات الاشتراك.",
            "error"
        );
    }
}


async function loadPlans() {

    const grid =
        $("plansGrid");

    if (!grid) {
        return;
    }

    try {

        const data =
            await api(
                "/api/subscription/plans"
            );

        const plans =
            data.plans ||
            data.data ||
            {};


        grid.innerHTML =
            Object.entries(plans)
                .map(([id, plan]) => {

                    return `
                        <article
                            class="plan-card"
                            data-plan="${escapeHtml(id)}"
                        >

                            <div class="plan-icon">
                                💎
                            </div>

                            <h3>
                                ${escapeHtml(
                                    plan.name
                                )}
                            </h3>

                            <div class="plan-price">
                                ${number(
                                    plan.amount,
                                    2
                                )}
                                <span>USDT</span>
                            </div>

                            <p>
                                وصول إلى الأدوات المدفوعة.
                            </p>

                            <button
                                class="btn btn-primary full-width choose-plan"
                                data-plan="${escapeHtml(id)}"
                                type="button"
                            >
                                اختيار الباقة
                            </button>

                        </article>
                    `;
                })
                .join("");


        grid.querySelectorAll(
            ".choose-plan"
        ).forEach(button => {

            button.addEventListener(
                "click",
                () => selectPlan(
                    button.dataset.plan,
                    plans[
                        button.dataset.plan
                    ]
                )
            );

        });

    } catch (error) {

        grid.innerHTML = `
            <div class="empty-state full-grid">
                تعذر تحميل الباقات.
            </div>
        `;
    }
}


async function loadPaymentSettings() {

    try {

        const data =
            await api(
                "/api/settings/public"
            );

        const settings =
            data.data || {};


        if ($("trc20Address")) {
            $("trc20Address").textContent =
                settings.trc20_address ||
                "لم يتم ضبط عنوان TRC20.";
        }


        if ($("binancePayAddress")) {
            $("binancePayAddress").textContent =
                settings.binance_pay ||
                "لم يتم ضبط بيانات Binance Pay.";
        }

    } catch (error) {

        console.error(error);
    }
}


function selectPlan(id, plan) {

    state.selectedPlan = id;

    $("selectedPlan").value =
        id;

    $("selectedPlanTitle").textContent =
        plan.name;

    $("selectedPlanAmount").textContent =
        `${number(plan.amount, 2)} USDT`;

    $("selectedPlanBox").style.display =
        "block";


    document.querySelectorAll(
        ".plan-card"
    ).forEach(card => {

        card.classList.toggle(
            "selected",
            card.dataset.plan === id
        );

    });


    $("selectedPlanBox").scrollIntoView({
        behavior: "smooth",
        block: "start"
    });
}


function setupSubscription() {

    document.querySelectorAll(
        ".payment-method"
    ).forEach(button => {

        button.addEventListener(
            "click",
            () => {

                document.querySelectorAll(
                    ".payment-method"
                ).forEach(x => {
                    x.classList.remove(
                        "active"
                    );
                });

                button.classList.add(
                    "active"
                );

                state.paymentMethod =
                    button.dataset.method;

                $("selectedPaymentMethod").value =
                    state.paymentMethod;


                const trc =
                    $("trc20PaymentBox");

                const binance =
                    $("binancePayBox");


                if (
                    state.paymentMethod ===
                    "TRC20"
                ) {

                    trc.style.display =
                        "block";

                    binance.style.display =
                        "none";

                } else {

                    trc.style.display =
                        "none";

                    binance.style.display =
                        "block";
                }

            }
        );

    });


    $("copyTrc20Btn")?.addEventListener(
        "click",
        async () => {

            const value =
                $("trc20Address")
                    ?.textContent
                    ?.trim();

            if (!value) {
                return;
            }

            try {

                await navigator.clipboard.writeText(
                    value
                );

                toast(
                    "تم نسخ عنوان TRC20.",
                    "success"
                );

            } catch (_) {

                toast(
                    "تعذر النسخ تلقائياً.",
                    "error"
                );
            }
        }
    );


    $("subscriptionForm")?.addEventListener(
        "submit",
        async event => {

            event.preventDefault();

            if (!state.user) {

                toast(
                    "سجل الدخول أولاً.",
                    "error"
                );

                return;
            }

            const plan =
                $("selectedPlan")?.value;

            const txid =
                $("paymentTxid")
                    ?.value
                    ?.trim();

            const method =
                $("selectedPaymentMethod")
                    ?.value ||
                "TRC20";


            if (!plan) {

                toast(
                    "اختر الباقة أولاً.",
                    "error"
                );

                return;
            }


            if (!txid) {

                toast(
                    "أدخل رقم العملية TXID.",
                    "error"
                );

                return;
            }


            const button =
                $("submitSubscriptionBtn");

            setLoading(
                button,
                true,
                "⏳ جاري إرسال الطلب..."
            );


            try {

                const data =
                    await api(
                        "/api/subscription/request",
                        {
                            method: "POST",
                            body: JSON.stringify({
                                plan,
                                method,
                                txid
                            })
                        }
                    );

                toast(
                    data.message ||
                    "تم إرسال الطلب.",
                    "success"
                );

                $("paymentTxid").value = "";

            } catch (error) {

                if (error.status === 401) {

                    toast(
                        "يجب تسجيل الدخول أولاً.",
                        "error"
                    );

                    setTimeout(
                        () => {
                            window.location.href =
                                "/login";
                        },
                        600
                    );

                } else {

                    toast(
                        error.message ||
                        "تعذر إرسال الطلب.",
                        "error"
                    );
                }

            } finally {

                setLoading(
                    button,
                    false
                );
            }

        }
    );
}


/* ============================================================
   STATS
   ============================================================ */

async function loadStats() {

    try {

        const data =
            await api(
                "/api/binance/markets"
            );

        if ($("statMarkets")) {
            $("statMarkets").textContent =
                number(
                    data.count || 0,
                    0
                );
        }

    } catch (_) {}
}


async function checkBinanceStatus() {

    const box =
        $("binanceStatus");

    try {

        const data =
            await api(
                "/api/binance/test"
            );

        if (data.connected) {

            box.innerHTML = `
                <span class="status-dot"></span>
                <span>بيانات Binance متاحة</span>
            `;

            if ($("statBinance")) {
                $("statBinance").textContent =
                    "متصل";
            }

        } else {

            throw new Error();
        }

    } catch (_) {

        box.innerHTML = `
            <span class="status-dot danger"></span>
            <span>تعذر الاتصال</span>
        `;

        if ($("statBinance")) {
            $("statBinance").textContent =
                "غير متاح";
        }
    }
}


/* ============================================================
   THEME
   ============================================================ */

function setupTheme() {

    const button =
        $("themeBtn");

    const saved =
        localStorage.getItem(
            "mudarib_theme"
        );

    if (saved === "light") {
        document.body.classList.add(
            "light-theme"
        );
    }


    updateThemeIcon();


    button?.addEventListener(
        "click",
        () => {

            document.body.classList.toggle(
                "light-theme"
            );

            localStorage.setItem(
                "mudarib_theme",
                document.body.classList.contains(
                    "light-theme"
                )
                ? "light"
                : "dark"
            );

            updateThemeIcon();
        }
    );
}


function updateThemeIcon() {

    const button =
        $("themeBtn");

    if (!button) {
        return;
    }

    button.textContent =
        document.body.classList.contains(
            "light-theme"
        )
        ? "☀️"
        : "🌙";
}


/* ============================================================
   GENERAL
   ============================================================ */

function setupGeneral() {

    setupTheme();

    $("refreshNewsBtn")?.addEventListener(
        "click",
        loadNews
    );
}


/* ============================================================
   BOOT
   ============================================================ */

async function boot() {

    setupNavigation();
    setupMobileMenu();

    setupAuth();

    setupScanner();
    setupAnalysis();

    setupRecent();

    setupFutures();

    setupNews();

    setupSubscription();

    setupGeneral();

    renderRecent();

    await checkAuth();

    await loadStats();

    await checkBinanceStatus();

    await runScanner();

    await loadAnalysis();

    await loadNews();


    setInterval(
        () => {

            if (
                !document.hidden
            ) {
                runScanner();
            }

        },
        60_000
    );


    setInterval(
        () => {

            if (
                !document.hidden
            ) {
                loadNews();
            }

        },
        10 * 60_000
    );
}


document.addEventListener(
    "DOMContentLoaded",
    boot
);
