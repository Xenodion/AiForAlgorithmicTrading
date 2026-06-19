"""
Surface construction from accepted IV points.

The fitted grid is intentionally simple for now: linear interpolation by
maturity slice in total variance space on forward log-moneyness coordinates,
with no extrapolation outside each slice.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from math import exp, isfinite, log, sqrt
from typing import Any


SURFACE_MODEL_VERSION = "forward-log-moneyness-total-variance-v3"


def _third_friday(year: int, month_num: int) -> date:
    first = date(year, month_num, 1)
    days_until_friday = (4 - first.weekday()) % 7
    return first + timedelta(days=days_until_friday + 14)


def maturity_years(month: str, today: date | None = None) -> float:
    today = today or date.today()
    year = int(str(month)[:4])
    month_num = int(str(month)[4:6])
    expiry = _third_friday(year, month_num)
    return max((expiry - today).days / 365.0, 1 / 365.0)


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _mean(values: list[float]) -> float | None:
    clean = [v for v in values if isfinite(v)]
    if not clean:
        return None
    return sum(clean) / len(clean)


def build_iv_points(
    option_rows: list[dict[str, Any]],
    spot: float,
    rate: float = 0.03,
    forwards_by_maturity: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    forwards_by_maturity = forwards_by_maturity or {}
    points = []
    for row in option_rows:
        strike = _as_float(row.get("Strike"))
        iv_pct = _as_float(row.get("IV %"))
        if not row.get("Surface Eligible") or strike is None or iv_pct is None:
            continue

        maturity = str(row.get("Maturity"))
        t = maturity_years(maturity)
        sigma = iv_pct / 100.0
        forward = forwards_by_maturity.get(maturity) or spot * exp(rate * t)
        log_moneyness = log(strike / forward) if strike > 0 and forward > 0 else None
        total_variance = sigma * sigma * t

        points.append({
            "Maturity": maturity,
            "Strike": strike,
            "Type": row.get("Type"),
            "Right": row.get("Right"),
            "Delta": row.get("Delta"),
            "IV %": iv_pct,
            "Implied Vol": sigma,
            "Maturity Years": t,
            "Forward": forward,
            "Forward Source": "curve" if maturity in forwards_by_maturity else "spot_rate_fallback",
            "Log Moneyness": log_moneyness,
            "Total Variance": total_variance,
            "Mid": row.get("Mid"),
            "Quote Quality": row.get("Quote Quality"),
            "QC Status": row.get("QC Status"),
            "QC Reasons": row.get("QC Reasons") or [],
            "IV Source": row.get("IV Source"),
            "IV Status": row.get("IV Status"),
            "IV Model": row.get("IV Model"),
            "IV Iterations": row.get("IV Iterations"),
            "IV Residual": row.get("IV Residual"),
            "Surface Eligible": row.get("Surface Eligible"),
        })
    return points


def _interpolate_total_variance(curve: list[dict[str, Any]], coordinate: float) -> tuple[float | None, str]:
    exact = [point["Total Variance"] for point in curve if point["Coordinate"] == coordinate]
    exact_value = _mean(exact)
    if exact_value is not None:
        return exact_value, "observed"

    lower = next((point for point in reversed(curve) if point["Coordinate"] < coordinate), None)
    upper = next((point for point in curve if point["Coordinate"] > coordinate), None)
    if not lower or not upper:
        return None, "outside_slice"

    weight = (coordinate - lower["Coordinate"]) / (upper["Coordinate"] - lower["Coordinate"])
    total_variance = lower["Total Variance"] + weight * (upper["Total Variance"] - lower["Total Variance"])
    return total_variance, "interpolated"


def _strike_from_log_moneyness(coordinate: float, forward: float) -> float | None:
    if coordinate is None or forward <= 0:
        return None
    return forward * exp(coordinate)


def _build_slice_curve(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for point in points:
        coordinate = point.get("Log Moneyness")
        if coordinate is None:
            continue
        buckets[round(float(coordinate), 10)].append(point)

    curve = []
    for coordinate, bucket in buckets.items():
        total_variance = _mean([point["Total Variance"] for point in bucket])
        strike = _mean([point["Strike"] for point in bucket])
        if total_variance is None or strike is None:
            continue
        sample = bucket[0]
        iv_pct = sqrt(max(total_variance / sample["Maturity Years"], 0.0)) * 100.0
        curve.append({
            "Coordinate": coordinate,
            "Log Moneyness": coordinate,
            "Strike": strike,
            "IV %": iv_pct,
            "Total Variance": total_variance,
            "Maturity": sample["Maturity"],
            "Maturity Years": sample["Maturity Years"],
            "Forward": sample["Forward"],
            "Observation Count": len(bucket),
            "Rights": sorted({str(point.get("Right") or point.get("Type") or "") for point in bucket}),
        })
    return sorted(curve, key=lambda point: point["Coordinate"])


def _calendar_diagnostics(grid_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_coordinate: dict[float, list[dict[str, Any]]] = {}
    for row in grid_rows:
        if row.get("Total Variance") is None:
            continue
        by_coordinate.setdefault(row["Log Moneyness"], []).append(row)

    violations = []
    for coordinate, rows in by_coordinate.items():
        ordered = sorted(rows, key=lambda row: row["Maturity Years"])
        for prev, curr in zip(ordered, ordered[1:]):
            if curr["Total Variance"] + 1e-8 < prev["Total Variance"]:
                violations.append({
                    "logMoneyness": coordinate,
                    "fromMaturity": prev["Maturity"],
                    "toMaturity": curr["Maturity"],
                    "fromTotalVariance": prev["Total Variance"],
                    "toTotalVariance": curr["Total Variance"],
                })

    return {
        "checkedCoordinates": len(by_coordinate),
        "violationCount": len(violations),
        "violations": violations[:20],
    }


def build_surface(
    option_rows: list[dict[str, Any]],
    spot: float,
    rate: float = 0.03,
    forwards_by_maturity: dict[str, float] | None = None,
    forward_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    forwards_by_maturity = forwards_by_maturity or {}
    iv_points = build_iv_points(
        option_rows,
        spot=spot,
        rate=rate,
        forwards_by_maturity=forwards_by_maturity,
    )
    maturities = sorted({point["Maturity"] for point in iv_points})
    coordinates = sorted({
        round(point["Log Moneyness"], 10)
        for point in iv_points
        if point.get("Log Moneyness") is not None
    })

    by_maturity = {
        maturity: _build_slice_curve([point for point in iv_points if point["Maturity"] == maturity])
        for maturity in maturities
    }

    grid_rows = []
    z_full = []
    fit_source_counts = Counter()
    slice_diagnostics = []

    for coordinate in coordinates:
        z_row = []
        for maturity in maturities:
            curve = by_maturity[maturity]
            t = maturity_years(maturity)
            forward = forwards_by_maturity.get(maturity) or spot * exp(rate * t)
            strike = _strike_from_log_moneyness(coordinate, forward)
            total_variance, fit_source = _interpolate_total_variance(curve, coordinate)
            fit_source_counts[fit_source] += 1
            if total_variance is None:
                iv_pct = None
            else:
                iv_pct = sqrt(max(total_variance / t, 0.0)) * 100.0

            z_row.append(iv_pct)
            grid_rows.append({
                "Maturity": maturity,
                "Strike": strike,
                "IV %": iv_pct,
                "Total Variance": total_variance,
                "Maturity Years": t,
                "Forward": forward,
                "Log Moneyness": coordinate,
                "Fit Source": fit_source,
            })
        z_full.append(z_row)

    common_coordinates = [
        coordinate
        for coordinate, z_row in zip(coordinates, z_full)
        if z_row and all(value is not None for value in z_row)
    ]
    display_coordinates = coordinates
    display_rows = grid_rows
    z = z_full

    for maturity, points in by_maturity.items():
        point_errors = []
        for point in points:
            fitted_total_variance, _ = _interpolate_total_variance(by_maturity[maturity], point["Coordinate"])
            if fitted_total_variance is not None:
                fitted_iv = sqrt(max(fitted_total_variance / point["Maturity Years"], 0.0)) * 100.0
                point_errors.append(fitted_iv - point["IV %"])
        rmse = sqrt(sum(error * error for error in point_errors) / len(point_errors)) if point_errors else None
        max_abs_error = max((abs(error) for error in point_errors), default=None)
        slice_diagnostics.append({
            "maturity": maturity,
            "acceptedPoints": sum(point["Observation Count"] for point in points),
            "fittedKnots": len(points),
            "strikeMin": min((point["Strike"] for point in points), default=None),
            "strikeMax": max((point["Strike"] for point in points), default=None),
            "logMoneynessMin": min((point["Log Moneyness"] for point in points), default=None),
            "logMoneynessMax": max((point["Log Moneyness"] for point in points), default=None),
            "fitMethod": "linear interpolation in forward log-moneyness total variance",
            "rmse": rmse,
            "maxAbsError": max_abs_error,
            "forward": forwards_by_maturity.get(maturity),
            "quality": "usable" if len(points) >= 4 else "sparse",
            "warnings": [] if len(points) >= 4 else ["sparse_slice"],
        })

    calendar = _calendar_diagnostics(grid_rows)
    warnings = []
    if not iv_points:
        warnings.append("no_surface_eligible_points")
    if calendar["violationCount"]:
        warnings.append("calendar_total_variance_decrease")
    if iv_points and not common_coordinates:
        warnings.append("no_complete_common_log_moneyness_domain")

    return {
        "modelVersion": SURFACE_MODEL_VERSION,
        "coordinateSystem": "common forward log-moneyness grid; fitted in total variance; no extrapolation outside each maturity slice",
        "spot": spot,
        "rate": rate,
        "forwardModel": forward_diagnostics.get("modelVersion") if forward_diagnostics else "spot * exp(rate * T) proxy",
        "forwardDiagnostics": forward_diagnostics or {},
        "ivPoints": iv_points,
        "grid": {
            "maturities": maturities,
            "coordinates": display_coordinates,
            "logMoneyness": display_coordinates,
            "strikes": display_coordinates,
            "z": z,
            "rows": display_rows,
            "renderMode": "full_slice_support_with_nulls",
        },
        "diagnosticGrid": {
            "maturities": maturities,
            "coordinates": coordinates,
            "logMoneyness": coordinates,
            "strikes": coordinates,
            "z": z_full,
            "rows": grid_rows,
            "renderMode": "full_slice_support_with_nulls",
        },
        "diagnostics": {
            "rawRows": len(option_rows),
            "acceptedPoints": len(iv_points),
            "rejectedRows": len(option_rows) - len(iv_points),
            "fitSourceCounts": dict(fit_source_counts),
            "displayGrid": {
                "coordinateCount": len(display_coordinates),
                "coordinateMin": min(display_coordinates, default=None),
                "coordinateMax": max(display_coordinates, default=None),
                "commonCoordinateCount": len(common_coordinates),
                "commonCoordinateMin": min(common_coordinates, default=None),
                "commonCoordinateMax": max(common_coordinates, default=None),
                "strikeCount": len(display_coordinates),
                "strikeMin": min(display_coordinates, default=None),
                "strikeMax": max(display_coordinates, default=None),
                "excludedOutsideCommonDomain": len(coordinates) - len(common_coordinates),
            },
            "slices": slice_diagnostics,
            "calendar": calendar,
            "warnings": warnings,
        },
    }
