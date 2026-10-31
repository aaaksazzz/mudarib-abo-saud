"""Live Binance order-book flow confirmation.

This is an observable order-book snapshot, not proof of hidden institutional orders.
Only Binance Spot, USD-M and COIN-M books are supported by this adapter.
"""
from statistics import median


BOOK_ENDPOINTS = {
    "spot": "https://api.binance.com/api/v3/depth",
    "futures": "https://fapi.binance.com/fapi/v1/depth",
    "coinm": "https://dapi.binance.com/dapi/v1/depth",
}


def analyse_orderbook_flow(kind, symbol, side, fetcher):
    """Return a transparent top-of-book imbalance snapshot or an unavailable status."""
    endpoint = BOOK_ENDPOINTS.get(kind)
    if not endpoint:
        return {
            "status": "unavailable",
            "label": "بيانات دفتر الأوامر غير مربوطة لهذا السوق",
            "source": None,
            "imbalance": None,
            "bid_notional": None,
            "ask_notional": None,
            "large_bid_wall": False,
            "large_ask_wall": False,
        }
    if side not in ("BUY", "SELL"):
        return {"status": "unavailable", "label": "اتجاه غير محدد", "source": "Binance order book"}
    try:
        payload = fetcher(endpoint, {"symbol": symbol, "limit": 20})
        bids = payload.get("bids") or []
        asks = payload.get("asks") or []
        if not bids or not asks:
            raise ValueError("empty order book")

        def notionals(levels):
            values = []
            for level in levels[:20]:
                price, quantity = float(level[0]), float(level[1])
                if price > 0 and quantity > 0:
                    values.append(price * quantity)
            return values

        bid_values, ask_values = notionals(bids), notionals(asks)
        bid_total, ask_total = sum(bid_values), sum(ask_values)
        total = bid_total + ask_total
        if total <= 0 or not bid_values or not ask_values:
            raise ValueError("invalid order book values")
        imbalance = (bid_total - ask_total) / total
        bid_median, ask_median = median(bid_values), median(ask_values)
        bid_wall = max(bid_values) >= max(bid_median * 5, 1)
        ask_wall = max(ask_values) >= max(ask_median * 5, 1)
        aligned = imbalance >= 0.12 if side == "BUY" else imbalance <= -0.12
        opposed = imbalance <= -0.12 if side == "BUY" else imbalance >= 0.12
        status = "supportive" if aligned else ("opposing" if opposed else "balanced")
        return {
            "status": status,
            "label": {
                "supportive": "دفتر الأوامر يدعم اتجاه الصفقة",
                "opposing": "دفتر الأوامر يعاكس اتجاه الصفقة",
                "balanced": "دفتر الأوامر متوازن؛ لا يوجد تفوق واضح",
            }[status],
            "source": "Binance public order-book snapshot",
            "imbalance": round(imbalance, 4),
            "bid_notional": round(bid_total, 2),
            "ask_notional": round(ask_total, 2),
            "large_bid_wall": bid_wall,
            "large_ask_wall": ask_wall,
            "levels": min(len(bid_values), len(ask_values)),
            "warning": "لقطة لحظية قابلة للتغير؛ لا تثبت هوية المتداول أو وجود أوامر مخفية",
        }
    except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError, OverflowError):
        return {
            "status": "unavailable",
            "label": "تعذر التحقق من دفتر الأوامر",
            "source": "Binance public order-book snapshot",
            "imbalance": None,
            "bid_notional": None,
            "ask_notional": None,
            "large_bid_wall": False,
            "large_ask_wall": False,
        }
