"""
IBKR Client Portal Web API — REST client.

The Client Portal Gateway runs locally (https://localhost:5000) and acts as
a proxy to IBKR servers. Authentication is done once in a browser; this
client then calls the REST endpoints directly.

Usage:
    client = IBKRClient.from_config("configs/broker.yaml")
    client.check_auth()          # raises if not authenticated
    data = client.get(endpoint)  # returns parsed JSON
"""

from __future__ import annotations

import logging
import time
import urllib3
import yaml
import requests
from typing import Any

# The gateway uses a self-signed certificate — suppress the warning locally
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class IBKRClient:
    """Thin wrapper around the Client Portal REST API."""

    def __init__(self, base_url: str, verify_ssl: bool, timeout: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.verify = verify_ssl
        self.timeout = timeout
        self._session = requests.Session()

    @classmethod
    def from_config(cls, config_path: str) -> "IBKRClient":
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        conn = cfg["connection"]
        return cls(
            base_url=conn["base_url"],
            verify_ssl=conn.get("verify_ssl", False),
            timeout=conn.get("timeout_seconds", 10),
        )

    # ------------------------------------------------------------------
    # Core HTTP helpers
    # ------------------------------------------------------------------

    def get(self, endpoint: str, params: dict | None = None) -> Any:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        resp = self._session.get(url, params=params, verify=self.verify, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def post(self, endpoint: str, json: dict | None = None) -> Any:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        resp = self._session.post(url, json=json, verify=self.verify, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def check_auth(self) -> dict:
        """Verify the gateway session is authenticated. Raises if not."""
        status = self.get("/iserver/auth/status")
        if not status.get("authenticated"):
            raise ConnectionError(
                "Not authenticated. Open https://localhost:5000 in your browser and log in."
            )
        logger.info("Auth OK - connected=%s, competing=%s",
                    status.get("connected"), status.get("competing"))
        return status

    def tickle(self) -> None:
        """Keep the session alive (call every ~60 s)."""
        self.get("/tickle")

    def get_accounts(self) -> list:
        """Return the list of accounts available in this session."""
        return self.get("/iserver/accounts").get("accounts", [])

    # ------------------------------------------------------------------
    # Contract resolution
    # ------------------------------------------------------------------

    def search_contract(self, symbol: str, sec_type: str = "") -> list:
        """Search for contracts by symbol. Returns a list of matches."""
        payload = {"symbol": symbol, "name": False}
        if sec_type:
            payload["secType"] = sec_type
        return self.post("/iserver/secdef/search", json=payload)

    def get_contract_info(self, conid: int) -> dict:
        """Return full contract details for a given conid."""
        return self.get(f"/iserver/contract/{conid}/info")

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def snapshot(self, conids: list[int], fields: list[str]) -> list:
        """
        Request a market-data snapshot for one or more contracts.
        Returns a list of dicts keyed by field ID.

        Common field IDs:
          31=last, 84=bid, 86=ask, 70=high, 71=low, 82=chg, 83=chg%
          85=ask size (NOT ask price)
          7308=delta, 7309=gamma, 7310=vega, 7311=theta, 7636=IV%
        """
        params = {
            "conids": ",".join(str(c) for c in conids),
            "fields": ",".join(fields),
        }
        # First call registers the subscription; IBKR then computes model
        # fields (IV%, Greeks). Without a pause the second call arrives before
        # IBKR's pricing engine has finished — all derived fields come back
        # empty. 0.5 s is enough for liquid index options; increase if Greeks
        # are still missing on slow market-data days.
        self.get("/iserver/marketdata/snapshot", params=params)
        time.sleep(0.5)
        return self.get("/iserver/marketdata/snapshot", params=params)

    def unsubscribe_all(self) -> None:
        """Cancel all active market-data subscriptions."""
        try:
            self.get("/iserver/marketdata/unsubscribeall")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Option chains
    # ------------------------------------------------------------------

    def get_option_strikes(self, conid: int, month: str, exchange: str = "") -> dict:
        """
        Return available strikes for an options chain.
        month format: YYYYMM  e.g. "202607"
        """
        params = {"conid": conid, "sectype": "OPT", "month": month}
        if exchange:
            params["exchange"] = exchange
        return self.get("/iserver/secdef/strikes", params=params)

    def get_option_chain_months(self, conid: int) -> list:
        """Return available expiry months for an underlying's option chain."""
        result = self.get(f"/iserver/secdef/option/params?conid={conid}&exchange=&sectype=OPT&month=&strike=")
        # The response varies; return raw for inspection
        return result

    def search_options_by_strike(
        self, conid: int, month: str, strike: float, right: str, exchange: str = ""
    ) -> list:
        """
        Resolve a specific option contract (conid) given strike, expiry, right.
        right: 'C' or 'P'
        """
        params = {
            "conid": conid,
            "sectype": "OPT",
            "month": month,
            "strike": strike,
            "right": right,
        }
        if exchange:
            params["exchange"] = exchange
        return self.get("/iserver/secdef/strike", params=params)
