"""
Data-quality checks for the discovered universe (Step 2).

Each check is a small named function returning a list of human-readable
message strings (empty list = nothing to report). run_all_checks()
aggregates them into {"errors": [...], "warnings": [...]}.

- "errors"   -> something the acceptance criteria require to be correct
                (e.g. multiplier/currency must always be populated on a
                resolved contract).
- "warnings" -> expected/benign situations worth flagging but not failing
                on (e.g. empty strikes near expiry, weekend markets).
"""

from __future__ import annotations


def check_duplicate_option_months(option_chain: list[dict]) -> list[str]:
    seen, dupes = set(), set()
    for entry in option_chain:
        month = entry["expiry_month"]
        if month in seen:
            dupes.add(month)
        seen.add(month)
    return [f"Duplicate option chain expiry_month: {m}" for m in sorted(dupes)]


def check_duplicate_futures_conids(futures_chain: list[dict]) -> list[str]:
    seen, dupes = set(), set()
    for entry in futures_chain:
        conid = entry.get("conid")
        if conid is None:
            continue
        if conid in seen:
            dupes.add(conid)
        seen.add(conid)
    return [f"Duplicate futures conid: {c}" for c in sorted(dupes)]


def check_multipliers(entries: list[dict], label: str) -> list[str]:
    """Flag entries that have a resolved contract but no usable multiplier."""
    msgs = []
    for entry in entries:
        has_contract = entry.get("sample_conid") or entry.get("conid")
        if not has_contract:
            continue
        multiplier = entry.get("multiplier")
        if multiplier is None or multiplier <= 0:
            msgs.append(
                f"{label} {entry['expiry_month']}: invalid multiplier {multiplier!r}"
            )
    return msgs


def check_currencies(entries: list[dict], label: str) -> list[str]:
    """Flag entries that have a resolved contract but no currency."""
    msgs = []
    for entry in entries:
        has_contract = entry.get("sample_conid") or entry.get("conid")
        if not has_contract:
            continue
        currency = entry.get("currency")
        if not currency:
            msgs.append(f"{label} {entry['expiry_month']}: missing currency")
    return msgs


def check_empty_strikes(option_chain: list[dict]) -> list[str]:
    return [
        f"Option chain {entry['expiry_month']}: no strikes returned (empty_strikes)"
        for entry in option_chain
        if "empty_strikes" in entry.get("quality_flags", [])
    ]


def check_trading_class_issues(option_chain: list[dict], futures_chain: list[dict]) -> list[str]:
    msgs = []
    for entry in option_chain:
        if "trading_class_mismatch" in entry.get("quality_flags", []):
            msgs.append(
                f"Option chain {entry['expiry_month']}: trading_class "
                f"{entry.get('trading_class')!r} does not match configured class"
            )
    for entry in futures_chain:
        if "trading_class_not_found" in entry.get("quality_flags", []):
            msgs.append(
                f"Futures chain {entry['expiry_month']}: configured trading "
                f"class not found among candidates, fell back to "
                f"{entry.get('trading_class')!r}"
            )
    return msgs


def run_all_checks(option_chain: list[dict], futures_chain: list[dict]) -> dict:
    errors = []
    errors += check_duplicate_option_months(option_chain)
    errors += check_duplicate_futures_conids(futures_chain)
    errors += check_multipliers(option_chain, "Option chain")
    errors += check_multipliers(futures_chain, "Futures chain")
    errors += check_currencies(option_chain, "Option chain")
    errors += check_currencies(futures_chain, "Futures chain")

    warnings = []
    warnings += check_empty_strikes(option_chain)
    warnings += check_trading_class_issues(option_chain, futures_chain)

    return {"errors": errors, "warnings": warnings}
