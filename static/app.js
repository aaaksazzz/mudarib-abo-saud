/* ============================================================
   مضارب أبو سعود
   static/app.js
   ============================================================ */

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

    sort: "score",
    sortDir: -1,

    chart: null,

    recent: JSON.parse(
        localStorage.getItem("mudarib_recent") || "[]"
    )
};


/* ============================================================
   HELPERS
   ============================================================ */

function $(id) {
    return document.getElementById(id);
}


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
        maximumFractionDigits: digits
    });
}


function price(value) {
    const n = Number(value);

    if (!Number.isFinite(n)) {
        return "-";
    }

    if (n >= 1000) {
        return n.toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
    }

    if (n >= 1) {
        return n.toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 6
        });
    }

    return n.toLocaleString("en-US", {
        minimumFractionDigits: 4,
        maximumFractionDigits: 10
    });
}


function api(url, options = {}) {
    return fetch(url, {
        credentials: "same-origin",
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {})
        }
    }).then(async response => {

        let data = {};

        try {
            data = await response.json();
        } catch (_) {
            data = {};
        }

        if (!response.ok || data.ok === false) {
            throw new Error(
                data.error ||
                data.message ||
                `خطأ HTTP ${response.status}`
            );
        }

        return data;
    });
}


function toast(message, type = "info") {

    let container = $("toastContainer");

    if (!container) {
        container = document.createElement("div");
        container.id = "toastContainer";
        container.className = "toast-container";
        document.body.appendChild(container);
    }

    const item = document.createElement("div");

    item.className =
        `toast toast-${type}`;

    item.textContent = message;

    container.appendChild(item);

    setTimeout(() => {
        item.classList.add("hide");

        setTimeout(() => {
            item.remove();
        }, 300);

    }, 3000);
}


function setLoading(element, loading, text = "جاري التحميل...") {

    if (!element) {
        return;
    }

    if (loading) {

        if (!element.dataset.originalText) {
            element.dataset.originalText =
                element.textContent;
        }

        element.disabled = true;
        element.textContent = text;

    } else {

        element.disabled = false;

        if (element.dataset.originalText) {
            element.textContent =
                element.dataset.originalText;

            delete element.dataset.originalText;
        }
    }
}


/* ============================================================
   NAVIGATION
   ============================================================ */

const sectionTitles = {
    dashboard: "الرئيسية",
    scanner: "ماسح العملات",
    futures: "فيوتشر",
    recent: "آخر التحليلات",
    news: "الأخبار",
    subscription: "الاشتراك"
};


function showSection(sectionName) {

    document
        .querySelectorAll(".section")
        .forEach(section => {
            section.classList.remove("active");
        });

    const section = $(
        sectionName
    );

    if (section) {
        section.classList.add("active");
    }

    document
        .querySelectorAll("[data-section]")
        .forEach(link => {

            link.classList.toggle(
                "active",
                link.dataset.section === sectionName
            );

        });

    const title = $("pageTitle");

    if (title) {
        title.textContent =
            sectionTitles[sectionName] ||
            "الرئيسية";
    }

    history.replaceState(
        null,
        "",
        sectionName === "dashboard"
            ? "/"
            : `/#${sectionName}`
    );
}


function setupNavigation() {

    document
        .querySelectorAll("[data-section]")
        .forEach(link => {

            link.addEventListener(
                "click",
                event => {

                    event.preventDefault();

                    const section =
                        link.dataset.section;

                    showSection(section);

                    if (section === "futures") {
                        runFuturesScan();
                    }

                    if (section === "news") {
                        loadNews();
                    }
                }
            );
        });


    const hash =
        location.hash.replace("#", "");

    if (
        hash &&
        sectionTitles[hash]
    ) {
        showSection(hash);
    } else {
        showSection("dashboard");
    }
}


/* ============================================================
   AUTH
   ============================================================ */

async function checkAuth() {

    try {

        const data =
            await api("/api/auth/me");

        state.user =
            data.logged_in
                ? data.user
                : null;

    } catch (error) {

        console.error(
            "AUTH:",
            error
        );

        state.user = null;
    }


    try {

        const admin =
            await api("/api/admin/me");

        state.admin =
            !!admin.admin;

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


    if (state.user) {

        if (userBadge) {
            userBadge.textContent =
                state.user.name ||
                state.user.email;
        }

        if (loginBtn) {
            loginBtn.style.display =
                "none";
        }

        if (registerBtn) {
            registerBtn.style.display =
                "none";
        }

        if (logoutBtn) {
            logoutBtn.style.display =
                "";
        }

        if (subscriptionLink) {
            subscriptionLink.style.display =
                "";
        }

    } else {

        if (userBadge) {
            userBadge.textContent =
                "زائر";
        }

        if (loginBtn) {
            loginBtn.style.display =
                "";
        }

        if (registerBtn) {
            registerBtn.style.display =
                "";
        }

        if (logoutBtn) {
            logoutBtn.style.display =
                "none";
        }

        if (subscriptionLink) {
            subscriptionLink.style.display =
                "none";
        }
    }


    if (adminLink) {

        adminLink.style.display =
            state.admin
                ? ""
                : "none";
    }
}


function setupAuthButtons() {

    const loginBtn =
        $("loginBtn");

    const registerBtn =
        $("registerBtn");

    const logoutBtn =
        $("logoutBtn");


    if (loginBtn) {

        loginBtn.onclick = () => {
            location.href =
                "/login";
        };
    }


    if (registerBtn) {

        registerBtn.onclick = () => {
            location.href =
                "/register";
        };
    }


    if (logoutBtn) {

        logoutBtn.onclick =
            async () => {

                try {

                    await api(
                        "/api/auth/logout",
                        {
                            method: "POST"
                        }
                    );

                    state.user = null;

                    updateAuthUI();

                    toast(
                        "تم تسجيل الخروج",
                        "success"
                    );

                    setTimeout(() => {
                        location.href = "/";
                    }, 300);

                } catch (error) {

                    toast(
                        error.message,
                        "error"
                    );
                }
            };
    }
}


/* ============================================================
   SCANNER
   ============================================================ */

async function runScanner() {

    if (state.scannerBusy) {
        return;
    }

    state.scannerBusy = true;

    const button =
        $("scanBtn");

    setLoading(
        button,
        true,
        "جاري الفحص..."
    );


    const status =
        $("scannerStatus");

    if (status) {
        status.textContent =
            "جاري فحص العملات...";
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

        updateStats();

        if (status) {
            status.textContent =
                `تم فحص ${state.results.length} عملة`;
        }

    } catch (error) {

        console.error(error);

        if (status) {
            status.textContent =
                "تعذر الاتصال ببيانات Binance";
        }

        toast(
            error.message ||
            "تعذر تشغيل الماسح",
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


function renderScanner() {

    const grid =
        $("scannerGrid");

    if (!grid) {
        return;
    }

    if (!state.results.length) {

        grid.innerHTML = `
            <div class="empty-state">
                لا توجد نتائج حالياً.
            </div>
        `;

        return;
    }


    let results =
        [...state.results];


    const searchInput =
        $("scannerSearch");

    const search =
        searchInput
            ? searchInput.value
                .trim()
                .toUpperCase()
            : "";


    if (search) {

        results =
            results.filter(item =>
                String(item.symbol || "")
                    .includes(search)
            );
    }


    const signalFilter =
        $("signalFilter");

    const selectedSignal =
        signalFilter
            ? signalFilter.value
            : "all";


    if (
        selectedSignal &&
        selectedSignal !== "all"
    ) {

        results =
            results.filter(item =>
                item.signal ===
                selectedSignal
            );
    }


    results.sort((a, b) => {

        const av =
            Number(
                a[state.sort] ?? 0
            );

        const bv =
            Number(
                b[state.sort] ?? 0
            );

        return (
            av - bv
        ) * state.sortDir;
    });


    grid.innerHTML =
        results.map(
            renderScannerCard
        ).join("");
}


function renderScannerCard(item) {

    const signal =
        item.signal || "محايد";

    let signalClass =
        "neutral";

    if (
        signal.includes("شراء")
    ) {
        signalClass = "buy";
    }

    if (
        signal.includes("بيع")
    ) {
        signalClass = "sell";
    }


    return `
        <article
            class="coin-card"
            data-symbol="${escapeHtml(item.symbol)}"
            onclick="openCoinAnalysis('${escapeHtml(item.symbol)}')"
        >

            <div class="coin-card-head">

                <strong>
                    ${escapeHtml(item.symbol)}
                </strong>

                <span class="signal ${signalClass}">
                    ${escapeHtml(signal)}
                </span>

            </div>

            <div class="coin-price">
                ${price(item.price)}
            </div>

            <div class="coin-details">

                <span>
                    القوة
                    <b>${number(item.score, 0)}</b>
                </span>

                <span>
                    RSI
                    <b>${number(item.rsi, 1)}</b>
                </span>

            </div>

            <div class="score-bar">

                <span
                    style="width:${Math.max(
                        0,
                        Math.min(
                            100,
                            Number(item.score || 0)
                        )
                    )}%"
                ></span>

            </div>

            <div class="coin-card-footer">
                اضغط لعرض التحليل
                <span>←</span>
            </div>

        </article>
    `;
}


/* ============================================================
   SCANNER FILTERS
   ============================================================ */

function setupScanner() {

    const scanBtn =
        $("scanBtn");

    if (scanBtn) {
        scanBtn.onclick =
            runScanner;
    }


    document
        .querySelectorAll(
            "[data-interval]"
        )
        .forEach(button => {

            button.addEventListener(
                "click",
                () => {

                    document
                        .querySelectorAll(
                            "[data-interval]"
                        )
                        .forEach(x =>
                            x.classList.remove(
                                "active"
                            )
                        );

                    button.classList.add(
                        "active"
                    );

                    state.interval =
                        button.dataset.interval;

                    runScanner();
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


    const filter =
        $("signalFilter");

    if (filter) {

        filter.addEventListener(
            "change",
            renderScanner
        );
    }


    document
        .querySelectorAll(
            "[data-sort]"
        )
        .forEach(button => {

            button.addEventListener(
                "click",
                () => {

                    const sort =
                        button.dataset.sort;

                    if (
                        state.sort === sort
                    ) {
                        state.sortDir *= -1;
                    } else {
                        state.sort =
                            sort;

                        state.sortDir =
                            -1;
                    }

                    renderScanner();
                }
            );
        });
}


/* ============================================================
   ANALYSIS
   ============================================================ */

async function loadAnalysis(
    symbol = state.symbol
) {

    state.symbol =
        symbol.toUpperCase();


    const symbolInput =
        $("symbolInput");

    if (symbolInput) {
        symbolInput.value =
            state.symbol;
    }


    const title =
        $("analysisSymbol");

    if (title) {
        title.textContent =
            state.symbol;
    }


    try {

        const data =
            await api(
                `/api/binance/analysis?symbol=${encodeURIComponent(
                    state.symbol
                )}&interval=${encodeURIComponent(
                    state.interval
                )}`
            );

        renderAnalysis(
            data.data
        );

        addRecent(
            state.symbol
        );

    } catch (error) {

        console.error(error);

        toast(
            error.message ||
            "تعذر تحميل التحليل",
            "error"
        );
    }
}


function renderAnalysis(data) {

    if (!data) {
        return;
    }


    const values = {
        analysisPrice:
            price(data.price),

        analysisSignal:
            data.signal || "محايد",

        analysisScore:
            number(data.score, 0),

        analysisRsi:
            number(data.rsi, 1),

        analysisEma20:
            price(data.ema20),

        analysisEma50:
            price(data.ema50),

        analysisEma200:
            price(data.ema200)
    };


    Object.entries(values)
        .forEach(([id, value]) => {

            const element =
                $(id);

            if (element) {
                element.textContent =
                    value;
            }
        });


    const signal =
        $("analysisSignal");

    if (signal) {

        signal.classList.remove(
            "buy",
            "sell",
            "neutral"
        );

        if (
            String(data.signal)
                .includes("شراء")
        ) {
            signal.classList.add(
                "buy"
            );
        } else if (
            String(data.signal)
                .includes("بيع")
        ) {
            signal.classList.add(
                "sell"
            );
        } else {
            signal.classList.add(
                "neutral"
            );
        }
    }


    updateAnalysisChart(
        data
    );
}


async function openCoinAnalysis(
    symbol
) {

    showSection(
        "dashboard"
    );

    await loadAnalysis(
        symbol
    );

    const target =
        $("analysisPanel");

    if (target) {

        target.scrollIntoView({
            behavior: "smooth",
            block: "start"
        });
    }
}


/* ============================================================
   CHART
   ============================================================ */

function updateAnalysisChart(data) {

    const canvas =
        $("analysisChart");

    if (
        !canvas ||
        typeof Chart === "undefined"
    ) {
        return;
    }


    const ctx =
        canvas.getContext("2d");


    if (state.chart) {
        state.chart.destroy();
    }


    const priceValue =
        Number(data.price || 0);

    const ema20 =
        Number(data.ema20 || 0);

    const ema50 =
        Number(data.ema50 || 0);

    const ema200 =
        Number(data.ema200 || 0);


    state.chart =
        new Chart(ctx, {
            type: "line",

            data: {
                labels: [
                    "EMA200",
                    "EMA50",
                    "EMA20",
                    "السعر"
                ],

                datasets: [
                    {
                        label:
                            "السعر والمؤشرات",

                        data: [
                            ema200,
                            ema50,
                            ema20,
                            priceValue
                        ],

                        tension: 0.35,

                        borderWidth: 2,

                        pointRadius: 4
                    }
                ]
            },

            options: {
                responsive: true,

                maintainAspectRatio: false,

                plugins: {
                    legend: {
                        display: true
                    }
                },

                scales: {
                    y: {
                        beginAtZero: false
                    }
                }
            }
        });
}


/* ============================================================
   RECENT
   ============================================================ */

function addRecent(symbol) {

    symbol =
        String(symbol || "")
            .toUpperCase();

    if (!symbol) {
        return;
    }


    state.recent =
        state.recent.filter(
            x => x !== symbol
        );

    state.recent.unshift(
        symbol
    );

    state.recent =
        state.recent.slice(0, 20);


    localStorage.setItem(
        "mudarib_recent",
        JSON.stringify(
            state.recent
        )
    );


    renderRecent();
}


function renderRecent() {

    const container =
        $("recentList");

    if (!container) {
        return;
    }


    if (!state.recent.length) {

        container.innerHTML = `
            <div class="empty-state">
                لا توجد تحليلات سابقة.
            </div>
        `;

        return;
    }


    container.innerHTML =
        state.recent.map(
            symbol => `
                <button
                    class="recent-item"
                    onclick="openCoinAnalysis('${escapeHtml(symbol)}')"
                >
                    <strong>
                        ${escapeHtml(symbol)}
                    </strong>

                    <span>
                        عرض التحليل ←
                    </span>
                </button>
            `
        ).join("");
}


/* ============================================================
   FUTURES
   ============================================================ */

async function runFuturesScan() {

    if (state.futuresBusy) {
        return;
    }

    state.futuresBusy = true;


    const button =
        $("futuresScanBtn");

    setLoading(
        button,
        true,
        "جاري فحص الفيوتشر..."
    );


    const status =
        $("futuresStatus");

    if (status) {
        status.textContent =
            "جاري فحص عقود Binance Futures...";
    }


    try {

        const data =
            await api(
                "/api/futures/scan"
            );

        state.futuresResults =
            Array.isArray(data.data)
                ? data.data
                : [];

        renderFutures();

        if (status) {
            status.textContent =
                `تم العثور على ${state.futuresResults.length} فرصة`;
        }

    } catch (error) {

        console.error(
            "FUTURES:",
            error
        );

        if (status) {
            status.textContent =
                "تعذر تشغيل الفيوتشر";
        }

        toast(
            error.message ||
            "تعذر تحميل صفقات الفيوتشر",
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


    let results =
        [...state.futuresResults];


    const search =
        $("futuresSearch");


    const query =
        search
            ? search.value
                .trim()
                .toUpperCase()
            : "";


    if (query) {

        results =
            results.filter(item =>
                String(item.symbol || "")
                    .includes(query)
            );
    }


    if (
        state.futuresFilter !==
        "all"
    ) {

        results =
            results.filter(item =>
                item.direction ===
                state.futuresFilter
            );
    }


    if (!results.length) {

        grid.innerHTML = `
            <div class="empty-state">
                لا توجد فرص مطابقة حالياً.
                <br>
                اضغط فحص الصفقات لإعادة البحث.
            </div>
        `;

        return;
    }


    grid.innerHTML =
        results.map(
            renderFutureCard
        ).join("");
}


function renderFutureCard(item) {

    const long =
        item.direction === "LONG";


    const directionClass =
        long
            ? "buy"
            : "sell";


    const directionText =
        long
            ? "LONG — شراء"
            : "SHORT — بيع";


    return `
        <article
            class="future-card"
            onclick="openCoinAnalysis('${escapeHtml(item.symbol)}')"
        >

            <div class="future-head">

                <div>
                    <strong>
                        ${escapeHtml(item.symbol)}
                    </strong>

                    <small>
                        15m Futures
                    </small>
                </div>

                <span class="signal ${directionClass}">
                    ${directionText}
                </span>

            </div>


            <div class="future-score">

                <span>
                    قوة الإشارة
                </span>

                <strong>
                    ${number(item.score, 0)}%
                </strong>

            </div>


            <div class="future-levels">

                <div>
                    <small>دخول</small>
                    <b>
                        ${price(item.entry)}
                    </b>
                </div>

                <div>
                    <small>الهدف</small>
                    <b>
                        ${price(item.target)}
                    </b>
                </div>

                <div>
                    <small>وقف</small>
                    <b>
                        ${price(item.stop)}
                    </b>
                </div>

            </div>


            <div class="future-footer">

                <span>
                    RSI ${number(item.rsi, 1)}
                </span>

                <span>
                    رافعة تحليلية ${number(
                        item.leverage,
                        0
                    )}x
                </span>

            </div>

        </article>
    `;
}


function setupFutures() {

    const button =
        $("futuresScanBtn");

    if (button) {
        button.onclick =
            runFuturesScan;
    }


    const search =
        $("futuresSearch");

    if (search) {

        search.addEventListener(
            "input",
            renderFutures
        );
    }


    document
        .querySelectorAll(
            "[data-futures-filter]"
        )
        .forEach(button => {

            button.addEventListener(
                "click",
                () => {

                    document
                        .querySelectorAll(
                            "[data-futures-filter]"
                        )
                        .forEach(x =>
                            x.classList.remove(
                                "active"
                            )
                        );

                    button.classList.add(
                        "active"
                    );

                    state.futuresFilter =
                        button.dataset
                            .futuresFilter;

                    renderFutures();
                }
            );
        });
}


/* ============================================================
   NEWS
   ============================================================ */

async function loadNews() {

    const container =
        $("newsList");

    if (!container) {
        return;
    }


    container.innerHTML = `
        <div class="loading-state">
            جاري تحميل الأخبار...
        </div>
    `;


    try {

        const data =
            await api(
                "/api/news"
            );

        const news =
            Array.isArray(data.data)
                ? data.data
                : [];


        if (!news.length) {

            container.innerHTML = `
                <div class="empty-state">
                    لا توجد أخبار متاحة حالياً.
                </div>
            `;

            return;
        }


        container.innerHTML =
            news.map(
                (item, index) => {

                    const title =
                        item.title ||
                        "خبر العملات الرقمية";

                    const description =
                        item.description ||
                        "";

                    return `
                        <article
                            class="news-card"
                            onclick='openNewsArticle(${JSON.stringify({
                                title,
                                description,
                                source:
                                    item.source ||
                                    "أخبار العملات",
                                published:
                                    item.published ||
                                    ""
                            })})'
                        >

                            <div class="news-source">
                                ${escapeHtml(
                                    item.source ||
                                    "أخبار العملات"
                                )}
                            </div>

                            <h3>
                                ${escapeHtml(title)}
                            </h3>

                            <p>
                                ${escapeHtml(
                                    description
                                )}
                            </p>

                            <div class="news-footer">
                                <span>
                                    ${escapeHtml(
                                        item.published ||
                                        ""
                                    )}
                                </span>

                                <b>
                                    اقرأ الخبر ←
                                </b>
                            </div>

                        </article>
                    `;
                }
            ).join("");


    } catch (error) {

        console.error(
            "NEWS:",
            error
        );

        container.innerHTML = `
            <div class="empty-state error">
                تعذر تحميل الأخبار حالياً.
            </div>
        `;
    }
}


function openNewsArticle(article) {

    let modal =
        $("newsArticleModal");


    if (!modal) {

        modal =
            document.createElement("div");

        modal.id =
            "newsArticleModal";

        modal.className =
            "modal news-modal";

        modal.innerHTML = `
            <div class="modal-card news-article-card">

                <button
                    type="button"
                    class="modal-close"
                    id="closeNewsArticle"
                >
                    ×
                </button>

                <div
                    class="news-article-source"
                    id="newsArticleSource"
                ></div>

                <h2
                    id="newsArticleTitle"
                ></h2>

                <div
                    class="news-article-date"
                    id="newsArticleDate"
                ></div>

                <div
                    class="news-article-content"
                    id="newsArticleContent"
                ></div>

            </div>
        `;

        document.body.appendChild(
            modal
        );


        $("closeNewsArticle").onclick =
            () => {
                modal.classList.remove(
                    "show"
                );
            };


        modal.addEventListener(
            "click",
            event => {

                if (
                    event.target === modal
                ) {
                    modal.classList.remove(
                        "show"
                    );
                }
            }
        );
    }


    $("newsArticleSource").textContent =
        article.source ||
        "أخبار العملات";


    $("newsArticleTitle").textContent =
        article.title ||
        "";


    $("newsArticleDate").textContent =
        article.published ||
        "";


    $("newsArticleContent").textContent =
        article.description ||
        "لا يوجد وصف إضافي لهذا الخبر.";


    modal.classList.add(
        "show"
    );
}


/* ============================================================
   SUBSCRIPTION
   ============================================================ */

async function loadSubscription() {

    if (!state.user) {
        return;
    }


    try {

        const data =
            await api(
                "/api/subscription/my"
            );


        const status =
            $("subscriptionStatus");


        if (!status) {
            return;
        }


        if (
            data.data &&
            data.data.is_premium
        ) {

            const until =
                data.data.premium_until
                    ? new Date(
                        data.data.premium_until
                    ).toLocaleDateString(
                        "ar-SA"
                    )
                    : "-";


            status.innerHTML = `
                <div class="premium-active">
                    <strong>
                        ⭐ اشتراكك فعال
                    </strong>

                    <span>
                        ينتهي في ${until}
                    </span>
                </div>
            `;

        } else {

            status.innerHTML = `
                <div class="premium-inactive">
                    الاشتراك غير مفعل
                </div>
            `;
        }

    } catch (error) {

        console.error(
            "SUBSCRIPTION:",
            error
        );
    }
}


async function loadPlans() {

    try {

        const data =
            await api(
                "/api/subscription/plans"
            );

        const container =
            $("plansContainer");

        if (!container) {
            return;
        }


        const plans =
            data.data || {};


        container.innerHTML =
            Object.entries(plans)
                .map(
                    ([id, plan]) => `
                        <button
                            type="button"
                            class="plan-card"
                            data-plan="${escapeHtml(id)}"
                        >

                            <strong>
                                ${escapeHtml(
                                    plan.name
                                )}
                            </strong>

                            <b>
                                $${number(
                                    plan.amount,
                                    0
                                )}
                            </b>

                            <span>
                                اختيار الباقة
                            </span>

                        </button>
                    `
                ).join("");


        container
            .querySelectorAll(
                "[data-plan]"
            )
            .forEach(button => {

                button.onclick = () => {

                    container
                        .querySelectorAll(
                            "[data-plan]"
                        )
                        .forEach(x =>
                            x.classList.remove(
                                "selected"
                            )
                        );

                    button.classList.add(
                        "selected"
                    );

                    const input =
                        $("selectedPlan");

                    if (input) {
                        input.value =
                            button.dataset.plan;
                    }
                };
            });

    } catch (error) {

        console.error(
            "PLANS:",
            error
        );
    }
}


async function submitSubscription() {

    if (!state.user) {

        location.href =
            "/login";

        return;
    }


    const plan =
        $("selectedPlan")
            ? $("selectedPlan").value
            : "";


    const txid =
        $("paymentTxid")
            ? $("paymentTxid").value.trim()
            : "";


    const method =
        $("paymentMethod")
            ? $("paymentMethod").value
            : "TRC20";


    if (!plan) {

        toast(
            "اختر الباقة أولاً",
            "error"
        );

        return;
    }


    if (!txid) {

        toast(
            "أدخل رقم العملية TXID",
            "error"
        );

        return;
    }


    try {

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
            "تم إرسال طلب الاشتراك",
            "success"
        );


        if ($("paymentTxid")) {
            $("paymentTxid").value = "";
        }


    } catch (error) {

        toast(
            error.message,
            "error"
        );
    }
}


/* ============================================================
   PUBLIC SETTINGS
   ============================================================ */

async function loadPublicSettings() {

    try {

        const data =
            await api(
                "/api/settings/public"
            );


        const address =
            data.data &&
            data.data.trc20_address;


        const addressElements =
            document.querySelectorAll(
                "[data-trc20-address]"
            );


        addressElements.forEach(
            element => {
                element.textContent =
                    address || "-";
            }
        );


        const qr =
            $("trc20Qr");


        if (
            qr &&
            address &&
            typeof QRCode !== "undefined"
        ) {

            qr.innerHTML = "";

            new QRCode(
                qr,
                {
                    text: address,
                    width: 180,
                    height: 180
                }
            );
        }

    } catch (error) {

        console.error(
            "SETTINGS:",
            error
        );
    }
}


/* ============================================================
   DASHBOARD STATS
   ============================================================ */

function updateStats() {

    const total =
        $("totalCoins");

    const buy =
        $("buyCount");

    const sell =
        $("sellCount");

    const neutral =
        $("neutralCount");


    if (total) {
        total.textContent =
            state.results.length;
    }


    if (buy) {

        buy.textContent =
            state.results.filter(
                x =>
                    String(
                        x.signal || ""
                    ).includes("شراء")
            ).length;
    }


    if (sell) {

        sell.textContent =
            state.results.filter(
                x =>
                    String(
                        x.signal || ""
                    ).includes("بيع")
            ).length;
    }


    if (neutral) {

        neutral.textContent =
            state.results.filter(
                x =>
                    x.signal === "محايد"
            ).length;
    }
}


/* ============================================================
   BINANCE STATUS
   ============================================================ */

async function checkBinanceStatus() {

    const element =
        $("binanceStatus");

    if (!element) {
        return;
    }


    try {

        await api(
            "/api/binance/test"
        );

        element.textContent =
            "Binance متصل";

        element.classList.add(
            "online"
        );

    } catch (_) {

        element.textContent =
            "Binance غير متصل";

        element.classList.remove(
            "online"
        );
    }
}


/* ============================================================
   EVENTS
   ============================================================ */

function setupGeneralEvents() {

    const symbolForm =
        $("symbolForm");

    if (symbolForm) {

        symbolForm.addEventListener(
            "submit",
            event => {

                event.preventDefault();

                const input =
                    $("symbolInput");

                if (!input) {
                    return;
                }

                const symbol =
                    input.value
                        .trim()
                        .toUpperCase();

                if (!symbol) {
                    return;
                }

                loadAnalysis(
                    symbol
                );
            }
        );
    }


    const refreshNews =
        $("refreshNewsBtn");

    if (refreshNews) {
        refreshNews.onclick =
            loadNews;
    }


    const subscriptionButton =
        $("submitSubscriptionBtn");

    if (subscriptionButton) {
        subscriptionButton.onclick =
            submitSubscription;
    }


    const themeButton =
        $("themeBtn");

    if (themeButton) {

        themeButton.onclick =
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
            };
    }


    const savedTheme =
        localStorage.getItem(
            "mudarib_theme"
        );

    if (
        savedTheme === "light"
    ) {

        document.body.classList.add(
            "light-theme"
        );
    }
}


/* ============================================================
   BOOT
   ============================================================ */

async function boot() {

    setupNavigation();

    setupAuthButtons();

    setupScanner();

    setupFutures();

    setupGeneralEvents();

    renderRecent();

    await checkAuth();

    await loadPublicSettings();

    await loadPlans();

    await loadSubscription();

    await checkBinanceStatus();

    await runScanner();

    await loadAnalysis(
        state.symbol
    );

    await loadNews();


    // تحديث الماسح كل دقيقة
    setInterval(
        () => {
            runScanner();
        },
        60 * 1000
    );


    // تحديث الأخبار كل 10 دقائق
    setInterval(
        () => {
            loadNews();
        },
        10 * 60 * 1000
    );
}


/* ============================================================
   GLOBAL
   ============================================================ */

window.openCoinAnalysis =
    openCoinAnalysis;

window.openNewsArticle =
    openNewsArticle;

window.runFuturesScan =
    runFuturesScan;

window.runScanner =
    runScanner;


document.addEventListener(
    "DOMContentLoaded",
    boot
);
