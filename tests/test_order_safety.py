from __future__ import annotations

import unittest

from src.orders.safety import build_ibkr_order, submit_order, validate_order


ROUTING_ON = {
    "enabled": True,
    "paper_only": True,
    "max_quantity": 5,
    "allowed_order_types": ["LIMIT"],
    "allowed_tifs": ["DAY"],
    "confirmation_phrase": "SEND ORDER",
    "audit_path": "/tmp/order-safety-test.jsonl",
}


class FakeClient:
    def __init__(self) -> None:
        self.calls = []

    def place_order(self, account_id: str, order: dict) -> list[dict]:
        self.calls.append((account_id, order))
        return [{"order_id": "123", "order_status": "Submitted"}]


def _ticket(**overrides) -> dict:
    ticket = {
        "accountId": "DU123",
        "underlying": "ESTX50",
        "conid": 11004968,
        "side": "BUY",
        "quantity": 1,
        "orderType": "LIMIT",
        "limitPrice": 5000,
        "tif": "DAY",
        "outsideRTH": False,
        "confirmation": "SEND ORDER",
    }
    ticket.update(overrides)
    return ticket


class OrderSafetyTest(unittest.TestCase):
    def test_submit_is_blocked_when_routing_disabled(self) -> None:
        validation = validate_order(_ticket(), {**ROUTING_ON, "enabled": False}, ["DU123"], for_submit=True)
        self.assertFalse(validation["valid"])
        self.assertIn("routing_disabled", validation["errors"])

    def test_submit_requires_paper_account_and_confirmation(self) -> None:
        validation = validate_order(
            _ticket(accountId="U123", confirmation=""),
            ROUTING_ON,
            ["U123"],
            for_submit=True,
        )
        self.assertFalse(validation["valid"])
        self.assertIn("paper_account_required", validation["errors"])
        self.assertIn("confirmation_phrase_required", validation["errors"])

    def test_quantity_limit_blocks_large_orders(self) -> None:
        validation = validate_order(_ticket(quantity=6), ROUTING_ON, ["DU123"], for_submit=True)
        self.assertFalse(validation["valid"])
        self.assertIn("quantity_above_configured_limit", validation["errors"])

    def test_limit_order_payload_uses_client_portal_shape(self) -> None:
        validation = validate_order(_ticket(), ROUTING_ON, ["DU123"], for_submit=True)
        self.assertTrue(validation["valid"])
        self.assertEqual(
            build_ibkr_order(validation["normalizedTicket"]),
            {
                "conid": 11004968,
                "side": "BUY",
                "quantity": 1.0,
                "orderType": "LMT",
                "tif": "DAY",
                "outsideRTH": False,
                "price": 5000.0,
                "cOID": validation["normalizedTicket"]["clientOrderId"],
            },
        )

    def test_submit_calls_client_after_validation(self) -> None:
        client = FakeClient()
        result = submit_order(client, _ticket(), ROUTING_ON, ["DU123"])

        self.assertEqual(result["status"], "submitted")
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][0], "DU123")


if __name__ == "__main__":
    unittest.main()
