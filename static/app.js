const $ = id => document.getElementById(id);

const state = {
    user: null,
    admin: false,

    interval: "15m",
    symbol: "BTCUSDT",

    results: [],
    signals: new Set(),

    sort: "change",
    dir: -1,

    busy: false,

    chart: null,
    plan: null,

    recent: JSON.parse(
        localStorage.getItem("mudarib_recent") || "[]"
    )
};

const signalRank = {
    "شراء قوي": 5,
    "شراء": 4,
    "حيادي": 3,
    "بيع": 2,
    "بيع قوي": 1
};


/* =====================================================
   API
===================================================== */

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

        throw new Error(
            data.message ||
            `HTTP ${response.status}`
        );
    }

    return data;
}


/* =====================================================
   FORMAT
===================================================== */

function fmt(value) {

    if (
        value === null ||
        value === undefined ||
        Number.isNaN(Number(value))
    ) {
        return "—";
    }

    const v = Number(value);

    if (v === 0) return "0";

    if (Math.abs(v) >= 1000) {

        return v.toLocaleString("en-US", {
            maximumFractionDigits: 2
        });

    }

    if (Math.abs(v) >= 1) {

        return v.toLocaleString("en-US", {
            maximumFractionDigits: 4
        });

    }

    return v.toLocaleString("en-US", {
        maximumFractionDigits: 8
    });
}


function pct(value) {

    if (
        value === null ||
        value === undefined ||
        Number.isNaN(Number(value))
    ) {
        return "—";
    }

    const v = Number(value);

    return (
        `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`
    );
}


function money(value) {

    const v = Number(value || 0);

    if (v >= 1e9) {
        return `${(v / 1e9).toFixed(2)}B`;
    }

    if (v >= 1e6) {
        return `${(v / 1e6).toFixed(2)}M`;
    }

    if (v >= 1e3) {
        return `${(v / 1e3).toFixed(1)}K`;
    }

    return fmt(v);
}


function sigClass(signal) {

    if (
        signal === "شراء قوي" ||
        signal === "شراء"
    ) {
        return "buy";
    }

    if (
        signal === "بيع قوي" ||
        signal === "بيع"
    ) {
        return "sell";
    }

    return "neutral";
}


/* =====================================================
   NAVIGATION
===================================================== */

function showSection(id) {

    document
        .querySelectorAll(".section")
        .forEach(section => {

            section.classList.toggle(
                "active",
                section.id === id
            );

        });


    document
        .querySelectorAll(".nav-item")
        .forEach(button => {

            button.classList.toggle(
                "active",
                button.dataset.section === id
            );

        });


    const names = {

        dashboard: "الرئيسية",

        scanner: "ماسح الفرص",

        recent: "الصفقات الحديثة",

        saudi: "السوق السعودي",

        usmarket: "السوق الأمريكي",

        forex: "الفوركس",

        futures: "الفيوتشر",

        news: "الأخبار",

        subscription: "الاشتراك"

    };


    if ($("pageTitle")) {

        $("pageTitle").textContent =
            names[id] || "الرئيسية";

    }


    closeMenu();

    window.scrollTo({
        top: 0,
        behavior: "smooth"
    });


    /*
     * تحميل القسم عند فتحه
     */

    if (id === "saudi") {
        loadSaudi();
    }

    if (id === "usmarket") {
        loadUSMarket();
    }

    if (id === "forex") {
        loadForex();
    }

    if (id === "futures") {
        loadFutures();
    }

    if (id === "recent") {
        renderRecent();
    }

    if (id === "news") {
        loadNews();
    }

    if (
        id === "subscription" &&
        state.user
    ) {
        loadSubscription();
    }

}


document
    .querySelectorAll(".nav-item")
    .forEach(button => {

        button.addEventListener(
            "click",
            event => {

                event.preventDefault();

                showSection(
                    button.dataset.section
                );

            }
        );

    });


/* =====================================================
   MENU
===================================================== */

function closeMenu() {

    document.body.classList.remove(
        "menu-open"
    );

}


if ($("menuBtn")) {

    $("menuBtn").onclick = event => {

        event.stopPropagation();

        document.body.classList.toggle(
            "menu-open"
        );

    };

}


document.addEventListener(
    "click",
    event => {

        if (
            !document.body.classList.contains(
                "menu-open"
            )
        ) {
            return;
        }

        const sidebar = $("sidebar");
        const menu = $("menuBtn");

        if (
            sidebar &&
            !sidebar.contains(event.target) &&
            menu &&
            !menu.contains(event.target)
        ) {

            closeMenu();

        }

    }
);


window.addEventListener(
    "resize",
    () => {

        if (window.innerWidth > 1000) {
            closeMenu();
        }

    }
);


/* =====================================================
   AUTH MODAL
===================================================== */

function openAuth(type = "login") {

    const modal = $("authModal");

    if (!modal) return;

    modal.hidden = false;

    modal.classList.add("show");


    const loginForm =
        $("loginForm");

    const registerForm =
        $("registerForm");


    if (loginForm) {
        loginForm.hidden =
            type !== "login";
    }

    if (registerForm) {
        registerForm.hidden =
            type !== "register";
    }


    const loginTab =
        $("loginTab");

    const registerTab =
        $("registerTab");


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


    clearAuthMessages();

}


function closeAuth() {

    const modal =
        $("authModal");

    if (!modal) return;

    modal.classList.remove("show");

    modal.hidden = true;

}


function clearAuthMessages() {

    const box =
        $("authMsg");

    if (!box) return;

    box.innerHTML = "";

    box.className = "";

}


function showAuthMessage(
    message,
    type = "error"
) {

    const box =
        $("authMsg");

    if (!box) return;

    box.className =
        `auth-message ${type}`;

    box.textContent =
        message;

}


if ($("loginBtn")) {

    $("loginBtn").onclick =
        () => openAuth("login");

}


if ($("registerBtn")) {

    $("registerBtn").onclick =
        () => openAuth("register");

}


if ($("loginTab")) {

    $("loginTab").onclick =
        () => openAuth("login");

}


if ($("registerTab")) {

    $("registerTab").onclick =
        () => openAuth("register");

}


document
    .querySelectorAll(
        '[data-close="authModal"]'
    )
    .forEach(button => {

        button.onclick =
            closeAuth;

    });


/* =====================================================
   AUTH CHECK
===================================================== */

async function checkAuth() {

    try {

        const data =
            await api(
                "/api/auth/me"
            );

        state.user =
            data.user || null;

    } catch (_) {

        state.user = null;

    }


    updateAuth();


    try {

        const admin =
            await api(
                "/api/admin/me"
            );

        state.admin =
            !!admin.admin;

    } catch (_) {

        state.admin = false;

    }


    if ($("adminLink")) {

        $("adminLink").hidden =
            !state.admin;

    }

}


function updateAuth() {

    const logged =
        !!state.user;


    if ($("userBadge")) {

        $("userBadge").textContent =
            logged
                ? (
                    state.user.name ||
                    state.user.email ||
                    state.user.username ||
                    "مستخدم"
                )
                : "زائر";

    }


    if ($("loginBtn")) {
        $("loginBtn").hidden =
            logged;
    }


    if ($("registerBtn")) {
        $("registerBtn").hidden =
            logged;
    }


    if ($("logoutBtn")) {
        $("logoutBtn").hidden =
            !logged;
    }


    if ($("subscriptionNav")) {
        $("subscriptionNav").hidden =
            !logged;
    }


    if ($("subscription")) {
        $("subscription").hidden =
            !logged;
    }


    if (logged) {
        loadSubscription();
    }

}


/* =====================================================
   LOGIN
===================================================== */

if ($("loginForm")) {

    $("loginForm").addEventListener(
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


            if (!email || !password) {

                showAuthMessage(
                    "اكتب البريد الإلكتروني وكلمة المرور."
                );

                return;

            }


            const button =
                $("loginForm")
                    .querySelector(
                        'button[type="submit"], button'
                    );


            if (button) {

                button.disabled = true;

                button.textContent =
                    "جاري تسجيل الدخول...";

            }


            try {

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


                if (!data.user) {

                    throw new Error(
                        "تم الدخول لكن لم يتم استلام بيانات المستخدم."
                    );

                }


                state.user =
                    data.user;


                updateAuth();


                closeAuth();


                if ($("systemStatus")) {

                    $("systemStatus")
                        .textContent =
                        "تم تسجيل الدخول ✅";

                }

            } catch (error) {

                showAuthMessage(
                    error.message ||
                    "فشل تسجيل الدخول."
                );

            } finally {

                if (button) {

                    button.disabled = false;

                    button.textContent =
                        "دخول";

                }

            }

        }
    );

}


/* =====================================================
   REGISTER
===================================================== */

if ($("registerForm")) {

    $("registerForm").addEventListener(
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


            if (!name || !email || !password) {

                showAuthMessage(
                    "عبّ جميع البيانات المطلوبة."
                );

                return;

            }


            if (password.length < 6) {

                showAuthMessage(
                    "كلمة المرور لازم تكون 6 أحرف على الأقل."
                );

                return;

            }


            const button =
                $("registerForm")
                    .querySelector(
                        'button[type="submit"], button'
                    );


            if (button) {

                button.disabled = true;

                button.textContent =
                    "جاري إنشاء الحساب...";

            }


            try {

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


                if (!data.user) {

                    throw new Error(
                        "تم إنشاء الحساب لكن لم يتم تسجيل الدخول."
                    );

                }


                state.user =
                    data.user;


                updateAuth();


                closeAuth();


                if ($("systemStatus")) {

                    $("systemStatus")
                        .textContent =
                        "تم إنشاء الحساب ✅";

                }

            } catch (error) {

                showAuthMessage(
                    error.message ||
                    "فشل إنشاء الحساب."
                );

            } finally {

                if (button) {

                    button.disabled = false;

                    button.textContent =
                        "إنشاء الحساب";

                }

            }

        }
    );

}


/* =====================================================
   LOGOUT
===================================================== */

if ($("logoutBtn")) {

    $("logoutBtn").onclick =
        async () => {

            try {

                await api(
                    "/api/auth/logout",
                    {
                        method: "POST"
                    }
                );

            } catch (_) {}


            state.user = null;

            state.admin = false;


            updateAuth();


            if ($("adminLink")) {
                $("adminLink").hidden = true;
            }


            showSection(
                "dashboard"
            );

        };

}


/* =====================================================
   DASHBOARD INTERVALS
===================================================== */

document
    .querySelectorAll(
        "#dashIntervals button"
    )
    .forEach(button => {

        button.onclick = () => {

            document
                .querySelectorAll(
                    "#dashIntervals button"
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


            loadAnalysis();

        };

    });


/* =====================================================
   SCANNER INTERVALS
===================================================== */

document
    .querySelectorAll(
        "#intervalChips button"
    )
    .forEach(button => {

        button.onclick = () => {

            document
                .querySelectorAll(
                    "#intervalChips button"
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

        };

    });


/* =====================================================
   SIGNAL FILTER
===================================================== */

document
    .querySelectorAll(
        ".signal-chips button"
    )
    .forEach(button => {

        button.onclick = () => {

            button.classList.toggle(
                "active"
            );


            const signal =
                button.dataset.signal;


            if (
                state.signals.has(signal)
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

        };

    });


/* =====================================================
   SORT
===================================================== */

if ($("sortField")) {

    $("sortField").onchange =
        event => {

            state.sort =
                event.target.value;

            renderScanner();

        };

}


if ($("sortDir")) {

    $("sortDir").onclick =
        () => {

            state.dir *= -1;


            $("sortDir")
                .textContent =
                state.dir === -1
                    ? "↓ تنازلي"
                    : "↑ تصاعدي";


            renderScanner();

        };

}


if ($("scannerSearch")) {

    $("scannerSearch").oninput =
        renderScanner;

}


if ($("scanBtn")) {

    $("scanBtn").onclick =
        runScanner;

}


/* =====================================================
   FILTERED SCANNER
===================================================== */

function filtered() {

    let rows =
        [...state.results];


    const search =
        $("scannerSearch")
            ? $("scannerSearch")
                .value
                .trim()
                .toUpperCase()
            : "";


    if (search) {

        rows =
            rows.filter(
                item =>
                    String(
                        item.symbol || ""
                    )
                    .toUpperCase()
                    .includes(search)
            );

    }


    if (state.signals.size) {

        rows =
            rows.filter(
                item =>
                    state.signals.has(
                        item.signal
                    )
            );

    }


    const field =
        state.sort;


    rows.sort((a, b) => {

        let av;
        let bv;


        if (field === "signal") {

            av =
                signalRank[
                    a.signal
                ] || 0;

            bv =
                signalRank[
                    b.signal
                ] || 0;

        } else if (
            field === "symbol"
        ) {

            av =
                String(
                    a.symbol || ""
                );

            bv =
                String(
                    b.symbol || ""
                );


            return (
                av.localeCompare(bv) *
                state.dir
            );

        } else {

            av =
                Number(
                    a[field] || 0
                );

            bv =
                Number(
                    b[field] || 0
                );

        }


        return (
            av - bv
        ) * state.dir;

    });


    return rows;

}


/* =====================================================
   RENDER SCANNER
===================================================== */

function renderScanner() {

    if (!$("scannerBody")) return;


    const rows =
        filtered();


    if (!rows.length) {

        $("scannerBody").innerHTML =
            `
            <tr>
                <td
                    colspan="7"
                    class="empty"
                >
                    لا توجد نتائج مطابقة
                </td>
            </tr>
            `;

        return;

    }


    $("scannerBody").innerHTML =
        rows.map(item => {

            const symbol =
                String(
                    item.symbol || ""
                );


            return `
                <tr
                    onclick="selectSymbol('${escapeAttr(symbol)}')"
                >

                    <td>
                        <b>
                            ${symbol.replace(
                                "USDT",
                                ""
                            )}
                        </b>

                        <small>
                            USDT
                        </small>
                    </td>

                    <td>
                        ${fmt(item.price)}
                    </td>

                    <td class="${
                        Number(item.change || 0) >= 0
                            ? "up"
                            : "down"
                    }">
                        ${pct(item.change)}
                    </td>

                    <td>
                        <span
                            class="signal ${sigClass(item.signal)}"
                        >
                            ${item.signal || "حيادي"}
                        </span>
                    </td>

                    <td>
                        ${fmt(
                            item.score10 ??
                            (
                                Number(
                                    item.score || 0
                                ) / 10
                            )
                        )}
                    </td>

                    <td>
                        ${money(item.volume)}
                    </td>

                    <td>
                        ${
                            item.interval ||
                            state.interval
                        }
                    </td>

                </tr>
            `;

        }).join("");

}


/* =====================================================
   ESCAPE
===================================================== */

function escapeAttr(value) {

    return String(value)
        .replace(/\\/g, "\\\\")
        .replace(/'/g, "\\'");

}


/* =====================================================
   SCANNER
===================================================== */

async function runScanner() {

    if (state.busy) return;


    state.busy = true;


    if ($("scannerStatus")) {

        $("scannerStatus")
            .textContent =
            "جاري فحص السوق...";

    }


    try {

        const data =
            await api(
                `/api/spot/scan?interval=${encodeURIComponent(
                    state.interval
                )}&limit=40`
            );


        state.results =
            Array.isArray(
                data.results
            )
                ? data.results
                : [];


        if ($("scannerStatus")) {

            $("scannerStatus")
                .textContent =
                `تم العثور على ${state.results.length} فرصة` +
                (
                    data.cached
                        ? " — نتيجة محفوظة مؤقتًا"
                        : ""
                );

        }


        renderScanner();

        captureRecent();


    } catch (error) {

        /*
         * توافق مع المسار القديم
         */

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

            captureRecent();


            if ($("scannerStatus")) {

                $("scannerStatus")
                    .textContent =
                    `تم العثور على ${state.results.length} فرصة`;

            }

        } catch (secondError) {

            if ($("scannerStatus")) {

                $("scannerStatus")
                    .textContent =
                    `تعذر الفحص: ${secondError.message}`;

            }

        }

    } finally {

        state.busy = false;

    }

}


/* =====================================================
   RECENT
===================================================== */

function captureRecent() {

    const now =
        Date.now();


    const bucket =
        Math.floor(
            now / 300000
        );


    const oldKeys =
        new Set(
            state.recent.map(
                x => x.key
            )
        );


    state.results
        .filter(
            x =>
                x.signal === "شراء" ||
                x.signal === "شراء قوي"
        )
        .slice(0, 15)
        .forEach(item => {

            const key =
                `${item.symbol}|${item.interval}|${item.signal}|${bucket}`;


            if (
                oldKeys.has(key)
            ) {
                return;
            }


            state.recent.unshift({

                ...item,

                key,

                time: now

            });

        });


    state.recent =
        state.recent.slice(
            0,
            60
        );


    localStorage.setItem(
        "mudarib_recent",
        JSON.stringify(
            state.recent
        )
    );


    renderRecent();

}


function renderRecent() {

    if (!$("recentList")) return;


    if (!state.recent.length) {

        $("recentList").innerHTML =
            `
            <div class="empty-card">
                ما فيه صفقات سبوت حديثة حتى الآن.
                شغّل الماسح.
            </div>
            `;

        return;

    }


    $("recentList").innerHTML =
        state.recent
            .slice(0, 30)
            .map(item => {

                return `
                    <div
                        class="recent-card"
                        onclick="selectSymbol('${escapeAttr(item.symbol)}')"
                    >

                        <div>
                            <b>
                                ${item.symbol}
                            </b>

                            <small>
                                ${new Date(
                                    item.time
                                ).toLocaleString(
                                    "ar-SA"
                                )}
                            </small>
                        </div>

                        <span
                            class="signal ${sigClass(item.signal)}"
                        >
                            ${item.signal}
                        </span>

                        <div>
                            <small>
                                السعر
                            </small>

                            <b>
                                ${fmt(item.price)}
                            </b>
                        </div>

                        <div class="${
                            Number(item.change || 0) >= 0
                                ? "up"
                                : "down"
                        }">
                            ${pct(item.change)}
                        </div>

                        <div>
                            <small>
                                TP1 / وقف
                            </small>

                            <b>
                                ${fmt(item.tp1)}
                                /
                                ${fmt(item.sl)}
                            </b>
                        </div>

                    </div>
                `;

            })
            .join("");

}


if ($("clearRecent")) {

    $("clearRecent").onclick =
        () => {

            state.recent = [];


            localStorage.removeItem(
                "mudarib_recent"
            );


            renderRecent();

        };

}


/* =====================================================
   GENERIC MARKET TABLE
===================================================== */

function renderMarketTable(
    bodyId,
    rows,
    symbolLabel = ""
) {

    const body =
        $(bodyId);


    if (!body) return;


    if (!Array.isArray(rows) || !rows.length) {

        body.innerHTML =
            `
            <tr>
                <td
                    colspan="8"
                    class="empty"
                >
                    لا توجد فرص حاليًا.
                </td>
            </tr>
            `;

        return;

    }


    body.innerHTML =
        rows
            .slice(0, 100)
            .map(item => {

                const signal =
                    item.signal ||
                    "حيادي";


                return `
                    <tr>

                        <td>
                            <b>
                                ${
                                    item.symbol ||
                                    symbolLabel ||
                                    "—"
                                }
                            </b>
                        </td>

                        <td>
                            ${fmt(item.price)}
                        </td>

                        <td>
                            <span
                                class="signal ${sigClass(signal)}"
                            >
                                ${signal}
                            </span>
                        </td>

                        <td>
                            ${fmt(
                                item.score
                            )}/100
                        </td>

                        <td>
                            ${
                                item.rsi != null
                                    ? Number(
                                        item.rsi
                                    ).toFixed(1)
                                    : "—"
                            }
                        </td>

                        <td>
                            ${fmt(item.entry)}
                        </td>

                        <td>
                            ${fmt(
                                item.tp1 ||
                                item.target ||
                                item.tp
                            )}
                        </td>

                        <td>
                            ${fmt(item.sl)}
                        </td>

                    </tr>
                `;

            })
            .join("");

}


/* =====================================================
   SAUDI MARKET
===================================================== */

async function loadSaudi() {

    const body =
        $("saudiBody");


    if (!body) return;


    if ($("saudiStatus")) {

        $("saudiStatus")
            .textContent =
            "جاري تحميل السوق السعودي...";

    }


    body.innerHTML =
        `
        <tr>
            <td colspan="8" class="empty">
                جاري تحميل الأسهم السعودية...
            </td>
        </tr>
        `;


    try {

        const data =
            await api(
                "/api/saudi/scan?interval=1d&limit=100"
            );


        const rows =
            data.results ||
            data.signals ||
            [];


        renderMarketTable(
            "saudiBody",
            rows
        );


        if ($("saudiStatus")) {

            $("saudiStatus")
                .textContent =
                `تم تحميل ${rows.length} سهم سعودي`;

        }


    } catch (error) {

        body.innerHTML =
            `
            <tr>
                <td
                    colspan="8"
                    class="empty"
                >
                    تعذر تحميل السوق السعودي:
                    ${error.message}
                </td>
            </tr>
            `;


        if ($("saudiStatus")) {

            $("saudiStatus")
                .textContent =
                `خطأ: ${error.message}`;

        }

    }

}


if ($("refreshSaudi")) {

    $("refreshSaudi").onclick =
        loadSaudi;

}


/* =====================================================
   US MARKET
===================================================== */

async function loadUSMarket() {

    const body =
        $("usMarketBody");


    if (!body) return;


    if ($("usStatus")) {

        $("usStatus")
            .textContent =
            "جاري تحميل السوق الأمريكي...";

    }


    body.innerHTML =
        `
        <tr>
            <td colspan="8" class="empty">
                جاري تحميل الأسهم الأمريكية...
            </td>
        </tr>
        `;


    try {

        let data;


        try {

            data =
                await api(
                    "/api/usmarket/scan?limit=100"
                );

        } catch (_) {

            data =
                await api(
                    "/api/usmarket/signals?limit=100"
                );

        }


        const rows =
            data.results ||
            data.signals ||
            [];


        renderMarketTable(
            "usMarketBody",
            rows
        );


        if ($("usStatus")) {

            $("usStatus")
                .textContent =
                `تم تحميل ${rows.length} سهم أمريكي`;

        }


    } catch (error) {

        body.innerHTML =
            `
            <tr>
                <td
                    colspan="8"
                    class="empty"
                >
                    تعذر تحميل السوق الأمريكي:
                    ${error.message}
                </td>
            </tr>
            `;


        if ($("usStatus")) {

            $("usStatus")
                .textContent =
                `خطأ: ${error.message}`;

        }

    }

}


if ($("refreshUSMarket")) {

    $("refreshUSMarket").onclick =
        loadUSMarket;

}


/* =====================================================
   FOREX
===================================================== */

async function loadForex() {

    const body =
        $("forexBody");


    if (!body) return;


    if ($("forexStatus")) {

        $("forexStatus")
            .textContent =
            "جاري تحميل الفوركس...";

    }


    body.innerHTML =
        `
        <tr>
            <td colspan="8" class="empty">
                جاري تحميل أزواج الفوركس...
            </td>
        </tr>
        `;


    try {

        const data =
            await api(
                "/api/forex/scan?interval=1h&limit=100"
            );


        const rows =
            data.results ||
            data.signals ||
            [];


        renderMarketTable(
            "forexBody",
            rows
        );


        if ($("forexStatus")) {

            $("forexStatus")
                .textContent =
                `تم تحميل ${rows.length} زوج فوركس`;

        }


    } catch (error) {

        body.innerHTML =
            `
            <tr>
                <td
                    colspan="8"
                    class="empty"
                >
                    تعذر تحميل الفوركس:
                    ${error.message}
                </td>
            </tr>
            `;


        if ($("forexStatus")) {

            $("forexStatus")
                .textContent =
                `خطأ: ${error.message}`;

        }

    }

}


if ($("refreshForex")) {

    $("refreshForex").onclick =
        loadForex;

}


/* =====================================================
   FUTURES
===================================================== */

async function loadFutures() {

    const body =
        $("futuresBody");


    if (!body) return;


    if ($("futuresStatus")) {

        $("futuresStatus")
            .textContent =
            "جاري تحميل الفيوتشر...";

    }


    body.innerHTML =
        `
        <tr>
            <td colspan="8" class="empty">
                جاري تحميل عقود الفيوتشر...
            </td>
        </tr>
        `;


    try {

        const data =
            await api(
                "/api/futures/scan?interval=15m&limit=50"
            );


        const rows =
            data.results ||
            data.signals ||
            [];


        renderMarketTable(
            "futuresBody",
            rows
        );


        if ($("futuresStatus")) {

            $("futuresStatus")
                .textContent =
                `تم تحميل ${rows.length} عقد فيوتشر`;

        }


    } catch (error) {

        body.innerHTML =
            `
            <tr>
                <td
                    colspan="8"
                    class="empty"
                >
                    تعذر تحميل الفيوتشر:
                    ${error.message}
                </td>
            </tr>
            `;


        if ($("futuresStatus")) {

            $("futuresStatus")
                .textContent =
                `خطأ: ${error.message}`;

        }

    }

}


if ($("refreshFutures")) {

    $("refreshFutures").onclick =
        loadFutures;

}


/* =====================================================
   DASHBOARD ANALYSIS
===================================================== */

async function loadAnalysis() {

    const symbol =
        state.symbol;


    try {

        let data;


        try {

            data =
                await api(
                    `/api/spot/analysis?symbol=${encodeURIComponent(
                        symbol
                    )}&interval=${encodeURIComponent(
                        state.interval
                    )}`
                );

        } catch (_) {

            data =
                await api(
                    `/api/binance/analysis?symbol=${encodeURIComponent(
                        symbol
                    )}&interval=${encodeURIComponent(
                        state.interval
                    )}`
                );

        }


        const analysis =
            data.analysis ||
            data;


        if ($("dashSymbol")) {

            $("dashSymbol")
                .textContent =
                symbol;

        }


        if ($("dashPrice")) {

            $("dashPrice")
                .textContent =
                fmt(analysis.price);

        }


        if ($("dashChange")) {

            $("dashChange")
                .textContent =
                analysis.change != null
                    ? pct(analysis.change)
                    : "—";

        }


        if ($("dashSignal")) {

            $("dashSignal")
                .textContent =
                analysis.signal ||
                "حيادي";

            $("dashSignal")
                .className =
                `signal-text ${sigClass(
                    analysis.signal
                )}`;

        }


        if ($("bigSignal")) {

            $("bigSignal")
                .textContent =
                analysis.signal ||
                "حيادي";

            $("bigSignal")
                .className =
                `signal-big ${sigClass(
                    analysis.signal
                )}`;

        }


        if ($("scoreText")) {

            $("scoreText")
                .textContent =
                `${fmt(
                    analysis.score
                )}/100`;

        }


        if ($("scoreBar")) {

            $("scoreBar")
                .style.width =
                `${Math.max(
                    0,
                    Math.min(
                        100,
                        Number(
                            analysis.score || 0
                        )
                    )
                )}%`;

        }


        if ($("entry")) {
            $("entry").textContent =
                fmt(analysis.entry);
        }


        if ($("tp1")) {
            $("tp1").textContent =
                fmt(analysis.tp1);
        }


        if ($("tp2")) {
            $("tp2").textContent =
                fmt(analysis.tp2);
        }


        if ($("tp3")) {
            $("tp3").textContent =
                fmt(analysis.tp3);
        }


        if ($("sl")) {
            $("sl").textContent =
                fmt(analysis.sl);
        }


        if ($("rsi")) {

            $("rsi").textContent =
                analysis.rsi != null
                    ? Number(
                        analysis.rsi
                    ).toFixed(1)
                    : "—";

        }


        if ($("ema20")) {
            $("ema20").textContent =
                fmt(analysis.ema20);
        }


        if ($("ema50")) {
            $("ema50").textContent =
                fmt(analysis.ema50);
        }


        if ($("ema200")) {
            $("ema200").textContent =
                fmt(analysis.ema200);
        }


        if ($("analysisMeta")) {

            $("analysisMeta")
                .textContent =
                `${symbol} · ${state.interval}`;

        }


        if ($("reasons")) {

            $("reasons").innerHTML =
                (analysis.reasons || [])
                    .map(
                        reason =>
                            `<li>${reason}</li>`
                    )
                    .join("");

        }


        drawChart(
            analysis.candles || []
        );


    } catch (error) {

        if ($("bigSignal")) {

            $("bigSignal")
                .textContent =
                error.message;

        }

    }

}


/* =====================================================
   SYMBOL
===================================================== */

window.selectSymbol =
    symbol => {

        if (!symbol) return;


        state.symbol =
            symbol;


        showSection(
            "dashboard"
        );


        loadAnalysis();

    };


/* =====================================================
   CHART
===================================================== */

function drawChart(candles) {

    if (
        !$("priceChart") ||
        !window.Chart
    ) {
        return;
    }


    if (!Array.isArray(candles)) {
        return;
    }


    if (!candles.length) {
        return;
    }


    if (state.chart) {

        try {
            state.chart.destroy();
        } catch (_) {}

    }


    const labels =
        candles.map(
            candle =>
                new Date(
                    candle.t
                ).toLocaleTimeString(
                    "ar-SA",
                    {
                        hour: "2-digit",
                        minute: "2-digit"
                    }
                )
        );


    const prices =
        candles.map(
            candle =>
                Number(
                    candle.c
                )
        );


    state.chart =
        new Chart(
            $("priceChart"),
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

                            borderWidth: 2,

                            pointRadius: 0,

                            tension: 0.2

                        }

                    ]

                },

                options: {

                    responsive: true,

                    maintainAspectRatio:
                        false,

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

                            grid: {

                                color:
                                    "rgba(127,127,127,.15)"

                            }

                        }

                    }

                }

            }
        );

}


/* =====================================================
   NEWS
===================================================== */

async function loadNews() {

    if (!$("newsList")) return;


    $("newsList").innerHTML =
        `
        <div class="empty-card">
            جاري تحميل الأخبار...
        </div>
        `;


    try {

        const data =
            await api(
                "/api/news"
            );


        const news =
            data.news || [];


        if (!news.length) {

            $("newsList").innerHTML =
                `
                <div class="empty-card">
                    لا توجد أخبار متاحة حاليًا.
                </div>
                `;

            return;

        }


        $("newsList").innerHTML =
            news.map(item => `

                <a
                    class="news-card"
                    href="${item.link || "#"}"
                    target="_blank"
                    rel="noopener noreferrer"
                >

                    <small>
                        ${item.source || ""}
                        ·
                        ${item.published || ""}
                    </small>

                    <h3>
                        ${item.title || ""}
                    </h3>

                    <p>
                        ${item.description || ""}
                    </p>

                </a>

            `).join("");


    } catch (error) {

        $("newsList").innerHTML =
            `
            <div class="empty-card">
                ${error.message}
            </div>
            `;

    }

}


if ($("newsBtn")) {

    $("newsBtn").onclick =
        loadNews;

}


/* =====================================================
   SUBSCRIPTION
===================================================== */

async function loadSubscription() {

    if (!state.user) return;


    try {

        const plans =
            await api(
                "/api/subscription/plans"
            );


        renderPlans(
            plans
        );


        const subscription =
            await api(
                "/api/subscription/my"
            );


        if ($("subscriptionStatus")) {

            $("subscriptionStatus")
                .innerHTML =
                subscription.active

                    ? `
                        <div class="active-plan">
                            ✅ اشتراكك فعال
                            —
                            ${subscription.plan}
                            —
                            ينتهي
                            ${new Date(
                                subscription.expires
                            ).toLocaleDateString(
                                "ar-SA"
                            )}
                        </div>
                    `

                    : `
                        <div class="inactive-plan">
                            لا يوجد اشتراك فعال حاليًا.
                        </div>
                    `;

        }


        renderPaymentHistory(
            subscription.requests ||
            []
        );


    } catch (error) {

        if ($("subscriptionStatus")) {

            $("subscriptionStatus")
                .innerHTML =
                `
                <div class="error">
                    ${error.message}
                </div>
                `;

        }

    }

}


function renderPlans(data) {

    if (!$("plans")) return;


    const plans =
        data.plans || {};


    if ($("payAddress")) {

        $("payAddress").value =
            data.address || "";

    }


    $("plans").innerHTML =
        Object.entries(plans)
            .map(
                ([key, plan]) => `

                    <button
                        class="plan-card"
                        data-plan="${key}"
                    >

                        <b>
                            ${plan.name}
                        </b>

                        <strong>
                            ${plan.amount} USDT
                        </strong>

                        <small>
                            دفع عبر TRC20
                        </small>

                    </button>

                `
            )
            .join("");


    document
        .querySelectorAll(
            ".plan-card"
        )
        .forEach(button => {

            button.onclick =
                () =>
                    choosePlan(
                        button.dataset.plan,
                        plans[
                            button.dataset.plan
                        ]
                    );

        });

}


function choosePlan(
    key,
    plan
) {

    state.plan =
        key;


    if ($("paymentBox")) {
        $("paymentBox").hidden =
            false;
    }


    if ($("chosenPlan")) {

        $("chosenPlan")
            .innerHTML =
            `
            الباقة المختارة:
            <b>${plan.name}</b>
            —
            <b>${plan.amount} USDT</b>
            `;

    }


    if ($("qrBox")) {

        $("qrBox").innerHTML =
            "";

    }


    if (
        window.QRCode &&
        $("payAddress") &&
        $("qrBox")
    ) {

        QRCode.toCanvas(
            $("qrBox"),
            $("payAddress").value,
            {
                width: 190
            },
            () => {}
        );

    }


    if ($("paymentBox")) {

        $("paymentBox")
            .scrollIntoView({
                behavior: "smooth"
            });

    }

}


if ($("copyAddress")) {

    $("copyAddress").onclick =
        async () => {

            try {

                await navigator.clipboard.writeText(
                    $("payAddress").value
                );


                $("copyAddress")
                    .textContent =
                    "تم النسخ ✓";


                setTimeout(
                    () => {

                        if ($("copyAddress")) {

                            $("copyAddress")
                                .textContent =
                                "نسخ";

                        }

                    },
                    1500
                );


            } catch (_) {

                $("payAddress")
                    .select();

                document.execCommand(
                    "copy"
                );

            }

        };

}


if ($("sendPayment")) {

    $("sendPayment").onclick =
        async () => {

            if (!state.plan) {

                $("paymentMsg").innerHTML =
                    `
                    <span class="error">
                        اختر الباقة أولًا.
                    </span>
                    `;

                return;

            }


            const txid =
                $("txid")
                    .value
                    .trim();


            if (!txid) {

                $("paymentMsg").innerHTML =
                    `
                    <span class="error">
                        أدخل TXID بعد التحويل.
                    </span>
                    `;

                return;

            }


            try {

                const data =
                    await api(
                        "/api/subscription/request",
                        {

                            method:
                                "POST",

                            body:
                                JSON.stringify({
                                    plan:
                                        state.plan,

                                    txid:
                                        txid
                                })

                        }
                    );


                $("paymentMsg").innerHTML =
                    `
                    <span class="ok">
                        ${
                            data.message ||
                            "تم إرسال الطلب"
                        } ✅
                    </span>
                    `;


                $("txid").value =
                    "";


                loadSubscription();


            } catch (error) {

                $("paymentMsg").innerHTML =
                    `
                    <span class="error">
                        ${error.message}
                    </span>
                    `;

            }

        };

}


function renderPaymentHistory(
    rows
) {

    if (!$("paymentHistory")) {
        return;
    }


    if (!rows.length) {

        $("paymentHistory").innerHTML =
            "";

        return;

    }


    $("paymentHistory").innerHTML =
        `
        <h3>
            طلبات الدفع
        </h3>

        <div class="payment-history">

            ${rows.map(item => `

                <div>

                    <b>
                        ${item.plan}
                    </b>

                    <span>
                        ${item.amount} USDT
                    </span>

                    <span
                        class="status-${item.status}"
                    >
                        ${
                            item.status === "pending"
                                ? "قيد المراجعة"
                                : item.status === "approved"
                                    ? "مقبول"
                                    : "مرفوض"
                        }
                    </span>

                </div>

            `).join("")}

        </div>
        `;

}


/* =====================================================
   THEME
===================================================== */

if ($("themeBtn")) {

    $("themeBtn").onclick =
        () => {

            document.body
                .classList
                .toggle("light");


            localStorage.setItem(
                "theme",
                document.body
                    .classList
                    .contains("light")
                    ? "light"
                    : "dark"
            );

        };

}


if (
    localStorage.getItem(
        "theme"
    ) === "light"
) {

    document.body
        .classList
        .add("light");

}


/* =====================================================
   BOOT
===================================================== */

async function boot() {

    try {

        await checkAuth();


        if ($("systemStatus")) {

            $("systemStatus")
                .textContent =
                state.user
                    ? "متصل — مسجل دخول ✅"
                    : "متصل";

        }


        /*
         * الكريبتو
         */

        await runScanner();


        await loadAnalysis();


        /*
         * الأخبار
         */

        await loadNews();


        /*
         * لا نحمل الأسواق الأربعة
         * من البداية حتى ما نضغط Yahoo/OKX.
         *
         * يتم تحميلها عند فتح القسم.
         */


    } catch (error) {

        console.error(
            "BOOT ERROR:",
            error
        );

    }


    /*
     * تحديث الماسح
     */

    setInterval(
        runScanner,
        60000
    );


    /*
     * الأخبار
     */

    setInterval(
        loadNews,
        600000
    );

}


/* =====================================================
   START
===================================================== */

boot();
