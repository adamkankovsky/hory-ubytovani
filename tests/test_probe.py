from __future__ import annotations

import unittest

from hory.probe import Budget, _execute_searches
from hory.staying import CallResult, StayingAPIError


def _spec(key: str) -> dict:
    return {
        "key": key,
        "label": key,
        "adults": 4,
        "children": 0,
        "child_ages": [],
        "params": {},
    }


class FakeClient:
    spent_credits = 0

    def __init__(self) -> None:
        self.calls = 0

    def call(self, path, params, *, role):
        self.calls += 1
        error = StayingAPIError(
            "All actors failed",
            status=200,
            type_="upstream_unavailable",
            code="all_actors_failed",
            retryable=True,
        )
        return CallResult(False, None, error, 200, 0, 0.1, "raw/x.json", None, False)


class SearchFailureTests(unittest.TestCase):
    def _config(self, **extra) -> dict:
        config = {
            "platforms": ["airbnb", "booking"],
            "limit": 10,
            "detail_reserve": 0,
            "search_specs": [_spec("whole"), _spec("sub1"), _spec("sub2")],
        }
        config.update(extra)
        return config

    def test_upstream_failure_stops_after_first_call(self) -> None:
        client = FakeClient()
        records = _execute_searches(client, self._config(), Budget(100))
        self.assertEqual(client.calls, 1)
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["abort"])

    def test_continue_flag_tries_all_searches(self) -> None:
        client = FakeClient()
        records = _execute_searches(
            client,
            self._config(continue_on_upstream_error=True),
            Budget(100),
        )
        self.assertEqual(client.calls, 3)
        self.assertEqual(len(records), 3)
        self.assertFalse(any(record["abort"] for record in records))


if __name__ == "__main__":
    unittest.main()
