// ======================================================
// 🔎 ماسح الفرص + ⚡ الصفقات الحديثة
// ======================================================

const recentTradesKey = "recent_opportunities_v1";

function getRecentTrades() {
  try {
    return JSON.parse(localStorage.getItem(recentTradesKey) || "[]");
  } catch {
    return [];
  }
}

function saveRecentTrades(list) {
  localStorage.setItem(
    recentTradesKey,
    JSON.stringify(list.slice(0, 100))
  );
}

function signalClass(signal) {
  if (signal === "شراء قوي") return "signal-strong-buy";
  if (signal === "شراء") return "signal-buy";
  if (signal === "بيع قوي") return "signal-strong-sell";
  if (signal === "بيع") return "signal-sell";
  return "signal-neutral";
}

function signalIcon(signal) {
  if (signal === "شراء قوي") return "🟢🟢";
  if (signal === "شراء") return "🟢";
  if (signal === "بيع قوي") return "🔴🔴";
  if (signal === "بيع") return "🔴";
  return "⚪";
}

function renderRecentTrades() {
  const box = document.getElementById("recentTradeRows");
  if (!box) return;

  const trades = getRecentTrades();

  if (!trades.length) {
    box.innerHTML =
      `<tr><td colspan="6">لا توجد صفقات حديثة</td></tr>`;
    return;
  }

  box.innerHTML = trades.map(t => `
    <tr>
      <td><strong>${t.symbol}</strong></td>
      <td>${formatPrice(t.price)}</td>
      <td>${Number(t.change || 0).toFixed(2)}%</td>
      <td class="${signalClass(t.signal)}">
        ${signalIcon(t.signal)} ${t.signal}
      </td>
      <td>${t.interval}</td>
      <td>${t.time}</td>
    </tr>
  `).join("");
}

function addRecentTrade(item) {
  const list = getRecentTrades();

  const exists = list.find(
    x =>
      x.symbol === item.symbol &&
      x.interval === item.interval &&
      x.signal === item.signal
  );

  if (exists) return;

  list.unshift(item);
  saveRecentTrades(list);
  renderRecentTrades();
}

function formatPrice(price) {
  const n = Number(price);

  if (!Number.isFinite(n)) return "--";

  if (n >= 1000) return n.toLocaleString(
    "en-US",
    { maximumFractionDigits: 2 }
  );

  if (n >= 1) return n.toFixed(4);

  if (n >= 0.01) return n.toFixed(6);

  return n.toFixed(8);
}


async function runOpportunityScanner() {
  const rows = document.getElementById("opportunityRows");
  if (!rows) return;

  const interval =
    document.getElementById("scannerInterval")?.value || "15m";

  const signalFilter =
    document.getElementById("scannerSignal")?.value || "ALL";

  const sortBy =
    document.getElementById("scannerSort")?.value || "change";

  rows.innerHTML =
    `<tr><td colspan="5">🔄 جاري فحص العملات...</td></tr>`;

  try {
    const response = await fetch(
      `/api/binance/scan?interval=${encodeURIComponent(interval)}&limit=100`
    );

    const data = await response.json();

    if (!response.ok || data.ok === false) {
      throw new Error(data.error || "فشل الفحص");
    }

    let results = data.results || [];

    // فلترة الإشارة
    if (signalFilter !== "ALL") {
      results = results.filter(
        x => x.signal === signalFilter
      );
    }

    // الترتيب
    results.sort((a, b) => {

      if (sortBy === "price") {
        return Number(b.price || 0) - Number(a.price || 0);
      }

      if (sortBy === "score") {
        return Number(b.score || 0) - Number(a.score || 0);
      }

      if (sortBy === "volume") {
        return Number(b.volume || 0) -
               Number(a.volume || 0);
      }

      return Number(b.change || 0) -
             Number(a.change || 0);
    });

    if (!results.length) {
      rows.innerHTML =
        `<tr><td colspan="5">لا توجد نتائج مطابقة</td></tr>`;
      return;
    }

    rows.innerHTML = results.map(x => {

      const signal = x.signal || "حيادي";
      const price = x.price ?? 0;
      const change = Number(x.change || 0);
      const score = Number(
        x.score ?? x.score10 ?? 0
      );

      return `
        <tr>
          <td>
            <strong>${x.symbol}</strong>
          </td>

          <td>
            ${formatPrice(price)}
          </td>

          <td class="${change >= 0 ? "positive" : "negative"}">
            ${change >= 0 ? "+" : ""}
            ${change.toFixed(2)}%
          </td>

          <td class="${signalClass(signal)}">
            ${signalIcon(signal)}
            ${signal}
          </td>

          <td>
            <strong>${score}</strong>
          </td>
        </tr>
      `;

    }).join("");

    // إضافة الإشارات القوية للصفقات الحديثة
    results.forEach(x => {

      if (
        x.signal !== "شراء قوي" &&
        x.signal !== "شراء" &&
        x.signal !== "بيع قوي" &&
        x.signal !== "بيع"
      ) {
        return;
      }

      addRecentTrade({
        symbol: x.symbol,
        price: x.price,
        change: x.change || 0,
        signal: x.signal,
        interval: interval,
        time: new Date().toLocaleString("ar-SA")
      });

    });

  } catch (error) {

    console.error(error);

    rows.innerHTML = `
      <tr>
        <td colspan="5">
          ❌ ${error.message || "حدث خطأ أثناء الفحص"}
        </td>
      </tr>
    `;
  }
}


// الأزرار
document
  .getElementById("scanNowBtn")
  ?.addEventListener("click", runOpportunityScanner);

document
  .getElementById("scannerInterval")
  ?.addEventListener("change", runOpportunityScanner);

document
  .getElementById("scannerSignal")
  ?.addEventListener("change", runOpportunityScanner);

document
  .getElementById("scannerSort")
  ?.addEventListener("change", runOpportunityScanner);

document
  .getElementById("clearRecentBtn")
  ?.addEventListener("click", () => {

    localStorage.removeItem(recentTradesKey);
    renderRecentTrades();

  });


// تشغيل أولي
document.addEventListener("DOMContentLoaded", () => {
  renderRecentTrades();
  runOpportunityScanner();
});
