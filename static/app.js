/* =========================================================
   موقع تداول - Frontend
========================================================= */

"use strict";

const $ = (selector, parent = document) => {
    return parent.querySelector(selector);
};

const $$ = (selector, parent = document) => {
    return [...parent.querySelectorAll(selector)];
};

/* =========================================================
   HELPERS
========================================================= */

function showToast(message, type = "") {
    let toast = $(".toast");

    if (!toast) {
        toast = document.createElement("div");
        toast.className = "toast";
        document.body.appendChild(toast);
    }

    toast.textContent = message;
    toast.className = "toast show " + type;

    clearTimeout(window.__toastTimer);

    window.__toastTimer = setTimeout(() => {
        toast.classList.remove("show");
    }, 3000);
}

async function api(url, options = {}) {
    const config = {
        credentials: "same-origin",
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {})
        },
        ...options
    };

    try {
        const response = await fetch(url, config);

        const contentType = response.headers.get("content-type") || "";

        let data;

        if (contentType.includes("application/json")) {
            data = await response.json();
        } else {
            const text = await response.text();

            data = {
                ok: response.ok,
                message: text
            };
        }

        if (!response.ok) {
            throw new Error(
                data.message ||
                data.error ||
                "حدث خطأ في الطلب"
            );
        }

        return data;

    } catch (error) {
        console.error(error);
        throw error;
    }
}

function formatNumber(value, decimals = 4) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "--";
    }

    return number.toLocaleString("en-US", {
        minimumFractionDigits: 0,
        maximumFractionDigits: decimals
    });
}

function formatPercent(value) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "--";
    }

    return `${number >= 0 ? "+" : ""}${number.toFixed(2)}%`;
}

/* =========================================================
   MOBILE MENU
========================================================= */

function initMobileMenu() {
    const menuButton = $(".mobile-menu");
    const nav = $(".nav");

    if (!menuButton || !nav) {
        return;
    }

    menuButton.addEventListener("click", () => {
        nav.classList.toggle("open");
    });

    $$(".nav a, .nav button", nav).forEach(item => {
        item.addEventListener("click", () => {
            nav.classList.remove("open");
        });
    });
}

/* =========================================================
   LOGIN
========================================================= */

function initLogin() {
    const form = $("#loginForm");

    if (!form) {
        return;
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();

        const username =
            ($("#username", form)?.value || "").trim();

        const password =
            ($("#password", form)?.value || "");

        if (!username || !password) {
            showToast("اكتب اسم المستخدم وكلمة المرور", "error");
            return;
        }

        const button = $("button[type='submit']", form);

        if (button) {
            button.disabled = true;
            button.textContent = "جاري الدخول...";
        }

        try {
            const data = await api("/api/login", {
                method: "POST",
                body: JSON.stringify({
                    username,
                    password
                })
            });

            showToast(
                data.message || "تم تسجيل الدخول",
                "success"
            );

            setTimeout(() => {
                window.location.href = data.redirect || "/";
            }, 500);

        } catch (error) {
            showToast(
                error.message || "بيانات الدخول غير صحيحة",
                "error"
            );
        } finally {
            if (button) {
                button.disabled = false;
                button.textContent = "دخول";
            }
        }
    });
}

/* =========================================================
   REGISTER
========================================================= */

function initRegister() {
    const form = $("#registerForm");

    if (!form) {
        return;
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();

        const username =
            ($("#username", form)?.value || "").trim();

        const email =
            ($("#email", form)?.value || "").trim();

        const password =
            ($("#password", form)?.value || "");

        const confirmPassword =
            ($("#confirm_password", form)?.value ||
             $("#confirmPassword", form)?.value ||
             "");

        if (!username || !password) {
            showToast(
                "اكتب اسم المستخدم وكلمة المرور",
                "error"
            );
            return;
        }

        if (confirmPassword && password !== confirmPassword) {
            showToast(
                "كلمتا المرور غير متطابقتين",
                "error"
            );
            return;
        }

        const button = $("button[type='submit']", form);

        if (button) {
            button.disabled = true;
            button.textContent = "جاري إنشاء الحساب...";
        }

        try {
            const payload = {
                username,
                password
            };

            if (email) {
                payload.email = email;
            }

            const data = await api("/api/register", {
                method: "POST",
                body: JSON.stringify(payload)
            });

            showToast(
                data.message || "تم إنشاء الحساب",
                "success"
            );

            setTimeout(() => {
                window.location.href =
                    data.redirect || "/login";
            }, 700);

        } catch (error) {
            showToast(
                error.message || "تعذر إنشاء الحساب",
                "error"
            );
        } finally {
            if (button) {
                button.disabled = false;
                button.textContent = "إنشاء الحساب";
            }
        }
    });
}

/* =========================================================
   LOGOUT
========================================================= */

function initLogout() {
    const buttons = $$(
        "#logoutBtn, [data-logout], .logout-btn"
    );

    buttons.forEach(button => {
        button.addEventListener("click", async () => {
            try {
                const data = await api("/api/logout", {
                    method: "POST"
                });

                showToast(
                    data.message || "تم تسجيل الخروج",
                    "success"
                );

                setTimeout(() => {
                    window.location.href =
                        data.redirect || "/login";
                }, 500);

            } catch (error) {
                showToast(
                    error.message || "تعذر تسجيل الخروج",
                    "error"
                );
            }
        });
    });
}

/* =========================================================
   MARKET / ANALYSIS
========================================================= */

let analysisTimer = null;

async function loadAnalysis() {
    const symbolInput =
        $("#symbol") ||
        $("#symbolInput") ||
        $("input[name='symbol']");

    const timeframe =
        $("#timeframe") ||
        $("select[name='timeframe']");

    if (!symbolInput) {
        return;
    }

    const symbol =
        (symbolInput.value || "BTCUSDT")
        .trim()
        .toUpperCase();

    const interval =
        timeframe?.value || "15m";

    if (!symbol) {
        return;
    }

    const resultBox =
        $("#analysisResult") ||
        $("#analysis") ||
        $(".signal-box");

    if (resultBox) {
        resultBox.classList.add("loading");
    }

    try {
        /*
         * نحاول أكثر من endpoint حتى يبقى
         * الواجهة متوافقة مع نسخ الموقع المختلفة.
         */

        const endpoints = [
            `/api/analyze?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}`,
            `/api/analysis?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}`,
            `/api/signal?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}`
        ];

        let data = null;
        let lastError = null;

        for (const endpoint of endpoints) {
            try {
                data = await api(endpoint);

                if (data) {
                    break;
                }
            } catch (error) {
                lastError = error;
            }
        }

        if (!data) {
            throw lastError ||
                new Error("لم تصل نتيجة التحليل");
        }

        renderAnalysis(data);

    } catch (error) {
        console.error(error);

        if (resultBox) {
            resultBox.innerHTML = `
                <div class="signal">
                    <div class="signal-name signal-neutral">
                        تعذر تحميل التحليل
                    </div>
                    <div class="muted">
                        ${escapeHtml(error.message || "")}
                    </div>
                </div>
            `;
        }
    } finally {
        if (resultBox) {
            resultBox.classList.remove("loading");
        }
    }
}

function renderAnalysis(data) {
    const resultBox =
        $("#analysisResult") ||
        $("#analysis") ||
        $(".signal-box");

    if (!resultBox) {
        return;
    }

    const signal =
        data.signal ||
        data.action ||
        data.result ||
        data.status ||
        "محايد";

    const price =
        data.price ??
        data.current_price ??
        data.last_price ??
        data.close;

    const change =
        data.change_percent ??
        data.change ??
        data.price_change;

    const timeframe =
        data.interval ||
        data.timeframe ||
        "15m";

    const symbol =
        data.symbol ||
        $("#symbol")?.value ||
        "BTCUSDT";

    const signalText =
        String(signal);

    let signalClass = "signal-neutral";

    if (
        /شراء|buy|long|strong_buy/i.test(signalText)
    ) {
        signalClass = "signal-buy";
    } else if (
        /بيع|sell|short|strong_sell/i.test(signalText)
    ) {
        signalClass = "signal-sell";
    }

    resultBox.innerHTML = `
        <div class="signal">

            <div class="muted">
                ${escapeHtml(symbol)}
            </div>

            <div class="signal-name ${signalClass}">
                ${escapeHtml(signalText)}
            </div>

            <div class="signal-price">
                ${price !== undefined
                    ? formatNumber(price, 8)
                    : "--"}
            </div>

            <div class="signal-meta">

                <div>
                    <span>التغير</span>
                    <strong>
                        ${change !== undefined
                            ? formatPercent(change)
                            : "--"}
                    </strong>
                </div>

                <div>
                    <span>الفريم</span>
                    <strong>
                        ${escapeHtml(timeframe)}
                    </strong>
                </div>

                <div>
                    <span>التحديث</span>
                    <strong>
                        الآن
                    </strong>
                </div>

            </div>
        </div>
    `;
}

function initAnalysis() {
    const button =
        $("#analyzeBtn") ||
        $("#analyzeButton") ||
        "[data-analyze]";

    const analyzeButton =
        typeof button === "string"
            ? $(button)
            : button;

    if (!analyzeButton) {
        return;
    }

    analyzeButton.addEventListener(
        "click",
        loadAnalysis
    );

    const symbolInput =
        $("#symbol") ||
        $("#symbolInput") ||
        $("input[name='symbol']");

    if (symbolInput) {
        symbolInput.addEventListener("keydown", event => {
            if (event.key === "Enter") {
                event.preventDefault();
                loadAnalysis();
            }
        });
    }

    loadAnalysis();

    clearInterval(analysisTimer);

    analysisTimer = setInterval(
        loadAnalysis,
        30000
    );
}

/* =========================================================
   WATCHLIST
========================================================= */

function initWatchlist() {
    $$("[data-symbol]").forEach(item => {
        item.addEventListener("click", () => {
            const symbol = item.dataset.symbol;

            const input =
                $("#symbol") ||
                $("#symbolInput") ||
                $("input[name='symbol']");

            if (!input || !symbol) {
                return;
            }

            input.value = symbol;

            loadAnalysis();

            window.scrollTo({
                top: 0,
                behavior: "smooth"
            });
        });
    });
}

/* =========================================================
   SETTINGS
========================================================= */

function initSettings() {
    const form = $("#settingsForm");

    if (!form) {
        return;
    }

    form.addEventListener("submit", async event => {
        event.preventDefault();

        const data = {};

        $$("input, select", form).forEach(input => {
            if (!input.name) {
                return;
            }

            if (input.type === "checkbox") {
                data[input.name] = input.checked;
            } else {
                data[input.name] = input.value;
            }
        });

        try {
            const result = await api(
                "/api/settings",
                {
                    method: "POST",
                    body: JSON.stringify(data)
                }
            );

            showToast(
                result.message || "تم حفظ الإعدادات",
                "success"
            );

        } catch (error) {
            showToast(
                error.message || "تعذر حفظ الإعدادات",
                "error"
            );
        }
    });
}

/* =========================================================
   ADMIN
========================================================= */

function initAdmin() {
    const userTable =
        $("#usersTable") ||
        $("#adminUsers");

    if (!userTable) {
        return;
    }

    loadAdminUsers();
}

async function loadAdminUsers() {
    const table =
        $("#usersTable") ||
        $("#adminUsers");

    if (!table) {
        return;
    }

    try {
        const data =
            await api("/api/admin/users");

        const users =
            Array.isArray(data)
                ? data
                : (data.users || []);

        if (!users.length) {
            return;
        }

        const tbody =
            $("tbody", table);

        if (!tbody) {
            return;
        }

        tbody.innerHTML = users.map(user => `
            <tr>
                <td>${escapeHtml(user.id ?? "--")}</td>
                <td>${escapeHtml(user.username ?? "--")}</td>
                <td>${escapeHtml(user.email ?? "--")}</td>
                <td>${escapeHtml(user.plan ?? "free")}</td>
                <td>${formatDate(user.created_at)}</td>
            </tr>
        `).join("");

    } catch (error) {
        console.error(
            "Admin users:",
            error
        );
    }
}

/* =========================================================
   DATE
========================================================= */

function formatDate(value) {
    if (!value) {
        return "--";
    }

    try {
        const number = Number(value);

        const date =
            number > 100000000000
                ? new Date(number)
                : new Date(number * 1000);

        if (Number.isNaN(date.getTime())) {
            return "--";
        }

        return date.toLocaleDateString(
            "ar-SA"
        );

    } catch {
        return "--";
    }
}

/* =========================================================
   ESCAPE HTML
========================================================= */

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

/* =========================================================
   AUTO REFRESH
========================================================= */

function initAutoRefresh() {
    const elements =
        $$("[data-auto-refresh]");

    elements.forEach(element => {
        const seconds =
            Number(
                element.dataset.autoRefresh
            ) || 30;

        setInterval(() => {
            window.dispatchEvent(
                new CustomEvent(
                    "site:auto-refresh"
                )
            );
        }, seconds * 1000);
    });
}

/* =========================================================
   START
========================================================= */

document.addEventListener(
    "DOMContentLoaded",
    () => {

        initMobileMenu();
        initLogin();
        initRegister();
        initLogout();

        initAnalysis();
        initWatchlist();
        initSettings();

        initAdmin();
        initAutoRefresh();

        console.log(
            "موقع تداول: JavaScript loaded successfully"
        );
    }
);
