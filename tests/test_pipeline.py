from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from hory.probe import main


def _property(platform: str, listing_id: str, name: str, property_type: str, max_occupancy: int, total: float) -> dict:
    return {
        "id": f"stays_{platform}_{listing_id}",
        "platform": platform,
        "platformListingId": listing_id,
        "url": f"https://example.test/{platform}/{listing_id}",
        "name": name,
        "propertyType": property_type,
        "location": {"lat": 47.39, "lng": 13.68, "country": "AT", "city": "Schladming"},
        "maxOccupancy": max_occupancy,
        "bedrooms": 3,
        "bathrooms": 1,
        "amenities": ["parking_free", "crib"],
        "images": ["https://example.test/a.jpg"],
        "host": {"name": "Host"},
        "price": {"currency": "EUR", "nightlyPrice": total / 4, "totalPrice": total, "nights": 4},
    }


PROPERTIES = [
    _property("booking", "house1", "Chalet Alpenblick", "house", 15, 2000),
    _property("booking", "apt1", "Apartments Alpenblick", "apartment", 4, 900),
    _property("airbnb", "111", "Chalet Alpenblick", "house", 15, 1900),
    _property("airbnb", "222", "Apartment Alpenblick 2", "apartment", 4, 500),
]


class _Handler(BaseHTTPRequestHandler):
    requests: list[str] = []

    def log_message(self, format: str, *args) -> None:
        return

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        type(self).requests.append(self.path)
        query = parse_qs(parsed.query)
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
                200,
                {
                    "data": PROPERTIES,
                    "meta": {
                        "requestId": "req_search",
                        "platforms": ["airbnb", "booking"],
                        "cached": False,
                        "partial": False,
                        "creditsCharged": 20,
                        "pagination": {"limit": 10, "nextCursor": None, "hasMore": False},
                        "platformResults": [
                            {"platform": "airbnb", "status": "ok", "creditsCharged": 12, "count": 2},
                            {"platform": "booking", "status": "ok", "creditsCharged": 8, "count": 2},
                        ],
                        "warnings": [],
                    },
                },
            )
            return
        if parsed.path.startswith("/v1/listing/"):
            listing_id = parsed.path.rsplit("/", 1)[-1]
            prop = next((item for item in PROPERTIES if item["platformListingId"] == listing_id), PROPERTIES[0])
            self._send(
                200,
                {
                    "data": dict(prop, identity={"requestedId": listing_id, "resolvedId": listing_id}),
                    "meta": {"requestId": "req_listing", "creditsCharged": 3, "warnings": []},
                },
            )
            return
        if parsed.path == "/v1/price":
            listing_id = (query.get("listingId") or [""])[0]
            adults = int((query.get("adults") or ["2"])[0])
            if "apt" in listing_id and adults >= 12:
                self._send(
                    400,
                    {
                        "error": {
                            "type": "invalid_request",
                            "code": "no_availability",
                            "message": "No single room fits the party",
                            "requestId": "req_price",
                            "creditsCharged": 0,
                            "retryable": False,
                        }
                    },
                )
                return
            total = 2000 if listing_id in {"111", "house1"} else 800
            self._send(
                200,
                {
                    "data": {
                        "platform": "booking" if listing_id in {"house1", "apt1"} else "airbnb",
                        "listingId": listing_id,
                        "currency": "EUR",
                        "nightlyPrice": total / 4,
                        "totalPrice": total,
                        "priceBasis": "quoted_total",
                        "fees": {"cleaning": 50, "service": None, "taxes": 100},
                        "nights": 4,
                        "occupancy": {
                            "adults": adults,
                            "children": int((query.get("children") or ["0"])[0]),
                            "childAges": [int(value) for value in query.get("childAges", [])],
                        },
                        "url": f"https://example.test/price/{listing_id}",
                    },
                    "meta": {"requestId": "req_price", "creditsCharged": 3, "warnings": []},
                },
            )
            return
        self._send(404, {"error": {"code": "not_found", "message": "not found"}})


class PipelineTests(unittest.TestCase):
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

    def test_end_to_end_report(self) -> None:
        os.environ["NO_PROXY"] = "127.0.0.1,localhost"
        os.environ["no_proxy"] = "127.0.0.1,localhost"
        os.environ["STAYINGAPI_BASE_URL"] = self.base_url
        os.environ["STAYINGAPI_KEY"] = "stay_test_pipeline"
        with tempfile.TemporaryDirectory() as tempdir:
            code = main(
                [
                    "--out",
                    tempdir,
                    "--allow-sandbox",
                    "--min-interval",
                    "0",
                    "--max-credits",
                    "200",
                    "--detail-candidates",
                    "4",
                    "--split-probes",
                    "1",
                    "--max-sub-searches",
                    "2",
                ]
            )
            self.assertEqual(code, 0)
            runs = list(Path(tempdir).iterdir())
            self.assertEqual(len(runs), 1)
            run_dir = runs[0]
            self.assertTrue((run_dir / "report.md").exists())
            self.assertTrue((run_dir / "summary.json").exists())
            self.assertTrue((run_dir / "candidates.csv").exists())
            self.assertTrue((run_dir / "analysis_inputs.json").exists())
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["answers"]["q1_scope"]["status"], "ČÁSTEČNĚ")
            self.assertEqual(summary["answers"]["q5_credit_cost"]["status"], "ANO (změřeno)")
            self.assertGreater(summary["credits"]["total"], 0)
            self.assertTrue(any(item["key"] == "whole" for item in summary["searches"]))
            report_text = (run_dir / "report.md").read_text(encoding="utf-8")
            self.assertIn("Odpovědi na ověřovací otázky", report_text)
            self.assertIn("Kredity", report_text)

            reanalyze_code = main(["--reanalyze", str(run_dir)])
            self.assertEqual(reanalyze_code, 0)


if __name__ == "__main__":
    unittest.main()
