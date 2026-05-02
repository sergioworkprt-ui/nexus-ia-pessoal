"""
NEXUS Web Intelligence — Web Rules
Safety policies for HTTP fetching: allowed domains, rate limits,
content constraints, and legal/ethical scraping guards.
All violations raise WebRulesViolation before any network call is made.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Violation exception
# ---------------------------------------------------------------------------

class WebRulesViolation(Exception):
    """Raised when a web operation breaches the active policy."""

    def __init__(self, rule: str, detail: str) -> None:
        super().__init__(f"[{rule}] {detail}")
        self.rule   = rule
        self.detail = detail


# ---------------------------------------------------------------------------
# Per-domain policy override
# ---------------------------------------------------------------------------

@dataclass
class DomainPolicy:
    """Fine-grained rules for a specific domain or subdomain pattern."""
    pattern:              str              # exact domain or glob (e.g. "*.example.com")
    allowed:              bool  = True
    rate_limit_per_min:   int   = 30
    max_response_kb:      int   = 512
    require_https:        bool  = False
    custom_user_agent:    Optional[str] = None


# ---------------------------------------------------------------------------
# Global web policy
# ---------------------------------------------------------------------------

@dataclass
class WebPolicy:
    """
    Top-level policy governing all HTTP operations.
    Safe defaults: HTTPS preferred, limited response size, no dangerous content types.
    """
    # Transport
    allowed_schemes:         Set[str]  = field(default_factory=lambda: {"https", "http"})
    require_https:           bool      = False

    # Domain controls
    blocked_domains:         Set[str]  = field(default_factory=lambda: {
        "localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254",  # SSRF protection
        "10.0.0.0", "172.16.0.0", "192.168.0.0",                 # private ranges (simplified)
    })
    allowed_domains:         Optional[Set[str]] = None  # None = allow all non-blocked

    # Response limits
    max_response_size_kb:    int   = 2048      # 2 MB default cap
    max_redirects:           int   = 5
    request_timeout_seconds: float = 15.0

    # Rate limiting (global)
    max_requests_per_minute: int   = 60
    default_rate_per_domain: int   = 20        # per-domain requests per minute

    # Content
    allowed_content_types:   Set[str] = field(default_factory=lambda: {
        "text/html", "text/plain", "application/json",
        "application/xml", "text/xml", "text/csv",
    })
    block_binary_content:    bool  = True

    # Ethical scraping
    respect_robots_txt:      bool  = True      # flag for callers to honour
    add_crawl_delay:         bool  = True      # honour Crawl-delay in robots.txt

    # Per-domain overrides
    domain_policies:         List[DomainPolicy] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Rate limiter (per domain)
# ---------------------------------------------------------------------------

class _DomainBucket:
    """Sliding-window rate limiter for a single domain."""

    def __init__(self, limit: int, window: float = 60.0) -> None:
        self._limit    = limit
        self._window   = window
        self._calls: List[float] = []
        self._lock     = threading.Lock()

    def is_allowed(self) -> bool:
        now = time.monotonic()
        with self._lock:
            cutoff = now - self._window
            self._calls = [t for t in self._calls if t > cutoff]
            if len(self._calls) >= self._limit:
                return False
            self._calls.append(now)
            return True

    def remaining(self) -> int:
        now = time.monotonic()
        with self._lock:
            cutoff = now - self._window
            active = [t for t in self._calls if t > cutoff]
            return max(0, self._limit - len(active))


# ---------------------------------------------------------------------------
# Web Rules engine
# ---------------------------------------------------------------------------

class WebRules:
    """
    Evaluates all web policy rules before and after fetch operations.

    Usage:
        rules = WebRules()
        rules.check_url("https://example.com/data.json")   # raises on violation
        rules.check_content_type("application/json")
        rules.check_response_size(512_000)
        rules.record_request("example.com")
    """

    def __init__(self, policy: Optional[WebPolicy] = None) -> None:
        self._policy   = policy or WebPolicy()
        self._buckets: Dict[str, _DomainBucket] = {}
        self._global_bucket = _DomainBucket(
            self._policy.max_requests_per_minute, window=60.0
        )
        self._bucket_lock  = threading.Lock()
        self._violation_log: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Pre-fetch checks
    # ------------------------------------------------------------------

    def check_url(self, url: str) -> None:
        """
        Validate a URL against all policy constraints.
        Raises WebRulesViolation on the first failure.
        """
        parsed = self._parse(url)

        self._check_scheme(parsed.scheme, url)
        self._check_domain(parsed.netloc or parsed.hostname or "", url)

        if self._policy.require_https and parsed.scheme != "https":
            self._raise("HTTPS_REQUIRED", f"'{url}' must use HTTPS.")

        # Per-domain policy
        domain_pol = self._domain_policy(parsed.netloc or "")
        if domain_pol and not domain_pol.allowed:
            self._raise("DOMAIN_POLICY_BLOCKED", f"Domain '{parsed.netloc}' is blocked by policy.")
        if domain_pol and domain_pol.require_https and parsed.scheme != "https":
            self._raise("DOMAIN_REQUIRES_HTTPS",
                        f"Domain '{parsed.netloc}' requires HTTPS.")

    def check_content_type(self, content_type: str, url: str = "") -> None:
        """Raise if the response content-type is not in the allowed set."""
        if not self._policy.block_binary_content:
            return
        base_type = content_type.split(";")[0].strip().lower()
        if base_type and base_type not in self._policy.allowed_content_types:
            self._raise(
                "CONTENT_TYPE_BLOCKED",
                f"Content-type '{base_type}' is not allowed (url: {url!r}). "
                f"Allowed: {sorted(self._policy.allowed_content_types)}",
            )

    def check_response_size(self, size_bytes: int, url: str = "") -> None:
        """Raise if the response body exceeds the configured size limit."""
        limit = self._policy.max_response_size_kb * 1024
        if size_bytes > limit:
            self._raise(
                "RESPONSE_TOO_LARGE",
                f"Response size {size_bytes // 1024} KB exceeds limit "
                f"{self._policy.max_response_size_kb} KB (url: {url!r}).",
            )

    def check_rate_limit(self, domain: str) -> None:
        """Raise if the per-domain or global rate limit has been reached."""
        if not self._global_bucket.is_allowed():
            self._raise(
                "GLOBAL_RATE_LIMIT",
                f"Global rate limit of {self._policy.max_requests_per_minute} "
                "req/min reached. Slow down.",
            )
        bucket = self._get_bucket(domain)
        if not bucket.is_allowed():
            domain_pol = self._domain_policy(domain)
            limit = domain_pol.rate_limit_per_min if domain_pol else self._policy.default_rate_per_domain
            self._raise(
                "DOMAIN_RATE_LIMIT",
                f"Rate limit of {limit} req/min reached for '{domain}'.",
            )

    # ------------------------------------------------------------------
    # Post-fetch recording
    # ------------------------------------------------------------------

    def record_request(self, domain: str) -> None:
        """Call after a successful fetch to update counters."""
        # Buckets are already updated in check_rate_limit; this is a no-op
        # placeholder for future metrics hooks.
        pass

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def rate_status(self, domain: str) -> Dict[str, Any]:
        bucket = self._get_bucket(domain)
        dom_pol = self._domain_policy(domain)
        limit = dom_pol.rate_limit_per_min if dom_pol else self._policy.default_rate_per_domain
        return {
            "domain": domain,
            "remaining_requests": bucket.remaining(),
            "limit_per_minute": limit,
            "global_remaining": self._global_bucket.remaining(),
        }

    def violation_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        return list(self._violation_log[-limit:])

    def update_policy(self, policy: WebPolicy) -> None:
        self._policy = policy

    def snapshot(self) -> Dict[str, Any]:
        p = self._policy
        return {
            "allowed_schemes":         list(p.allowed_schemes),
            "require_https":           p.require_https,
            "max_response_size_kb":    p.max_response_size_kb,
            "max_requests_per_minute": p.max_requests_per_minute,
            "default_rate_per_domain": p.default_rate_per_domain,
            "respect_robots_txt":      p.respect_robots_txt,
            "blocked_domains":         sorted(p.blocked_domains),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_scheme(self, scheme: str, url: str) -> None:
        if scheme not in self._policy.allowed_schemes:
            self._raise(
                "SCHEME_NOT_ALLOWED",
                f"Scheme '{scheme}' is not allowed in '{url}'. "
                f"Allowed: {sorted(self._policy.allowed_schemes)}",
            )

    def _check_domain(self, netloc: str, url: str) -> None:
        hostname = netloc.split(":")[0].lower()

        # SSRF: block private/loopback ranges
        for blocked in self._policy.blocked_domains:
            if hostname == blocked or hostname.endswith("." + blocked):
                self._raise("BLOCKED_DOMAIN",
                            f"Domain '{hostname}' is blocked (url: {url!r}).")

        # Allowlist check
        if self._policy.allowed_domains is not None:
            if not any(
                hostname == a or hostname.endswith("." + a)
                for a in self._policy.allowed_domains
            ):
                self._raise(
                    "DOMAIN_NOT_ALLOWLISTED",
                    f"Domain '{hostname}' is not in the allowed-domains list.",
                )

    def _domain_policy(self, netloc: str) -> Optional[DomainPolicy]:
        hostname = netloc.split(":")[0].lower()
        for dp in self._policy.domain_policies:
            pattern = dp.pattern.lstrip("*.")
            if hostname == pattern or hostname.endswith("." + pattern):
                return dp
        return None

    def _get_bucket(self, domain: str) -> _DomainBucket:
        with self._bucket_lock:
            if domain not in self._buckets:
                dom_pol = self._domain_policy(domain)
                limit = (dom_pol.rate_limit_per_min if dom_pol
                         else self._policy.default_rate_per_domain)
                self._buckets[domain] = _DomainBucket(limit)
            return self._buckets[domain]

    def _raise(self, rule: str, detail: str) -> None:
        self._violation_log.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "rule": rule,
            "detail": detail,
        })
        raise WebRulesViolation(rule, detail)

    @staticmethod
    def _parse(url: str):  # -> urllib.parse.ParseResult
        parsed = urlparse(url)
        if not parsed.scheme:
            raise WebRulesViolation("INVALID_URL", f"URL has no scheme: '{url}'.")
        return parsed
