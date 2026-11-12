import React from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

const markets = [
  ["Binance Spot", "فوري"],
  ["Binance Futures", "عقود USD-M"],
  ["Binance Alpha", "أصول Alpha"],
  ["US Stocks", "الأسهم الأمريكية"],
  ["US Contracts", "العقود الأمريكية"],
  ["Saudi Market", "السوق السعودي"],
  ["Forex & Gold", "الفوركس والذهب"],
] as const;

function App() {
  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand-mark">AS</div>
        <div><strong>SMART TRADING PRO</strong><span>GLOBAL MARKET TERMINAL</span></div>
        <span className="live"><i /> متابعة السوق</span>
      </header>
      <section className="intro">
        <p className="eyebrow">لوحة الأسواق</p>
        <h1>نظرة واضحة على السوق.</h1>
        <p className="muted">عرض الأسواق أولاً. بيانات الصفقات تُحمّل بشكل مستقل حتى لا تتعطل الصفحة.</p>
      </section>
      <section className="market-grid" aria-label="الأسواق">
        {markets.map(([name, label], index) => (
          <article className="market-card" key={name}>
            <span className="market-index">{String(index + 1).padStart(2, "0")}</span>
            <div><strong>{name}</strong><span>{label}</span></div>
            <span className="arrow" aria-hidden="true">↗</span>
          </article>
        ))}
      </section>
      <footer>تحليل ومتابعة فقط · لا يتم تنفيذ أوامر تداول آلية</footer>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode><App /></React.StrictMode>,
);
