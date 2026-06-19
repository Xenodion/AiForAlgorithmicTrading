"""
Controlled order workflow for IBKR Client Portal.

Live routing is disabled by default and must be enabled in configuration. Even
when enabled, submissions require a tradable conid, account selection, size
limits, a paper-account guard, and an explicit confirmation phrase.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml


ORDER_SAFETY_VERSION = "order-safety-v2"
DEFAULT_ROUTING_CONFIG = {
    "enabled": False,
    "paper_only": True,
    "max_quantity": 10,
    "allowed_order_types": ["LIMIT"],
    "allowed_tifs": ["DAY"],
    "confirmation_phrase": "SEND ORDER",
    "audit_path": "data/audit/orders.jsonl",
}
ORDER_TYPE_MAP = {"LIMIT": "LMT", "MARKET": "MKT", "LMT": "LMT", "MKT": "MKT"}


def load_order_routing_config(config_path: str | Path) -> dict[str, Any]:
    with open(config_path) as handle:
        cfg = yaml.safe_load(handle) or {}
    routing = {**DEFAULT_ROUTING_CONFIG, **(cfg.get("order_routing") or {})}
    routing["enabled"] = bool(routing.get("enabled")) and os.environ.get("IBKR_ORDER_ROUTING_KILL_SWITCH") != "1"
    routing["max_quantity"] = float(routing.get("max_quantity") or DEFAULT_ROUTING_CONFIG["max_quantity"])
    routing["allowed_order_types"] = [str(item).upper() for item in routing.get("allowed_order_types") or []]
    routing["allowed_tifs"] = [str(item).upper() for item in routing.get("allowed_tifs") or []]
    return routing


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _routing_enabled(routing: dict[str, Any] | None) -> bool:
    return bool((routing or DEFAULT_ROUTING_CONFIG).get("enabled"))


def build_ibkr_order(normalized: dict[str, Any]) -> dict[str, Any]:
    order: dict[str, Any] = {
        "conid": normalized["conid"],
        "side": normalized["side"],
        "quantity": normalized["quantity"],
        "orderType": ORDER_TYPE_MAP[normalized["orderType"]],
        "tif": normalized["tif"],
        "outsideRTH": normalized["outsideRTH"],
    }
    if normalized["orderType"] in {"LIMIT", "LMT"}:
        order["price"] = normalized["limitPrice"]
    if normalized.get("clientOrderId"):
        order["cOID"] = normalized["clientOrderId"]
    return order


def validate_order(
    ticket: dict[str, Any],
    routing: dict[str, Any] | None = None,
    accounts: list[str] | None = None,
    *,
    for_submit: bool = False,
) -> dict[str, Any]:
    routing = {**DEFAULT_ROUTING_CONFIG, **(routing or {})}
    errors: list[str] = []
    warnings: list[str] = []

    account_id = str(ticket.get("accountId") or "").strip()
    underlying = str(ticket.get("underlying") or ticket.get("symbol") or "").strip().upper()
    side = str(ticket.get("side") or "").upper()
    order_type = str(ticket.get("orderType") or "").upper()
    order_type = {"LMT": "LIMIT", "MKT": "MARKET"}.get(order_type, order_type)
    tif = str(ticket.get("tif") or "DAY").upper()
    quantity_value = _float_or_zero(ticket.get("quantity"))
    limit_value = _float_or_zero(ticket.get("limitPrice"))
    conid = _int_or_none(ticket.get("conid"))
    outside_rth = bool(ticket.get("outsideRTH", False))
    confirmation = str(ticket.get("confirmation") or "")
    client_order_id = str(ticket.get("clientOrderId") or f"codex-{uuid4().hex[:12]}")

    if not underlying:
        errors.append("missing_underlying")
    if side not in {"BUY", "SELL"}:
        errors.append("invalid_side")
    if order_type not in {"LIMIT", "MARKET"}:
        errors.append("invalid_order_type")
    if order_type not in routing["allowed_order_types"]:
        errors.append("order_type_not_allowed")
    if tif not in routing["allowed_tifs"]:
        errors.append("tif_not_allowed")
    if quantity_value <= 0:
        errors.append("non_positive_quantity")
    if quantity_value > routing["max_quantity"]:
        errors.append("quantity_above_configured_limit")
    if order_type == "MARKET":
        warnings.append("market_order_requires_manual_review")
    if order_type == "LIMIT" and limit_value <= 0:
        errors.append("invalid_limit_price")
    if not conid:
        errors.append("missing_tradable_conid")

    if for_submit:
        if not _routing_enabled(routing):
            errors.append("routing_disabled")
        if not account_id:
            errors.append("missing_account")
        if accounts is not None and account_id and account_id not in accounts:
            errors.append("account_not_available")
        if routing.get("paper_only") and account_id and not account_id.upper().startswith("DU"):
            errors.append("paper_account_required")
        if confirmation != routing["confirmation_phrase"]:
            errors.append("confirmation_phrase_required")
    elif not account_id:
        warnings.append("missing_account_for_live_submit")

    normalized = {
        "accountId": account_id or None,
        "underlying": underlying,
        "conid": conid,
        "side": side,
        "quantity": quantity_value,
        "orderType": order_type,
        "limitPrice": limit_value if order_type == "LIMIT" else None,
        "tif": tif,
        "outsideRTH": outside_rth,
        "clientOrderId": client_order_id,
    }

    return {
        "version": ORDER_SAFETY_VERSION,
        "valid": not errors,
        "routingEnabled": _routing_enabled(routing),
        "paperOnly": bool(routing.get("paper_only")),
        "maxQuantity": routing["max_quantity"],
        "confirmationPhrase": routing["confirmation_phrase"],
        "errors": errors,
        "warnings": warnings,
        "normalizedTicket": normalized,
        "ibkrOrder": build_ibkr_order(normalized) if not errors and conid else None,
    }


def _append_audit(routing: dict[str, Any], event: dict[str, Any]) -> None:
    audit_path = Path(str(routing.get("audit_path") or DEFAULT_ROUTING_CONFIG["audit_path"]))
    if not audit_path.is_absolute():
        audit_path = Path.cwd() / audit_path
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True, default=str) + "\n")


def dry_run_order(ticket: dict[str, Any], routing: dict[str, Any] | None = None, accounts: list[str] | None = None) -> dict[str, Any]:
    validation = validate_order(ticket, routing, accounts)
    return {
        "dryRunId": f"dry-{uuid4().hex[:12]}",
        "createdAt": _now(),
        "status": "accepted_for_preview" if validation["valid"] else "rejected",
        "routingEnabled": validation["routingEnabled"],
        "message": "Dry-run only. No broker order was sent.",
        "validation": validation,
    }


def submit_order(client: Any, ticket: dict[str, Any], routing: dict[str, Any], accounts: list[str]) -> dict[str, Any]:
    validation = validate_order(ticket, routing, accounts, for_submit=True)
    submit_id = f"submit-{uuid4().hex[:12]}"
    base = {
        "submitId": submit_id,
        "createdAt": _now(),
        "routingEnabled": _routing_enabled(routing),
        "validation": validation,
    }
    _append_audit(routing, {"event": "submit_requested", **base})

    if not validation["valid"]:
        result = {
            **base,
            "orderId": None,
            "status": "blocked",
            "message": "Order blocked by server-side validation.",
        }
        _append_audit(routing, {"event": "submit_blocked", **result})
        return result

    normalized = validation["normalizedTicket"]
    ibkr_order = validation["ibkrOrder"]
    response = client.place_order(normalized["accountId"], ibkr_order)
    status = "submitted"
    reply_id = None
    message = "Order sent to IBKR Client Portal Gateway."
    if isinstance(response, list) and response and isinstance(response[0], dict):
        first = response[0]
        reply_id = first.get("id") or first.get("replyId")
        if reply_id:
            status = "broker_confirmation_required"
            message = "IBKR requires an additional broker confirmation reply."
    result = {
        **base,
        "orderId": None,
        "status": status,
        "message": message,
        "brokerResponse": response,
        "replyId": reply_id,
    }
    _append_audit(routing, {"event": "submit_response", **result})
    return result


def reply_order(client: Any, reply_id: str, confirmed: bool, routing: dict[str, Any], confirmation: str) -> dict[str, Any]:
    if not _routing_enabled(routing):
        return {"status": "blocked", "routingEnabled": False, "message": "Real order routing is disabled by configuration."}
    if confirmation != routing["confirmation_phrase"]:
        return {"status": "blocked", "routingEnabled": True, "message": "Confirmation phrase is required."}
    response = client.reply_order(reply_id, confirmed)
    result = {
        "replyId": reply_id,
        "createdAt": _now(),
        "routingEnabled": True,
        "status": "confirmed" if confirmed else "rejected",
        "brokerResponse": response,
    }
    _append_audit(routing, {"event": "reply_response", **result})
    return result
