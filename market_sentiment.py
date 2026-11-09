"""Public-source sentiment consensus plus price-risk levels.

The engine never claims to search the entire internet. It uses publicly reachable
Google News RSS and (for ordinary US equity tickers) Stocktwits streams, records
source coverage, and keeps sentiment separate from technical invalidation.
"""
import math
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from urllib.parse import quote
import xml.etree.ElementTree as ET
import requests

HEADERS = {"User-Agent": "SMART-TRADING-PRO/1.0 (public market sentiment reader)", "Accept": "application/json, application/rss+xml, application/xml"}
POSITIVE = (
    "bullish","buy","upgrade","outperform","beats estimates","beat estimates","record high","surge","rally","rallies","gains","inflow","adoption","approval","breakout",
    "صعود","ارتفاع","مكاسب","شراء","إيجابي","اختراق","نمو","موافقة","تدفقات داخلة","انتعاش","يرتفع","يرتفع بقوة",
    "hausse","subida","ganancias","anstieg","gewinne","kenaikan","yükseliş","baisse des taux","वृद्धि","लाभ"
)
NEGATIVE = (
    "bearish","sell","downgrade","underperform","misses estimates","missed estimates","record low","crash","plunge","selloff","outflow","hack","lawsuit","bankruptcy","liquidation","warning",
    "هبوط","انخفاض","خسائر","بيع","سلبي","انهيار","تصفية","اختراق أمني","دعوى","إفلاس","تحذير","يتراجع","يتراجع بقوة",
    "caída","bajada","pérdidas","rückgang","verluste","penurunan","kerugian","düşüş","kayıp","गिरावट","नुकसान"
)
HIGH_TRUST = ("reuters","bloomberg","financial times","wall street journal","wsj","cnbc","associated press","ap news","marketwatch","yahoo finance","the economist")
MED_TRUST = ("investing.com","benzinga","barron's","barrons","seeking alpha","coindesk","cointelegraph","the block","kitco","cme group")
_cache = {}
_cache_lock = threading.Lock()
CACHE_SECONDS = 300

def _headline_score(title):
    text = str(title or "").casefold()
    pos = sum(1 for word in POSITIVE if word in text)
    neg = sum(1 for word in NEGATIVE if word in text)
    if pos == neg:
        return 0
    return 1 if pos > neg else -1

def _publisher_weight(name):
    value = str(name or "").casefold()
    if any(x in value for x in HIGH_TRUST):
        return 1.35
    if any(x in value for x in MED_TRUST):
        return 1.15
    return 0.85

def _freshness_weight(published):
    try:
        dt = parsedate_to_datetime(str(published))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600)
        if age_hours <= 24:
            return 1.0
        if age_hours <= 72:
            return 0.75
        if age_hours <= 168:
            return 0.45
        return 0.2
    except Exception:
        return 0.5

def _google_news(symbol, market, display_name=None):
    terms = [str(display_name or "").strip(), str(symbol).strip()]
    if market in ("spot", "futures", "alpha"):
        terms.append("cryptocurrency")
    elif market == "forex":
        terms.append("forex OR gold OR silver")
    elif market == "saudi":
        terms.append("Tadawul OR Saudi stock")
    query = " ".join(x for x in terms if x)
    url = "https://news.google.com/rss/search?q=" + quote(query) + "&hl=en-US&gl=US&ceid=US:en"
    response = requests.get(url, headers=HEADERS, timeout=(3, 7))
    response.raise_for_status()
    root = ET.fromstring(response.content)
    items = []
    for node in root.findall("./channel/item")[:20]:
        title = (node.findtext("title") or "").strip()
        if not title:
            continue
        source_node = node.find("source")
        source = (source_node.text or "").strip() if source_node is not None else "Google News RSS"
        source_url = source_node.attrib.get("url", "") if source_node is not None else ""
        published = (node.findtext("pubDate") or "").strip()
        score = _headline_score(title)
        if score:
            items.append({"title": title[:350], "source": source, "source_url": source_url,
                          "published_at": published, "article_url": (node.findtext("link") or "").strip(), "score": score,
                          "weight": _publisher_weight(source) * _freshness_weight(published),
                          "provider": "Google News RSS"})
    return items

def _stocktwits(symbol):
    # Stocktwits has a public symbol stream; skip non-standard market identifiers.
    if not re.fullmatch(r"[A-Z]{1,6}", str(symbol or "")):
        return []
    url = "https://api.stocktwits.com/api/2/streams/symbol/" + quote(symbol) + ".json"
    response = requests.get(url, headers=HEADERS, timeout=(3, 6))
    response.raise_for_status()
    payload = response.json()
    messages = payload.get("messages") or []
    items = []
    for message in messages[:30]:
        sentiment = ((message.get("entities") or {}).get("sentiment") or {}).get("basic")
        score = 1 if sentiment == "Bullish" else -1 if sentiment == "Bearish" else 0
        if not score:
            continue
        user = message.get("user") or {}
        followers = max(0, int(user.get("followers") or 0))
        weight = 0.8 + min(followers, 5000) / 25000
        items.append({"title": str(message.get("body") or "")[:350],
                      "source": "Stocktwits community", "source_url": "",
                      "published_at": str(message.get("created_at") or ""),
                      "article_url": "https://stocktwits.com/symbol/" + quote(symbol), "score": score, "weight": weight, "provider": "Stocktwits"})
    return items

def collect_sentiment(symbol, market, display_name=None):
    items = []
    errors = []
    try:
        items.extend(_google_news(symbol, market, display_name))
    except Exception as exc:
        errors.append("Google News RSS: " + type(exc).__name__)
    if market == "us-stocks":
        try:
            items.extend(_stocktwits(symbol))
        except Exception as exc:
            errors.append("Stocktwits: " + type(exc).__name__)
    # De-duplicate exact headline/message text while retaining source diversity.
    unique = {}
    for item in items:
        key = re.sub(r"\W+", "", item["title"].casefold())
        if key and key not in unique:
            unique[key] = item
    items = list(unique.values())
    positive = sum(x["weight"] for x in items if x["score"] > 0)
    negative = sum(x["weight"] for x in items if x["score"] < 0)
    total = positive + negative
    score = (positive - negative) / total if total else 0.0
    side = "BUY" if score >= 0.12 else "SELL" if score <= -0.12 else "NEUTRAL"
    providers = sorted(set(x["provider"] for x in items))
    return {
        "side": side, "sentiment_score": round(score * 100, 1),
        "positive_mentions": sum(1 for x in items if x["score"] > 0),
        "negative_mentions": sum(1 for x in items if x["score"] < 0),
        "mentions": len(items), "providers": providers, "source_errors": errors,
        "evidence": sorted(items, key=lambda x: x["weight"], reverse=True)[:6],
        "coverage": "limited_public_sources" if items else "no_public_mentions"
    }

def technical_levels(market, symbol, sentiment_side, klines_fn):
    rows = klines_fn(market, symbol, "1d", 40)
    # Exclude the still-forming daily candle.
    bars = rows[:-1] if isinstance(rows, list) and len(rows) > 16 else []
    parsed = []
    for row in bars:
        try:
            op, high, low, close = (float(row[i]) for i in (1, 2, 3, 4))
            if not all(math.isfinite(x) and x > 0 for x in (op, high, low, close)) or high < low:
                continue
            parsed.append((high, low, close))
        except (TypeError, ValueError, IndexError):
            continue
    if len(parsed) < 15:
        return None
    entry = parsed[-1][2]
    ranges = []
    for i, (high, low, close) in enumerate(parsed[-14:]):
        previous = parsed[-15 + i][2] if i else parsed[-15][2]
        ranges.append(max(high - low, abs(high - previous), abs(low - previous)))
    atr = sum(ranges) / len(ranges)
    if not math.isfinite(atr) or atr <= 0:
        return None
    direction = 1 if sentiment_side == "BUY" else -1
    recent = parsed[-8:]
    if direction > 0:
        structural = min(x[1] for x in recent)
        stop = structural - max(atr * 0.15, entry * 0.0005)
        risk = entry - stop
        if risk <= 0 or risk / entry > 0.08:
            return None
        targets = [entry + risk * n for n in (1, 2, 3)]
    else:
        structural = max(x[0] for x in recent)
        stop = structural + max(atr * 0.15, entry * 0.0005)
        risk = stop - entry
        if risk <= 0 or risk / entry > 0.08:
            return None
        targets = [entry - risk * n for n in (1, 2, 3)]
    if min([entry, stop] + targets) <= 0:
        return None
    return {"entry": round(entry, 10), "stop": round(stop, 10),
            "tp1": round(targets[0], 10), "tp2": round(targets[1], 10),
            "tp3": round(targets[2], 10), "risk_pct": round(risk / entry * 100, 3),
            "reward_risk_tp3": 3.0, "technical_source": "Daily public OHLCV; ATR and 8-day swing invalidation"}

def scan_market(market, universe, klines_fn, limit=35):
    now = time.time()
    with _cache_lock:
        cached = _cache.get(market)
        if cached and now - cached[0] < CACHE_SECONDS:
            return dict(cached[1], cached=True)
    ranked = sorted(universe, key=lambda x: float(x.get("quote_volume") or 0), reverse=True)[:max(1, min(int(limit), 60))]
    results, errors = [], 0
    coverage = {"assets_with_mentions": 0, "assets_without_mentions": 0,
                "provider_failures": 0, "neutral_assets": 0, "technical_unavailable": 0}
    def inspect(item):
        symbol = str(item.get("symbol") or "")
        if not symbol:
            return {"signal": None, "sentiment": None, "errors": 0}
        sentiment = collect_sentiment(symbol, market, item.get("name"))
        if sentiment["mentions"] == 0:
            return {"signal": None, "sentiment": sentiment, "errors": len(sentiment["source_errors"])}
        if sentiment["side"] == "NEUTRAL":
            return {"signal": None, "sentiment": sentiment, "errors": len(sentiment["source_errors"])}
        levels = technical_levels(market, symbol, sentiment["side"], klines_fn)
        if not levels:
            return {"signal": None, "sentiment": sentiment, "errors": len(sentiment["source_errors"]), "technical_unavailable": True}
        votes = sentiment["positive_mentions"] + sentiment["negative_mentions"]
        consensus = abs(sentiment["sentiment_score"])
        confidence = min(95, round(45 + consensus * 0.35 + min(votes, 8) * 2))
        signal = {"market": market, "symbol": symbol, "side": sentiment["side"],
                  "sentiment_score": sentiment["sentiment_score"], "confidence": confidence,
                  "mentions": sentiment["mentions"], "positive_mentions": sentiment["positive_mentions"],
                  "negative_mentions": sentiment["negative_mentions"], "providers": sentiment["providers"],
                  "coverage": sentiment["coverage"], "evidence": sentiment["evidence"],
                  "source_errors": sentiment["source_errors"], "quote_volume": item.get("quote_volume"),
                  "change_pct_24h": item.get("change_pct"), **levels}
        return {"signal": signal, "sentiment": sentiment, "errors": len(sentiment["source_errors"])}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(inspect, item) for item in ranked]
        for future in as_completed(futures):
            try:
                result = future.result()
                sentiment = result.get("sentiment") or {}
                if sentiment.get("mentions", 0):
                    coverage["assets_with_mentions"] += 1
                else:
                    coverage["assets_without_mentions"] += 1
                if sentiment.get("side") == "NEUTRAL":
                    coverage["neutral_assets"] += 1
                if result.get("technical_unavailable"):
                    coverage["technical_unavailable"] += 1
                coverage["provider_failures"] += result.get("errors", 0)
                if result.get("signal"):
                    results.append(result["signal"])
            except Exception:
                errors += 1
    results.sort(key=lambda x: (x["confidence"], abs(x["sentiment_score"]), float(x.get("quote_volume") or 0)), reverse=True)
    payload = {"ok": True, "market": market, "engine": "PUBLIC_SENTIMENT_CONSENSUS_V1",
               "checked_assets": len(ranked), "signals_found": len(results), "analysis_errors": errors,
               "coverage_stats": coverage, "signals": results[:30],
               "sources": ["Google News RSS"] + (["Stocktwits"] if market == "us-stocks" else []),
               "source_scope": "مصادر عامة متاحة فقط؛ لا تمثل كامل الإنترنت أو جميع المتداولين",
               "updated_at": datetime.now(timezone.utc).isoformat(), "cached": False}
    with _cache_lock:
        _cache[market] = (now, payload)
    return payload
