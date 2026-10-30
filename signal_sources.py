"""Strict parsers for public, free signal feeds.

Only accept a signal when the source post itself contains a supported symbol,
side, entry, stop and at least three correctly ordered targets. Source results
and missing timeframe are disclosed; no missing values are invented.
"""
import html
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

CHANNELS = ("behtarinforex", "STPFOREX")
MAX_AGE_SECONDS = 24 * 60 * 60
CACHE_TTL = 180
CACHE = {"at": 0, "data": None}
LOCK = threading.RLock()

SYMBOLS = {
    "XAUUSD": "XAUUSD", "XAU/USD": "XAUUSD", "GOLD": "XAUUSD",
    "XAGUSD": "XAGUSD", "XAG/USD": "XAGUSD", "SILVER": "XAGUSD",
    "EURUSD": "EURUSD", "EUR/USD": "EURUSD", "GBPUSD": "GBPUSD",
    "GBP/USD": "GBPUSD", "USDJPY": "USDJPY", "USD/JPY": "USDJPY",
    "AUDUSD": "AUDUSD", "AUD/USD": "AUDUSD", "USDCAD": "USDCAD",
    "USD/CAD": "USDCAD", "USDCHF": "USDCHF", "USD/CHF": "USDCHF",
    "NZDUSD": "NZDUSD", "NZD/USD": "NZDUSD", "EURGBP": "EURGBP",
    "EUR/GBP": "EURGBP", "EURJPY": "EURJPY", "EUR/JPY": "EURJPY",
    "GBPJPY": "GBPJPY", "GBP/JPY": "GBPJPY",
}
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_NUMBER = r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]*\.[0-9]+)"


def _normalise(value):
    value = str(value or "").translate(_DIGITS)
    return value.replace("٫", ".").replace("٬", ",").replace("：", ":").replace("−", "-")


def _numbers(value):
    result = []
    for raw in re.findall(_NUMBER, _normalise(value)):
        try:
            number = float(raw.replace(",", ""))
            if number > 0:
                result.append(number)
        except (TypeError, ValueError, OverflowError):
            continue
    return result


def _published_at(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    except (TypeError, ValueError, OverflowError):
        return 0


def _fetch_channel(channel):
    request = urllib.request.Request(
        "https://t.me/s/" + channel,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        page = response.read(900_000).decode("utf-8", "replace")
    blocks = re.split(r'(?=<div class="tgme_widget_message_wrap)', page)[1:]
    rows = []
    for block in blocks[-80:]:
        body = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.S)
        stamp = re.search(r'<time[^>]*datetime="([^"]+)"', block, re.S)
        link = re.search(r'href="(https://t\.me/' + re.escape(channel) + r'/\d+)"', block)
        if not body or not stamp or not link:
            continue
        message = html.unescape(re.sub(r"<[^>]+>", " ", body.group(1)))
        message = re.sub(r"\s+", " ", message).strip()
        published = _published_at(stamp.group(1))
        if message and published:
            rows.append({
                "channel": channel,
                "text": message,
                "published_at": published,
                "url": link.group(1),
            })
    return rows


def _extract_symbol(text):
    for token in re.findall(r"(?<![A-Z0-9])(?:XAU\s*/\s*USD|XAG\s*/\s*USD|EUR\s*/\s*USD|GBP\s*/\s*USD|USD\s*/\s*JPY|AUD\s*/\s*USD|USD\s*/\s*CAD|USD\s*/\s*CHF|NZD\s*/\s*USD|EUR\s*/\s*GBP|EUR\s*/\s*JPY|GBP\s*/\s*JPY|XAUUSD|XAGUSD|EURUSD|GBPUSD|USDJPY|AUDUSD|USDCAD|USDCHF|NZDUSD|EURGBP|EURJPY|GBPJPY|GOLD|SILVER)(?![A-Z0-9])", text, re.I):
        key = re.sub(r"\s+", "", token).upper()
        if key in SYMBOLS:
            return SYMBOLS[key]
    return ""


def _extract_targets(text):
    text = _normalise(text)
    found = {}
    for index in range(1, 7):
        patterns = (
            rf"\bTP\s*[-#]?\s*{index}\s*[:=@-]?\s*{_NUMBER}",
            rf"\bTarget\s*{index}\s*[:=@-]?\s*{_NUMBER}",
            rf"\bTake\s*Profit\s*{index}\s*[:=@-]?\s*{_NUMBER}",
            rf"(?:تارگت|هدف)\s*{index}\s*[:=@-]?\s*{_NUMBER}",
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                values = _numbers(match.group(1))
                if values:
                    found[index] = values[0]
                    break
    if len(found) >= 3:
        return [found[index] for index in sorted(found)[:5]]
    # Some STP posts publish all targets in one explicit TP field, e.g.
    # "حد سود (TP): 4435_4490_4525". This reads only that labelled field.
    block = re.search(
        r"(?:targets?|take\s*profit|حد\s*سود|تارگت)\s*(?:\(?TP\)?)?\s*[:：]\s*(.*?)"
        r"(?=\s*(?:stop\s*loss|stoploss|\bSL\b|استاپ|حد\s*ضرر|entry|نقاط?\s*ورود)|$)",
        text, re.I,
    )
    return _numbers(block.group(1))[:5] if block else []


def _extract_signal(row, now):
    text = _normalise(row.get("text"))
    published = int(row.get("published_at") or 0)
    age = now - published
    if not published or age < -300 or age > MAX_AGE_SECONDS:
        return None
    # Do not parse result/update posts as new entries.
    if re.search(r"\b(?:target\s*hit|tp\s*[1-6]\s*(?:hit|reached)|stop\s*loss\s*hit|closed|result)\b|(?:تحقق|ضرب|وصل)\s*(?:الهدف|الاستوب)", text, re.I):
        return None
    symbol = _extract_symbol(text)
    if not symbol:
        return None
    buy = bool(re.search(r"\bBUY\b|شراء|خرید", text, re.I))
    sell = bool(re.search(r"\bSELL\b|بيع|فروش", text, re.I))
    if buy == sell:
        return None
    side = "LONG" if buy else "SHORT"

    entry_match = re.search(
        r"(?:entry\s*(?:points?|price)?|نقاط?\s*الدخول|نقاط?\s*ورود|نقطه\s*ورود)\s*[:：]\s*"
        r"([0-9۰-۹٠-٩][0-9۰-۹٠-٩,٬]*(?:\.[0-9۰-۹٠-٩]+)?"
        r"(?:\s*[,،/_-]\s*[0-9۰-۹٠-٩][0-9۰-۹٠-٩,٬]*(?:\.[0-9۰-۹٠-٩]+)?)?)",
        text, re.I,
    )
    stop_match = re.search(
        r"(?:stop\s*loss|stoploss|\bSL\b|استاپ\s*لاس|حد\s*ضرر)\s*[:：]?\s*"
        r"([0-9۰-۹٠-٩][0-9۰-۹٠-٩,٬]*(?:\.[0-9۰-۹٠-٩]+)?)",
        text, re.I,
    )
    if not entry_match or not stop_match:
        return None
    entries = _numbers(entry_match.group(1))
    stops = _numbers(stop_match.group(1))
    targets = _extract_targets(text)
    if not entries or not stops or len(targets) < 3:
        return None
    entry_min, entry_max = min(entries), max(entries)
    entry = (entry_min + entry_max) / 2
    stop = stops[0]
    targets = targets[:5]
    if not all(x > 0 for x in [entry_min, entry_max, entry, stop] + targets):
        return None
    if side == "LONG" and not (stop < entry and all(x > entry for x in targets)):
        return None
    if side == "SHORT" and not (stop > entry and all(x < entry for x in targets)):
        return None

    tf = ""
    tf_match = re.search(r"(?<![A-Z0-9])(M15|15M|M30|30M|H1|1H|H4|4H|D1|1D|W1|1W)(?![A-Z0-9])", text, re.I)
    if tf_match:
        token = tf_match.group(1).upper()
        tf = {"M15": "15m", "15M": "15m", "M30": "30m", "30M": "30m",
              "H1": "1h", "1H": "1h", "H4": "4h", "4H": "4h",
              "D1": "1d", "1D": "1d", "W1": "1w", "1W": "1w"}[token]
    return {
        "symbol": symbol,
        "direction": "شراء" if side == "LONG" else "بيع",
        "original_direction": side,
        "market": "forex",
        "entry": entry,
        "entry_min": entry_min,
        "entry_max": entry_max,
        "levels": {
            "entry": entry, "entry_min": entry_min, "entry_max": entry_max,
            "stop_loss": stop,
            **{"tp" + str(i + 1): value for i, value in enumerate(targets)},
        },
        "timeframe": tf or "غير مذكور من المصدر",
        "timeframe_provided": bool(tf),
        "published_at": published,
        "age_hours": round(max(0, age) / 3600, 1),
        "status": "صفقة منشورة؛ النتيجة غير مدققة بعد",
        "source": "Telegram @" + row["channel"],
        "source_url": row["url"],
        "source_performance_verified": False,
        "has_complete_levels": True,
        "generated_by_site": False,
    }


def fetch_forex_signals(limit=20, refresh=False):
    now = int(time.time())
    with LOCK:
        if not refresh and CACHE["data"] is not None and now - CACHE["at"] < CACHE_TTL:
            cached = dict(CACHE["data"])
            cached["items"] = list(cached.get("items", []))[:limit]
            cached["count"] = len(cached["items"])
            cached["cached"] = True
            return cached
    rows, failed = [], 0
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(_fetch_channel, channel): channel for channel in CHANNELS}
        for future in as_completed(futures):
            try:
                rows.extend(future.result())
            except Exception as exc:
                failed += 1
                print("Public forex signal source failed:", futures[future], type(exc).__name__)
    items, seen = [], set()
    for row in rows:
        item = _extract_signal(row, now)
        if not item:
            continue
        key = item["source_url"]
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    items.sort(key=lambda item: item["published_at"], reverse=True)
    data = {
        "ok": True,
        "market": "forex",
        "items": items[:limit],
        "count": min(len(items), limit),
        "sources_checked": len(CHANNELS),
        "sources_failed": failed,
        "sources": list(CHANNELS),
        "message": (
            "تم جلب صفقات منشورة حديثًا وبها دخول ووقف و3 أهداف على الأقل. الفريم غير مذكور في بعض المنشورات، وأداء المصادر لم يُدقق مستقلًا."
            if items else
            "لم نجد خلال آخر 24 ساعة منشورًا يجمع الدخول والوقف و3 أهداف صريحة؛ لم نكمل أي مستوى بالتخمين."
        ),
    }
    with LOCK:
        CACHE.update({"at": now, "data": data})
    return data
