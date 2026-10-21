import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import urlsplit

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")

import app as app_module


class AssetReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        value = attrs.get("src") if tag == "script" else (
            attrs.get("href") if tag == "link" else None
        )
        if value and not urlsplit(value).netloc:
            self.paths.add("/" + value.lstrip("/"))


class StaticSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_pages_and_every_referenced_frontend_asset_are_served(self):
        parser = AssetReferences()
        for path in ("/", "/index.html", "/news", "/news.html"):
            with self.subTest(path=path), self.client.get(path) as response:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, "text/html")
                parser.feed(response.get_data(as_text=True))

        self.assertIn("/styles/main.css", parser.paths)
        self.assertIn("/scripts/app.js", parser.paths)
        for path in parser.paths:
            with self.subTest(path=path), self.client.get(path) as response:
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.data)

    def test_private_files_are_denied_even_when_they_exist(self):
        private_files = (
            "finance.db", "finance.db-wal", "finance.db-shm", "backup.sqlite3",
            ".env", ".gitignore", ".git/config", ".git/HEAD",
            "app.py", "database.py", "README.md", "requirements.txt",
            "Makefile", "start.sh", "scripts/bulk_archive.py",
            "scripts/internal.js", "scripts/.secret.js", "styles/private.css",
            "styles/.env", "styles/finance.db", "styles/app.py", "styles/README.md",
            "styles/.git/config", "tests/test_security.py",
            "data_service/app.py", "data_service/index.html",
            "data_service/scripts/private.js", "private.html",
        )
        # Fixtures ensure a 404 proves access was denied, not just a missing file.
        with tempfile.TemporaryDirectory() as root:
            for name in private_files:
                file = Path(root, name)
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text("private fixture")
            with patch.object(app_module.app, "root_path", root):
                for name in private_files:
                    for method in ("GET", "HEAD"):
                        with self.subTest(path=name, method=method):
                            response = self.client.open("/" + name, method=method)
                            self.assertEqual(response.status_code, 404)

    def test_traversal_encoded_paths_and_directory_requests_are_denied(self):
        for path in (
            "/styles/../app.py", "/scripts/../finance.db",
            "/styles/%2e%2e/app.py", "/%2egit/config", "/%61pp.py",
            "/scripts%2fbulk_archive.py", "/styles/../../.git/config",
            "/scripts/..%5capp.py", "/styles/main.css/../../finance.db",
            "/styles/main.css%00.py", "/finance.db?name=index.html",
            "/styles/", "/scripts/", "/data_service/", "/.git/",
            "/missing.js", "/api/missing",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_api_routes_still_take_precedence(self):
        with patch("app.md.list_symbols", return_value=[{"symbol": "AAPL"}]):
            response = self.client.get("/api/symbols")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [{"symbol": "AAPL"}])
        response = self.client.get("/api/ohlcv/AAPL?limit=0")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "limit must be a positive integer"})


def configured_app(origins=None, port=None):
    # Execute startup configuration in isolation without reloading the shared app
    # used by other test modules or changing its registered routes/hooks.
    with patch.dict(os.environ):
        for key, value in (("ALLOWED_ORIGINS", origins), ("PORT", port)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        spec = importlib.util.spec_from_file_location("app", app_module.__file__)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module.app


class CorsSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.default_app = configured_app()
        cls.custom_port_app = configured_app(port="9123")
        cls.custom_origins_app = configured_app(
            " https://desk.example.com, ,https://charts.example.org , "
        )
        cls.empty_origins_app = configured_app(" , ")
        cls.wildcard_origins_app = configured_app("https://*.example.com,.*")

    def assert_cors(self, app, origin, allowed):
        client = app.test_client()
        for method in ("GET", "OPTIONS"):
            headers = {"Origin": origin}
            if method == "OPTIONS":
                headers.update({
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Content-Type",
                })
            with self.subTest(origin=origin, method=method):
                # Validation avoids data-service/network calls for the GET.
                response = client.open("/api/ohlcv/AAPL?limit=0", method=method,
                                       headers=headers)
                self.assertEqual(response.status_code, 200 if method == "OPTIONS" else 400)
                if allowed:
                    self.assertEqual(response.headers["Access-Control-Allow-Origin"], origin)
                    if method == "OPTIONS":
                        self.assertIn("POST", response.headers["Access-Control-Allow-Methods"])
                        self.assertIn("Content-Type", response.headers["Access-Control-Allow-Headers"])
                else:
                    self.assertFalse(any(key.lower().startswith("access-control-")
                                         for key in response.headers.keys()))

    def test_default_local_origins(self):
        for origin in ("http://localhost:8050", "http://127.0.0.1:8050"):
            self.assert_cors(self.default_app, origin, True)
        for origin in (
            "https://evil.example", "null", "http://localhost:8051",
            "http://127.0.0.1:8051", "https://localhost:8050",
            "http://localhost:8050.evil.example", "http://127x0x0x1:8050",
        ):
            self.assert_cors(self.default_app, origin, False)

    def test_default_origins_follow_configured_port(self):
        for origin in ("http://localhost:9123", "http://127.0.0.1:9123"):
            self.assert_cors(self.custom_port_app, origin, True)
        self.assert_cors(self.custom_port_app, "http://localhost:8050", False)

    def test_env_origins_replace_defaults_and_match_exactly(self):
        for origin in ("https://desk.example.com", "https://charts.example.org"):
            self.assert_cors(self.custom_origins_app, origin, True)
        for origin in (
            "http://localhost:8050", "http://127.0.0.1:8050",
            "https://deskXexample.com", "https://desk.example.com.evil.example",
            "https://desk.example.com:8443", "http://desk.example.com",
            "https://desk.example.com/", "https://evil.example",
        ):
            self.assert_cors(self.custom_origins_app, origin, False)

    def test_empty_env_disables_cross_origin_access(self):
        for origin in ("http://localhost:8050", "https://evil.example", "null"):
            self.assert_cors(self.empty_origins_app, origin, False)

    def test_env_entries_are_not_wildcards_or_regexes(self):
        for origin in ("https://desk.example.com", "https://evil.example"):
            self.assert_cors(self.wildcard_origins_app, origin, False)

    def test_same_origin_requests_work_without_cors_headers(self):
        with self.default_app.test_client().get("/") as response:
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("Access-Control-Allow-Origin", response.headers)


if __name__ == "__main__":
    unittest.main()
