import time

from signal_sources import _extract_signal


def _row(text, channel="behtarinforex", age=60):
    now = int(time.time())
    return {
        "channel": channel,
        "text": text,
        "published_at": now - age,
        "url": "https://t.me/" + channel + "/123",
    }


def test_accepts_complete_public_gold_signal_and_discloses_missing_timeframe():
    row = _row(
        "Trading Symbol: XAUUSD (Gold) Trade Type: BUY "
        "Entry Points: 5197, 5192 Stop Loss: 5187 "
        "Target 1: 5201 Target 2: 5205 Target 3: 5209"
    )
    signal = _extract_signal(row, int(time.time()))
    assert signal is not None
    assert signal["symbol"] == "XAUUSD"
    assert signal["original_direction"] == "LONG"
    assert signal["levels"]["tp3"] == 5209
    assert signal["timeframe"] == "غير مذكور من المصدر"
    assert signal["timeframe_provided"] is False
    assert signal["source_performance_verified"] is False


def test_accepts_persian_stp_signal_with_explicit_three_target_list():
    row = _row(
        "نماد معاملاتی: GOLD نوع معامله: خرید نقاط ورود: 4355_4330 "
        "حد ضرر: 4320 حد سود (TP): 4435_4490_4525",
        channel="STPFOREX",
    )
    signal = _extract_signal(row, int(time.time()))
    assert signal is not None
    assert signal["symbol"] == "XAUUSD"
    assert signal["levels"]["tp1"] == 4435
    assert signal["levels"]["tp2"] == 4490
    assert signal["levels"]["tp3"] == 4525


def test_rejects_incomplete_signal_without_three_explicit_targets():
    row = _row(
        "XAUUSD BUY Entry: 5197 Stop Loss: 5187 "
        "TP1: 5201 TP2: 5205"
    )
    assert _extract_signal(row, int(time.time())) is None


def test_rejects_old_or_wrong_side_signal():
    old = _row(
        "XAUUSD BUY Entry: 5197 Stop Loss: 5187 "
        "TP1: 5201 TP2: 5205 TP3: 5209",
        age=25 * 60 * 60,
    )
    wrong_side = _row(
        "XAUUSD BUY Entry: 5197 Stop Loss: 5200 "
        "TP1: 5201 TP2: 5205 TP3: 5209"
    )
    now = int(time.time())
    assert _extract_signal(old, now) is None
    assert _extract_signal(wrong_side, now) is None
