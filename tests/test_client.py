from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from hory.staying import RawStore, StayingClient


class _Handler(BaseHTTPRequestHandler):
    calls: list[str] = []
    job_polls = 0

    def log_message(self, format: str, *args) -> None:
        return

    def _send(self, status: int, payload: dict, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        type(self).calls.append(self.path)
        if parsed.path == "/v1/account":
            self._send(
                200,
                {
                    "data": {
                        "plan": {"code": "free", "name": "Free", "status": "active"},
                        "key": {"env": "sandbox"},
                        "credits": {"balance": 300, "available": 300, "held": 0},
                        "rateLimit": {"requestsPerMinute": 30},
                    }
                },
            )
            return
        if parsed.path == "/v1/search":
            self._send(
                202,
                {
                    "data": {
                        "jobId": "job_1",
                        "status": "pending",
                        "pollUrl": "/v1/jobs/job_1",
                        "estimatedSeconds": 1,
                    },
                    "meta": {"requestId": "req_202", "creditsCharged": 0},
                },
                {"Retry-After": "0.1"},
            )
            return
        if parsed.path == "/v1/jobs/job_1":
            type(self).job_polls += 1
            if type(self).job_polls == 1:
                self._send(
                    200,
                    {
                        "data": {"jobId": "job_1", "status": "running", "estimatedSeconds": 1},
                        "meta": {"requestId": "req_poll", "creditsCharged": 0},
                    },
                )
                return
            self._send(
                200,
                {
                    "data": {
                        "jobId": "job_1",
                        "status": "completed",
                        "result": [
                            {
                                "id": "stays_airbnb_1",
                                "platform": "airbnb",
                                "platformListingId": "1",
                                "name": "Chalet Test",
                                "propertyType": "house",
                                "location": {"lat": 47.39, "lng": 13.68},
                                "maxOccupancy": 15,
                            }
                        ],
                    },
                    "meta": {
                        "requestId": "req_done",
                        "platforms": ["airbnb", "booking"],
                        "cached": False,
                        "partial": False,
                        "creditsCharged": 7,
                        "pagination": None,
                        "platformResults": [
                            {
                                "platform": "airbnb",
                                "status": "ok",
                                "creditsCharged": 7,
                                "cached": False,
                                "count": 1,
                            }
                        ],
                        "warnings": [],
                    },
                },
            )
            return
        if parsed.path == "/v1/price":
            self._send(
                400,
                {
                    "error": {
                        "type": "invalid_request",
                        "code": "no_availability",
                        "message": "No single room fits",
                        "param": None,
                        "requestId": "req_400",
                        "creditsCharged": 0,
                        "retryable": False,
                    }
                },
            )
            return
        if parsed.path == "/v1/fatal":
            self._send(
                401,
                {
                    "error": {
                        "type": "authentication_error",
                        "code": "invalid_api_key",
                        "message": "Bad key",
                        "requestId": "req_401",
                        "creditsCharged": 0,
                        "retryable": False,
                    }
                },
            )
            return
        self._send(404, {"error": {"code": "not_found", "message": "not found"}})


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        _Handler.calls = []
        _Handler.job_polls = 0
        self.tempdir = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.tempdir.name) / "run"
        self.store = RawStore(self.run_dir)
        self.client = StayingClient(
            "stay_test_unit",
            base_url=self.base_url,
            store=self.store,
            max_wait=5,
            min_interval=0,
        )
        self.client.session.trust_env = False

    def tearDown(self) -> None:
        self.client.close()
        self.tempdir.cleanup()

    def test_async_job_and_query_encoding(self) -> None:
        result = self.client.call(
            "/v1/search",
            {
                "location": "Schladming, Austria",
                "childAges": [6, 9],
                "platforms": "airbnb,booking",
            },
            role="search_test",
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.credits, 7)
        self.assertEqual(result.meta.get("requestId"), "req_done")
        self.assertEqual(result.data[0]["name"], "Chalet Test")
        self.assertTrue((self.run_dir / result.raw_file).exists())

        search_call = _Handler.calls[0]
        query = parse_qs(urlparse(search_call).query)
        self.assertEqual(query["childAges"], ["6", "9"])
        self.assertEqual(query["platforms"], ["airbnb,booking"])
        manifest = (self.run_dir / "manifest.jsonl").read_text(encoding="utf-8").strip()
        self.assertIn("search_test", manifest)

    def test_error_is_recorded_and_not_fatal(self) -> None:
        result = self.client.call("/v1/price", {"platform": "booking"}, role="price_test")
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "no_availability")
        self.assertFalse(result.fatal)
        self.assertEqual(result.credits, 0)
        self.assertTrue((self.run_dir / result.raw_file).exists())

    def test_auth_error_is_fatal(self) -> None:
        result = self.client.call("/v1/fatal", {}, role="fatal_test")
        self.assertFalse(result.ok)
        self.assertTrue(result.fatal)

    def test_account_is_free(self) -> None:
        result = self.client.account()
        self.assertTrue(result.ok)
        self.assertEqual(result.credits, 0)
        self.assertEqual(result.data["credits"]["available"], 300)


if __name__ == "__main__":
    unittest.main()
