"""SecurityManager — PIN, JWT, audit log, input validation, rate limiting."""
from __future__ import annotations
import hashlib, os, re, secrets, time
from datetime import datetime
from pathlib import Path
from typing import List
import jwt
from nexus.services.logger.logger import get_logger

log = get_logger("security")

_BLOCKED = [
    r"rm\s+-rf", r"drop\s+table", r"format\s+c:",
    r"sudo\s+rm", r"shutdown", r":\(\)\{:\|:&\};:",
]
_AUDIT = Path(os.getenv("LOG_DIR", "/var/log/nexus")) / "audit.log"


class SecurityManager:
    def __init__(self):
        self._secret = os.getenv("NEXUS_SECRET_KEY", secrets.token_hex(32))
        self._api_key = os.getenv("NEXUS_API_KEY", "nexus-change-me")
        self._pin_hash = os.getenv("NEXUS_PIN_HASH", "")
        self._financial_authorized = False
        self._loop_count = 0
        self._max_loops = 10
        self._rate: dict[str, list[float]] = {}

    # ── audit ─────────────────────────────────────────────────────────────
    def _audit(self, event: str, detail: str = ""):
        entry = f"{datetime.utcnow().isoformat()} [{event}] {detail}\n"
        try:
            _AUDIT.parent.mkdir(parents=True, exist_ok=True)
            with _AUDIT.open("a") as f:
                f.write(entry)
        except Exception:
            pass
        log.info(f"AUDIT {event} {detail}")

    def get_audit_log(self, lines: int = 50) -> List[str]:
        try:
            if _AUDIT.exists():
                return _AUDIT.read_text().splitlines()[-lines:]
        except Exception:
            pass
        return []

    # ── input validation ──────────────────────────────────────────────────
    def validate_input(self, text: str) -> bool:
        for pattern in _BLOCKED:
            if re.search(pattern, text, re.IGNORECASE):
                self._audit("BLOCKED_INPUT", text[:80])
                return False
        return True

    # ── PIN ────────────────────────────────────────────────────────────────
    def verify_pin(self, pin: str) -> bool:
        h = hashlib.sha256(pin.encode()).hexdigest()
        if not self._pin_hash:
            if len(pin) >= 4 and pin.isdigit():
                self._pin_hash = h
                self._audit("PIN_SET")
                return True
            return False
        ok = h == self._pin_hash
        self._audit("PIN_VERIFY", "ok" if ok else "FAILED")
        return ok

    def set_pin(self, pin: str) -> bool:
        if len(pin) >= 4 and pin.isdigit():
            self._pin_hash = hashlib.sha256(pin.encode()).hexdigest()
            self._audit("PIN_CHANGED")
            return True
        return False

    # ── JWT ────────────────────────────────────────────────────────────────
    def generate_token(self, scope: str = "full", ttl: int = 3600) -> str:
        payload = {"scope": scope, "iat": int(time.time()), "exp": int(time.time()) + ttl}
        return jwt.encode(payload, self._secret, algorithm="HS256")

    def verify_token(self, token: str) -> bool:
        if token == self._api_key:
            return True
        try:
            jwt.decode(token, self._secret, algorithms=["HS256"])
            return True
        except Exception:
            return False

    # ── rate limiting ─────────────────────────────────────────────────────
    def check_rate(self, key: str, limit: int = 10, window: int = 60) -> bool:
        now = time.time()
        hits = self._rate.setdefault(key, [])
        hits[:] = [t for t in hits if now - t < window]
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    # ── financial ────────────────────────────────────────────────────────
    def validate_financial(self, amount: float) -> bool:
        max_order = float(os.getenv("RISK_MAX_ORDER", "10"))
        if not self._financial_authorized:
            self._audit("FINANCIAL_BLOCKED", f"amount={amount}")
            return False
        if amount > max_order:
            self._audit("FINANCIAL_LIMIT", f"amount={amount}>max={max_order}")
            return False
        return True

    def authorize_financial(self, confirm_code: str | None = None) -> bool:
        if confirm_code == os.getenv("TRADING_CONFIRM_CODE", "NEXUS-REAL-CONFIRM"):
            self._financial_authorized = True
            self._audit("FINANCIAL_AUTHORIZED")
            log.warning("Financial actions AUTHORIZED")
            return True
        return False

    def revoke_financial(self):
        self._financial_authorized = False
        self._audit("FINANCIAL_REVOKED")

    # ── loop protection ───────────────────────────────────────────────────
    def check_loop(self) -> bool:
        self._loop_count += 1
        if self._loop_count > self._max_loops:
            log.error("Loop protection triggered")
            self.reset_loop()
            return False
        return True

    def reset_loop(self):
        self._loop_count = 0

    def status(self) -> dict:
        return {
            "financial_authorized": self._financial_authorized,
            "loop_count": self._loop_count,
            "pin_configured": bool(self._pin_hash),
        }
