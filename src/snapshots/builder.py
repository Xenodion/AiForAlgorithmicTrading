"""
Deterministic market-state snapshots for current on-demand data.

This is intentionally small: it labels the reference price used by downstream
analytics before the larger raw-event replay layer exists.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


SNAPSHOT_BUILDER_VERSION = "market-snapshot-v1"


def _reference_price(row: dict[str, Any]) -> tuple[float | None, str]:
    qc_reference = row.get("QC Reference Price")
    qc_reference_type = row.get("QC Reference Type")
    if isinstance(qc_reference, int | float) and qc_reference > 0 and qc_reference_type:
        return float(qc_reference), str(qc_reference_type)
    mid = row.get("Mid")
    if row.get("Quote Quality") != "last only" and isinstance(mid, int | float) and mid > 0:
        return float(mid), "mid"
    last = row.get("Last")
    if isinstance(last, int | float) and last > 0:
        return float(last), "last"
    return None, "missing"


def build_option_snapshot(
    *,
    underlying: str,
    spot: float,
    option_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    snapshot_ts = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    rows = []
    reference_counts: dict[str, int] = {}

    for row in option_rows:
        reference_price, reference_type = _reference_price(row)
        reference_counts[reference_type] = reference_counts.get(reference_type, 0) + 1
        rows.append({
            **row,
            "Snapshot Timestamp": snapshot_ts,
            "Snapshot Version": SNAPSHOT_BUILDER_VERSION,
            "Underlying": underlying,
            "Reference Price": reference_price,
            "Reference Type": reference_type,
            "Market State Flags": [] if reference_price is not None else ["missing_reference_price"],
        })

    return {
        "snapshotVersion": SNAPSHOT_BUILDER_VERSION,
        "snapshotTs": snapshot_ts,
        "underlying": underlying,
        "spot": spot,
        "rows": rows,
        "diagnostics": {
            "rowCount": len(rows),
            "referenceCounts": reference_counts,
            "missingReference": reference_counts.get("missing", 0),
        },
    }
