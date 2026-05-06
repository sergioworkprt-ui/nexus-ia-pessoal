"""
NEXUS — IBKR Gateway Module

High-level facade for the IBKR Client Portal Gateway running on Render at
https://ibkr-gateway-04-08.onrender.com

This module wraps IBKRClientPortal and adds:
  - Render URL as default endpoint
  - Explicit login() with browser-auth instructions + auto-reauthenticate
  - Auto-retry on 401: every public method retries once after reauthenticate()
  - get_snapshot(conid)     → market data snapshot (price, bid, ask, volume)
  - get_contract_info(conid) → full contract details
  - get_pnl()               → partitioned P&L for all accounts
  - All return clean dicts / lists (no raw CPG structures)

Usage:
    from nexus_runtime.ibkr_gateway import IBKRGateway

    gw = IBKRGateway()
    auth = gw.login()          # returns auth dict; see 'authenticated' key
    print(gw.get_accounts())
    print(gw.get_pnl())
    gw.stop_keepalive()

Chat commands (via CommandEngine):
    gateway status             → authentication + session status
    gateway login              → attempt re-auth + show browser URL if needed
    gateway accounts           → list IBKR accounts
    gateway positions          → live open positions
    gateway pnl                → partitioned P&L
    gateway snapshot <conid>   → market snapshot for a conid
    gateway contract <conid>   → full contract info
"""

from __future__ import annotations

import functools
import time
from typing import Any, Dict, List, Optional

from .ibkr_client_portal import IBKRClientPortal, CPGAuthError, CPGRequestError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RENDER_URL = "https://ibkr-gateway-04-08.onrender.com"

# Market-data fields requested in snapshot calls:
#   31 = last price, 55 = symbol, 70 = high, 71 = low,
#   84 = bid, 85 = ask size, 86 = ask, 87 = volume, 7295 = open
_SNAPSHOT_FIELDS = "31,55,70,71,84,85,86,87,7295"


# ---------------------------------------------------------------------------
# Auto-reauth decorator
# ---------------------------------------------------------------------------

def _reauth_retry(method):
    """
    Decorator that retries a method once after reauthenticate() on CPGAuthError
    or HTTP 401. Covers both gateway-restart and session-expiry cases.
    """
    @functools.wraps(method)
    def wrapper(self: "IBKRGateway", *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except CPGAuthError:
            self._cpg.reauthenticate()
            time.sleep(1)          # brief pause for session to settle
            return method(self, *args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# IBKRGateway
# ---------------------------------------------------------------------------

class IBKRGateway:
    """
    NEXUS interface to the IBKR Client Portal Gateway on Render.

    Delegates all HTTP transport to IBKRClientPortal (stdlib-only, cookie-jar,
    SSL, keepalive) and adds:
      - login() with user-friendly instructions when browser auth is needed
      - auto-retry on 401 via @_reauth_retry
      - get_snapshot / get_contract_info / get_pnl
    """

    def __init__(
        self,
        base_url:            str  = RENDER_URL,
        account_id:          str  = "",
        verify_ssl:          bool = True,      # Render has a valid TLS cert
        timeout_s:           int  = 15,
        keepalive_interval_s: int = 55,
        log_path:            str  = "logs/ibkr_gateway.jsonl",
        auto_confirm_orders: bool = True,
        paper:               bool = True,
    ) -> None:
        self._cpg = IBKRClientPortal(
            base_url             = base_url,
            account_id           = account_id,
            verify_ssl           = verify_ssl,
            timeout_s            = timeout_s,
            keepalive_interval_s = keepalive_interval_s,
            log_path             = log_path,
            auto_confirm_orders  = auto_confirm_orders,
            paper                = paper,
        )
        self._base_url = base_url

    # ------------------------------------------------------------------
    # Auth / session
    # ------------------------------------------------------------------

    def login(self) -> Dict[str, Any]:
        """
        Check current auth status; attempt silent re-auth if not authenticated.

        Returns a dict:
          {
            "authenticated": bool,
            "connected":     bool,
            "session_valid": bool,
            "message":       str,   # human-readable status or instructions
            "browser_url":   str,   # URL to open if manual login is needed
          }

        If `authenticated` is False after reauthentication, the user must
        visit `browser_url` in a browser to complete the SSO login.
        """
        status = self._cpg.auth_status()
        authenticated = status.get("authenticated", False)

        if not authenticated:
            # Attempt silent re-auth (works if session cookie is still valid
            # but IBKR kicked the session; common after Render restarts)
            self._cpg.reauthenticate()
            time.sleep(1)
            status = self._cpg.auth_status()
            authenticated = status.get("authenticated", False)

        if authenticated:
            self._cpg.start_keepalive()
            message = "Authenticated. Keepalive started."
        else:
            message = (
                "Not authenticated. Open the browser URL below, log in with "
                "your IBKR credentials, then call login() again."
            )

        return {
            "authenticated": authenticated,
            "connected":     status.get("connected", False),
            "session_valid": authenticated,
            "message":       message,
            "browser_url":   self._base_url,
            "raw":           status,
        }

    def is_authenticated(self) -> bool:
        """Return True if the current session is authenticated."""
        return self._cpg.auth_status().get("authenticated", False)

    def keep_alive(self) -> bool:
        """
        Send a single /tickle request to keep the session alive.
        Returns True if the session is still valid.
        """
        return self._cpg.tickle()

    def start_keepalive(self) -> None:
        """Start the background keepalive thread (calls /tickle every ~55 s)."""
        self._cpg.start_keepalive()

    def stop_keepalive(self) -> None:
        """Stop the background keepalive thread."""
        self._cpg.stop_keepalive()

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------

    @_reauth_retry
    def get_accounts(self) -> List[Dict[str, Any]]:
        """
        Return a list of IBKR accounts.
        Each dict has at minimum: accountId, type, currency, tradingType.
        """
        raw = self._cpg.get_accounts()
        return [_clean(a) for a in raw]

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    @_reauth_retry
    def get_positions(self, account_id: str = "") -> List[Dict[str, Any]]:
        """
        Return open positions for an account.
        Each dict has: conid, ticker, position, mktValue, avgCost,
                       unrealizedPnl, realizedPnl, currency.
        """
        raw = self._cpg.get_positions(account_id=account_id)
        return [_clean(p) for p in raw]

    # ------------------------------------------------------------------
    # P&L
    # ------------------------------------------------------------------

    @_reauth_retry
    def get_pnl(self) -> Dict[str, Any]:
        """
        GET /iserver/account/pnl/partitioned
        Returns per-account P&L split by realized, unrealized, and daily.

        Example output:
          {
            "upnl": {"DU1234567": {"rowType": 1, "dpl": 0.0, "nl": 12345.0, ...}},
            "accounts": ["DU1234567"],
          }
        """
        try:
            data = self._cpg._get("/iserver/account/pnl/partitioned")
            return _clean(data) if isinstance(data, dict) else {"raw": data}
        except CPGAuthError:
            raise
        except Exception as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Market data snapshot
    # ------------------------------------------------------------------

    @_reauth_retry
    def get_snapshot(
        self,
        conid: int,
        fields: str = _SNAPSHOT_FIELDS,
    ) -> Dict[str, Any]:
        """
        GET /iserver/marketdata/snapshot?conids={conid}&fields={fields}

        Returns a clean dict with human-readable field names where possible:
          last_price, bid, ask, high, low, volume, open, symbol, conid
        """
        try:
            result = self._cpg._get(
                "/iserver/marketdata/snapshot",
                params={"conids": str(conid), "fields": fields},
            )
            raw_list = result if isinstance(result, list) else [result]
            if not raw_list:
                return {"conid": conid, "error": "no data returned"}
            item = raw_list[0] if isinstance(raw_list[0], dict) else {}
            return _normalise_snapshot(conid, item)
        except CPGAuthError:
            raise
        except Exception as exc:
            return {"conid": conid, "error": str(exc)}

    # ------------------------------------------------------------------
    # Contract info
    # ------------------------------------------------------------------

    @_reauth_retry
    def get_contract_info(self, conid: int) -> Dict[str, Any]:
        """
        GET /iserver/contract/{conid}/info
        Returns full contract details: symbol, secType, currency, exchange,
        expiry, multiplier, etc.
        """
        try:
            data = self._cpg._get(f"/iserver/contract/{conid}/info")
            return _clean(data) if isinstance(data, dict) else {"raw": data}
        except CPGAuthError:
            raise
        except Exception as exc:
            return {"conid": conid, "error": str(exc)}

    # ------------------------------------------------------------------
    # Convenience wrappers for existing CPG methods
    # ------------------------------------------------------------------

    @_reauth_retry
    def get_balance(self, account_id: str = "") -> Dict[str, Any]:
        """Return equity, cash, and available funds for an account."""
        return {
            "equity":           self._cpg.get_equity(account_id),
            "cash":             self._cpg.get_cash(account_id),
            "available_funds":  self._cpg.get_available_funds(account_id),
        }

    @_reauth_retry
    def get_open_orders(self) -> List[Dict[str, Any]]:
        """Return open orders from the gateway."""
        return [_clean(o) for o in self._cpg.get_open_orders()]

    def status(self) -> Dict[str, Any]:
        """Return a combined gateway status dict suitable for display."""
        auth = self._cpg.auth_status()
        return {
            "base_url":      self._base_url,
            "authenticated": auth.get("authenticated", False),
            "connected":     auth.get("connected", False),
            "competing":     auth.get("competing", False),
            "paper":         self._cpg._paper,
            "browser_url":   self._base_url,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(obj: Any) -> Any:
    """Recursively strip None values and convert to plain Python types."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_clean(i) for i in obj]
    return obj


# CPG snapshot field codes → human-readable names
_FIELD_MAP = {
    "31":   "last_price",
    "55":   "symbol",
    "70":   "high",
    "71":   "low",
    "84":   "bid",
    "85":   "ask_size",
    "86":   "ask",
    "87":   "volume",
    "7295": "open",
}


def _normalise_snapshot(conid: int, raw: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"conid": conid}
    for raw_key, human_key in _FIELD_MAP.items():
        if raw_key in raw:
            val = raw[raw_key]
            # CPG returns prices as strings like "182.34" or "C182.34" (closing)
            if isinstance(val, str):
                val = val.lstrip("C").lstrip("H").strip()
                try:
                    val = float(val)
                except ValueError:
                    pass
            out[human_key] = val
    # Pass through any fields we didn't map
    for k, v in raw.items():
        if k not in _FIELD_MAP and k != "conid":
            out[k] = v
    return out
