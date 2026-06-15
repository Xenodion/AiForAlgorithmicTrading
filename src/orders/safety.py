"""
Order validation and dry-run helpers.

Real routing is disabled by default. These helpers create an auditable order
workflow without sending anything to the broker.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


ORDER_SAFETY_VERSION = "order-safety-v1"
ROUTING_ENABLED = False


def validate_order(ticket: dict[str, Any]) -> dict[str, Any]:
    errors = []
    warnings = []

    underlying = str(ticket.get("underlying") or "").strip().upper()
    side = str(ticket.get("side") or "").upper()
    order_type = str(ticket.get("orderType") or "").upper()
    quantity = ticket.get("quantity")
    limit_price = ticket.get("limitPrice")

    if not underlying:
        errors.append("missing_underlying")
    if side not in {"BUY", "SELL"}:
        errors.append("invalid_side")
    if order_type not in {"LIMIT", "MARKET"}:
        errors.append("invalid_order_type")
    try:
        quantity_value = float(quantity)
    except (TypeError, ValueError):
        quantity_value = 0
    if quantity_value <= 0:
        errors.append("non_positive_quantity")
    if quantity_value > 100:
        warnings.append("large_quantity")
    if order_type == "MARKET":
        warnings.append("market_order_requires_manual_review")
    if order_type == "LIMIT":
        try:
            limit_value = float(limit_price)
        except (TypeError, ValueError):
            limit_value = 0
        if limit_value <= 0:
            errors.append("invalid_limit_price")

    return {
        "version": ORDER_SAFETY_VERSION,
        "valid": not errors,
        "routingEnabled": ROUTING_ENABLED,
        "errors": errors,
        "warnings": warnings,
        "normalizedTicket": {
            "underlying": underlying,
            "side": side,
            "quantity": quantity_value,
            "orderType": order_type,
            "limitPrice": float(limit_price) if order_type == "LIMIT" and limit_price not in (None, "") else None,
        },
    }


def dry_run_order(ticket: dict[str, Any]) -> dict[str, Any]:
    validation = validate_order(ticket)
    return {
        "dryRunId": f"dry-{uuid4().hex[:12]}",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "status": "accepted_for_preview" if validation["valid"] else "rejected",
        "routingEnabled": ROUTING_ENABLED,
        "message": "Dry-run only. No broker order was sent.",
        "validation": validation,
    }


def submit_order(ticket: dict[str, Any]) -> dict[str, Any]:
    validation = validate_order(ticket)
    return {
        "orderId": None,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "status": "blocked",
        "routingEnabled": ROUTING_ENABLED,
        "message": "Real order routing is disabled by configuration.",
        "validation": validation,
    }

