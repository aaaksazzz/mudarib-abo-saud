/* ==========================================
   تحليل تداول
   القائمة مخفية عند البداية
========================================== */


/* =========================
   عناصر القائمة
========================= */

const menuBtn = document.getElementById("menuBtn");
const closeMenu = document.getElementById("closeMenu");
const sidebar = document.getElementById("sidebar");
const overlay = document.getElementById("overlay");


/* فتح القائمة */

function openMenu() {

    sidebar.classList.add("open");

    overlay.classList.add("show");
}


/* إغلاق القائمة */

function closeSidebar() {

    sidebar.classList.remove("open");

    overlay.classList.remove("show");
}


/* زر القائمة */

menuBtn.addEventListener("click", openMenu);


/* زر الإغلاق */

closeMenu.addEventListener("click", closeSidebar);


/* الضغط خارج القائمة */

overlay.addEventListener("click", closeSidebar);



/* =========================
   التنقل بين الصفحات
========================= */

document.querySelectorAll(".nav-item").forEach(button => {

    button.addEventListener("click", () => {

        const page = button.dataset.page;

        openPage(page);

        closeSidebar();

    });

});


function openPage(pageName) {

    document.querySelectorAll(".page").forEach(page => {

        page.classList.remove("active");

    });


    const target = document.getElementById(pageName);

    if (target) {

        target.classList.add("active");

    }


    document.querySelectorAll(".nav-item").forEach(button => {

        button.classList.remove("active");

        if (button.dataset.page === pageName) {

            button.classList.add("active");

        }

    });


    window.scrollTo({
        top: 0,
        behavior: "smooth"
    });


    if (pageName === "crypto") {

        loadCrypto();

    }

}


window.openPage = openPage;



/* =========================
   الوضع الليلي
========================= */

function toggleTheme() {

    document.body.classList.toggle("dark");

    localStorage.setItem(
        "theme",
        document.body.classList.contains("dark")
            ? "dark"
            : "light"
    );

}


window.toggleTheme = toggleTheme;


/* استرجاع الوضع */

if (localStorage.getItem("theme") === "dark") {

    document.body.classList.add("dark");

}



/* =========================
   Binance
========================= */

let binanceSymbols = [];


async function loadCrypto() {

    const list = document.getElementById("cryptoList");

    const count = document.getElementById("cryptoCount");


    list.innerHTML = `
        <div class="loading">
            جاري تحميل جميع عملات Binance...
        </div>
    `;


    try {

        const response =
            await fetch("/api/binance/exchange-info");


        if (!response.ok) {

            throw new Error("فشل الاتصال");

        }


        const data = await response.json();


        binanceSymbols =
            data.symbols
                .filter(symbol =>
                    symbol.status === "TRADING"
                    &&
                    symbol.quoteAsset === "USDT"
                );


        count.textContent =
            `${binanceSymbols.length} عملة`;


        renderCrypto(binanceSymbols);


    } catch (error) {

        list.innerHTML = `
            <div class="loading">
                ⚠️ تعذر تحميل عملات Binance
            </div>
        `;

        count.textContent = "خطأ في الاتصال";

    }

}


function renderCrypto(symbols) {

    const list =
        document.getElementById("cryptoList");


    if (!symbols.length) {

        list.innerHTML =
            `<div class="empty">لا توجد نتائج</div>`;

        return;

    }


    list.innerHTML =
        symbols
        .slice(0, 300)
        .map(symbol => `

            <div class="asset-card">

                <h3>
                    🪙 ${symbol.symbol}
                </h3>

                <p>
                    Base:
                    ${symbol.baseAsset}
                </p>

                <p>
                    Quote:
                    ${symbol.quoteAsset}
                </p>

                <button
                    onclick="analyzeSymbol('${symbol.symbol}')"
                >
                    📊 تحليل
                </button>

            </div>

        `)
        .join("");

}


/* بحث العملات */

document
.getElementById("cryptoSearch")
.addEventListener("input", function () {

    const search =
        this.value.toUpperCase().trim();


    if (!search) {

        renderCrypto(binanceSymbols);

        return;

    }


    const results =
        binanceSymbols.filter(symbol =>
            symbol.symbol.includes(search)
        );


    renderCrypto(results);

});



/* =========================
   تحليل
========================= */

function analyzeSymbol(symbol) {

    document.getElementById("analysisSymbol").value =
        symbol;


    openPage("analysis");

    runAnalysis();

}


window.analyzeSymbol = analyzeSymbol;


async function runAnalysis() {

    const symbol =
        document
        .getElementById("analysisSymbol")
        .value
        .trim()
        .toUpperCase();


    const timeframe =
        document
        .getElementById("analysisTimeframe")
        .value;


    const result =
        document.getElementById("analysisResult");


    if (!symbol) {

        result.innerHTML = `
            <div class="empty">
                اكتب رمز السهم أو العملة أولًا.
            </div>
        `;

        return;

    }


    result.innerHTML = `
        <div class="loading">
            🔎 جاري تحليل ${symbol} على ${timeframe}...
        </div>
    `;


    try {

        const response =
            await fetch(
                `/api/binance/klines?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(timeframe)}&limit=100`
            );


        if (!response.ok) {

            throw new Error("لا توجد بيانات");

        }


        const candles =
            await response.json();


        if (!candles.length) {

            throw new Error("لا توجد شموع");

        }


        const last =
            candles[candles.length - 1];


        const previous =
            candles[candles.length - 2];


        const price =
            Number(last[4]);


        const prevPrice =
            Number(previous[4]);


        const change =
            ((price - prevPrice) / prevPrice) * 100;


        let signal = "حيادي";


        if (change > 1) {

            signal = "شراء";

        } else if (change < -1) {

            signal = "بيع";

        }


        result.innerHTML = `

            <div class="panel">

                <h2>
                    ${symbol}
                </h2>

                <h3>
                    السعر:
                    ${price}
                </h3>

                <p>
                    الفريم:
                    ${timeframe}
                </p>

                <p>
                    التغير الأخير:
                    ${change.toFixed(2)}%
                </p>

                <h2>
                    الإشارة:
                    ${signal}
                </h2>

                <hr>

                <p>
                    📊 المؤشرات الفنية المتقدمة يتم ربطها
                    بمصدر البيانات والتحليل الفعلي في المرحلة التالية.
                </p>

            </div>

        `;


    } catch (error) {

        result.innerHTML = `

            <div class="empty">

                ⚠️ ما قدرنا نجيب بيانات
                <br><br>

                تأكد أن الرمز موجود في Binance Spot.

            </div>

        `;

    }

}


window.runAnalysis = runAnalysis;



/* =========================
   السعودي
========================= */

function loadSaudi() {

    const list =
        document.getElementById("saudiList");


    list.innerHTML = `

        <div class="empty">

            🇸🇦 سيتم تحميل جميع أسهم السوق السعودي
            الرئيسية + نمو عند ربط مصدر البيانات السعودي.

        </div>

    `;

}


window.loadSaudi = loadSaudi;



/* =========================
   الأمريكي
========================= */

function loadUS() {

    const list =
        document.getElementById("usList");


    list.innerHTML = `

        <div class="empty">

            🇺🇸 سيتم تحميل جميع أسهم NYSE + NASDAQ
            عند ربط مصدر البيانات الأمريكي.

        </div>

    `;

}


window.loadUS = loadUS;



/* =========================
   الفاحص
========================= */

function runScanner() {

    const results =
        document.getElementById("scannerResults");


    results.innerHTML = `

        <div class="loading">

            🔎 جاري فحص الأسواق...

            <br><br>

            سيتم ربط الفاحص بالبيانات الحية
            والمؤشرات الفنية المتقدمة.

        </div>

    `;

}


window.runScanner = runScanner;



/* =========================
   الأخبار
========================= */

function loadNews(type = "all") {

    const list =
        document.getElementById("newsList");


    let title = "آخر الأخبار";


    if (type === "saudi") {

        title = "🇸🇦 أخبار السوق السعودي";

    }


    if (type === "us") {

        title = "🇺🇸 أخبار السوق الأمريكي";

    }


    if (type === "crypto") {

        title = "🪙 أخبار العملات الرقمية";

    }


    list.innerHTML = `

        <div class="news-card">

            <h3>${title}</h3>

            <p>
                سيتم ربط مركز الأخبار بمصادر الأخبار
                الفعلية في المرحلة التالية.
            </p>

        </div>

    `;

}


window.loadNews = loadNews;



/* =========================
   البحث العام
========================= */

function searchMarket() {

    const value =
        document
        .getElementById("globalSearch")
        .value
        .trim()
        .toUpperCase();


    if (!value) {

        return;

    }


    document.getElementById("analysisSymbol").value =
        value;


    openPage("analysis");

    runAnalysis();

}


window.searchMarket = searchMarket;



/* =========================
   تشغيل أولي
========================= */

document.addEventListener("DOMContentLoaded", () => {

    /*
       مهم:
       لا نفتح القائمة هنا.
       الموقع يبدأ والقائمة مغلقة.
    */

    closeSidebar();

});
