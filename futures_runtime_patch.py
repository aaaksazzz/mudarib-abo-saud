"""Safety/idempotency runtime patch for the real USD-M Futures worker.

Goals:
- exactly one market entry per signal candle;
- never re-enter the same signal after it closes;
- never use the legacy STOP endpoint;
- place one Binance Algo STOP_MARKET hard stop after a filled entry;
- use the strategy's real SL instead of an ultra-tight leverage-divided stop;
- fail closed if protection cannot be confirmed.
"""
from datetime import datetime, timezone, timedelta
import time


def _utc_now():
    return datetime.now(timezone.utc)


def _signal_key(appmod, state):
    symbol = str(state.get("symbol") or "").upper()
    side = str(state.get("side") or "").upper()
    tf = str(state.get("timeframe") or "15m")
    candle = str(state.get("candle_start") or "")
    if not candle:
        try:
            candle = appmod._candle_start(tf).isoformat()
        except Exception:
            candle = _utc_now().isoformat()
    return "|".join((symbol, side, tf, candle))


def _candle_end_epoch(appmod, state):
    tf = str(state.get("timeframe") or "15m")
    try:
        start = appmod._candle_start(tf)
        if tf.endswith("m"):
            return (start + timedelta(minutes=int(tf[:-1]))).timestamp()
        if tf.endswith("h"):
            return (start + timedelta(hours=int(tf[:-1]))).timestamp()
        if tf == "1d":
            return (start + timedelta(days=1)).timestamp()
        if tf == "1w":
            return (start + timedelta(days=7)).timestamp()
        if tf == "1M":
            if start.month == 12:
                nxt = start.replace(year=start.year + 1, month=1)
            else:
                nxt = start.replace(month=start.month + 1)
            return nxt.timestamp()
    except Exception:
        pass
    return time.time() + 900


def _init_guard(appmod):
    c = appmod.db()
    c.execute("""
        CREATE TABLE IF NOT EXISTS futures_entry_guard(
            signal_key TEXT PRIMARY KEY,
            locked_until REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'reserved',
            order_id TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.commit()
    c.close()


def _reserve_signal(appmod, signal_key, temporary_seconds=90):
    """Atomically reserve this exact signal so two workers cannot submit it."""
    now = time.time()
    until = now + max(30, int(temporary_seconds))
    c = appmod.db()
    try:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(
            "SELECT locked_until,status FROM futures_entry_guard WHERE signal_key=?",
            (signal_key,),
        ).fetchone()
        if row and float(row["locked_until"] or 0) > now:
            c.execute("ROLLBACK")
            return False
        c.execute(
            """INSERT INTO futures_entry_guard(signal_key,locked_until,status,updated_at)
               VALUES(?,?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(signal_key) DO UPDATE SET
                 locked_until=excluded.locked_until,
                 status=excluded.status,
                 updated_at=CURRENT_TIMESTAMP""",
            (signal_key, until, "inflight"),
        )
        c.commit()
        return True
    except Exception:
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        c.close()


def _finalize_signal(appmod, signal_key, locked_until, status, order_id=None):
    c = appmod.db()
    c.execute(
        """UPDATE futures_entry_guard
           SET locked_until=?, status=?, order_id=?, updated_at=CURRENT_TIMESTAMP
           WHERE signal_key=?""",
        (float(locked_until), status, str(order_id or ""), signal_key),
    )
    c.commit()
    c.close()


def install(appmod):
    _init_guard(appmod)

    original_prepare = getattr(appmod, "_futures_bot_prepare_real", None)
    original_execute = getattr(appmod, "_futures_bot_execute_real", None)
    if original_execute is None:
        raise RuntimeError("Expected Futures executor was not found")

    # Persist the exact signal candle selected for execution.
    if original_prepare is not None:
        def patched_prepare(timeframe="15m"):
            result = original_prepare(timeframe)
            try:
                bot = result.get("bot") or {}
                if result.get("ok") and bot.get("status") == "ready":
                    key = _signal_key(appmod, bot)
                    # Store the candle key without changing the existing strategy.
                    appmod._futures_bot_write({"entry_signal_key": key})
                    bot = appmod._futures_bot_read()
                    result["bot"] = bot
            except Exception as exc:
                print("[AUTO-FUTURES] signal guard prepare warning: {}: {}".format(
                    type(exc).__name__, str(exc)[:180]
                ), flush=True)
            return result
        appmod._futures_bot_prepare_real = patched_prepare

    def patched_execute():
        import os

        if not os.getenv("BINANCE_API_KEY", "").strip() or not os.getenv("BINANCE_API_SECRET", "").strip():
            return {"ok": False, "message": "BINANCE_API_KEY و BINANCE_API_SECRET غير مهيأة في Northflank"}

        state = appmod._futures_bot_read()
        if state.get("status") != "ready":
            return {"ok": False, "message": "لا توجد صفقة جاهزة للتنفيذ", "bot": state}

        symbol = str(state.get("symbol") or "").upper()
        side = str(state.get("side") or "BUY").upper()
        if not symbol.endswith("USDT") or side not in ("BUY", "SELL"):
            return {"ok": False, "message": "بيانات الصفقة غير صالحة", "bot": state}

        signal_key = str(state.get("entry_signal_key") or _signal_key(appmod, state))

        # Never submit the same signal twice, even after a position was closed.
        if not _reserve_signal(appmod, signal_key, temporary_seconds=90):
            print("[AUTO-FUTURES] DUPLICATE SIGNAL BLOCKED key={}".format(signal_key), flush=True)
            appmod._futures_bot_write({
                "status": "idle",
                "enabled": 0,
                "auto_enabled": 0,
                "last_error": "تم منع إعادة الدخول لنفس إشارة/شمعة التداول",
            })
            return {
                "ok": False,
                "real_orders": True,
                "message": "تم منع إعادة الدخول لنفس الإشارة",
                "bot": appmod._futures_bot_read(),
            }

        entry_order = None
        try:
            rules = appmod._futures_symbol_rules(symbol)
            entry = float(state.get("entry") or 0)
            balance, status = appmod._futures_available_usdt()
            if balance is None or balance <= 0 or entry <= 0:
                raise RuntimeError("الرصيد أو سعر الدخول غير صالح")

            max_leverage = appmod._futures_max_leverage(symbol)
            if max_leverage < 1:
                raise RuntimeError("الرمز لا يدعم رافعة صالحة")
            leverage = min(20, int(max_leverage))
            qty, margin = appmod._futures_order_quantity(balance, entry, leverage, rules)

            # Verify account state immediately before the write.
            live_positions = appmod._futures_any_live_positions()
            if live_positions is None:
                raise RuntimeError("تعذر التحقق من مراكز Binance قبل الدخول")
            if live_positions:
                symbols = ", ".join(x["symbol"] for x in live_positions[:6])
                raise RuntimeError("يوجد مركز Futures مفتوح مسبقاً: {}".format(symbols))

            existing = appmod._futures_exchange_position_info(symbol)
            if existing and float(existing.get("quantity") or 0) > 0:
                raise RuntimeError("يوجد مركز حقيقي مفتوح مسبقاً على {}".format(symbol))

            appmod._binance_futures_signed_request(
                "POST", "/fapi/v1/leverage",
                {"symbol": symbol, "leverage": leverage},
            )

            dual = appmod._binance_futures_signed_request(
                "GET", "/fapi/v1/positionSide/dual"
            )
            hedge = bool(dual.get("dualSidePosition"))
            position_side = ("LONG" if side == "BUY" else "SHORT") if hedge else None

            entry_params = {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": appmod._format_step_value(qty, rules["step_size"]),
                "newOrderRespType": "RESULT",
            }
            if position_side:
                entry_params["positionSide"] = position_side

            print("[AUTO-FUTURES] REAL ENTRY SUBMIT symbol={} side={} tf={} key={}".format(
                symbol, side, state.get("timeframe"), signal_key
            ), flush=True)

            entry_order = appmod._binance_futures_signed_request(
                "POST", "/fapi/v1/order", entry_params
            )

            actual_qty = float(entry_order.get("executedQty") or 0)
            actual_entry = float(entry_order.get("avgPrice") or entry_order.get("price") or 0)

            if actual_qty <= 0 or actual_entry <= 0:
                live = appmod._futures_exchange_position_info(symbol)
                if live and float(live.get("quantity") or 0) > 0 and float(live.get("entry_price") or 0) > 0:
                    actual_qty = float(live["quantity"])
                    actual_entry = float(live["entry_price"])
                else:
                    raise RuntimeError("أمر الدخول لم يُؤكد فعلياً")

            now_iso = _utc_now().isoformat()

            # IMPORTANT: keep the strategy's real price SL. Do not divide it by leverage.
            # The old patch made a 5% strategy stop become 0.25% at 20x, causing instant exits.
            strategy_sl = float(state.get("sl") or 0)
            if side == "BUY":
                valid_sl = 0 < strategy_sl < actual_entry
            else:
                valid_sl = strategy_sl > actual_entry
            sl = strategy_sl if valid_sl else (
                actual_entry * 0.98 if side == "BUY" else actual_entry * 1.02
            )
            distance_pct = abs(actual_entry - sl) / actual_entry * 100
            if distance_pct < 0.75 or distance_pct > 10:
                sl = actual_entry * 0.02
                sl = actual_entry * (0.98 if side == "BUY" else 1.02)

            # Preserve the existing UI targets, but the exchange-side hard safety order is SL.
            tp1 = float(state.get("tp1") or (actual_entry * (1.05 if side == "BUY" else 0.95)))
            tp2 = float(state.get("tp2") or (actual_entry * (1.075 if side == "BUY" else 0.925)))
            tp3 = float(state.get("tp3") or (actual_entry * (1.10 if side == "BUY" else 0.90)))

            appmod._futures_bot_write({
                "enabled": 1,
                "auto_enabled": 1,
                "status": "open",
                "entry": actual_entry,
                "quantity": actual_qty,
                "balance_usdt": balance,
                "margin_usdt": margin,
                "notional_usdt": margin * leverage,
                "leverage": leverage,
                "tp1": tp1,
                "tp2": tp2,
                "tp3": tp3,
                "sl": sl,
                "opened_at": now_iso,
                "last_price": actual_entry,
                "last_checked_at": now_iso,
                "peak_profit_pct": 0,
                "protected_profit_pct": 0,
                "protection_price": sl,
                "outcome": None,
                "realized_pct": None,
                "halted": 0,
                "last_error": None,
                "entry_signal_key": signal_key,
                "entry_order_id": str(entry_order.get("orderId") or ""),
            })

            tick = rules["tick_size"]
            sl_price = appmod._round_step(sl, tick)
            close_side = "SELL" if side == "BUY" else "BUY"

            # Binance Futures now requires conditional STOP orders through the Algo API.
            # One hard SL is deliberately used; no 3-TP Algo burst after entry.
            sl_params = {
                "algoType": "CONDITIONAL",
                "symbol": symbol,
                "side": close_side,
                "type": "STOP_MARKET",
                "workingType": "MARK_PRICE",
                "triggerPrice": appmod._format_step_value(sl_price, tick),
            }
            if position_side:
                sl_params["positionSide"] = position_side
                sl_params["quantity"] = appmod._format_step_value(actual_qty, rules["step_size"])
            else:
                sl_params["closePosition"] = "true"

            sl_order = appmod._binance_futures_signed_request(
                "POST", "/fapi/v1/algoOrder", sl_params
            )

            live_orders = appmod._futures_open_protection_orders(symbol)
            sl_ok = any(
                str(o.get("orderType", o.get("type", ""))).upper() == "STOP_MARKET"
                and str(o.get("algoStatus", "NEW")).upper() == "NEW"
                for o in live_orders
            )
            if not sl_ok:
                raise RuntimeError("Binance لم يؤكد وقف الخسارة بعد الدخول")

            _finalize_signal(
                appmod,
                signal_key,
                _candle_end_epoch(appmod, state),
                "executed",
                entry_order.get("orderId"),
            )

            print(
                "[AUTO-FUTURES] PROTECTION PLACED symbol={} SL={} algoId={}".format(
                    symbol, appmod._format_step_value(sl_price, tick), sl_order.get("algoId")
                ),
                flush=True,
            )

            return {
                "ok": True,
                "real_orders": True,
                "message": "تم فتح الصفقة ووقف الخسارة الحقيقي مؤكد على Binance",
                "bot": appmod._futures_bot_read(),
                "orders": [("SL", sl_order)],
            }

        except Exception as exc:
            detail = "{}: {}".format(type(exc).__name__, str(exc)[:500])
            current = appmod._futures_bot_read()

            # If no exchange position exists, allow a later retry after a short cooldown.
            # If a position exists but protection failed, close once and HALT.
            symbol2 = str(current.get("symbol") or symbol).upper()
            try:
                exchange_qty = float(appmod._futures_exchange_position(symbol2) or 0)
            except Exception:
                exchange_qty = 0.0

            if exchange_qty > 0:
                try:
                    open_orders = appmod._futures_open_protection_orders(symbol2)
                    has_sl = any(
                        str(o.get("orderType", o.get("type", ""))).upper() == "STOP_MARKET"
                        and str(o.get("algoStatus", "NEW")).upper() == "NEW"
                        for o in open_orders
                    )
                except Exception:
                    has_sl = False

                if not has_sl:
                    try:
                        appmod._futures_emergency_close(
                            symbol2,
                            str(current.get("side") or side),
                            attempts=3,
                        )
                    except Exception as close_exc:
                        print(
                            "[AUTO-FUTURES] emergency close failed symbol={} error={}: {}".format(
                                symbol2, type(close_exc).__name__, str(close_exc)[:220]
                            ),
                            flush=True,
                        )

                appmod._futures_halt(
                    "فشل حماية الصفقة بعد الدخول؛ تم منع أي إعادة دخول تلقائياً"
                )
                appmod._futures_bot_write({
                    "last_error": detail,
                    "halt_reason": "فشل حماية الصفقة بعد الدخول؛ تم منع أي إعادة دخول تلقائياً",
                })
                _finalize_signal(
                    appmod,
                    signal_key,
                    _candle_end_epoch(appmod, current),
                    "protection_failed",
                    (entry_order or {}).get("orderId"),
                )
                print("[AUTO-FUTURES] PROTECTION ERROR; no re-entry", flush=True)
            else:
                # No live position: do not leave the guard permanently stuck.
                _finalize_signal(
                    appmod,
                    signal_key,
                    time.time() + 60,
                    "retry_cooldown",
                    (entry_order or {}).get("orderId"),
                )
                appmod._futures_bot_write({
                    "status": "idle",
                    "enabled": 0,
                    "auto_enabled": 0,
                    "halted": 0,
                    "last_error": detail,
                })

            return {
                "ok": False,
                "real_orders": True,
                "message": "فشل التنفيذ الحقيقي",
                "detail": detail,
                "bot": appmod._futures_bot_read(),
            }

    appmod._futures_bot_execute_real = patched_execute
    print(
        "[AUTO-FUTURES] runtime safety patch installed: one-entry-per-signal + one Algo SL",
        flush=True,
    )
