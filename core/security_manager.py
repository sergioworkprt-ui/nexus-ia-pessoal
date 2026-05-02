"""
NEXUS Core — Security Manager
Enforces safety rules, rate limits, input validation, and access control.
"""

import hashlib
import hmac
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RateLimitBucket:
    limit: int
    window_seconds: float
    _calls: List[float] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def is_allowed(self) -> bool:
        now = time.monotonic()
        with self._lock:
            cutoff = now - self.window_seconds
            self._calls = [t for t in self._calls if t > cutoff]
            if len(self._calls) >= self.limit:
                return False
            self._calls.append(now)
            return True

    def remaining(self) -> int:
        now = time.monotonic()
        with self._lock:
            cutoff = now - self.window_seconds
            active = [t for t in self._calls if t > cutoff]
            return max(0, self.limit - len(active))


@dataclass
class SecurityPolicy:
    max_input_length: int = 8192
    allowed_commands: Optional[Set[str]] = None       # None = all allowed
    blocked_patterns: List[str] = field(default_factory=list)
    rate_limit_per_minute: int = 60
    require_auth: bool = False
    allowed_origins: Optional[Set[str]] = None        # None = all allowed
    log_all_requests: bool = True


class SecurityViolation(Exception):
    """Raised when a security check fails."""

    def __init__(self, reason: str, code: str = "SECURITY_VIOLATION") -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code


# ---------------------------------------------------------------------------
# Security Manager
# ---------------------------------------------------------------------------

class SecurityManager:
    """
    Central security layer for the NEXUS system.

    Responsibilities:
    - Input validation and sanitisation
    - Rate limiting per actor/key
    - Command allow/block lists
    - Token-based authentication (HMAC)
    - Audit-ready violation logging
    """

    def __init__(self, policy: Optional[SecurityPolicy] = None, secret_key: str = "") -> None:
        self._policy = policy or SecurityPolicy()
        self._secret_key = secret_key.encode() if secret_key else b""
        self._rate_buckets: Dict[str, RateLimitBucket] = {}
        self._bucket_lock = threading.Lock()
        self._compiled_patterns = [re.compile(p, re.IGNORECASE) for p in self._policy.blocked_patterns]
        self._blocked_actors: Set[str] = set()
        self._violation_log: List[Dict[str, Any]] = []
        self._log_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_input(self, data: str, actor: str = "anonymous") -> str:
        """
        Validate and return sanitised input.
        Raises SecurityViolation on failure.
        """
        self._check_actor_blocked(actor)
        self._check_rate_limit(actor)
        self._check_length(data)
        self._check_blocked_patterns(data, actor)
        return data.strip()

    def validate_command(self, command: str, actor: str = "anonymous") -> str:
        """Ensure the command is on the allow list (if configured)."""
        self._check_actor_blocked(actor)
        if self._policy.allowed_commands is not None:
            cmd_name = command.split()[0].lower() if command.strip() else ""
            if cmd_name not in self._policy.allowed_commands:
                self._record_violation(actor, "BLOCKED_COMMAND", command)
                raise SecurityViolation(f"Command '{cmd_name}' is not permitted.", "BLOCKED_COMMAND")
        return command

    def authenticate(self, token: str, actor: str = "anonymous") -> bool:
        """Verify an HMAC-SHA256 token. Returns True on success."""
        if not self._policy.require_auth:
            return True
        if not self._secret_key:
            raise SecurityViolation("Authentication required but no secret key is configured.", "AUTH_MISCONFIGURED")
        try:
            # Expected format: "<timestamp>.<signature>"
            ts_str, sig = token.split(".", 1)
            ts = float(ts_str)
        except (ValueError, AttributeError):
            self._record_violation(actor, "INVALID_TOKEN_FORMAT", token[:16])
            raise SecurityViolation("Malformed authentication token.", "INVALID_TOKEN")

        age = abs(time.time() - ts)
        if age > 300:  # 5-minute window
            self._record_violation(actor, "EXPIRED_TOKEN", token[:16])
            raise SecurityViolation("Authentication token has expired.", "EXPIRED_TOKEN")

        expected = hmac.new(self._secret_key, ts_str.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            self._record_violation(actor, "INVALID_SIGNATURE", token[:16])
            raise SecurityViolation("Invalid token signature.", "INVALID_SIGNATURE")

        return True

    def generate_token(self, timestamp: Optional[float] = None) -> str:
        """Generate a valid HMAC token for the given (or current) timestamp."""
        ts = str(timestamp or time.time())
        sig = hmac.new(self._secret_key, ts.encode(), hashlib.sha256).hexdigest()
        return f"{ts}.{sig}"

    def block_actor(self, actor: str) -> None:
        self._blocked_actors.add(actor)

    def unblock_actor(self, actor: str) -> None:
        self._blocked_actors.discard(actor)

    def is_blocked(self, actor: str) -> bool:
        return actor in self._blocked_actors

    def violations(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._log_lock:
            return list(self._violation_log[-limit:])

    def rate_limit_status(self, actor: str) -> Dict[str, Any]:
        bucket = self._get_or_create_bucket(actor)
        return {
            "actor": actor,
            "remaining_calls": bucket.remaining(),
            "limit": self._policy.rate_limit_per_minute,
            "window_seconds": bucket.window_seconds,
        }

    def update_policy(self, policy: SecurityPolicy) -> None:
        self._policy = policy
        self._compiled_patterns = [re.compile(p, re.IGNORECASE) for p in policy.blocked_patterns]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_actor_blocked(self, actor: str) -> None:
        if actor in self._blocked_actors:
            raise SecurityViolation(f"Actor '{actor}' is blocked.", "ACTOR_BLOCKED")

    def _check_rate_limit(self, actor: str) -> None:
        bucket = self._get_or_create_bucket(actor)
        if not bucket.is_allowed():
            self._record_violation(actor, "RATE_LIMIT_EXCEEDED", "")
            raise SecurityViolation(
                f"Rate limit exceeded for '{actor}'. Try again later.", "RATE_LIMIT_EXCEEDED"
            )

    def _check_length(self, data: str) -> None:
        if len(data) > self._policy.max_input_length:
            raise SecurityViolation(
                f"Input exceeds maximum length of {self._policy.max_input_length} characters.",
                "INPUT_TOO_LONG",
            )

    def _check_blocked_patterns(self, data: str, actor: str) -> None:
        for pattern in self._compiled_patterns:
            if pattern.search(data):
                self._record_violation(actor, "BLOCKED_PATTERN", pattern.pattern)
                raise SecurityViolation(
                    f"Input matches a blocked pattern: '{pattern.pattern}'.", "BLOCKED_PATTERN"
                )

    def _get_or_create_bucket(self, actor: str) -> RateLimitBucket:
        with self._bucket_lock:
            if actor not in self._rate_buckets:
                self._rate_buckets[actor] = RateLimitBucket(
                    limit=self._policy.rate_limit_per_minute,
                    window_seconds=60.0,
                )
            return self._rate_buckets[actor]

    def _record_violation(self, actor: str, code: str, detail: str) -> None:
        entry: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "code": code,
            "detail": detail,
        }
        with self._log_lock:
            self._violation_log.append(entry)
