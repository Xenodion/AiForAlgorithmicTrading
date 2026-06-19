"""
FastAPI backend for the React volatility dashboard.

Run:
    uvicorn src.api.server:app --reload --port 8000
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.analytics.pricer import (
    black_scholes,
    greeks,
    scenario_grid,
)
from src.connectivity.session import IBKRClient
from src.data.fetcher import (
    FUTURES_TENOR_MONTHS,
    FUTURES_TENORS,
    get_component_spots,
    get_futures_prices,
    get_options_table,
    get_price_history,
    get_spot,
    resolve_components,
    resolve_index,
    select_futures_curve,
)
from src.forwards.engine import build_forward_curve
from src.iv.solver import solve_implied_volatility
from src.orders.safety import ORDER_SAFETY_VERSION, dry_run_order, submit_order, validate_order
from src.qc.options import QUOTE_QC_VERSION, apply_quote_qc
from src.risk.portfolio import (
    backtest_report,
    portfolio_report,
    scenario_report,
    value_position,
    Position as RiskPosition,
)
from src.snapshots.builder import build_option_snapshot
from src.storage.artifacts import latest_run_summary, record_options_surface_run
from src.storage.strategies import (
    delete_strategy,
    list_strategies,
    load_strategy,
    save_strategy,
)
from src.surfaces.engine import build_surface
from src.validation.checks import latest_run_validation


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs" / "broker.yaml"


app = FastAPI(
    title="Volatility Infrastructure API",
    version="1.0.0",
    description="React-facing API over the existing IBKR data and pricing modules.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@dataclass
class Runtime:
    client: IBKRClient
    index: dict[str, Any]
    components: dict[str, dict[str, Any]]
    started_at: datetime = field(default_factory=datetime.utcnow)


_runtime: Runtime | None = None
_runtime_lock = threading.Lock()
_tickle_started = False
_cache: dict[str, tuple[float, Any]] = {}
_cache_locks: dict[str, threading.Lock] = {}
_cache_locks_guard = threading.Lock()


class PositionInput(BaseModel):
    label: str = "ESTX50 ATM C"
    option_type: Literal["call", "put"] = "call"
    strike: float = Field(gt=0)
    maturity: float = Field(gt=0)
    rate: float = 0.03
    sigma: float = Field(gt=0)
    quantity: int = 1
    multiplier: float = 10


class BacktestRequest(BaseModel):
    positions: list[PositionInput]
    period: str = "3m"


class ScenarioRequest(BaseModel):
    positions: list[PositionInput]
    spot_value: float = Field(gt=0)
    spot_shocks: list[float] | None = None
    vol_shocks: list[float] | None = None
    day_shocks: list[int] | None = None


class StrategyRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    underlying: str | None = None
    positions: list[PositionInput] = Field(min_length=1)
    strategy_id: str | None = None


class DeleteStrategyRequest(BaseModel):
    strategy_id: str = Field(min_length=1)


class OrderTicket(BaseModel):
    underlying: str = "ESTX50"
    side: Literal["BUY", "SELL"] = "BUY"
    quantity: float = Field(default=1, gt=0)
    orderType: Literal["LIMIT", "MARKET"] = "LIMIT"
    limitPrice: float | None = None


@app.on_event("startup")
def _startup_surface_warmup() -> None:
    def _warm() -> None:
        # Give the server a moment to finish starting, then pre-build the
        # surface so Operations tab has a stored run on first open.
        time.sleep(8)
        try:
            rt = runtime()
            cache_key = "surface:10:0.03"
            _ttl(cache_key, 60, lambda: _surface_payload(rt, notional=10, rate=0.03))
        except Exception:
            pass

    threading.Thread(target=_warm, daemon=True, name="surface-warmup").start()


def _start_tickle(client: IBKRClient) -> None:
    global _tickle_started
    if _tickle_started:
        return

    def keepalive() -> None:
        while True:
            time.sleep(55)
            try:
                client.tickle()
            except Exception:
                try:
                    client.post("/iserver/reauthenticate")
                except Exception:
                    pass

    threading.Thread(target=keepalive, daemon=True, name="ibkr-api-tickle").start()
    _tickle_started = True


def runtime() -> Runtime:
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            client = IBKRClient.from_config(str(CONFIG_PATH))
            client.check_auth()
            index = resolve_index(client)
            components = resolve_components(client)
            _start_tickle(client)
            _runtime = Runtime(client=client, index=index, components=components)
    return _runtime


def _ttl(key: str, ttl_seconds: int, loader):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl_seconds:
        return hit[1]

    with _cache_locks_guard:
        lock = _cache_locks.setdefault(key, threading.Lock())

    with lock:
        now = time.time()
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl_seconds:
            return hit[1]
        value = loader()
        _cache[key] = (now, value)
        return value


def _clean(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return _clean(value.to_dict(orient="records"))
    if isinstance(value, pd.Series):
        return _clean(value.to_dict())
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _month_label(month: str) -> str:
    return date(int(month[:4]), int(month[4:6]), 1).strftime("%b%y")


def _maturity_years(month: str) -> float:
    year = int(str(month)[:4])
    month_num = int(str(month)[4:6])
    if month_num == 12:
        expiry = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        expiry = date(year, month_num + 1, 1) - timedelta(days=1)
    return max((expiry - date.today()).days / 365.0, 1 / 365.0)


def _option_price(row: pd.Series) -> float | None:
    bid, ask = row.get("Bid"), row.get("Ask")
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    last = row.get("Last")
    if last is not None and last > 0:
        return float(last)
    return None


def _mid_price(row: pd.Series) -> float | None:
    bid, ask = row.get("Bid"), row.get("Ask")
    if bid is None or ask is None or pd.isna(bid) or pd.isna(ask):
        return None
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    return (bid + ask) / 2.0


def _intrinsic_value(row: pd.Series, spot: float) -> float:
    strike = float(row.get("Strike") or 0)
    option_type = "put" if str(row.get("Right") or row.get("Type", "")).upper().startswith("P") else "call"
    return max(spot - strike, 0.0) if option_type == "call" else max(strike - spot, 0.0)


def _quote_qc(row: pd.Series, spot: float) -> tuple[str, list[str], bool]:
    reasons = []
    bid, ask, last = row.get("Bid"), row.get("Ask"), row.get("Last")
    mid = _mid_price(row)

    if bid is None or ask is None or pd.isna(bid) or pd.isna(ask):
        reasons.append("missing_bid_ask")
    elif bid <= 0 or ask <= 0:
        reasons.append("non_positive_bid_ask")
    elif ask < bid:
        reasons.append("crossed_market")

    if mid is None:
        if last is not None and pd.notna(last) and last > 0:
            reasons.append("last_only")
        else:
            reasons.append("empty_quote")
    else:
        spread_pct = (ask - bid) / mid if mid > 0 else float("inf")
        if spread_pct > 0.50:
            reasons.append("extreme_spread")
        elif spread_pct > 0.15:
            reasons.append("wide_spread")

        intrinsic = _intrinsic_value(row, spot)
        if mid + 1e-9 < intrinsic:
            reasons.append("below_intrinsic")

    iv = row.get("IV %")
    if iv is None or pd.isna(iv):
        reasons.append("missing_iv")
    elif iv <= 0 or iv > 200:
        reasons.append("implausible_iv")

    if any(reason in reasons for reason in [
        "crossed_market",
        "empty_quote",
        "missing_iv",
        "implausible_iv",
        "below_intrinsic",
        "extreme_spread",
    ]):
        return "reject", reasons, False
    if any(reason in reasons for reason in ["wide_spread", "last_only", "missing_bid_ask", "non_positive_bid_ask"]):
        return "caution", reasons, mid is not None and iv is not None and pd.notna(iv)
    return "usable", reasons, True


def _fill_missing_iv(df: pd.DataFrame, spot: float, rate: float = 0.03) -> pd.DataFrame:
    df = df.copy()
    if df.empty:
        return df
    if "IV Source" not in df.columns:
        df["IV Source"] = df["IV %"].apply(lambda v: "IBKR" if pd.notna(v) else None)
    df["IV Status"] = df["IV %"].apply(lambda v: "provided" if pd.notna(v) else "missing")
    df["IV Price"] = None
    df["IV Model"] = df["IV %"].apply(lambda v: "IBKR snapshot" if pd.notna(v) else None)
    df["IV Iterations"] = None
    df["IV Residual"] = None
    df["IV Lower Vol"] = None
    df["IV Upper Vol"] = None
    df["IV Reason"] = None
    df["IV Intrinsic"] = None

    for idx, row in df[df["IV %"].isna()].iterrows():
        price = _option_price(row)
        option_type = "put" if "put" in str(row.get("Type", "")).lower() else "call"
        result = solve_implied_volatility(
            price=price,
            spot=spot,
            strike=float(row["Strike"]),
            maturity=_maturity_years(row["Maturity"]),
            rate=rate,
            option_type=option_type,
        )
        df.at[idx, "IV Price"] = result["price"]
        df.at[idx, "IV Status"] = result["status"]
        df.at[idx, "IV Model"] = result["model"]
        df.at[idx, "IV Iterations"] = result["iterations"]
        df.at[idx, "IV Residual"] = result["residual"]
        df.at[idx, "IV Lower Vol"] = result["lower_vol"]
        df.at[idx, "IV Upper Vol"] = result["upper_vol"]
        df.at[idx, "IV Reason"] = result["reason"]
        df.at[idx, "IV Intrinsic"] = result["intrinsic"]

        if result["implied_vol"] is not None:
            df.at[idx, "IV %"] = round(result["implied_vol"] * 100, 4)
            df.at[idx, "IV Source"] = "BS fallback"
        else:
            df.at[idx, "IV Source"] = None

    return df


def _apply_quote_qc(df: pd.DataFrame, spot: float) -> pd.DataFrame:
    return apply_quote_qc(df, spot)


def _option_rows(rt: Runtime, notional: float = 10) -> list[dict[str, Any]]:
    spot = get_spot(rt.client, rt.index["conid"])
    spot_price = float(spot.get("last") or spot.get("close") or 5000)
    rows = get_options_table(rt.client, rt.index["conid"], rt.index["opt_months"], spot_price)
    if not rows:
        return []

    df = _fill_missing_iv(pd.DataFrame(rows), spot_price)
    df = _apply_quote_qc(df, spot_price)
    df["Reference Spot"] = spot_price
    df["Reference Rate"] = 0.03
    for greek in ["Delta", "Gamma", "Vega", "Theta"]:
        if greek in df.columns:
            df[f"{greek} (€)"] = df[greek].apply(
                lambda v: round(v * notional, 4) if v is not None and pd.notna(v) else None
            )
    if "Vega" in df.columns:
        def _rtv(row: pd.Series) -> float | None:
            v = row.get("Vega")
            if v is None or pd.isna(v):
                return None
            t = _maturity_years(str(row["Maturity"]))
            return round(float(v) / t ** 0.5, 4)
        df["Root Time Vega"] = df.apply(_rtv, axis=1)
        df["Root Time Vega (€)"] = df["Root Time Vega"].apply(
            lambda v: round(v * notional, 4) if v is not None and pd.notna(v) else None
        )
    return _clean(df)


def _cached_option_rows(rt: Runtime, notional: float) -> list[dict[str, Any]]:
    return _ttl(f"options:{notional}", 60, lambda: _option_rows(rt, notional=notional))


def _option_diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"totalRows": 0, "maturities": []}

    df = pd.DataFrame(rows)

    def counts(column: str) -> dict[str, int]:
        if column not in df.columns:
            return {}
        return {str(k): int(v) for k, v in df[column].explode().value_counts(dropna=False).items()}

    def reason_counts(frame: pd.DataFrame) -> dict[str, int]:
        if "QC Reasons" not in frame.columns:
            return {}
        reasons = [
            reason
            for values in frame["QC Reasons"]
            for reason in (values if isinstance(values, list) else [])
        ]
        return {str(k): int(v) for k, v in pd.Series(reasons).value_counts().items()}

    by_maturity = []
    for maturity, group in df.groupby("Maturity", dropna=False):
        by_maturity.append({
            "maturity": maturity,
            "rows": int(len(group)),
            "surfaceEligible": int(group["Surface Eligible"].fillna(False).sum()),
            "ivCount": int(group["IV %"].notna().sum()),
            "qcStatus": {str(k): int(v) for k, v in group["QC Status"].value_counts(dropna=False).items()},
            "quoteQuality": {str(k): int(v) for k, v in group["Quote Quality"].value_counts(dropna=False).items()},
            "ivSource": {str(k): int(v) for k, v in group["IV Source"].value_counts(dropna=False).items()},
            "qcReasons": reason_counts(group),
        })

    return {
        "totalRows": int(len(df)),
        "surfaceEligible": int(df["Surface Eligible"].fillna(False).sum()),
        "ivCount": int(df["IV %"].notna().sum()),
        "qcVersion": QUOTE_QC_VERSION,
        "qcStatus": counts("QC Status"),
        "quoteQuality": counts("Quote Quality"),
        "ivSource": counts("IV Source"),
        "qcReasons": reason_counts(df),
        "maturities": by_maturity,
    }


def _recompute_surface_iv(
    rows: list[dict[str, Any]],
    forwards_by_maturity: dict[str, float],
    spot: float,
    rate: float,
) -> list[dict[str, Any]]:
    """
    Re-invert every surface-eligible quote to implied vol against that
    maturity's forward (Black-76 via an effective-spot transform), so the
    whole surface uses ONE consistent inversion. This removes the seam caused
    by mixing IBKR's forward-based IV (field 7636) with the spot-based BS
    fallback, and makes the put and call agree at the ATM strike by put-call
    parity. Falls back to the row's existing IV % when the inversion fails.
    """
    out = []
    for row in rows:
        new_row = dict(row)
        if row.get("Surface Eligible"):
            price = row.get("Mid") or row.get("QC Reference Price")
            try:
                price = float(price)
                strike = float(row.get("Strike"))
            except (TypeError, ValueError):
                price, strike = None, None
            if price and price > 0 and strike and strike > 0:
                maturity = str(row.get("Maturity"))
                t = _maturity_years(maturity)
                forward = forwards_by_maturity.get(maturity) or spot * math.exp(rate * t)
                effective_spot = forward * math.exp(-rate * t)
                option_type = "put" if "put" in str(row.get("Type", "")).lower() else "call"
                result = solve_implied_volatility(
                    price=price,
                    spot=effective_spot,
                    strike=strike,
                    maturity=t,
                    rate=rate,
                    option_type=option_type,
                )
                if result["implied_vol"] is not None:
                    new_row["IV %"] = round(result["implied_vol"] * 100, 4)
                    new_row["IV Source"] = "BS forward"
                    new_row["IV Status"] = "converged"
        out.append(new_row)
    return out


def _surface_payload(rt: Runtime, notional: float, rate: float = 0.03) -> dict[str, Any]:
    rows = _cached_option_rows(rt, notional)
    reference_spot = next((row.get("Reference Spot") for row in rows if row.get("Reference Spot")), None)
    spot = get_spot(rt.client, rt.index["conid"])
    spot_price = float(spot.get("last") or spot.get("close") or reference_spot or 5000)
    forward_payload = build_forward_curve(rows, spot=spot_price, rate=rate)
    surface_rows = _recompute_surface_iv(rows, forward_payload["forwards"], spot_price, rate)
    surface_payload = build_surface(
        surface_rows,
        spot=spot_price,
        rate=rate,
        forwards_by_maturity=forward_payload["forwards"],
        forward_diagnostics=forward_payload["diagnostics"],
    )
    surface_payload["forwardCurve"] = forward_payload
    option_diagnostics = _option_diagnostics(rows)
    manifest = record_options_surface_run(
        underlying=rt.index.get("symbol") or rt.index.get("name") or "unknown",
        notional=notional,
        rate=rate,
        option_rows=rows,
        option_diagnostics=option_diagnostics,
        surface_payload=surface_payload,
        quote_qc_version=option_diagnostics.get("qcVersion"),
    )
    surface_payload["storageManifest"] = manifest
    return surface_payload


def _forward_payload(rt: Runtime, notional: float, rate: float = 0.03) -> dict[str, Any]:
    rows = _cached_option_rows(rt, notional)
    reference_spot = next((row.get("Reference Spot") for row in rows if row.get("Reference Spot")), None)
    spot = get_spot(rt.client, rt.index["conid"])
    spot_price = float(spot.get("last") or spot.get("close") or reference_spot or 5000)
    return build_forward_curve(rows, spot=spot_price, rate=rate)


def _option_snapshot_payload(rt: Runtime, notional: float) -> dict[str, Any]:
    rows = _cached_option_rows(rt, notional)
    reference_spot = next((row.get("Reference Spot") for row in rows if row.get("Reference Spot")), None) or 5000
    return build_option_snapshot(
        underlying=rt.index.get("symbol") or rt.index.get("name") or "unknown",
        spot=float(reference_spot),
        option_rows=rows,
    )


def _position_value(position: PositionInput, spot: float) -> dict[str, Any]:
    return value_position(RiskPosition.from_any(position), spot)


@app.get("/api/status")
def status():
    try:
        rt = runtime()
        return _clean({
            "connected": True,
            "startedAt": rt.started_at,
            "index": rt.index,
            "components": len(rt.components),
        })
    except Exception as exc:
        return {"connected": False, "error": str(exc)}


@app.get("/api/bootstrap")
def bootstrap():
    try:
        rt = runtime()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    components = [
        {"symbol": symbol, **info}
        for symbol, info in sorted(rt.components.items(), key=lambda item: item[1]["name"].lower())
    ]
    return _clean({
        "index": rt.index,
        "components": components,
        "futuresTenors": FUTURES_TENORS,
    })


@app.get("/api/runs/latest")
def latest_run():
    return _clean(latest_run_summary())


@app.get("/api/validation/latest")
def validation_latest():
    return _clean(latest_run_validation(latest_run_summary()))


@app.get("/api/operations/summary")
def operations_summary():
    latest = latest_run_summary()
    snapshot = None
    try:
        rt = runtime()
        snapshot = _ttl("option-snapshot:10", 60, lambda: _option_snapshot_payload(rt, notional=10))
    except Exception:
        pass
    return _clean({
        "latestRun": latest,
        "validation": latest_run_validation(latest),
        "orderSafetyVersion": ORDER_SAFETY_VERSION,
        "routingEnabled": False,
        "snapshot": {
            "version": snapshot.get("snapshotVersion") if snapshot else None,
            "ts": snapshot.get("snapshotTs") if snapshot else None,
            "underlying": snapshot.get("underlying") if snapshot else None,
            "spot": snapshot.get("spot") if snapshot else None,
            "rowCount": snapshot["diagnostics"]["rowCount"] if snapshot else None,
            "referenceCounts": snapshot["diagnostics"]["referenceCounts"] if snapshot else None,
            "missingReference": snapshot["diagnostics"]["missingReference"] if snapshot else None,
        } if snapshot else None,
    })


@app.get("/api/spot")
def spot(conid: int | None = None):
    try:
        rt = runtime()
        target_conid = conid or rt.index["conid"]
        return _clean(get_spot(rt.client, target_conid))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/history")
def history(
    conid: int | None = None,
    period: str = Query("3y"),
    bar: str = Query("1w"),
):
    try:
        rt = runtime()
        target_conid = conid or rt.index["conid"]
        return _clean(get_price_history(rt.client, target_conid, period=period, bar=bar))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/futures")
def futures():
    try:
        rt = runtime()
        cache_key = "futures"

        def load():
            curve = select_futures_curve(rt.index["fut_months"], FUTURES_TENORS, FUTURES_TENOR_MONTHS)
            curve_months = sorted({month for _, month in curve})
            price_rows = get_futures_prices(rt.client, rt.index["conid"], curve_months)
            price_by_month = {row["Month"]: row for row in price_rows}
            return [
                {
                    "Tenor": tenor,
                    "Month": month,
                    "Expiry": _month_label(month),
                    "Last": price_by_month.get(month, {}).get("Last"),
                    "Bid": price_by_month.get(month, {}).get("Bid"),
                    "Ask": price_by_month.get(month, {}).get("Ask"),
                }
                for tenor, month in curve
            ]

        return _clean(_ttl(cache_key, 45, load))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/options")
def options(notional: float = Query(10, gt=0)):
    try:
        rt = runtime()
        return _clean(_cached_option_rows(rt, notional=notional))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/options/diagnostics")
def options_diagnostics(notional: float = Query(10, gt=0)):
    try:
        rt = runtime()
        rows = _cached_option_rows(rt, notional=notional)
        return _clean(_option_diagnostics(rows))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/snapshot/options")
def option_snapshot(notional: float = Query(10, gt=0)):
    try:
        rt = runtime()
        cache_key = f"option-snapshot:{notional}"
        return _clean(_ttl(cache_key, 60, lambda: _option_snapshot_payload(rt, notional=notional)))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/forwards")
def forwards(notional: float = Query(10, gt=0), rate: float = Query(0.03)):
    try:
        rt = runtime()
        cache_key = f"forwards:{notional}:{rate}"
        return _clean(_ttl(cache_key, 60, lambda: _forward_payload(rt, notional=notional, rate=rate)))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/surface")
def surface(notional: float = Query(10, gt=0), rate: float = Query(0.03)):
    try:
        rt = runtime()
        cache_key = f"surface:{notional}:{rate}"
        return _clean(_ttl(cache_key, 60, lambda: _surface_payload(rt, notional=notional, rate=rate)))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/surface/diagnostics")
def surface_diagnostics(notional: float = Query(10, gt=0), rate: float = Query(0.03)):
    try:
        rt = runtime()
        cache_key = f"surface:{notional}:{rate}"
        payload = _ttl(cache_key, 60, lambda: _surface_payload(rt, notional=notional, rate=rate))
        return _clean(payload["diagnostics"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/components")
def components():
    try:
        rt = runtime()
        rows = get_component_spots(rt.client, rt.components)
        return _clean(rows)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/component/{symbol}")
def component_detail(
    symbol: str,
    period: str = Query("3y"),
    bar: str = Query("1w"),
):
    try:
        rt = runtime()
        symbol = symbol.upper()
        if symbol not in rt.components:
            raise HTTPException(status_code=404, detail=f"Unknown component {symbol}")
        info = rt.components[symbol]
        return _clean({
            "symbol": symbol,
            "name": info["name"],
            "conid": info["conid"],
            "spot": get_spot(rt.client, info["conid"]),
            "history": get_price_history(rt.client, info["conid"], period=period, bar=bar),
        })
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/risk/pricer")
def risk_pricer(
    spot_value: float = Query(5000, gt=0),
    strike: float = Query(5000, gt=0),
    maturity: float = Query(0.25, gt=0),
    rate: float = Query(0.03),
    sigma: float = Query(0.20, gt=0),
    multiplier: float = Query(10, gt=0),
):
    return _clean({
        option_type: {
            "price": round(black_scholes(spot_value, strike, maturity, rate, sigma, option_type), 4),
            "greeks": greeks(spot_value, strike, maturity, rate, sigma, option_type, multiplier),
        }
        for option_type in ["call", "put"]
    })


@app.get("/api/risk/scenario")
def risk_scenario(
    spot_value: float = Query(5000, gt=0),
    strike: float = Query(5000, gt=0),
    maturity: float = Query(0.25, gt=0),
    rate: float = Query(0.03),
    sigma: float = Query(0.20, gt=0),
    option_type: Literal["call", "put"] = "call",
    multiplier: float = Query(10, gt=0),
):
    rows = scenario_grid(
        S=spot_value,
        K=strike,
        T=maturity,
        r=rate,
        sigma=sigma,
        option_type=option_type,
        multiplier=multiplier,
        spot_shocks=[-0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15],
        vol_shocks=[-0.10, -0.05, 0.0, 0.05, 0.10],
    )
    return _clean(rows)


@app.post("/api/risk/position")
def risk_position(position: PositionInput, spot_value: float = Query(5000, gt=0)):
    return _clean(_position_value(position, spot_value))


@app.post("/api/risk/portfolio")
def risk_portfolio(payload: list[PositionInput], spot_value: float = Query(5000, gt=0)):
    return _clean(portfolio_report(payload, spot=spot_value))


@app.post("/api/risk/scenarios")
def risk_scenarios(payload: ScenarioRequest):
    return _clean(
        scenario_report(
            payload.positions,
            spot=payload.spot_value,
            spot_shocks=payload.spot_shocks,
            vol_shocks=payload.vol_shocks,
            day_shocks=payload.day_shocks,
        )
    )


@app.get("/api/risk/strategies")
def risk_strategies():
    return _clean({
        "storage": "parquet",
        "strategies": list_strategies(),
    })


@app.get("/api/risk/strategies/{strategy_id}")
def risk_strategy_detail(strategy_id: str):
    strategy = load_strategy(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail=f"Unknown strategy {strategy_id}")
    return _clean(strategy)


@app.post("/api/risk/strategies")
def risk_strategy_save(payload: StrategyRequest):
    strategy = save_strategy(
        strategy_id=payload.strategy_id,
        name=payload.name.strip(),
        description=payload.description,
        underlying=payload.underlying,
        positions=[position.model_dump() for position in payload.positions],
    )
    return _clean(strategy)


@app.post("/api/risk/strategies/delete")
def risk_strategy_delete(payload: DeleteStrategyRequest):
    deleted = delete_strategy(payload.strategy_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Unknown strategy {payload.strategy_id}")
    return {"deleted": True, "strategy_id": payload.strategy_id}


@app.post("/api/risk/backtest")
def risk_backtest(payload: BacktestRequest):
    try:
        rt = runtime()
        spot_now = get_spot(rt.client, rt.index["conid"])
        spot_today = float(spot_now.get("last") or spot_now.get("close") or 5000)
        history_rows = get_price_history(rt.client, rt.index["conid"], period=payload.period, bar="1d")
        return _clean(backtest_report(payload.positions, history_rows, spot_today)["rows"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/risk/backtest/report")
def risk_backtest_report(payload: BacktestRequest):
    try:
        rt = runtime()
        spot_now = get_spot(rt.client, rt.index["conid"])
        spot_today = float(spot_now.get("last") or spot_now.get("close") or 5000)
        history_rows = get_price_history(rt.client, rt.index["conid"], period=payload.period, bar="1d")
        return _clean(backtest_report(payload.positions, history_rows, spot_today))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/orders/preview")
def orders_preview():
    try:
        rt = runtime()
        accounts = rt.client.get_accounts()
        account_id = accounts[0] if accounts else None

        raw_orders = rt.client.get_open_orders()
        raw_positions = rt.client.get_positions(account_id) if account_id else []

        open_orders = [
            {
                "Order ID": str(o.get("orderId") or "—"),
                "Symbol": o.get("ticker") or o.get("symbol") or "—",
                "Side": o.get("side") or "—",
                "Qty": o.get("totalSize") or o.get("quantity") or "—",
                "Type": o.get("orderType") or "—",
                "Status": o.get("status") or "—",
            }
            for o in raw_orders
        ]
        positions = [
            {
                "Symbol": p.get("contractDesc") or p.get("ticker") or "—",
                "Qty": p.get("position") or "—",
                "Avg Price": p.get("avgCost"),
                "Market Price": p.get("mktPrice"),
                "PnL": p.get("unrealizedPnl"),
            }
            for p in raw_positions
        ]
    except Exception:
        open_orders = []
        positions = []

    return _clean({
        "openOrders": open_orders,
        "positions": positions,
        "routingEnabled": False,
        "safetyVersion": ORDER_SAFETY_VERSION,
    })


@app.post("/api/orders/validate")
def orders_validate(ticket: OrderTicket):
    return _clean(validate_order(ticket.model_dump()))


@app.post("/api/orders/dry-run")
def orders_dry_run(ticket: OrderTicket):
    return _clean(dry_run_order(ticket.model_dump()))


@app.post("/api/orders/submit")
def orders_submit(ticket: OrderTicket):
    return _clean(submit_order(ticket.model_dump()))


@app.post("/api/orders/cancel")
def orders_cancel(order_id: str = Query(...)):
    return {
        "orderId": order_id,
        "status": "not_routed",
        "routingEnabled": False,
        "message": "No live order exists because real routing is disabled.",
    }
