"""
NEXUS Web Intelligence — Fetcher
Safe HTTP client built on urllib (zero external dependencies).
Features: user-agent rotation, per-domain rate limiting, retries with
exponential backoff, response size guards, and WebRules integration.
"""

from __future__ import annotations

import gzip
import json
import ssl
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .web_rules import WebRules, WebPolicy, WebRulesViolation


# ---------------------------------------------------------------------------
# User-agent pool
# ---------------------------------------------------------------------------

_USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Edge/124.0.0.0 Safari/537.36",
    "NEXUS-Intelligence/1.0 (+https://github.com/sergioworkprt-ui/nexus-ia-pessoal)",
]


# ---------------------------------------------------------------------------
# Configuration & result
# ---------------------------------------------------------------------------

@dataclass
class FetchConfig:
    timeout_seconds:    float         = 15.0
    max_retries:        int           = 3
    retry_backoff:      float         = 1.5     # multiplier between retries
    retry_initial_wait: float         = 0.5     # seconds before first retry
    verify_ssl:         bool          = True
    follow_redirects:   bool          = True
    max_redirects:      int           = 5
    rotate_user_agents: bool          = True
    extra_headers:      Dict[str, str] = field(default_factory=dict)
    encoding:           str           = "utf-8"


@dataclass
class FetchResult:
    url:          str
    final_url:    str                    # after redirects
    status_code:  int
    content:      bytes
    content_type: str
    headers:      Dict[str, str]
    elapsed_ms:   float
    attempt:      int
    error:        Optional[str] = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300 and self.error is None

    def text(self, encoding: str = "utf-8") -> str:
        try:
            return self.content.decode(encoding, errors="replace")
        except Exception:
            return self.content.decode("latin-1", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text())

    def size_kb(self) -> float:
        return len(self.content) / 1024


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

class Fetcher:
    """
    Safe, rate-limited HTTP client for the NEXUS web intelligence subsystem.

    All requests are validated against WebRules before transmission.
    Responses are validated for content-type and size after receipt.
    Thread-safe.
    """

    def __init__(
        self,
        config: Optional[FetchConfig] = None,
        rules: Optional[WebRules] = None,
    ) -> None:
        self._cfg    = config or FetchConfig()
        self._rules  = rules  or WebRules()
        self._ua_idx = 0
        self._ua_lock = threading.Lock()
        self._ssl_ctx = self._build_ssl_context()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, url: str, params: Optional[Dict[str, str]] = None) -> FetchResult:
        """Perform a GET request with optional query parameters."""
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        return self._request("GET", url)

    def post(
        self,
        url: str,
        data: Optional[Dict[str, Any]] = None,
        json_body: Optional[Any] = None,
    ) -> FetchResult:
        """Perform a POST request with form data or a JSON body."""
        body: Optional[bytes] = None
        extra_headers: Dict[str, str] = {}
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            extra_headers["Content-Type"] = "application/json"
        elif data:
            body = urllib.parse.urlencode(data).encode("utf-8")
            extra_headers["Content-Type"] = "application/x-www-form-urlencoded"
        return self._request("POST", url, body=body, extra_headers=extra_headers)

    def fetch_json(self, url: str, params: Optional[Dict[str, str]] = None) -> Any:
        """Shortcut: GET and parse JSON response."""
        result = self.get(url, params=params)
        if not result.ok:
            raise ValueError(f"HTTP {result.status_code} for {url}: {result.error}")
        return result.json()

    def fetch_text(self, url: str, params: Optional[Dict[str, str]] = None) -> str:
        """Shortcut: GET and return text content."""
        result = self.get(url, params=params)
        if not result.ok:
            raise ValueError(f"HTTP {result.status_code} for {url}: {result.error}")
        return result.text()

    # ------------------------------------------------------------------
    # Core request logic
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        body: Optional[bytes] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> FetchResult:
        # Pre-flight rule checks
        self._rules.check_url(url)
        domain = urllib.parse.urlparse(url).netloc.split(":")[0]
        self._rules.check_rate_limit(domain)

        last_error: Optional[str] = None
        wait = self._cfg.retry_initial_wait

        for attempt in range(1, self._cfg.max_retries + 2):
            t0 = time.perf_counter()
            try:
                result = self._do_request(method, url, body, extra_headers or {}, attempt)
                self._rules.check_content_type(result.content_type, url)
                self._rules.check_response_size(len(result.content), url)
                self._rules.record_request(domain)
                return result
            except WebRulesViolation:
                raise   # never retry rule violations
            except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
                last_error = str(exc)
                if attempt > self._cfg.max_retries:
                    break
                time.sleep(wait)
                wait *= self._cfg.retry_backoff
            except Exception as exc:
                last_error = str(exc)
                break

        elapsed = (time.perf_counter() - t0) * 1000
        return FetchResult(
            url=url, final_url=url, status_code=0,
            content=b"", content_type="",
            headers={}, elapsed_ms=elapsed,
            attempt=attempt, error=last_error,
        )

    def _do_request(
        self,
        method: str,
        url: str,
        body: Optional[bytes],
        extra_headers: Dict[str, str],
        attempt: int,
    ) -> FetchResult:
        headers = {
            "User-Agent":      self._next_user_agent(),
            "Accept":          "text/html,application/json,application/xml,*/*;q=0.8",
            "Accept-Encoding": "gzip, identity",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection":      "close",
            **self._cfg.extra_headers,
            **extra_headers,
        }

        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        opener = urllib.request.OpenerDirector()
        opener.addheaders = []
        if self._cfg.follow_redirects:
            opener.add_handler(urllib.request.HTTPRedirectHandler())
        opener.add_handler(urllib.request.HTTPDefaultErrorHandler())
        opener.add_handler(urllib.request.HTTPSHandler(context=self._ssl_ctx))
        opener.add_handler(urllib.request.HTTPHandler())

        t0 = time.perf_counter()
        with opener.open(req, timeout=self._cfg.timeout_seconds) as resp:
            raw        = resp.read()
            status     = resp.status
            final_url  = resp.url or url
            resp_hdrs  = {k.lower(): v for k, v in resp.headers.items()}
            ct         = resp_hdrs.get("content-type", "")

        # Decompress gzip if needed
        if resp_hdrs.get("content-encoding", "") == "gzip":
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass

        elapsed = (time.perf_counter() - t0) * 1000
        return FetchResult(
            url=url, final_url=final_url, status_code=status,
            content=raw, content_type=ct,
            headers=resp_hdrs, elapsed_ms=round(elapsed, 2),
            attempt=attempt,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _next_user_agent(self) -> str:
        if not self._cfg.rotate_user_agents:
            return _USER_AGENTS[0]
        with self._ua_lock:
            ua = _USER_AGENTS[self._ua_idx % len(_USER_AGENTS)]
            self._ua_idx += 1
            return ua

    def _build_ssl_context(self) -> ssl.SSLContext:
        if self._cfg.verify_ssl:
            ctx = ssl.create_default_context()
        else:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode    = ssl.CERT_NONE
        return ctx
