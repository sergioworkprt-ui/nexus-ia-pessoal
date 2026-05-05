"""
NEXUS — IBKR Client Portal Gateway REST Client

Wraps the IBKR Client Portal Gateway (CPG) REST API.
The gateway runs as a Docker container (ghcr.io/interactivebrokers/clientportal-gateway)
and exposes a REST API, by default at https://localhost:5000/v1/api/.

Authentication note:
    The CPG requires an initial browser-based SSO login. After that, the session is
    maintained automatically via cookie + keepalive (GET /tickle every ~55 s).
    For paper trading this is identical; just use a Paper account in the gateway.

Configuration:
    base_url     — CPG endpoint, e.g. "https://localhost:5000" or "https://my-render-app.onrender.com"
    account_id   — IBKR account ID (e.g. "DU1234567"). Auto-detected if empty.
    verify_ssl   — False for the self-signed cert used by the local CPG container.
    paper        — True = paper account; affects logging only (CPG paper/live is
                   controlled by which gateway instance is used, not this flag).

Usage:
    cpg = IBKRClientPortal(base_url="https://localhost:5000", verify_ssl=False)
    cpg.start_keepalive()
    equity = cpg.get_equity()
    result = cpg.place_order("AAPL", "BUY", quantity=10)
    cpg.stop_keepalive()
"""

from __future__ import annotations

import http.cookiejar
import json
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CPGAuthError(Exception):
    """Session unauthenticated or expired — user must re-login via browser."""


class CPGRequestError(Exception):
    """Non-auth HTTP or connection error from the CPG."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# Security-type heuristics
# ---------------------------------------------------------------------------

_CRYPTO_SYMBOLS = {
    "BTC", "ETH", "SOL", "ADA", "XRP", "DOGE", "DOT", "AVAX",
    "MATIC", "LINK", "UNI", "LTC", "BCH", "ATOM", "NEAR",
}

_FOREX_BASE = {"EUR", "GBP", "AUD", "NZD", "CAD", "CHF", "JPY", "SEK", "NOK"}


def _sec_type_for(symbol: str) -> str:
    """Heuristic security-type mapping for common symbols."""
    s = symbol.upper().replace("-", "").replace("_", "")
    if s in _CRYPTO_SYMBOLS:
        return "CRYPTO"
    if len(s) == 6 and s[:3] in _FOREX_BASE:
        return "CASH"
    return "STK"


# ---------------------------------------------------------------------------
# Client Portal Gateway REST client
# ---------------------------------------------------------------------------

class IBKRClientPortal:
    """
    IBKR Client Portal Gateway REST client.

    Thread-safe. Uses only Python stdlib (urllib, ssl, http.cookiejar).
    All requests and responses are logged to a JSONL file for audit purposes.

    Quick start:
        cpg = IBKRClientPortal(base_url="https://localhost:5000")
        cpg.start_keepalive()

        # Check auth (user must have logged in via browser first)
        status = cpg.auth_status()

        # Market data, positions, orders
        equity = cpg.get_equity()
        positions = cpg.get_positions()
        orders = cpg.get_open_orders()

        # Place an order
        result = cpg.place_order("AAPL", "BUY", quantity=10)

        cpg.stop_keepalive()
    """

    BASE_PATH = "/v1/api"

    def __init__(
        self,
        base_url:              str   = "https://localhost:5000",
        account_id:            str   = "",
        verify_ssl:            bool  = False,
        timeout_s:             int   = 10,
        keepalive_interval_s:  int   = 55,
        log_path:              str   = "logs/ibkr_cpg.jsonl",
        max_retries:           int   = 2,
        auto_confirm_orders:   bool  = True,
        paper:                 bool  = True,
    ) -> None:
        self._base_url   = base_url.rstrip("/")
        self._account_id = account_id
        self._verify_ssl = verify_ssl
        self._timeout    = timeout_s
        self._ka_interval = keepalive_interval_s
        self._log_path   = Path(log_path)
        self._max_retries = max_retries
        self._auto_confirm = auto_confirm_orders
        self._paper      = paper

        self._lock       = threading.RLock()
        self._ka_timer: Optional[threading.Timer] = None
        self._session_valid = False

        # conid cache: "{symbol}:{sec_type}" → conid
        self._conid_cache: Dict[str, int] = {}

        # SSL context — disable verification for self-signed CPG cert
        self._ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        if not verify_ssl:
            self._ssl_ctx.check_hostname = False
            self._ssl_ctx.verify_mode    = ssl.CERT_NONE

        # Opener with cookie jar for session persistence
        self._jar    = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar),
            urllib.request.HTTPSHandler(context=self._ssl_ctx),
        )

        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log("init", {"base_url": self._base_url, "paper": self._paper, "verify_ssl": verify_ssl})

    # ------------------------------------------------------------------
    # Auth / session
    # ------------------------------------------------------------------

    def auth_status(self) -> Dict[str, Any]:
        """
        GET /iserver/auth/status
        Returns {"authenticated": bool, "connected": bool, "competing": bool, ...}
        """
        try:
            data = self._get("/iserver/auth/status")
            self._session_valid = bool(data.get("authenticated"))
            return data
        except CPGAuthError:
            return {"authenticated": False, "connected": False}
        except Exception as exc:
            self._log("auth_status_error", {"error": str(exc)})
            return {"authenticated": False, "error": str(exc)}

    def reauthenticate(self) -> bool:
        """POST /iserver/reauthenticate — trigger a silent re-auth."""
        try:
            self._post("/iserver/reauthenticate", {})
            return True
        except Exception as exc:
            self._log("reauthenticate_failed", {"error": str(exc)})
            return False

    def tickle(self) -> bool:
        """
        GET /tickle — session keepalive.
        Returns True if the session is still alive.
        """
        try:
            data = self._get("/tickle")
            alive = bool(data.get("session") or data.get("iserver", {}).get("authStatus", {}).get("authenticated"))
            with self._lock:
                self._session_valid = alive
            self._log("tickle", {"alive": alive})
            return alive
        except Exception as exc:
            self._log("tickle_failed", {"error": str(exc)})
            return False

    def start_keepalive(self) -> None:
        """Start a background daemon thread that calls /tickle every keepalive_interval_s."""
        self._schedule_ka()

    def stop_keepalive(self) -> None:
        """Stop the keepalive thread."""
        with self._lock:
            if self._ka_timer:
                self._ka_timer.cancel()
                self._ka_timer = None

    def _schedule_ka(self) -> None:
        t = threading.Timer(self._ka_interval, self._run_ka)
        t.daemon = True
        with self._lock:
            self._ka_timer = t
        t.start()

    def _run_ka(self) -> None:
        self.tickle()
        self._schedule_ka()

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------

    def get_accounts(self) -> List[Dict[str, Any]]:
        """GET /portfolio/accounts — list all accounts."""
        try:
            result = self._get("/portfolio/accounts")
            return result if isinstance(result, list) else []
        except Exception as exc:
            self._log("get_accounts_error", {"error": str(exc)})
            return []

    def get_account_id(self) -> str:
        """
        Return the configured account ID, or auto-detect from /portfolio/accounts.
        Raises CPGAuthError if no accounts are available (session not authenticated).
        """
        with self._lock:
            if self._account_id:
                return self._account_id

        accounts = self.get_accounts()
        if not accounts:
            raise CPGAuthError(
                "No accounts found. Authenticate via browser at the CPG URL first."
            )
        acct = accounts[0].get("accountId") or accounts[0].get("id", "")
        if not acct:
            raise CPGAuthError("Account ID could not be determined from /portfolio/accounts.")
        with self._lock:
            self._account_id = acct
        self._log("account_id_detected", {"account_id": acct})
        return acct

    def set_account_id(self, account_id: str) -> None:
        """Manually override the account ID (useful if auto-detect picks the wrong one)."""
        with self._lock:
            self._account_id = account_id

    # ------------------------------------------------------------------
    # Balance / equity
    # ------------------------------------------------------------------

    def get_summary(self, account_id: str = "") -> Dict[str, Any]:
        """GET /portfolio/{accountId}/summary — full account summary."""
        acct = account_id or self.get_account_id()
        try:
            return self._get(f"/portfolio/{acct}/summary")
        except Exception as exc:
            self._log("get_summary_error", {"error": str(exc)})
            return {}

    def get_equity(self, account_id: str = "") -> float:
        """Net liquidation value (total equity)."""
        summary = self.get_summary(account_id)
        netliq = summary.get("netliquidation", summary.get("NLV", {}))
        if isinstance(netliq, dict):
            return float(netliq.get("amount", netliq.get("value", 0.0)))
        return float(netliq or 0.0)

    def get_cash(self, account_id: str = "") -> float:
        """Total cash balance."""
        summary = self.get_summary(account_id)
        cash = summary.get("totalcashvalue", summary.get("TotalCashValue", {}))
        if isinstance(cash, dict):
            return float(cash.get("amount", cash.get("value", 0.0)))
        return float(cash or 0.0)

    def get_available_funds(self, account_id: str = "") -> float:
        """Available funds for new positions (buying power)."""
        summary = self.get_summary(account_id)
        avail = summary.get("availablefunds", summary.get("AvailableFunds", {}))
        if isinstance(avail, dict):
            return float(avail.get("amount", avail.get("value", 0.0)))
        return float(avail or 0.0)

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def get_positions(self, account_id: str = "") -> List[Dict[str, Any]]:
        """
        GET /portfolio/{accountId}/positions/0
        Returns a list of open position dicts from the CPG.
        CPG fields: conid, ticker, position, mktValue, avgCost, unrealizedPnl, ...
        """
        acct = account_id or self.get_account_id()
        try:
            result = self._get(f"/portfolio/{acct}/positions/0")
            return result if isinstance(result, list) else []
        except Exception as exc:
            self._log("get_positions_error", {"error": str(exc)})
            return []

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def get_open_orders(self) -> List[Dict[str, Any]]:
        """
        GET /iserver/account/orders
        Returns a list of open order dicts.
        """
        try:
            data = self._get("/iserver/account/orders")
            if isinstance(data, dict):
                orders = data.get("orders", [])
            elif isinstance(data, list):
                orders = data
            else:
                orders = []
            return orders
        except Exception as exc:
            self._log("get_orders_error", {"error": str(exc)})
            return []

    def place_order(
        self,
        symbol:           str,
        side:             str,           # "BUY" | "SELL"
        quantity:         float,
        order_type:       str  = "MKT",  # "MKT" | "LMT" | "STP"
        price:            Optional[float] = None,
        tif:              str  = "DAY",
        outside_rth:      bool = False,
        client_order_id:  str  = "",
        sec_type:         str  = "",     # auto-detected if empty
        conid:            Optional[int] = None,
        account_id:       str  = "",
    ) -> Dict[str, Any]:
        """
        POST /iserver/account/orders

        Handles the two-step CPG confirmation flow automatically when
        auto_confirm_orders=True (default).

        Returns the CPG order response dict, e.g.:
            {"order_id": 123456, "order_status": "PreSubmitted", ...}

        Raises:
            CPGRequestError  — HTTP/connection error
            CPGAuthError     — session unauthenticated
            ValueError       — conid cannot be resolved for symbol
        """
        acct = account_id or self.get_account_id()
        stype = sec_type or _sec_type_for(symbol)

        # Resolve conid unless caller provides it
        if conid is None:
            conid = self.get_conid(symbol, sec_type=stype)
        if not conid:
            raise ValueError(f"Cannot resolve contract ID for {symbol!r} ({stype}). "
                             f"Use cpg.set_conid('{symbol}', <conid>) to set it manually.")

        body = [{
            "acctId":     acct,
            "conid":      conid,
            "secType":    f"{conid}:{stype}",
            "cOID":       client_order_id or f"NX-{symbol}-{_now_ms()}",
            "orderType":  order_type.upper(),
            "side":       side.upper(),
            "quantity":   float(quantity),
            "tif":        tif.upper(),
            "outsideRTH": outside_rth,
        }]

        if order_type.upper() in ("LMT", "STP") and price is not None:
            body[0]["price"] = float(price)

        self._log("place_order", {
            "symbol": symbol, "side": side.upper(), "qty": quantity,
            "order_type": order_type, "price": price, "conid": conid,
            "sec_type": stype, "paper": self._paper,
        })

        response = self._post("/iserver/account/orders", body)
        return self._handle_order_response(response)

    def cancel_order(self, order_id: str, account_id: str = "") -> Dict[str, Any]:
        """DELETE /iserver/account/{acctId}/order/{orderId}"""
        acct = account_id or self.get_account_id()
        try:
            return self._delete(f"/iserver/account/{acct}/order/{order_id}")
        except Exception as exc:
            self._log("cancel_order_error", {"order_id": order_id, "error": str(exc)})
            return {"error": str(exc)}

    def _handle_order_response(self, response: Any) -> Dict[str, Any]:
        """
        The CPG place-order endpoint may return:
          a) Straight success: [{"order_id": 123, "order_status": "PreSubmitted"}]
          b) Confirmation request: [{"id": "some-uuid", "message": ["Order..."], "messageIds": [...]}]
        This method resolves (b) automatically if auto_confirm_orders is True.
        """
        if not isinstance(response, list) or not response:
            return response if isinstance(response, dict) else {"raw": str(response)}

        first = response[0]
        if not isinstance(first, dict):
            return {"raw": str(first)}

        # Confirmation required: has "id" (UUID) + "message" list, no "order_id"
        if "id" in first and "message" in first and "order_id" not in first:
            reply_id = first["id"]
            messages = first.get("message", [])
            self._log("order_reply_required", {"reply_id": reply_id, "messages": messages})

            if not self._auto_confirm:
                raise CPGRequestError(
                    f"CPG requires order confirmation (reply_id={reply_id}). "
                    f"Messages: {messages}. Set auto_confirm_orders=True or confirm manually."
                )

            confirmed = self._post(f"/iserver/reply/{reply_id}", {"confirmed": True})
            self._log("order_reply_confirmed", {"reply_id": reply_id, "response": confirmed})

            if isinstance(confirmed, list) and confirmed:
                return confirmed[0] if isinstance(confirmed[0], dict) else {"raw": str(confirmed[0])}
            return {"confirmed": True, "raw": confirmed}

        return first

    # ------------------------------------------------------------------
    # Contract lookup (conid resolution)
    # ------------------------------------------------------------------

    def search_contract(
        self, symbol: str, sec_type: str = "STK"
    ) -> List[Dict[str, Any]]:
        """
        GET /iserver/secdef/search?symbol=AAPL&secType=STK
        Returns raw CPG secdef search results.
        """
        try:
            result = self._get(
                "/iserver/secdef/search",
                params={"symbol": symbol.upper(), "name": "false", "secType": sec_type},
            )
            return result if isinstance(result, list) else []
        except Exception as exc:
            self._log("contract_search_error", {"symbol": symbol, "error": str(exc)})
            return []

    def get_conid(self, symbol: str, sec_type: str = "STK") -> Optional[int]:
        """
        Resolve a trading symbol to an IBKR contract ID (conid).
        Results are cached in memory for the lifetime of this object.

        Returns None if the symbol cannot be resolved.
        Use set_conid() to pin a known conid (e.g. for crypto or non-US equities).
        """
        cache_key = f"{symbol.upper()}:{sec_type}"
        with self._lock:
            if cache_key in self._conid_cache:
                return self._conid_cache[cache_key]

        results = self.search_contract(symbol, sec_type=sec_type)
        for item in results:
            # Some CPG versions return conid at top level
            conid = item.get("conid")
            if conid:
                cid = int(conid)
                self._cache_conid(cache_key, cid, symbol, sec_type)
                return cid

            # Others return a "contracts" list inside each result
            for contract in item.get("contracts", []):
                exch = contract.get("exchange", "").upper()
                if exch in ("SMART", "IDEALPRO", "PAXOS", ""):
                    cid = int(contract.get("conid", 0))
                    if cid:
                        self._cache_conid(cache_key, cid, symbol, sec_type)
                        return cid

            # Fallback: first non-zero conid in contracts
            for contract in item.get("contracts", []):
                cid = int(contract.get("conid", 0))
                if cid:
                    self._cache_conid(cache_key, cid, symbol, sec_type)
                    return cid

        self._log("conid_not_found", {"symbol": symbol, "sec_type": sec_type})
        return None

    def set_conid(self, symbol: str, conid: int, sec_type: str = "STK") -> None:
        """
        Manually pin a conid for a symbol. Useful for:
          - Crypto (e.g. BTC: set_conid("BTC", 13455763, "CRYPTO"))
          - Non-US equities
          - Instruments where auto-search is ambiguous
        """
        key = f"{symbol.upper()}:{sec_type}"
        with self._lock:
            self._conid_cache[key] = conid
        self._log("conid_pinned", {"symbol": symbol, "conid": conid, "sec_type": sec_type})

    def _cache_conid(self, key: str, cid: int, symbol: str, sec_type: str) -> None:
        with self._lock:
            self._conid_cache[key] = cid
        self._log("conid_resolved", {"symbol": symbol, "conid": cid, "sec_type": sec_type})

    # ------------------------------------------------------------------
    # Market data snapshot
    # ------------------------------------------------------------------

    def get_market_price(
        self, symbol: str, sec_type: str = "", conid: Optional[int] = None
    ) -> Optional[float]:
        """
        GET /iserver/marketdata/snapshot?conids={conid}&fields=31
        Field 31 = last traded price.
        Returns None if unavailable.
        """
        stype = sec_type or _sec_type_for(symbol)
        cid   = conid or self.get_conid(symbol, sec_type=stype)
        if not cid:
            return None
        try:
            data = self._get(
                "/iserver/marketdata/snapshot",
                params={"conids": str(cid), "fields": "31,84,86"},
            )
            if isinstance(data, list) and data:
                item = data[0]
                for key in ("31", 31):
                    val = item.get(key)
                    if val is not None:
                        return float(str(val).replace(",", ""))
        except Exception as exc:
            self._log("market_price_error", {"symbol": symbol, "error": str(exc)})
        return None

    # ------------------------------------------------------------------
    # Low-level HTTP
    # ------------------------------------------------------------------

    def _get(self, path: str, params: Optional[Dict[str, str]] = None) -> Any:
        return self._request("GET", path, params=params)

    def _post(self, path: str, body: Any) -> Any:
        return self._request("POST", path, body=body)

    def _delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    def _request(
        self,
        method:   str,
        path:     str,
        params:   Optional[Dict[str, str]] = None,
        body:     Any  = None,
        _attempt: int  = 0,
    ) -> Any:
        url = f"{self._base_url}{self.BASE_PATH}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        data = json.dumps(body).encode("utf-8") if body is not None else None
        req  = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "NEXUS-IBKR/1.0")

        self._log("req", {
            "method": method, "path": path,
            "body_bytes": len(data) if data else 0,
        })

        try:
            with self._opener.open(req, timeout=self._timeout) as resp:
                status  = resp.status
                raw     = resp.read().decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(raw) if raw.strip() else {}
                except json.JSONDecodeError:
                    parsed = {"raw": raw}
                self._log("resp", {"status": status, "path": path, "bytes": len(raw)})
                return parsed

        except urllib.error.HTTPError as exc:
            body_text = ""
            if exc.fp:
                try:
                    body_text = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
            self._log("http_error", {
                "status": exc.code, "path": path, "body": body_text[:500],
            })
            if exc.code == 401:
                raise CPGAuthError(
                    f"Session unauthenticated (HTTP 401) on {method} {path}. "
                    "Log in via the CPG browser interface."
                )
            raise CPGRequestError(
                f"HTTP {exc.code} on {method} {path}: {body_text[:300]}"
            )

        except urllib.error.URLError as exc:
            self._log("url_error", {"path": path, "error": str(exc.reason), "attempt": _attempt})
            if _attempt < self._max_retries:
                time.sleep(min(2.0 ** _attempt, 8.0))
                return self._request(method, path, params=params, body=body, _attempt=_attempt + 1)
            raise CPGRequestError(
                f"Connection error on {method} {path}: {exc.reason}. "
                f"Is the CPG running at {self._base_url}?"
            )

        except Exception as exc:
            self._log("request_error", {"path": path, "error": str(exc), "attempt": _attempt})
            raise CPGRequestError(f"Unexpected error on {method} {path}: {exc}")

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, action: str, data: Dict[str, Any]) -> None:
        entry = {"ts": _now_iso(), "action": action, **data}
        try:
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
        except Exception:
            pass  # logging must never crash the integration
