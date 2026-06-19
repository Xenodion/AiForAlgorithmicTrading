from __future__ import annotations

import unittest
from math import isclose, log, sqrt

from src.surfaces.engine import build_surface, maturity_years


def _row(maturity: str, strike: float, right: str, iv_pct: float) -> dict:
    return {
        "Maturity": maturity,
        "Strike": strike,
        "Right": right,
        "Type": "Call" if right == "C" else "Put",
        "IV %": iv_pct,
        "Mid": 1.0,
        "Quote Quality": "tight",
        "QC Status": "usable",
        "QC Reasons": [],
        "IV Source": "test",
        "Surface Eligible": True,
    }


class SurfaceEngineTest(unittest.TestCase):
    def test_surface_uses_log_moneyness_and_total_variance_aggregation(self) -> None:
        rows = [
            _row("202607", 90, "P", 24),
            _row("202607", 100, "C", 20),
            _row("202607", 100, "P", 22),
            _row("202607", 110, "C", 23),
            _row("202608", 90, "P", 25),
            _row("202608", 100, "C", 21),
            _row("202608", 100, "P", 23),
            _row("202608", 110, "C", 24),
        ]

        surface = build_surface(
            rows,
            spot=100,
            rate=0,
            forwards_by_maturity={"202607": 100, "202608": 100},
        )

        coordinates = surface["grid"]["coordinates"]
        self.assertEqual(surface["modelVersion"], "forward-log-moneyness-total-variance-v3")
        self.assertTrue(surface["coordinateSystem"].startswith("common forward log-moneyness grid"))
        self.assertEqual(coordinates, [round(log(0.9), 10), 0.0, round(log(1.1), 10)])
        self.assertLess(max(abs(value) for value in coordinates), 1)

        atm_row = next(
            row
            for row in surface["grid"]["rows"]
            if row["Maturity"] == "202607" and row["Log Moneyness"] == 0.0
        )
        expected_iv = sqrt(((0.20**2) + (0.22**2)) / 2) * 100
        self.assertTrue(isclose(atm_row["IV %"], expected_iv, rel_tol=1e-12))

        first_slice = next(item for item in surface["diagnostics"]["slices"] if item["maturity"] == "202607")
        self.assertEqual(first_slice["acceptedPoints"], 4)
        self.assertEqual(first_slice["fittedKnots"], 3)
        self.assertEqual(first_slice["fitMethod"], "linear interpolation in forward log-moneyness total variance")

    def test_surface_calendar_diagnostics_on_common_moneyness(self) -> None:
        rows = [
            _row("202607", 100, "C", 20),
            _row("202607", 110, "C", 22),
            _row("202608", 100, "C", 19),
            _row("202608", 110, "C", 21),
        ]

        surface = build_surface(
            rows,
            spot=100,
            rate=0,
            forwards_by_maturity={"202607": 100, "202608": 100},
        )

        calendar = surface["diagnostics"]["calendar"]
        self.assertEqual(calendar["checkedCoordinates"], 2)

        short_t = maturity_years("202607")
        long_t = maturity_years("202608")
        expected_break = (0.19**2) * long_t < (0.20**2) * short_t
        self.assertIs(bool(calendar["violationCount"]), expected_break)
