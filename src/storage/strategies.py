"""
Parquet-backed storage for user-created risk strategies.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STRATEGY_ROOT = ROOT / "data" / "strategies"
STRATEGY_PATH = STRATEGY_ROOT / "strategies.parquet"
STRATEGY_SCHEMA_VERSION = "risk-strategy-parquet-v1"

POSITION_COLUMNS = [
    "label",
    "option_type",
    "strike",
    "maturity",
    "rate",
    "sigma",
    "quantity",
    "multiplier",
]

COLUMNS = [
    "strategy_id",
    "name",
    "description",
    "underlying",
    "created_at",
    "updated_at",
    "schema_version",
    "position_index",
    *POSITION_COLUMNS,
]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS)


def _read_frame() -> pd.DataFrame:
    if not STRATEGY_PATH.exists():
        return _empty_frame()
    frame = pd.read_parquet(STRATEGY_PATH)
    for column in COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    return frame[COLUMNS]


def _write_frame(frame: pd.DataFrame) -> None:
    STRATEGY_ROOT.mkdir(parents=True, exist_ok=True)
    frame = frame[COLUMNS].sort_values(["updated_at", "strategy_id", "position_index"], ascending=[False, True, True])
    frame.to_parquet(STRATEGY_PATH, index=False, engine="pyarrow")


def list_strategies() -> list[dict[str, Any]]:
    frame = _read_frame()
    if frame.empty:
        return []

    rows = []
    for strategy_id, group in frame.groupby("strategy_id", sort=False):
        first = group.iloc[0]
        rows.append({
            "strategy_id": strategy_id,
            "name": first.get("name"),
            "description": first.get("description"),
            "underlying": first.get("underlying"),
            "created_at": first.get("created_at"),
            "updated_at": first.get("updated_at"),
            "position_count": int(len(group)),
            "schema_version": first.get("schema_version"),
        })
    return sorted(rows, key=lambda row: row.get("updated_at") or "", reverse=True)


def load_strategy(strategy_id: str) -> dict[str, Any] | None:
    frame = _read_frame()
    rows = frame[frame["strategy_id"] == strategy_id].sort_values("position_index")
    if rows.empty:
        return None

    first = rows.iloc[0]
    positions = []
    for _, row in rows.iterrows():
        positions.append({
            "label": row.get("label"),
            "option_type": row.get("option_type"),
            "strike": float(row.get("strike")),
            "maturity": float(row.get("maturity")),
            "rate": float(row.get("rate")),
            "sigma": float(row.get("sigma")),
            "quantity": int(row.get("quantity")),
            "multiplier": float(row.get("multiplier")),
        })

    return {
        "strategy_id": strategy_id,
        "name": first.get("name"),
        "description": first.get("description"),
        "underlying": first.get("underlying"),
        "created_at": first.get("created_at"),
        "updated_at": first.get("updated_at"),
        "schema_version": first.get("schema_version"),
        "positions": positions,
    }


def save_strategy(
    *,
    name: str,
    description: str | None,
    positions: list[dict[str, Any]],
    underlying: str | None = None,
    strategy_id: str | None = None,
) -> dict[str, Any]:
    current = _read_frame()
    strategy_id = strategy_id or f"strat-{uuid.uuid4().hex[:12]}"
    existing = current[current["strategy_id"] == strategy_id]
    created_at = existing.iloc[0].get("created_at") if not existing.empty else _now()
    updated_at = _now()

    payload_rows = []
    for index, position in enumerate(positions):
        payload_rows.append({
            "strategy_id": strategy_id,
            "name": name,
            "description": description or "",
            "underlying": underlying or "ESTX50",
            "created_at": created_at,
            "updated_at": updated_at,
            "schema_version": STRATEGY_SCHEMA_VERSION,
            "position_index": index,
            "label": position.get("label"),
            "option_type": position.get("option_type"),
            "strike": float(position.get("strike")),
            "maturity": float(position.get("maturity")),
            "rate": float(position.get("rate", 0.03)),
            "sigma": float(position.get("sigma")),
            "quantity": int(position.get("quantity", 1)),
            "multiplier": float(position.get("multiplier", 10.0)),
        })

    next_frame = current[current["strategy_id"] != strategy_id]
    next_frame = pd.concat([next_frame, pd.DataFrame(payload_rows, columns=COLUMNS)], ignore_index=True)
    _write_frame(next_frame)
    return load_strategy(strategy_id) or {"strategy_id": strategy_id, "positions": []}


def delete_strategy(strategy_id: str) -> bool:
    current = _read_frame()
    next_frame = current[current["strategy_id"] != strategy_id]
    if len(next_frame) == len(current):
        return False
    _write_frame(next_frame)
    return True
