"""
Pass/warn/fail validation report for the latest analytics run.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


VALIDATION_VERSION = "analytics-validation-v1"


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _check(name: str, status: str, metric: Any, threshold: str, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "metric": metric,
        "threshold": threshold,
        "detail": detail,
    }


def latest_run_validation(latest_run: dict[str, Any]) -> dict[str, Any]:
    if not latest_run.get("available"):
        return {
            "version": VALIDATION_VERSION,
            "status": "fail",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "checks": [
                _check("latest_run_available", "fail", 0, "latest run exists", "No stored analytics run is available."),
            ],
            "summary": {"pass": 0, "warn": 0, "fail": 1},
        }

    manifest = latest_run.get("manifest", {})
    surface = latest_run.get("surfaceDiagnostics", {})
    options = latest_run.get("optionDiagnostics", {})
    checks = []

    created_at = _parse_ts(manifest.get("created_at"))
    age_minutes = None
    if created_at:
        age_minutes = (datetime.now(timezone.utc) - created_at).total_seconds() / 60
    checks.append(
        _check(
            "run_freshness",
            "pass" if age_minutes is not None and age_minutes <= 120 else "warn",
            round(age_minutes, 1) if age_minutes is not None else None,
            "<= 120 minutes",
            "Latest analytics run freshness.",
        )
    )

    accepted = int(manifest.get("accepted_points") or 0)
    checks.append(
        _check(
            "surface_accepted_points",
            "pass" if accepted >= 30 else "warn" if accepted >= 10 else "fail",
            accepted,
            "pass >= 30, warn >= 10",
            "Number of IV points accepted into the surface.",
        )
    )

    rejected = int(manifest.get("rejected_rows") or 0)
    raw_rows = int(manifest.get("raw_rows") or 0)
    reject_ratio = rejected / raw_rows if raw_rows else 1
    checks.append(
        _check(
            "quote_reject_ratio",
            "pass" if reject_ratio <= 0.4 else "warn" if reject_ratio <= 0.7 else "fail",
            round(reject_ratio, 3),
            "pass <= 40%, warn <= 70%",
            "Share of option rows rejected by QC.",
        )
    )

    calendar_breaks = int(manifest.get("calendar_violations") or 0)
    checks.append(
        _check(
            "calendar_arbitrage",
            "pass" if calendar_breaks == 0 else "fail",
            calendar_breaks,
            "0 violations",
            "Total variance should not decrease across maturities for the same strike.",
        )
    )

    display_grid = surface.get("displayGrid", {})
    display_strikes = int(display_grid.get("strikeCount") or 0)
    checks.append(
        _check(
            "surface_common_domain",
            "pass" if display_strikes >= 5 else "warn" if display_strikes >= 2 else "fail",
            display_strikes,
            "pass >= 5 strikes",
            "Common strike domain used for the no-hole displayed surface.",
        )
    )

    slices = surface.get("slices") or []
    sparse = [item.get("maturity") for item in slices if item.get("quality") != "usable"]
    checks.append(
        _check(
            "surface_slice_quality",
            "pass" if not sparse else "warn",
            len(sparse),
            "0 sparse slices",
            f"Sparse maturities: {', '.join(sparse) if sparse else 'none'}.",
        )
    )

    qc_status = options.get("qcStatus", {})
    usable = int(qc_status.get("usable") or 0)
    checks.append(
        _check(
            "usable_quote_count",
            "pass" if usable >= 30 else "warn" if usable >= 10 else "fail",
            usable,
            "pass >= 30, warn >= 10",
            "Rows marked usable by quote QC.",
        )
    )

    counts = {"pass": 0, "warn": 0, "fail": 0}
    for item in checks:
        counts[item["status"]] += 1
    overall = "fail" if counts["fail"] else "warn" if counts["warn"] else "pass"

    return {
        "version": VALIDATION_VERSION,
        "status": overall,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "runId": manifest.get("run_id"),
        "checks": checks,
        "summary": counts,
    }

