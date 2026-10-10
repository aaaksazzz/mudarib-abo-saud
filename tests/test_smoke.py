import ast
import re
import unittest
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
        self.assertEqual(ui_frames, backend_frames)
        engine_line = re.search(r'if timeframe not in \{([^}]+)\}: timeframe="15m"', engine)
        self.assertIsNotNone(engine_line)
        engine_frames = set(re.findall(r'"([^"]+)"', engine_line.group(1)))
        self.assertTrue(set(backend_frames).issubset(engine_frames))

    def test_market_navigation_only_keeps_method_pages_on_technical_page(self):
        js = source("static/app.js")
        self.assertIn('page==="technical"&&marketKeys.indexOf(s)>=0', js)
        self.assertIn('if(routes[s]){window.location.href=routes[s];}', js)

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


if __name__ == "__main__":
    unittest.main()
