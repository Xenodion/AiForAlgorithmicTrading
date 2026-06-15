"""
IBKR Client Portal data fetching layer.
Returns plain dicts/lists — no pandas, no display logic here.
"""

from __future__ import annotations
import logging
from datetime import date
from src.connectivity.session import IBKRClient

logger = logging.getLogger(__name__)

SPOT_FIELDS   = ["31", "84", "86", "70", "71", "82", "83"]
#                last  bid   ask   high  low   chg   chg%
OPTION_FIELDS = ["31", "84", "86", "7308", "7309", "7310", "7311", "7636"]
#                last  bid   ask   delta  gamma  vega   theta  IV%
OPTION_DELTA_BUCKETS = [
    (0.05, 0.18),
    (0.10, 0.15),
    (0.15, 0.13),
    (0.20, 0.11),
    (0.25, 0.095),
    (0.30, 0.08),
]

# Standard term-structure tenors (per teacher spec: ~10 days, 1-18 months,
# 2 years, 3 years), paired 1:1 with the month offset used to pick the
# closest available contract for each tenor.
FUTURES_TENORS       = ["10d", "1m", "2m", "3m", "6m", "9m", "12m", "18m", "24m", "36m"]
FUTURES_TENOR_MONTHS = [0,     1,    2,    3,    6,    9,    12,    18,    24,    36]

MONTH_MAP = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}

# Eurostoxx 50 components — symbol + primary IBKR exchange
SX5E_COMPONENTS = [
    ("ADYEN",  "Adyen",               "AEB"),
    ("AIR",    "Airbus",              "SBF"),
    ("AI",     "Air Liquide",         "SBF"),
    ("ALV",    "Allianz",             "IBIS"),
    ("ASML",   "ASML",                "AEB"),
    ("AXA",    "AXA",                 "SBF"),
    ("BAS",    "BASF",                "IBIS"),
    ("BAYN",   "Bayer",               "IBIS"),
    ("BMW",    "BMW",                 "IBIS"),
    ("BNP",    "BNP Paribas",         "SBF"),
    ("CRH",    "CRH",                 "ISE"),
    ("DB1",    "Deutsche Boerse",     "IBIS"),
    ("DHL",    "DHL Group",           "IBIS"),
    ("DTE",    "Deutsche Telekom",    "IBIS"),
    ("ENEL",   "ENEL",                "BVME"),
    ("ENI",    "ENI",                 "BVME"),
    ("EL",     "EssilorLuxottica",    "SBF"),
    ("FLTR",   "Flutter",             "ISE"),
    ("HEIA",   "Heineken",            "AEB"),
    ("IBE",    "Iberdrola",           "BM"),
    ("IFX",    "Infineon",            "IBIS"),
    ("INGA",   "ING",                 "AEB"),
    ("ISP",    "Intesa Sanpaolo",     "BVME"),
    ("KER",    "Kering",              "SBF"),
    ("LIN",    "Linde",               "IBIS"),
    ("MC",     "LVMH",                "SBF"),
    ("MBG",    "Mercedes-Benz",       "IBIS"),
    ("MT",     "ArcelorMittal",       "AEB"),
    ("MUV2",   "Munich Re",           "IBIS"),
    ("NESTE",  "Neste",               "HEX"),
    ("NN",     "NN Group",            "AEB"),
    ("OR",     "L'Oreal",             "SBF"),
    ("PHIA",   "Philips",             "AEB"),
    ("PRX",    "Prosus",              "AEB"),
    ("RMS",    "Hermes",              "SBF"),
    ("RWE",    "RWE",                 "IBIS"),
    ("SAF",    "Safran",              "SBF"),
    ("SAN",    "Santander",           "BM"),
    ("SAP",    "SAP",                 "IBIS"),
    ("SIE",    "Siemens",             "IBIS"),
    ("SU",     "Schneider Electric",  "SBF"),
    ("GLE",    "Societe Generale",    "SBF"),
    ("TTE",    "TotalEnergies",       "SBF"),
    ("UCG",    "UniCredit",           "BVME"),
    ("DG",     "Vinci",               "SBF"),
    ("VNA",    "Vonovia",             "IBIS"),
    ("VOW3",   "Volkswagen",          "IBIS"),
    ("ENGI",   "Engie",               "SBF"),
    ("SG",     "Societe Generale B",  "SBF"),
    ("NOKIA",  "Nokia",               "HEX"),
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_months(months_str: str) -> list[str]:
    """Convert 'JUN26;JUL26;AUG26' → ['202606', '202607', '202608']."""
    result = []
    for m in months_str.split(";"):
        m = m.strip()
        if len(m) >= 5:
            name = m[:3].upper()
            year = "20" + m[3:5]
            num  = MONTH_MAP.get(name, "")
            if num:
                result.append(year + num)
    return result


def _num(val) -> float | None:
    """Parse IBKR field values — strips letter prefixes and % suffixes."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s in ("-", "N/A"):
        return None
    if s.endswith("%"):
        s = s[:-1]
    if s and s[0].isalpha() and len(s) > 1:
        s = s[1:]
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


# ── Index resolution ───────────────────────────────────────────────────────────

def resolve_index(client: IBKRClient, symbols=("ESTX50", "SX5E", "STOXX50E")) -> dict:
    """
    Find the index contract and extract option + futures months from its sections.
    Returns:
      { conid, name, symbol, opt_months: [YYYYMM, ...], fut_months: [YYYYMM, ...] }
    """
    for sym in symbols:
        try:
            results = client.search_contract(sym)
            if not (isinstance(results, list) and results):
                continue
            contract = results[0]
            conid = contract.get("conid")
            if not conid:
                continue

            opt_months, fut_months = [], []
            for section in contract.get("sections", []):
                months = _parse_months(section.get("months", ""))
                if section.get("secType") == "OPT":
                    opt_months = months
                elif section.get("secType") == "FUT":
                    fut_months = months

            info = {
                "conid":      int(conid),
                "name":       contract.get("companyName", sym),
                "symbol":     sym,
                "opt_months": opt_months,
                "fut_months": fut_months,
            }
            logger.info("Resolved %s -> conid=%s  opt=%d months  fut=%d months",
                        sym, conid, len(opt_months), len(fut_months))
            return info
        except Exception as exc:
            logger.warning("resolve_index %s: %s", sym, exc)

    raise RuntimeError("Could not resolve index - check IBKR entitlements")


# ── Spot price ─────────────────────────────────────────────────────────────────

def get_spot(client: IBKRClient, conid: int) -> dict:
    """Return spot price snapshot for an underlying conid."""
    try:
        snaps = client.snapshot([conid], SPOT_FIELDS)
        snap  = snaps[0] if isinstance(snaps, list) and snaps else {}
        last  = _num(snap.get("31"))
        chg   = _num(snap.get("82"))
        chg_p = _num(snap.get("83"))
        close = round(last - chg, 2) if last is not None and chg is not None else None
        return {
            "last":  last,
            "bid":   _num(snap.get("84")),
            "ask":   _num(snap.get("86")),
            "high":  _num(snap.get("70")),
            "low":   _num(snap.get("71")),
            "close": close,
            "chg":   chg,
            "chg_p": chg_p,
        }
    except Exception as exc:
        logger.error("get_spot: %s", exc)
        return {}


# ── Historical price data ──────────────────────────────────────────────────────

def get_price_history(client: IBKRClient, conid: int,
                      period: str = "3y", bar: str = "1w") -> list[dict]:
    """
    Fetch OHLCV history from IBKR.
    period: '3y', '1y', '6m', etc.
    bar:    '1w', '1d', '1h', etc.
    Returns list of { date, open, high, low, close }.
    """
    try:
        r = client.get("/iserver/marketdata/history", params={
            "conid": conid, "period": period, "bar": bar, "outsideRth": "false",
        })
        rows = []
        for d in r.get("data", []):
            import datetime
            ts = datetime.datetime.utcfromtimestamp(d["t"] / 1000)
            rows.append({
                "date":  ts,
                "open":  d.get("o"),
                "high":  d.get("h"),
                "low":   d.get("l"),
                "close": d.get("c"),
            })
        return rows
    except Exception as exc:
        logger.error("get_price_history: %s", exc)
        return []


# ── Futures curve ──────────────────────────────────────────────────────────────

def _resolve_futures_root(client: IBKRClient) -> int | None:
    """Find the ESTX50 futures root conid by searching with secType=FUT."""
    for sym in ("ESTX50", "SX5E", "STOXX50E"):
        try:
            results = client.post("/iserver/secdef/search", json={
                "symbol": sym, "secType": "FUT", "name": False,
            })
            if isinstance(results, list) and results:
                conid = results[0].get("conid")
                if conid:
                    logger.info("Futures root: %s -> conid=%s", sym, conid)
                    return int(conid)
        except Exception as exc:
            logger.debug("futures root %s: %s", sym, exc)
    return None


def get_futures_prices(client: IBKRClient, base_conid: int, fut_months: list[str]) -> list[dict]:
    """
    Resolve individual monthly futures conids via /iserver/secdef/info then snapshot them.
    Tries the futures root conid first; falls back to index conid.
    Selects the FESX contract (multiplier=10) over FSXE (multiplier=1) when both
    are returned for the same month.
    Returns list of { Month, Last, Bid, Ask }.
    """
    fut_root = _resolve_futures_root(client) or base_conid
    rows = []
    for month in fut_months[:24]:
        try:
            info = client.get("/iserver/secdef/info", params={
                "conid": fut_root, "sectype": "FUT", "month": month, "exchange": "EUREX",
            })
            if not (isinstance(info, list) and info):
                continue
            contract = next((c for c in info if c.get("tradingClass") == "FESX"), info[0])
            fut_conid = contract.get("conid")
            if not fut_conid:
                continue

            snaps = client.snapshot([int(fut_conid)], ["31", "84", "86"])
            snap  = snaps[0] if isinstance(snaps, list) and snaps else {}
            rows.append({
                "Month": month,
                "Last":  _num(snap.get("31")),
                "Bid":   _num(snap.get("84")),
                "Ask":   _num(snap.get("86")),
            })
        except Exception as exc:
            logger.debug("futures %s: %s", month, exc)
    return rows


def select_futures_curve(fut_months: list[str], tenors: list[str],
                          tenor_months: list[int]) -> list[tuple[str, str]]:
    """
    Pair each tenor label with the available contract month closest to
    (today + tenor_months[i]). Returns [(tenor, month), ...] in tenor order.
    EUREX only lists quarterly FESX expiries, so several tenors often map
    to the same month.
    """
    if not fut_months:
        return []

    def month_index(yyyymm: str) -> int:
        return int(yyyymm[:4]) * 12 + int(yyyymm[4:6]) - 1

    today_idx = month_index(date.today().strftime("%Y%m"))
    return [
        (tenor, min(fut_months, key=lambda m: abs(month_index(m) - (today_idx + n))))
        for tenor, n in zip(tenors, tenor_months)
    ]


# ── Component stocks ───────────────────────────────────────────────────────────

def resolve_components(client: IBKRClient) -> dict[str, dict]:
    """
    Resolve conids for all SX5E component stocks.
    Returns { symbol: { conid, name } }
    Call once at startup and cache the result.

    A plain symbol search often returns same-ticker stocks from other
    markets (e.g. "AIR" also matches AAR Corp on NYSE, "MC" also matches
    Moelis & Co). Disambiguate using the expected primary exchange first,
    falling back to a company-name match; skip the component entirely if
    neither yields a confident match (better than showing the wrong stock).
    """
    resolved = {}
    for symbol, name, exchange in SX5E_COMPONENTS:
        try:
            results = client.search_contract(symbol)
            if not (isinstance(results, list) and results):
                continue
            stk_results = [
                r for r in results
                if "STK" in [s.get("secType") for s in r.get("sections", [])]
            ]

            conid = next(
                (r.get("conid") for r in stk_results if r.get("description") == exchange),
                None,
            )
            if not conid:
                name_lo = name.lower()
                for r in stk_results:
                    company_lo = (r.get("companyName") or "").lower()
                    if company_lo and (name_lo in company_lo or company_lo.split()[0] in name_lo):
                        conid = r.get("conid")
                        break

            if conid:
                resolved[symbol] = {"conid": int(conid), "name": name}
                logger.debug("Component %s -> conid=%s", symbol, conid)
            else:
                logger.warning("Component %s (%s): no confident listing match, skipping", symbol, name)
        except Exception as exc:
            logger.warning("resolve_components %s: %s", symbol, exc)
    logger.info("Resolved %d/%d components", len(resolved), len(SX5E_COMPONENTS))
    return resolved


def get_component_spots(client: IBKRClient, components: dict[str, dict]) -> list[dict]:
    """
    Batch snapshot all component stocks.
    Returns list of { Symbol, Name, Last, Bid, Ask }.
    """
    conid_to_sym = {v["conid"]: (k, v["name"]) for k, v in components.items()}
    conids = list(conid_to_sym.keys())
    rows = []
    batch_size = 20

    for i in range(0, len(conids), batch_size):
        batch = conids[i:i + batch_size]
        try:
            snaps = client.snapshot(batch, ["31", "84", "86"])
            if not isinstance(snaps, list):
                continue
            for snap in snaps:
                cid = snap.get("conid")
                if cid and cid in conid_to_sym:
                    sym, name = conid_to_sym[cid]
                    rows.append({
                        "Symbol": sym,
                        "Name":   name,
                        "Last":   _num(snap.get("31")),
                        "Bid":    _num(snap.get("84")),
                        "Ask":    _num(snap.get("86")),
                    })
        except Exception as exc:
            logger.warning("component batch snapshot: %s", exc)

    return sorted(rows, key=lambda r: r["Symbol"])


# ── Option chain ───────────────────────────────────────────────────────────────

def get_strikes(client: IBKRClient, conid: int, month: str) -> list[float]:
    """Return sorted list of available strikes for a given YYYYMM month."""
    for exchange in ("EUREX", ""):
        try:
            result = client.get("/iserver/secdef/strikes", params={
                "conid": conid, "sectype": "OPT", "month": month, "exchange": exchange,
            })
            if isinstance(result, dict):
                strikes = sorted(set(result.get("call", []) + result.get("put", [])))
                if strikes:
                    return strikes
        except Exception as exc:
            logger.warning("get_strikes %s exchange=%s: %s", month, exchange, exc)
    return []


def get_option_conid(client: IBKRClient, conid: int, month: str, strike: float, right: str) -> int | None:
    """Resolve a single option contract conid via /iserver/secdef/info."""
    for exchange in ("EUREX", ""):
        try:
            result = client.get("/iserver/secdef/info", params={
                "conid": conid, "sectype": "OPT",
                "month": month, "strike": strike, "right": right,
                "exchange": exchange,
            })
            if isinstance(result, list) and result:
                return result[0].get("conid")
            if isinstance(result, dict):
                return result.get("conid")
        except Exception as exc:
            logger.debug(
                "get_option_conid %s %s %s exchange=%s: %s",
                month, strike, right, exchange, exc
            )
    return None


def _option_mid_and_quality(bid: float | None, ask: float | None,
                            last: float | None) -> tuple[float | None, float | None, str]:
    if bid is not None and ask is not None and bid > 0 and ask > 0 and ask >= bid:
        mid = (bid + ask) / 2.0
        spread = ask - bid
        spread_pct = spread / mid if mid > 0 else 1.0
        if spread_pct <= 0.05:
            quality = "tight"
        elif spread_pct <= 0.15:
            quality = "wide"
        else:
            quality = "very wide"
        return round(mid, 4), round(spread, 4), quality
    if last is not None and last > 0:
        return last, None, "last only"
    return None, None, "empty"


def _option_label(right: str, target: float | None, strike: float, atm_strike: float) -> str:
    if target is None:
        return "ATM call" if right == "C" else "ATM put"
    prefix = "+" if right == "C" else "-"
    side = "call" if right == "C" else "put"
    return f"{prefix}{int(target * 100)}Δ {side}"


def get_options_table(
    client: IBKRClient, conid: int, months: list[str], spot: float,
    delta_step: int = 5,
) -> list[dict]:
    """
    Build the options data table (Tab 1 / Tab 4).
    For each of the first 6 months: one contract per delta target from
    -30 to +30 in `delta_step` increments (Puts for negative targets,
    Calls for positive), with BOTH a Put and a Call resolved at the ATM
    (0) target. Strikes are picked via a simple OTM% proxy
    (|delta|/30 * 10%) - the real per-contract Delta from IBKR is
    returned in the "Delta" column. Conid lookups are deduplicated per
    unique (strike, right) to bound the number of IBKR calls.
    Returns list of row dicts with raw Greeks (€ translation done in app layer).
    """
    rows = []
    delta_targets = list(range(-30, 31, delta_step))

    for month in months[:6]:
        strikes = get_strikes(client, conid, month)
        if not strikes:
            logger.warning("No strikes for month %s", month)
            continue

        atm_strike = min(strikes, key=lambda k: abs(k - spot))
        targets: list[dict] = []
        for d in delta_targets:
            otm_pct = abs(d) / 30 * 0.10
            if d < 0:
                strike = min(strikes, key=lambda k: abs(k - spot * (1 - otm_pct)))
                targets.append({"strike": strike, "right": "P", "target": abs(d) / 100})
            elif d > 0:
                strike = min(strikes, key=lambda k: abs(k - spot * (1 + otm_pct)))
                targets.append({"strike": strike, "right": "C", "target": d / 100})
            else:
                targets.append({"strike": atm_strike, "right": "P", "target": None})
                targets.append({"strike": atm_strike, "right": "C", "target": None})

        # Resolve each unique (strike, right) once, even if several delta
        # targets collapse onto the same listed strike.
        conid_map: dict[tuple[float, str], int | None] = {}
        for contract in targets:
            strike = contract["strike"]
            right = contract["right"]
            key = (strike, right)
            if key not in conid_map:
                conid_map[key] = get_option_conid(client, conid, month, strike, right)

        unique_conids = {c for c in conid_map.values() if c}
        try:
            snaps = client.snapshot(list(unique_conids), OPTION_FIELDS) if unique_conids else []
            snap_map = {s.get("conid"): s for s in snaps} if isinstance(snaps, list) else {}
        except Exception as exc:
            logger.warning("option snapshot %s: %s", month, exc)
            snap_map = {}

        for contract in targets:
            strike = contract["strike"]
            right = contract["right"]
            opt_conid = conid_map.get((strike, right))
            if not opt_conid:
                logger.warning("No conid for %s %s %s", month, strike, right)
                continue
            s = snap_map.get(opt_conid, {})
            bid = _num(s.get("84"))
            ask = _num(s.get("86"))
            last = _num(s.get("31"))
            mid, spread, quality = _option_mid_and_quality(bid, ask, last)
            rows.append({
                "Maturity": month,
                "Strike": strike,
                "Type": "Call" if right == "C" else "Put",
                "Right": right,
                "Delta Target": contract["target"],
                "Label": _option_label(right, contract["target"], strike, atm_strike),
                "Bid": bid,
                "Ask": ask,
                "Last": last,
                "Mid": mid,
                "Spread": spread,
                "Quote Quality": quality,
                "IV %": _num(s.get("7636")),
                "Delta": _num(s.get("7308")),
                "Gamma": _num(s.get("7309")),
                "Vega": _num(s.get("7310")),
                "Theta": _num(s.get("7311")),
            })

    logger.info("Options table: %d rows for %d months", len(rows), len(months[:6]))
    return rows
