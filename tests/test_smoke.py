import ast
import re
import unittest
import research_engine
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(name):
    return (ROOT / name).read_text(encoding="utf-8")


def routed_functions(tree, path, method=None):
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            if not isinstance(dec.func.value, ast.Name) or dec.func.value.id != "app":
                continue
            if method and dec.func.attr != method:
                continue
            if dec.args and isinstance(dec.args[0], ast.Constant) and dec.args[0].value == path:
                found.append(node)
    return found


class SmokeTests(unittest.TestCase):
    def test_python_files_parse(self):
        for name in ("app.py", "research_engine.py"):
            with self.subTest(name=name):
                ast.parse(source(name), filename=name)

    def test_timeframes_match_across_ui_and_api(self):
        app = source("app.py")
        js = source("static/app.js")
        engine = source("research_engine.py")

        backend_match = re.search(r'TIMEFRAMES\s*=\s*(\[[^\]]+\])', app)
        ui_match = re.search(r'var timeframes\s*=\s*(\[[^;]+\]);', js)
        self.assertIsNotNone(backend_match)
        self.assertIsNotNone(ui_match)
        backend_frames = ast.literal_eval(backend_match.group(1))
        ui_frames = re.findall(r'\["([^"]+)","[^"]+"\]', ui_match.group(1))
        self.assertTrue(ui_frames)
        self.assertEqual(len(ui_frames), len(set(ui_frames)), "UI timeframes must not be duplicated")
        self.assertTrue(set(ui_frames).issubset(set(backend_frames)), "Every UI timeframe must be supported by the backend")
        engine_line = re.search(r'if timeframe not in \{([^}]+)\}: timeframe="15m"', engine)
        self.assertIsNotNone(engine_line)
        engine_frames = set(re.findall(r'"([^"]+)"', engine_line.group(1)))
        self.assertTrue(set(backend_frames).issubset(engine_frames))

    def test_market_navigation_uses_unified_independent_market_feeds(self):
        js = source("static/app.js")
        self.assertIn('home:"/static/index.html"', js)
        self.assertIn('var marketKeys=["spot","futures","alpha","contracts","us","saudi","forex"]', js)
        self.assertIn('if(routes[s]){window.location.href=routes[s];}', js)
        for market in ("spot", "futures", "alpha", "contracts", "us", "saudi", "forex"):
            self.assertIn(f'{market}:"/static/public-trades.html?market={market}&hours=24"', js)
        app = source("app.py")
        for route in ("/static/spot.html", "/static/futures.html", "/static/alpha.html", "/static/contracts.html", "/static/us.html", "/static/saudi.html", "/static/forex.html"):
            self.assertIn(route, app, f"Missing legacy redirect: {route}")
        self.assertIn("legacy_market_redirects", app)

    def test_all_futures_entry_and_preflight_routes_require_login(self):
        tree = ast.parse(source("app.py"))
        for path in ("/api/futures/entry", "/api/futures/preflight"):
            handlers = routed_functions(tree, path, "post" if path.endswith("/entry") else "get")
            self.assertTrue(handlers, f"Missing route: {path}")
            for handler in handlers:
                body = ast.unparse(handler)
                with self.subTest(path=path, handler=handler.name):
                    self.assertIn("_trade_user_required", body)
                    self.assertIn("401", body)

    def test_admin_pages_check_admin_role(self):
        tree = ast.parse(source("app.py"))
        handlers = routed_functions(tree, "/admin", "get")
        self.assertTrue(handlers)
        for handler in handlers:
            body = ast.unparse(handler)
            with self.subTest(handler=handler.name):
                self.assertIn("current_user", body)
                self.assertIn("is_admin", body)

    def test_market_alias_serves_the_selected_market(self):
        app = source("app.py")
        self.assertIn('files={"spot":"spot.html","futures":"futures.html","contracts":"contracts.html","us":"us.html","saudi":"saudi.html","forex":"forex.html"}', app)


    def test_analysis_rejects_invalid_ohlcv_data(self):
        good = [
            {"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 100.0}
            for _ in range(52)
        ]
        self.assertTrue(research_engine._valid_ohlcv(good, min_count=52))

        bad_cases = []
        bad = [dict(row) for row in good]
        bad[7]["close"] = 12.0  # close above candle high
        bad_cases.append(bad)

        bad = [dict(row) for row in good]
        bad[4]["volume"] = -1.0
        bad_cases.append(bad)

        bad = [dict(row) for row in good]
        bad[3]["high"] = float("nan")
        bad_cases.append(bad)

        bad = [dict(row) for row in good]
        bad[2]["low"] = 0.0
        bad_cases.append(bad)

        for candles in bad_cases:
            with self.subTest(candles=candles[0]):
                self.assertFalse(research_engine._valid_ohlcv(candles, min_count=52))

    def test_analysis_rejects_missing_or_short_candle_series(self):
        self.assertFalse(research_engine._valid_ohlcv([], min_count=1))
        self.assertFalse(research_engine._valid_ohlcv([{}] * 52, min_count=52))
        self.assertIsNone(research_engine._method_analysis([]))

    def test_bearish_fibonacci_uses_retracement_from_swing_low(self):
        engine = source("research_engine.py")
        self.assertIn("fib_up38=swing_lo+fib_range*.382; fib_up62=swing_lo+fib_range*.618", engine)
        self.assertIn("price<closes[-3] else 0", engine)
        self.assertIn("fib_up38<=price<=fib_up62", engine)


if __name__ == "__main__":
    unittest.main()
