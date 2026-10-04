"""Runtime safety patch for the real USD-M Futures worker.

Loaded before Uvicorn starts so the existing app can keep its UI/API while
replacing the protection sequence that was creating multiple Binance Algo
orders immediately after entry.
"""
from datetime import datetime, timezone


def install(appmod):
    original = getattr(appmod, "_futures_bot_execute_real", None)
    if original is None:
        raise RuntimeError("Expected Futures executor was not found")

    def patched_futures_bot_execute_real():
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

            appmod._binance_futures_signed_request(
                "POST", "/fapi/v1/leverage",
                {"symbol": symbol, "leverage": leverage},
            )

            dual = appmod._binance_futures_signed_request(
                "GET", "/fapi/v1/positionSide/dual"
            )
            hedge = bool(dual.get("dualSidePosition"))
            position_side = ("LONG" if side == "BUY" else "SHORT") if hedge else None

            live_positions = appmod._futures_any_live_positions()
            if live_positions is None:
                raise RuntimeError("تعذر التحقق من مراكز Binance قبل الدخول")
            if live_positions:
                symbols = ", ".join(x["symbol"] for x in live_positions[:6])
                raise RuntimeError("يوجد مركز Futures مفتوح مسبقاً: {}".format(symbols))

            existing = appmod._futures_exchange_position_info(symbol)
            if existing and float(existing.get("quantity") or 0) > 0:
                raise RuntimeError("يوجد مركز حقيقي مفتوح مسبقاً على {}".format(symbol))

            # Do not spam/cancel Algo orders here. Binance currently rate-limits
            # Algo placement to one order per 10 seconds and one per minute.
            entry_params = {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": appmod._format_step_value(qty, rules["step_size"]),
                "newOrderRespType": "RESULT",
            }
            if position_side:
                entry_params["positionSide"] = position_side

            entry_order = appmod._binance_futures_signed_request(
                "POST", "/fapi/v1/order", entry_params
            )

            actual_qty = float(entry_order.get("executedQty") or 0)
            actual_entry = float(
                entry_order.get("avgPrice")
                or entry_order.get("price")
                or 0
            )

            if actual_qty <= 0 or actual_entry <= 0:
                live = appmod._futures_exchange_position_info(symbol)
                if live and float(live.get("quantity") or 0) > 0 and float(live.get("entry_price") or 0) > 0:
                    actual_qty = float(live["quantity"])
                    actual_entry = float(live["entry_price"])
                else:
                    raise RuntimeError("أمر الدخول لم يُؤكد فعلياً")

            now = datetime.now(timezone.utc).isoformat()

            # Keep the site's existing target model, but do NOT create three
            # additional Algo orders. The exchange-side SL is the hard safety net.
            tp1 = actual_entry * (1 + (5.0 / leverage) / 100) if side == "BUY" else actual_entry * (1 - (5.0 / leverage) / 100)
            tp2 = actual_entry * (1 + (7.5 / leverage) / 100) if side == "BUY" else actual_entry * (1 - (7.5 / leverage) / 100)
            tp3 = actual_entry * (1 + (10.0 / leverage) / 100) if side == "BUY" else actual_entry * (1 - (10.0 / leverage) / 100)
            sl = actual_entry * (1 - (5.0 / leverage) / 100) if side == "BUY" else actual_entry * (1 + (5.0 / leverage) / 100)

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
                "opened_at": now,
                "last_price": actual_entry,
                "last_checked_at": now,
                "peak_profit_pct": 0,
                "protected_profit_pct": 0,
                "protection_price": sl,
                "outcome": None,
                "realized_pct": None,
                "halted": 0,
                "last_error": None,
            })

            tick = rules["tick_size"]
            sl_price = appmod._round_step(sl, tick)
            close_side = "SELL" if side == "BUY" else "BUY"

            # One exchange-side hard stop only. Quantity mode is compatible
            # with both one-way and hedge mode; reduceOnly is omitted in hedge.
            sl_params = {
                "algoType": "CONDITIONAL",
                "symbol": symbol,
                "side": close_side,
                "type": "STOP_MARKET",
                "quantity": appmod._format_step_value(actual_qty, rules["step_size"]),
                "workingType": "MARK_PRICE",
                "triggerPrice": appmod._format_step_value(sl_price, tick),
            }
            if position_side:
                sl_params["positionSide"] = position_side
            else:
                sl_params["reduceOnly"] = "true"

            sl_order = appmod._binance_futures_signed_request(
                "POST", "/fapi/v1/algoOrder", sl_params
            )

            live_orders = appmod._futures_open_protection_orders(symbol)
            sl_ok = any(
                str(o.get("orderType", o.get("type", ""))).upper() == "STOP_MARKET"
                for o in live_orders
            )
            if not sl_ok:
                raise RuntimeError("Binance لم يؤكد وقف الخسارة بعد الدخول")

            print(
                "[AUTO-FUTURES] PROTECTION PLACED symbol={} SL=OK algoId={}".format(
                    symbol, sl_order.get("algoId")
                ),
                flush=True,
            )

            return {
                "ok": True,
                "real_orders": True,
                "message": "تم فتح الصفقة ووضع وقف الخسارة الحقيقي على Binance",
                "bot": appmod._futures_bot_read(),
                "orders": [("SL", sl_order)],
            }

        except Exception as exc:
            current = appmod._futures_bot_read()
            detail = "{}: {}".format(type(exc).__name__, str(exc)[:500])

            # Never re-enter after a protection failure. If the market order
            # filled but the SL could not be confirmed, close once and halt.
            if current.get("status") == "open":
                symbol2 = str(current.get("symbol") or "").upper()
                try:
                    open_orders = appmod._futures_open_protection_orders(symbol2)
                    has_sl = any(
                        str(o.get("orderType", o.get("type", ""))).upper() == "STOP_MARKET"
                        for o in open_orders
                    )
                except Exception:
                    has_sl = False

                if not has_sl:
                    try:
                        q2 = float(appmod._futures_exchange_position(symbol2) or 0)
                        if q2 > 0:
                            rules2 = appmod._futures_symbol_rules(symbol2)
                            qty2 = appmod._floor_step(q2, rules2.get("step_size", 0))
                            dual2 = appmod._binance_futures_signed_request(
                                "GET", "/fapi/v1/positionSide/dual"
                            )
                            side2 = str(current.get("side") or "BUY").upper()
                            ps2 = (
                                ("LONG" if side2 == "BUY" else "SHORT")
                                if bool(dual2.get("dualSidePosition"))
                                else None
                            )
                            if qty2 > 0:
                                appmod._futures_market_close(symbol2, side2, qty2, ps2)
                                print(
                                    "[AUTO-FUTURES] protection missing; one emergency close sent symbol={}".format(symbol2),
                                    flush=True,
                                )
                    except Exception as close_exc:
                        print(
                            "[AUTO-FUTURES] emergency close failed symbol={} error={}: {}".format(
                                symbol2, type(close_exc).__name__, str(close_exc)[:220]
                            ),
                            flush=True,
                        )

                appmod._futures_halt("فشل وضع وقف الحماية؛ تم منع إعادة الدخول")
                appmod._futures_bot_write({
                    "last_error": detail,
                    "halt_reason": "فشل وضع وقف الحماية؛ تم منع إعادة الدخول",
                })
                print("[AUTO-FUTURES] PROTECTION ERROR; no re-entry", flush=True)

            elif current.get("status") == "ready":
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

    appmod._futures_bot_execute_real = patched_futures_bot_execute_real
    print("[AUTO-FUTURES] runtime protection patch installed: one exchange-side SL per entry", flush=True)
