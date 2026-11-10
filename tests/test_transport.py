"""Real Qt HTTP transport against a local, controlled HTTP server only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
import unittest
from unittest.mock import patch
from PySide6.QtTest import QTest
from rivenscope.network import Transport, USER_AGENT
from .test_integration import APP, wait_for, FIXTURES


class Handler(BaseHTTPRequestHandler):
    mode = "success"
    seen = []

    def do_GET(self):
        Handler.seen.append(dict(self.headers))
        if Handler.mode == "timeout": time.sleep(.3)
        code = 429 if Handler.mode == "limit" else 503 if Handler.mode == "error" else 200
        body = (FIXTURES / "versions.json").read_bytes()
        if Handler.mode == "oversized": body = b"x" * (4 * 1024 * 1024 + 100000)
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if code == 429: self.send_header("Retry-After", "120")
        self.end_headers()
        try: self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError): pass

    def log_message(self, *args): pass


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(2)

    def request(self, mode, timeout=1000):
        Handler.mode=mode; results=[]
        transport=Transport(timeout_ms=timeout); transport.finished.connect(results.append)
        with patch("rivenscope.network.BASE_URL", f"http://127.0.0.1:{self.server.server_port}"):
            transport.get("versions")
            self.assertTrue(wait_for(lambda:results))
        self.assertIsNone(transport.reply); self.assertFalse(transport.deadline.isActive())
        return results[0]

    def test_http_headers_limits_server_error_and_reconnect(self):
        self.assertEqual(self.request("success").status,200)
        headers={name.lower():value for name,value in Handler.seen[-1].items()}
        self.assertEqual(headers["user-agent"],USER_AGENT)
        self.assertEqual(headers["crossplay"],"true")
        result=self.request("limit"); self.assertEqual(result.status,429); self.assertEqual(result.retry_after,"120")
        self.assertEqual(self.request("error").status,503)
        self.assertEqual(self.request("success").status,200)

    def test_timeout_and_response_size_limit(self):
        result=self.request("timeout",40); self.assertEqual(result.status,0); self.assertTrue(result.error)
        result=self.request("oversized"); self.assertEqual(result.status,0); self.assertIn("4 MB",result.error)

    def test_cancel_active_request(self):
        Handler.mode="timeout"; transport=Transport(); results=[]; transport.finished.connect(results.append)
        with patch("rivenscope.network.BASE_URL", f"http://127.0.0.1:{self.server.server_port}"):
            transport.get("versions"); transport.abort()
            self.assertTrue(wait_for(lambda:results))
        self.assertTrue(results[0].cancelled)
