"""External trade-idea transformation helpers.

The source direction is retained for audit; only the site's displayed trade is
reversed. Price levels are reflected around the published entry so that the
resulting stop and targets remain on the correct side. This is a simulation,
not evidence that contrarian trades are profitable.
"""
import copy
import math


def invert_external_trade(row):
    if not isinstance(row, dict):
        return row
    item = copy.deepcopy(row)
    source_side = str(item.get("direction") or "")
    if source_side not in {"شراء", "بيع"}:
        return item
    levels = item.get("levels") if isinstance(item.get("levels"), dict) else {}
    try:
        entry = float(levels.get("entry", item.get("entry")))
    except (TypeError, ValueError, OverflowError):
        return item
    if not math.isfinite(entry) or entry <= 0:
        return item

    # Reflect every published numeric target/stop across the entry price.
    reflected = dict(levels)
    for key, value in list(levels.items()):
        if key in {"entry", "entry_min", "entry_max"}:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(number) and number > 0:
            reflected[key] = round(2.0 * entry - number, 12)
    reflected["entry"] = entry
    # Preserve an entry zone exactly; the inversion changes direction, not fill range.
    if "entry_min" in levels:
        reflected["entry_min"] = levels["entry_min"]
    if "entry_max" in levels:
        reflected["entry_max"] = levels["entry_max"]

    new_side = "بيع" if source_side == "شراء" else "شراء"
    item["levels"] = reflected
    item["entry"] = entry
    item["direction"] = new_side
    item["source_direction"] = source_side
    item["original_direction"] = "LONG" if new_side == "شراء" else "SHORT"
    item["strategy_mode"] = "external_reversal"
    item["external_source_weight"] = 90
    item["site_analysis_weight"] = 10
    item["direction_note"] = "اتجاه المصدر عُكس بواسطة الموقع؛ المستويات انعكست حول سعر الدخول."
    item["status"] = "توصية خارجية معكوسة؛ يلزم تقييم التحليل الفني والمخاطر"
    return item
