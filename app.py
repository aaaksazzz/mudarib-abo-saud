from flask import Flask, jsonify, render_template, abort
from datetime import datetime, timezone
import os
app = Flask(__name__, template_folder="templates", static_folder="static")

MARKETS = {
 "spot":("Binance Spot","spot"), "futures":("Binance USD-M Futures","futures"),
 "alpha":("Binance Alpha","alpha"), "us-stocks":("الأسهم الأمريكية","us-stocks"),
 "us-contracts":("العقود الأمريكية","us-contracts"), "saudi":("السوق السعودي","saudi"),
 "forex":("الفوركس والذهب","forex")
}
NAV = [("الرئيسية","/","home"),("الأسواق","/markets","markets"),("المحفظة","/portfolio","portfolio"),("الأخبار","/news","news"),("المدونة","/blog","blog"),("التنبيهات","/alerts","alerts"),("الحساب","/account","account")]

@app.get("/")
def home():
 return render_template("page.html", title="نظرة عامة", section="home", nav=NAV, markets=MARKETS, active="home")

@app.get("/markets")
def markets():
 return render_template("page.html", title="الأسواق", section="markets", nav=NAV, markets=MARKETS, active="markets")

@app.get("/markets/<market>")
def market_page(market):
 if market not in MARKETS: abort(404)
 return render_template("page.html", title=MARKETS[market][0], section="market", nav=NAV, markets=MARKETS, active="markets", market=market, market_title=MARKETS[market][0])

@app.get("/<section>")
def section_page(section):
 titles={"portfolio":"المحفظة","news":"الأخبار","blog":"المدونة","alerts":"التنبيهات","account":"الحساب"}
 if section not in titles: abort(404)
 return render_template("page.html", title=titles[section], section=section, nav=NAV, markets=MARKETS, active=section)

@app.get("/api/health")
def health():
 return jsonify({"ok":True,"service":"SMART TRADING PRO","utc":datetime.now(timezone.utc).isoformat()})

@app.get("/api/markets/<market>/tickers")
def tickers(market):
 if market not in MARKETS: return jsonify({"error":"سوق غير معروف"}),404
 try:
  from market_adapters import market_tickers
  rows=market_tickers(market)
  if market in ("spot","futures"):
   # The current adapter exposes candles for these markets; ticker universe is sourced from exchange metadata.
   return jsonify({"market":market,"items":rows,"count":len(rows),"source":"public market adapter"})
  return jsonify({"market":market,"items":rows,"count":len(rows),"source":"public market adapter"})
 except Exception as exc:
  app.logger.exception("market ticker failure: %s",market)
  return jsonify({"market":market,"items":[],"count":0,"error":"تعذر جلب بيانات هذا السوق حالياً","detail":str(exc)[:240]}),503

@app.get("/api/markets/<market>/<path:symbol>/candles")
def candles(market,symbol):
 if market not in MARKETS: return jsonify({"error":"سوق غير معروف"}),404
 try:
  from market_adapters import klines
  rows=klines(market,symbol.upper(),request_interval(),250)
  return jsonify({"market":market,"symbol":symbol.upper(),"interval":request_interval(),"candles":rows})
 except Exception as exc:
  app.logger.exception("candle failure")
  return jsonify({"error":"تعذر جلب الشموع","detail":str(exc)[:200]}),503

def request_interval():
 from flask import request
 interval=request.args.get("interval","15m")
 return interval if interval in ("15m","4h","1d","1w") else "15m"

@app.errorhandler(404)
def not_found(_):
 return render_template("page.html", title="الصفحة غير موجودة", section="notfound", nav=NAV, markets=MARKETS, active=""),404

if __name__ == "__main__":
 app.run(host="0.0.0.0",port=int(os.getenv("PORT","8080")))
