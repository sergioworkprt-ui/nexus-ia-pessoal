import re
from typing import List
from nexus.services.logger.logger import get_logger

log = get_logger("security")

_BLOCKED = [
    r"rm\s+-rf", r"drop\s+table", r"format\s+c:",
    r"sudo\s+rm", r"shutdown", r":(){:|:&};:",
]


class SecurityManager:
    def __init__(self):
        self._loop_count = 0
        self._max_loops = 10
        self._blocked_log: List[str] = []
        self._financial_authorized = False

    def validate_input(self, text: str) -> bool:
        for pattern in _BLOCKED:
            if re.search(pattern, text, re.IGNORECASE):
                self._blocked_log.append(text[:100])
                log.warning(f"Blocked: {text[:60]}")
                return False
        return True

    def validate_financial(self, amount: float) -> bool:
        if not self._financial_authorized:
            log.warning(f"Financial action blocked (not authorized): {amount}")
            return False
        if amount > 10.0:
            log.warning(f"Amount {amount} > max 10€")
            return False
        return True

    def authorize_financial(self):
        self._financial_authorized = True
        log.info("Financial actions authorized")

    def revoke_financial(self):
        self._financial_authorized = False

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
            "blocked_total": len(self._blocked_log),
        }
