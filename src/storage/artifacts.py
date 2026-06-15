"""
Local JSON artifact storage for analytics runs.

This is the first storage milestone from the final platform blueprint. It keeps
the output auditable without introducing a heavy columnar dependency yet.
"""

from __future__ import annotations

import json
import math
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
ANALYTICS_ROOT = ROOT / "data" / "analytics"
LATEST_PATH = ANALYTICS_ROOT / "latest.json"
ARTIFACT_VERSION = "analytics-run-json-v1"


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    created_at: str
    trade_date: str
    underlying: str
    notional: float
    rate: float
    artifact_version: str
    quote_qc_version: str | None
    surface_model_version: str | None
    raw_rows: int
    accepted_points: int
    rejected_rows: int
    calendar_violations: int
    warning_count: int
    run_path: str
    artifacts: dict[str, str]


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(_jsonable(payload), handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_path, path)


def _read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def record_options_surface_run(
    *,
    underlying: str,
    notional: float,
    rate: float,
    option_rows: list[dict[str, Any]],
    option_diagnostics: dict[str, Any],
    surface_payload: dict[str, Any],
    quote_qc_version: str | None,
) -> dict[str, Any]:
    created_at = datetime.utcnow().replace(microsecond=0)
    trade_date = created_at.date().isoformat()
    run_id = f"{created_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_dir = ANALYTICS_ROOT / f"trade_date={trade_date}" / run_id

    diagnostics = surface_payload.get("diagnostics", {})
    calendar = diagnostics.get("calendar", {})
    artifacts = {
        "option_rows": _relative(run_dir / "option_rows.json"),
        "option_diagnostics": _relative(run_dir / "option_diagnostics.json"),
        "surface": _relative(run_dir / "surface.json"),
        "surface_diagnostics": _relative(run_dir / "surface_diagnostics.json"),
        "manifest": _relative(run_dir / "manifest.json"),
    }

    manifest = RunManifest(
        run_id=run_id,
        created_at=created_at.isoformat() + "Z",
        trade_date=trade_date,
        underlying=underlying,
        notional=notional,
        rate=rate,
        artifact_version=ARTIFACT_VERSION,
        quote_qc_version=quote_qc_version,
        surface_model_version=surface_payload.get("modelVersion"),
        raw_rows=int(diagnostics.get("rawRows") or len(option_rows)),
        accepted_points=int(diagnostics.get("acceptedPoints") or 0),
        rejected_rows=int(diagnostics.get("rejectedRows") or 0),
        calendar_violations=int(calendar.get("violationCount") or 0),
        warning_count=len(diagnostics.get("warnings") or []),
        run_path=_relative(run_dir),
        artifacts=artifacts,
    )
    manifest_payload = asdict(manifest)

    _write_json(run_dir / "option_rows.json", option_rows)
    _write_json(run_dir / "option_diagnostics.json", option_diagnostics)
    _write_json(run_dir / "surface.json", surface_payload)
    _write_json(run_dir / "surface_diagnostics.json", diagnostics)
    _write_json(run_dir / "manifest.json", manifest_payload)
    _write_json(LATEST_PATH, manifest_payload)
    return manifest_payload


def latest_run_manifest() -> dict[str, Any] | None:
    return _read_json(LATEST_PATH)


def latest_run_summary() -> dict[str, Any]:
    manifest = latest_run_manifest()
    if not manifest:
        return {
            "available": False,
            "message": "No stored analytics run yet. Build a surface once to create the first run.",
        }

    run_dir = ROOT / manifest["run_path"]
    surface_diagnostics = _read_json(run_dir / "surface_diagnostics.json") or {}
    option_diagnostics = _read_json(run_dir / "option_diagnostics.json") or {}

    return {
        "available": True,
        "manifest": manifest,
        "surfaceDiagnostics": surface_diagnostics,
        "optionDiagnostics": option_diagnostics,
    }

