from __future__ import annotations

import json
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable

import requests

DEFAULT_BASE_URL = "https://api.stayingapi.com"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_dotenv(path: str | Path | None = None) -> Path | None:
    env_path = Path(path or os.environ.get("HORY_ENV_FILE", ".env"))
    if not env_path.exists():
        return None
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
    return env_path


class StayingAPIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        type_: str | None = None,
        code: str | None = None,
        param: str | None = None,
        retryable: bool = False,
        request_id: str | None = None,
        credits: int = 0,
        doc_url: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.type = type_
        self.code = code
        self.param = param
        self.retryable = retryable
        self.request_id = request_id
        self.credits = credits
        self.doc_url = doc_url
        self.payload = payload

    @property
    def fatal(self) -> bool:
        if self.status in (401, 402, 403):
            return True
        return self.code in {
            "missing_api_key",
            "invalid_api_key",
            "revoked_api_key",
            "insufficient_credits",
            "credit_balance_too_low",
            "email_unverified",
            "free_tier_budget_exhausted",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": str(self),
            "status": self.status,
            "type": self.type,
            "code": self.code,
            "param": self.param,
            "retryable": self.retryable,
            "request_id": self.request_id,
            "credits_charged": self.credits,
            "doc_url": self.doc_url,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None, status: int | None) -> "StayingAPIError":
        error = (payload or {}).get("error") or {}
        return cls(
            error.get("message") or f"HTTP {status}",
            status=status,
            type_=error.get("type"),
            code=error.get("code"),
            param=error.get("param"),
            retryable=bool(error.get("retryable")),
            request_id=error.get("requestId"),
            credits=int(error.get("creditsCharged") or 0),
            doc_url=error.get("docUrl"),
            payload=payload,
        )

    @classmethod
    def from_job(cls, error: dict[str, Any], body: dict[str, Any]) -> "StayingAPIError":
        return cls(
            error.get("message") or "Asynchronní úloha selhala",
            status=200,
            type_=error.get("type"),
            code=error.get("code"),
            retryable=bool(error.get("retryable")),
            request_id=(body.get("meta") or {}).get("requestId"),
            credits=int((body.get("meta") or {}).get("creditsCharged") or 0),
            payload=body,
        )


@dataclass
class CallResult:
    ok: bool
    payload: dict[str, Any] | None
    error: StayingAPIError | None
    http_status: int | None
    credits: int
    duration_s: float
    raw_file: str | None
    job: dict[str, Any] | None
    fatal: bool

    @property
    def data(self) -> Any:
        return (self.payload or {}).get("data")

    @property
    def meta(self) -> dict[str, Any]:
        return (self.payload or {}).get("meta") or {}


class RawStore:
    def __init__(self, run_dir: str | Path) -> None:
        self.run_dir = Path(run_dir)
        self.raw_dir = self.run_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.run_dir / "manifest.jsonl"
        self._seq = 0

    def save(
        self,
        role: str,
        params: dict[str, Any],
        payload: dict[str, Any] | None,
        http_status: int | None,
        duration_s: float,
        credits: int,
        job: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> str:
        self._seq += 1
        safe_role = re.sub(r"[^A-Za-z0-9_.-]+", "_", role).strip("_")[:60] or "call"
        rel_path = f"raw/{self._seq:04d}_{safe_role}.json"
        body = payload if payload is not None else {"_probe_error": error or {}}
        (self.run_dir / rel_path).write_text(
            json.dumps(body, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        meta = (payload or {}).get("meta") or {}
        nested_error = ((payload or {}).get("error") or {}) if error is None else error
        record = {
            "seq": self._seq,
            "created_at": now_iso(),
            "role": role,
            "params": params,
            "http_status": http_status,
            "duration_s": round(duration_s, 3),
            "credits": credits,
            "request_id": meta.get("requestId") or nested_error.get("requestId"),
            "cached": meta.get("cached"),
            "partial": meta.get("partial"),
            "warnings": meta.get("warnings") or [],
            "platform_results": meta.get("platformResults") or [],
            "error": error,
            "job": job,
            "raw_file": rel_path,
        }
        with self.manifest_path.open("a", encoding="utf-8") as manifest:
            manifest.write(json.dumps(record, ensure_ascii=False) + "\n")
        return rel_path


class StayingClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        store: RawStore,
        timeout: float = 90.0,
        max_wait: float = 900.0,
        max_retries: int = 5,
        min_interval: float | None = None,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.store = store
        self.timeout = timeout
        self.max_wait = max_wait
        self.max_retries = max_retries
        self.min_interval = min_interval or 0.0
        self.logger = logger
        self.session = requests.Session()
        self.spent_credits = 0
        self.credits_by_role: dict[str, int] = {}
        self.request_count = 0
        self.is_sandbox = api_key.startswith("stay_test_")
        self._next_allowed = 0.0

    def _log(self, message: str) -> None:
        if self.logger:
            self.logger(message)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": "hory-stayingapi-probe/0.1",
        }

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        wait = self._next_allowed - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._next_allowed = time.monotonic() + self.min_interval

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(30.0, 1.5 ** attempt) + random.uniform(0.0, 0.4)

    @staticmethod
    def _retry_after(response: requests.Response, default: float) -> float:
        raw = response.headers.get("Retry-After")
        if raw:
            try:
                value = float(raw)
            except ValueError:
                try:
                    parsed = parsedate_to_datetime(raw)
                    value = (parsed - datetime.now(timezone.utc)).total_seconds()
                except (TypeError, ValueError):
                    value = default
            return min(120.0, max(0.5, value))
        return default

    @staticmethod
    def _json(response: requests.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise StayingAPIError(
                f"Neplatná JSON odpověď (HTTP {response.status_code}): {response.text[:200]}",
                status=response.status_code,
                retryable=response.status_code >= 500,
            ) from exc
        if not isinstance(body, dict):
            raise StayingAPIError(
                "Odpověď API není JSON objekt",
                status=response.status_code,
            )
        return body

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], int, float, dict[str, Any] | None]:
        url = self.base_url + path
        started = time.monotonic()
        attempt = 0
        while True:
            self._throttle()
            self.request_count += 1
            try:
                response = self.session.request(
                    method,
                    url,
                    params=params,
                    headers=self._headers(),
                    timeout=(15.0, self.timeout),
                )
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise StayingAPIError(
                        f"Síťová chyba: {exc}",
                        retryable=True,
                    ) from exc
                delay = self._backoff(attempt)
                self._log(f"    síťová chyba, opakuji za {delay:.1f}s: {exc}")
                time.sleep(delay)
                attempt += 1
                continue

            if response.status_code == 202:
                payload = self._json(response)
                return self._resolve_job(payload, response, started)

            if response.status_code == 429:
                if attempt >= self.max_retries:
                    raise StayingAPIError.from_payload(self._json(response), 429)
                delay = self._retry_after(response, self._backoff(attempt))
                self._log(f"    rate limit, čekám {delay:.1f}s")
                time.sleep(delay)
                attempt += 1
                continue

            if response.status_code >= 500:
                payload = self._json(response)
                if attempt >= self.max_retries:
                    raise StayingAPIError.from_payload(payload, response.status_code)
                delay = self._retry_after(response, self._backoff(attempt))
                self._log(f"    HTTP {response.status_code}, opakuji za {delay:.1f}s")
                time.sleep(delay)
                attempt += 1
                continue

            payload = self._json(response)
            duration = time.monotonic() - started
            if 200 <= response.status_code < 300:
                return payload, response.status_code, duration, None
            raise StayingAPIError.from_payload(payload, response.status_code)

    def _resolve_job(
        self,
        payload: dict[str, Any],
        initial_response: requests.Response,
        started: float,
    ) -> tuple[dict[str, Any], int, float, dict[str, Any]]:
        data = payload.get("data") or {}
        job_id = data.get("jobId")
        if not job_id:
            raise StayingAPIError("Odpověď 202 neobsahuje jobId", status=202, payload=payload)
        poll_path = data.get("pollUrl") or f"/v1/jobs/{job_id}"
        estimated = data.get("estimatedSeconds")
        delay = self._retry_after(
            initial_response,
            min(8.0, max(2.0, float(estimated or 10) / 2.0)),
        )
        poll_url = poll_path if str(poll_path).startswith("http") else self.base_url + poll_path
        deadline = time.monotonic() + self.max_wait
        polls = 0
        while True:
            if time.monotonic() >= deadline:
                raise StayingAPIError(
                    f"Úloha {job_id} nedokončena do {self.max_wait:.0f}s",
                    code="job_timeout",
                    retryable=True,
                    payload=payload,
                )
            self._log(f"    úloha {job_id}: čekám {delay:.1f}s (pokus {polls + 1})")
            time.sleep(delay)
            self._throttle()
            self.request_count += 1
            try:
                poll_response = self.session.get(
                    poll_url,
                    headers=self._headers(),
                    timeout=(15.0, self.timeout),
                )
            except requests.RequestException as exc:
                delay = min(10.0, max(2.0, delay * 1.5))
                self._log(f"    poll chyba, opakuji za {delay:.1f}s: {exc}")
                continue

            if poll_response.status_code == 429:
                delay = self._retry_after(poll_response, min(10.0, delay * 1.5))
                continue
            if poll_response.status_code >= 500:
                delay = self._retry_after(poll_response, min(10.0, delay * 1.5))
                continue
            if poll_response.status_code >= 400:
                raise StayingAPIError.from_payload(self._json(poll_response), poll_response.status_code)

            body = self._json(poll_response)
            polls += 1
            job_data = body.get("data") or {}
            status = job_data.get("status")
            if status == "completed":
                duration = time.monotonic() - started
                job = {
                    "job_id": job_id,
                    "status": status,
                    "polls": polls,
                    "estimated_seconds": estimated,
                }
                return (
                    {"data": job_data.get("result"), "meta": body.get("meta") or {}},
                    200,
                    duration,
                    job,
                )
            if status == "failed":
                error = job_data.get("error") or {}
                raise StayingAPIError.from_job(error, body)
            delay = self._retry_after(
                poll_response,
                min(10.0, max(2.0, (float(job_data.get("estimatedSeconds") or estimated or 10)) / 2.0)),
            )

    def call(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        role: str,
    ) -> CallResult:
        started = time.monotonic()
        try:
            payload, status, duration, job = self._request("GET", path, params)
        except StayingAPIError as exc:
            duration = time.monotonic() - started
            error_payload = exc.payload or {"error": exc.to_dict()}
            raw_file = self.store.save(
                role,
                params or {},
                error_payload,
                exc.status,
                duration,
                0,
                error=exc.to_dict(),
            )
            self._log(f"{role}: chyba {exc.code or exc.status} ({duration:.1f}s)")
            return CallResult(
                False,
                None,
                exc,
                exc.status,
                0,
                duration,
                raw_file,
                None,
                exc.fatal,
            )

        credits = int((payload.get("meta") or {}).get("creditsCharged") or 0)
        self.spent_credits += credits
        self.credits_by_role[role] = self.credits_by_role.get(role, 0) + credits
        raw_file = self.store.save(
            role,
            params or {},
            payload,
            status,
            duration,
            credits,
            job=job,
        )
        self._log(f"{role}: HTTP {status}, {credits} kr., {duration:.1f}s")
        return CallResult(True, payload, None, status, credits, duration, raw_file, job, False)

    def account(self) -> CallResult:
        result = self.call("/v1/account", {}, role="account")
        if not result.ok and result.error:
            raise result.error
        return result

    def close(self) -> None:
        self.session.close()
