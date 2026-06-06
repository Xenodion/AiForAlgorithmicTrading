"""
Volatility Infrastructure — Tab 1: Agnostic Market Data
Run: .venv\\Scripts\\python app.py  then open http://localhost:8050
"""

import sys
import logging
import threading
import time
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, dash_table, Input, Output, State
import dash_bootstrap_components as dbc

sys.path.insert(0, str(Path(__file__).parent))
from src.connectivity.session import IBKRClient
from src.data.fetcher import (
    resolve_index, get_spot, get_options_table,
    get_futures_prices, resolve_components, get_component_spots,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("app")

# ── Connect ────────────────────────────────────────────────────────────────────
client = IBKRClient.from_config("configs/broker.yaml")
client.check_auth()
INDEX      = resolve_index(client)
COMPONENTS = resolve_components(client)

# ── Background tickle ──────────────────────────────────────────────────────────
def _tickle_loop():
    while True:
        time.sleep(55)
        try:
            client.tickle()
        except Exception as exc:
            logger.warning("Tickle failed (%s) — retrying reauth", exc)
            try:
                client.post("/iserver/reauthenticate")
            except Exception:
                pass

threading.Thread(target=_tickle_loop, daemon=True, name="tickle").start()
logger.info("Dashboard ready — %s (conid=%s) | %d components resolved",
            INDEX["name"], INDEX["conid"], len(COMPONENTS))

# ── Dash app ───────────────────────────────────────────────────────────────────
app = Dash(__name__, external_stylesheets=[dbc.themes.CYBORG])
app.title = "Vol Infra — Tab 1"

_TBL = dict(
    style_table={"overflowX": "auto"},
    style_header={"backgroundColor": "#16213e", "color": "white",
                  "fontWeight": "bold", "textAlign": "center"},
    style_cell={"backgroundColor": "#0f3460", "color": "white",
                "textAlign": "center", "padding": "6px 10px",
                "fontSize": 12, "minWidth": "60px"},
)

app.layout = dbc.Container([

    dcc.Interval(id="tick", interval=30_000, n_intervals=0),

    # ── Header ─────────────────────────────────────────────────────────────────
    dbc.Row(dbc.Col(html.Div([
        html.H2(INDEX["name"], style={"display": "inline", "marginRight": 16}),
        html.Span("Tab 1 — Agnostic Market Data",
                  style={"color": "#aaa", "fontSize": 14, "verticalAlign": "middle"}),
    ]), class_name="py-3")),

    # ── Spot cards ─────────────────────────────────────────────────────────────
    dbc.Row(id="spot-row", class_name="mb-4 g-2"),

    # ── Futures curve ───────────────────────────────────────────────────────────
    dbc.Row([
        dbc.Col(html.H4("Futures Curve"), width=12, class_name="mb-1"),
        dbc.Col(dbc.Spinner(html.Div(id="futures-table"), color="primary"), width=12),
    ], class_name="mb-4"),

    # ── Options chain ───────────────────────────────────────────────────────────
    dbc.Row([
        dbc.Col(html.H4("Options Chain  ·  -30Δ / ATM / +30Δ"), width=8, class_name="mb-1"),
        dbc.Col([
            dbc.InputGroup([
                dbc.InputGroupText("Multiplier (€)"),
                dbc.Input(id="notional", type="number", value=10, min=1, step=1,
                          style={"maxWidth": "100px"}),
            ], size="sm"),
        ], width=4, class_name="mb-1 d-flex align-items-center justify-content-end"),
        dbc.Col(dbc.Spinner(html.Div(id="options-table"), color="primary"), width=12),
    ], class_name="mb-4"),

    # ── Vol surface ─────────────────────────────────────────────────────────────
    dbc.Row([
        dbc.Col(html.H4("Volatility Surface"), width=12, class_name="mb-1"),
        dbc.Col(dbc.Spinner(dcc.Graph(id="vol-surface", style={"height": "500px"}),
                            color="primary"), width=12),
    ], class_name="mb-4"),

    # ── Component stocks ────────────────────────────────────────────────────────
    dbc.Row([
        dbc.Col(html.H4(f"Eurostoxx 50 Components  ({len(COMPONENTS)} resolved)"),
                width=12, class_name="mb-1"),
        dbc.Col(dbc.Spinner(html.Div(id="components-table"), color="primary"), width=12),
    ]),

], fluid=True)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _card(label, value, color="light"):
    if isinstance(value, float):
        txt = f"{value:,.2f}"
    elif value is not None:
        txt = str(value)
    else:
        txt = "—"
    return dbc.Col(dbc.Card(dbc.CardBody([
        html.P(label, className="text-muted mb-1", style={"fontSize": 11}),
        html.H5(txt, className=f"text-{color} mb-0", style={"fontSize": 15}),
    ]), style={"textAlign": "center", "padding": "10px"}), xs=6, sm=4, md=2)


def _fmt(v, decimals=2):
    if v is None:
        return "—"
    return f"{v:,.{decimals}f}"


EMPTY_FIG = go.Figure().update_layout(
    template="plotly_dark", paper_bgcolor="#111", plot_bgcolor="#111",
    title="No data yet — options chain loading",
)


# ── Callbacks ──────────────────────────────────────────────────────────────────

@app.callback(Output("spot-row", "children"), Input("tick", "n_intervals"))
def update_spot(_):
    spot = get_spot(client, INDEX["conid"])
    return [
        _card("Last",   spot.get("last"),  "warning"),
        _card("High",   spot.get("high"),  "success"),
        _card("Low",    spot.get("low"),   "danger"),
        _card("Change", spot.get("chg"),   "info"),
        _card("Chg %",  spot.get("chg_p"), "info"),
        _card("Close",  spot.get("close"), "secondary"),
    ]


@app.callback(Output("futures-table", "children"), Input("tick", "n_intervals"))
def update_futures(_):
    months = INDEX["fut_months"]
    if not months:
        return dbc.Alert("No futures months found.", color="warning")

    prices = get_futures_prices(client, INDEX["conid"], months)
    price_map = {r["Month"]: r for r in prices}

    rows = []
    for m in months[:24]:
        p = price_map.get(m, {})
        rows.append({
            "Month":    m,
            "Last":     _fmt(p.get("Last")),
            "Bid":      _fmt(p.get("Bid")),
            "Ask":      _fmt(p.get("Ask")),
            "Exchange": "EUREX",
        })

    return dash_table.DataTable(
        data=rows,
        columns=[{"name": c, "id": c} for c in ["Month", "Last", "Bid", "Ask", "Exchange"]],
        **_TBL, page_size=24,
    )


@app.callback(
    [Output("options-table", "children"), Output("vol-surface", "figure")],
    [Input("tick", "n_intervals"), Input("notional", "value")],
)
def update_options(_, notional):
    notional = float(notional or 10)
    spot_data = get_spot(client, INDEX["conid"])
    spot = spot_data.get("last") or spot_data.get("close") or 0
    months = INDEX["opt_months"]

    if not months or not spot:
        return dbc.Alert("No option data.", color="warning"), EMPTY_FIG

    rows = get_options_table(client, INDEX["conid"], months, float(spot))

    if not rows:
        return dbc.Alert("Options chain loading — retry in 30s.", color="info"), EMPTY_FIG

    # Add € columns
    for r in rows:
        r["Delta €"]  = _fmt(r["Delta"]  * notional if r["Delta"]  is not None else None)
        r["Gamma €"]  = _fmt(r["Gamma"]  * notional if r["Gamma"]  is not None else None)
        r["Vega €"]   = _fmt(r["Vega"]   * notional if r["Vega"]   is not None else None)
        r["Theta €"]  = _fmt(r["Theta"]  * notional if r["Theta"]  is not None else None)
        # Format raw Greeks for display
        r["Delta"]    = _fmt(r["Delta"],  4)
        r["Gamma"]    = _fmt(r["Gamma"],  6)
        r["Vega"]     = _fmt(r["Vega"],   4)
        r["Theta"]    = _fmt(r["Theta"],  4)
        r["IV %"]     = _fmt(r["IV %"],   2)
        r["Bid"]      = _fmt(r["Bid"])
        r["Ask"]      = _fmt(r["Ask"])
        r["Last"]     = _fmt(r["Last"])

    cols = ["Maturity", "Strike", "Type",
            "Bid", "Ask", "Last", "IV %",
            "Delta", "Delta €", "Gamma", "Gamma €",
            "Vega", "Vega €", "Theta", "Theta €"]

    table = dash_table.DataTable(
        data=rows,
        columns=[{"name": c, "id": c} for c in cols],
        sort_action="native",
        filter_action="native",
        page_size=20,
        **_TBL,
        style_data_conditional=[
            {"if": {"filter_query": '{Type} contains "call"'},
             "backgroundColor": "#0d2137", "color": "#64b5f6"},
            {"if": {"filter_query": '{Type} contains "put"'},
             "backgroundColor": "#1a0d0d", "color": "#ef9a9a"},
        ],
    )

    # Vol surface — IV% by Maturity × Strike
    df = pd.DataFrame(rows)
    df["IV_num"] = pd.to_numeric(df["IV %"].replace("—", None), errors="coerce")
    df["Strike_num"] = pd.to_numeric(df["Strike"], errors="coerce")
    surface_df = df[df["IV_num"].notna() & df["Strike_num"].notna()]

    if surface_df.empty:
        fig = EMPTY_FIG
    else:
        pivot = surface_df.pivot_table(
            values="IV_num", index="Strike_num", columns="Maturity", aggfunc="mean"
        )
        fig = go.Figure(go.Surface(
            z=pivot.values,
            x=list(pivot.columns),
            y=list(pivot.index),
            colorscale="Viridis",
            colorbar=dict(title="IV %", thickness=15),
        ))
        fig.update_layout(
            template="plotly_dark", paper_bgcolor="#111",
            title=f"{INDEX['name']} — Implied Volatility Surface",
            scene=dict(
                xaxis_title="Maturity", yaxis_title="Strike", zaxis_title="IV (%)",
                bgcolor="#111",
            ),
            margin=dict(l=0, r=0, t=40, b=0),
        )

    return table, fig


@app.callback(Output("components-table", "children"), Input("tick", "n_intervals"))
def update_components(_):
    if not COMPONENTS:
        return dbc.Alert("No components resolved.", color="warning")

    rows = get_component_spots(client, COMPONENTS)
    if not rows:
        return dbc.Alert("Component data loading...", color="info")

    for r in rows:
        r["Last"] = _fmt(r.get("Last"))
        r["Bid"]  = _fmt(r.get("Bid"))
        r["Ask"]  = _fmt(r.get("Ask"))

    return dash_table.DataTable(
        data=rows,
        columns=[{"name": c, "id": c} for c in ["Symbol", "Name", "Last", "Bid", "Ask"]],
        sort_action="native",
        filter_action="native",
        page_size=25,
        **_TBL,
    )


if __name__ == "__main__":
    app.run(debug=True, port=8050)
