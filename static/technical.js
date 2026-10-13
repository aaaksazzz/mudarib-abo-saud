(() => {
  const frameNames = {"15m":"15 دقيقة","1h":"ساعة","4h":"4 ساعات","1d":"يومي","1w":"أسبوعي","1M":"شهري"};
  function number(value) {
    return Number(value).toLocaleString("en-US", {maximumFractionDigits: Number(value) < 1 ? 8 : 4});
  }
  function volume(value) {
    return Number(value).toLocaleString("en-US", {notation:"compact", maximumFractionDigits:2});
  }
  function change(value) {
    const n = Number(value) || 0;
    return '<span class="' + (n >= 0 ? "green" : "red") + '">' + (n > 0 ? "+" : "") + n.toFixed(2) + '%</span>';
  }
  async function run(interval) {
    const market = typeof currentMarket === "string" ? currentMarket : "spot";
    const notice = document.getElementById("marketNotice");
    const body = document.getElementById("marketRows");
    const sub = document.getElementById("marketSub");
    if (!body || !notice || !sub) return;
    if (market !== "spot" && market !== "futures") {
      body.innerHTML = '<tr><td colspan="5" class="empty">هذا السوق غير مربوط ببيانات شموع مباشرة حتى الآن.</td></tr>';
      sub.textContent = "لا توجد بيانات فنية مباشرة لهذا السوق";
      notice.textContent = "فلتر EMA متعدد الفريمات متاح حاليًا لسبوت وفيوتشر Binance فقط؛ تم مسح نتائج السوق السابق لمنع خلط البيانات.";
      return;
    }
    notice.textContent = "جاري فحص EMA50 وEMA200 على " + frameNames[interval] + " وتأكيد الاتجاه على الفريم الأعلى…";
    body.innerHTML = '<tr><td colspan="5" class="empty">جاري فحص بيانات الشموع الفعلية…</td></tr>';
    try {
      const response = await fetch("/api/technical/" + market + "?interval=" + encodeURIComponent(interval) + "&limit=12", {cache:"no-store"});
      const data = await response.json();
      if (!response.ok || !data.live) throw new Error(data.message || "تعذر جلب البيانات");
      if (!data.items.length) {
        body.innerHTML = '<tr><td colspan="5" class="empty">ما فيه عملات اجتازت شروط الفلترة حاليًا.</td></tr>';
      } else {
        body.innerHTML = data.items.map(item =>
          '<tr><td><div class="coin"><span class="coin-icon">' + item.symbol.replace("USDT","").slice(0,4) + '</span>' + item.symbol + '</div></td>' +
          '<td>' + number(item.price) + '</td><td>' + change(item.change_pct) + '</td><td>' + volume(item.quote_volume) + '</td>' +
          '<td><span class="green">صاعد ✓</span><div class="muted" style="font-size:10px;margin-top:4px">EMA50 فوق 200 • تأكيد ' + item.higher_interval + '</div></td></tr>'
        ).join("");
      }
      sub.textContent = "فريم " + frameNames[interval] + " • فحص " + data.analyzed + " من " + data.scanned + " أصول • تحديث " + new Date(data.updated_at * 1000).toLocaleTimeString("ar-SA");
      notice.textContent = data.message;
    } catch (error) {
      body.innerHTML = '<tr><td colspan="5" class="empty">تعذر فحص الفريم الآن. جرّب التحديث بعد قليل.</td></tr>';
      notice.textContent = error.message || "تعذر الاتصال ببيانات الشموع.";
    }
  }
  document.querySelectorAll("[data-frame]").forEach(button => {
    button.addEventListener("click", () => run(button.dataset.frame));
  });
  // Expose the same real-data filter to the refresh button through a stable global function.
  window.smartTradingRefreshTechnical = () => {
    const selected = document.querySelector("[data-frame].active");
    run(selected ? selected.dataset.frame : "15m");
  };
})();