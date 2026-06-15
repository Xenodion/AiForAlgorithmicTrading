"""
Volatility Infrastructure Platform
Run: .venv\\Scripts\\streamlit run app.py
"""

import sys
import threading
import time
import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

sys.path.insert(0, str(Path(__file__).parent))
from src.connectivity.session import IBKRClient
from src.data.fetcher import (
    resolve_index, get_spot, get_options_table,
    get_futures_prices, resolve_components, get_component_spots,
    get_price_history, get_strikes, get_option_conid,
    select_futures_curve, FUTURES_TENORS, FUTURES_TENOR_MONTHS,
)
from src.analytics.pricer import black_scholes, greeks, scenario_grid, implied_volatility, pnl_approximation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _month_label(month: str) -> str:
    """'202609' -> 'Sep26'."""
    return date(int(month[:4]), int(month[4:6]), 1).strftime("%b%y")


def _fmt_maturity(month: str) -> str:
    """'202609' -> '2026-09' (display only — underlying value stays 'YYYYMM')."""
    return f"{str(month)[:4]}-{str(month)[4:6]}"


def _maturity_years(month: str) -> float:
    year = int(str(month)[:4])
    month_num = int(str(month)[4:6])
    if month_num == 12:
        expiry = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        expiry = date(year, month_num + 1, 1) - timedelta(days=1)
    return max((expiry - date.today()).days / 365.0, 1 / 365.0)


def _option_price(row: pd.Series) -> float | None:
    bid, ask, last = row.get("Bid"), row.get("Ask"), row.get("Last")
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    if last is not None and last > 0:
        return last
    return None


def explain(text: str) -> None:
    """Collapsible beginner-friendly explanation shown under a section title."""
    with st.expander("ℹ️ What is this?"):
        st.markdown(text)


def fill_missing_iv(df: pd.DataFrame, spot: float, rate: float = 0.03) -> pd.DataFrame:
    df = df.copy()
    if "IV Source" not in df.columns:
        df["IV Source"] = df["IV %"].apply(lambda v: "IBKR" if pd.notna(v) else None)

    for idx, row in df[df["IV %"].isna()].iterrows():
        price = _option_price(row)
        option_type = "put" if "put" in str(row.get("Type", "")).lower() else "call"
        iv = implied_volatility(
            price=price,
            S=spot,
            K=float(row["Strike"]),
            T=_maturity_years(row["Maturity"]),
            r=rate,
            option_type=option_type,
        ) if price else None
        if iv is not None:
            df.at[idx, "IV %"] = round(iv * 100, 4)
            df.at[idx, "IV Source"] = "BS fallback"

    return df


def filter_liquid_maturities(df: pd.DataFrame, min_points: int = 5) -> tuple[pd.DataFrame, list[str]]:
    """
    Drop maturities with fewer than `min_points` usable IV quotes — typical
    for the front month a few days from expiry, where the delayed feed has
    no live bid/ask for most delta-target strikes. Without this, those
    near-empty columns punch holes in the 3D IV surface.
    """
    counts = df.groupby("Maturity")["IV %"].apply(lambda s: s.notna().sum())
    good = counts[counts >= min_points].index
    if good.empty:
        # Nothing meets the bar (e.g. a cold cache before quotes warm up) -
        # showing a sparse surface beats showing none at all.
        return df, []
    dropped = list(counts[counts < min_points].index)
    return df[df["Maturity"].isin(good)].copy(), dropped


def _delta_sort_key(label: str) -> int:
    """Numeric ordering for 'Delta Target' labels: -30Δ ... ATM ... +30Δ."""
    return 0 if label == "ATM" else int(label.replace("Δ", ""))

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Volatility Infrastructure Platform",
    layout="wide",
    page_icon="📈",
)

# ── Init (runs once, cached for the lifetime of the server) ───────────────────
@st.cache_resource(show_spinner="Connecting to IBKR and resolving contracts...")
def init():
    client = IBKRClient.from_config("configs/broker.yaml")
    client.check_auth()
    index      = resolve_index(client)
    components = resolve_components(client)

    def _tickle():
        while True:
            time.sleep(55)
            try:
                client.tickle()
            except Exception:
                try:
                    client.post("/iserver/reauthenticate")
                except Exception:
                    pass

    threading.Thread(target=_tickle, daemon=True, name="tickle").start()
    return client, index, components


try:
    client, INDEX, COMPONENTS = init()
except Exception as e:
    st.error(f"**IBKR connection failed:** {e}")
    st.info("Start the gateway, log in at https://localhost:5000, then refresh this page.")
    st.stop()

# ── Auto-refresh every 10 min ──────────────────────────────────────────────────
st_autorefresh(interval=10 * 60_000, key="autorefresh")

# ── Header ─────────────────────────────────────────────────────────────────────
st.title("📈 Volatility Infrastructure Platform")
st.caption(
    f"**{INDEX['name']}** · conid {INDEX['conid']} · "
    f"{len(INDEX['opt_months'])} option months · "
    f"{len(COMPONENTS)} components resolved"
)

tab1, tab2, tab3, tab4 = st.tabs(
    ["📊 Data", "⚠️ Risk", "📤 Orders", "🌀 Surface"]
)

# ══════════════════════════════════════════════════════════════════════════════
with tab1:

    # ── Controls ───────────────────────────────────────────────────────────────
    col_btn, col_mult = st.columns([4, 1])
    with col_btn:
        manual_refresh = st.button("🔄 Refresh now")
    with col_mult:
        notional = st.number_input("Multiplier (€)", min_value=1, value=10, step=1,
                                   help="SX5E options: €10 per index point")

    # ── Spot ───────────────────────────────────────────────────────────────────
    st.subheader(f"Spot — {INDEX['name']}")
    explain(
        f"The live level of the **{INDEX['name']}** index, in **index points** "
        "(not €) — it's a weighted average of the 50 component stock prices, "
        "not a directly tradeable price.\n\n"
        "- **Last**: most recent quoted level\n"
        "- **High / Low**: today's range\n"
        "- **Close**: previous session's closing level\n"
        "- **Chg / Chg %**: change vs previous close\n\n"
        "Index points only become a € amount once you trade a derivative "
        "(future/option) — see the **Multiplier** field above."
    )
    spot = get_spot(client, INDEX["conid"])

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    def _fmt(v, decimals=2):
        return f"{v:,.{decimals}f}" if v is not None else "—"

    last  = spot.get("last")
    close = spot.get("close")
    delta = round(last - close, 2) if last and close else None

    c1.metric("Last",  _fmt(last),             f"{delta:+,.2f}" if delta else None)
    c2.metric("High",  _fmt(spot.get("high")))
    c3.metric("Low",   _fmt(spot.get("low")))
    c4.metric("Close", _fmt(close))
    c5.metric("Chg",   _fmt(spot.get("chg")))
    c6.metric("Chg %", f"{spot.get('chg_p'):+.2f}%" if spot.get("chg_p") else "—")

    st.divider()

    # ── 3Y Price history ───────────────────────────────────────────────────────
    st.subheader(f"{INDEX['name']} — 3 Year Price History")
    explain(
        "A **candlestick chart** of the index level over time.\n\n"
        "- Each candle shows the **Open / High / Low / Close** for one bar "
        "(one week or one day, depending on the **Bar** setting)\n"
        "- Green = price went up over the bar, red = price went down\n"
        "- The dotted orange line is the **50-bar moving average** — a smoothed "
        "trend line, useful to see if the index is currently above or below "
        "its recent average level\n\n"
        "Use **Period** to control how far back the chart goes."
    )
    col_period, col_bar = st.columns([3, 1])
    with col_period:
        period = st.select_slider("Period", options=["6m", "1y", "2y", "3y"], value="3y")
    with col_bar:
        bar = st.selectbox("Bar", ["1w", "1d"], index=0)

    with st.spinner("Loading history..."):
        history = get_price_history(client, INDEX["conid"], period=period, bar=bar)

    if history:
        import pandas as pd
        df_hist = pd.DataFrame(history)
        fig_hist = go.Figure()
        fig_hist.add_trace(go.Candlestick(
            x=df_hist["date"],
            open=df_hist["open"], high=df_hist["high"],
            low=df_hist["low"],  close=df_hist["close"],
            name=INDEX["name"],
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        ))
        # 50-week moving average
        df_hist["ma50"] = df_hist["close"].rolling(50).mean()
        fig_hist.add_trace(go.Scatter(
            x=df_hist["date"], y=df_hist["ma50"],
            name="50-bar MA", line=dict(color="#ff9800", width=1.5, dash="dot"),
        ))
        fig_hist.update_layout(
            height=420,
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
            margin=dict(l=0, r=0, t=20, b=0),
            legend=dict(orientation="h", y=1.02),
        )
        st.plotly_chart(fig_hist, use_container_width=True)
    else:
        st.info("Historical data unavailable.")

    st.divider()

    # ── Futures ────────────────────────────────────────────────────────────────
    st.subheader("Futures Curve")
    explain(
        "The **futures curve** (a.k.a. term structure): the price of "
        "**futures contracts** on the index at standard tenors — "
        "10 days, 1 to 18 months, 2 years and 3 years — each worth "
        f"**{notional}€ per index point** (see the Multiplier setting above).\n\n"
        "- **Last**: most recent traded price\n"
        "- **Bid / Ask**: prices people are currently willing to trade at — "
        "often missing for far-dated contracts, since they trade rarely and "
        "have no live quote, only a last traded price\n\n"
        "EUREX only lists **quarterly** expiries (Mar/Jun/Sep/Dec), so each "
        "tenor is mapped to the closest available contract month — several "
        "tenors can therefore point to the same expiry.\n\n"
        "⚠️ **Note on far-dated points**: where Bid/Ask are missing, "
        "**Last** is not a live price — it's whatever that contract's most "
        "recent trade happened to be, which could be days or weeks old. "
        "Don't read zigzags at the long end as today's curve shape, just "
        "as old prints from an illiquid contract.\n\n"
        "An upward-sloping curve (further expiries priced higher) is called "
        "**contango**; a downward-sloping curve is **backwardation**."
    )
    with st.spinner("Loading futures..."):
        curve = select_futures_curve(INDEX["fut_months"], FUTURES_TENORS, FUTURES_TENOR_MONTHS)
        curve_months = sorted({month for _, month in curve})
        fut_rows = get_futures_prices(client, INDEX["conid"], curve_months)

    if fut_rows and curve:
        price_by_month = {r["Month"]: r for r in fut_rows}
        df_fut = pd.DataFrame([
            {
                "Tenor": tenor,
                "Expiry": _month_label(month),
                "Last": price_by_month.get(month, {}).get("Last"),
                "Bid":  price_by_month.get(month, {}).get("Bid"),
                "Ask":  price_by_month.get(month, {}).get("Ask"),
            }
            for tenor, month in curve
        ])

        fig_fut = go.Figure()
        for col, color in [("Bid", "#66bb6a"), ("Last", "#42a5f5"), ("Ask", "#ef5350")]:
            fig_fut.add_trace(go.Scatter(
                x=df_fut["Tenor"], y=df_fut[col], name=col,
                mode="lines+markers", line=dict(width=2, color=color),
                marker=dict(size=6), connectgaps=False,
            ))
        fig_fut.update_layout(
            height=380,
            template="plotly_dark",
            margin=dict(l=0, r=0, t=20, b=0),
            legend=dict(orientation="h", y=1.02),
            xaxis_title="Tenor",
            yaxis_title="Index points",
        )
        st.plotly_chart(fig_fut, use_container_width=True)
        st.dataframe(df_fut, use_container_width=True, hide_index=True)
    else:
        st.info("Futures data unavailable — retrying on next refresh.")

    st.divider()

    # ── Options chain ──────────────────────────────────────────────────────────
    st.subheader("Options Chain — -30Δ to +30Δ (5Δ steps)")
    explain(
        "A snapshot of **option contracts** on the index for several "
        "maturities, with **one contract per delta target from -30 to "
        "+30 in steps of 5** (-30, -25, ..., -5, ATM, +5, ..., +30 — 13 "
        "targets) — out-of-the-money **puts** for negative targets, "
        "out-of-the-money **calls** for positive targets, and **both a "
        "Put and a Call at the at-the-money (ATM) target**.\n\n"
        "- **Delta Target**: the approximate bucket this row was selected "
        "for (e.g. `-30Δ`, `ATM`, `+15Δ`) — the strike is picked using a "
        "rough %-from-spot proxy, so the **actual** delta is shown in the "
        "**Delta** column\n"
        "- **Type**: Put or Call\n"
        "- **Bid / Ask / Last**: option prices in index points\n"
        "- **IV %**: implied volatility — the market's expectation of future "
        "price swings, derived from the option's price\n"
        "- **IV Source**: `IBKR` if IBKR returned the IV directly, or "
        "`BS fallback` if it was backed out locally with the Black-Scholes "
        "formula because IBKR didn't provide one\n"
        "- **Greeks (Δ, Γ, ν, θ)**: sensitivities of the option price to "
        "spot, and their **(€)** counterparts converted using the "
        "Multiplier above — e.g. Delta (€) ≈ how many € the position gains "
        "per 1-point move in the index"
    )
    spot_price = float(last or close or 0)

    if "df_options" not in st.session_state and spot_price > 0:
        with st.spinner("Loading options chain..."):
            opt_rows = get_options_table(
                client, INDEX["conid"], INDEX["opt_months"], spot_price
            )
            if opt_rows:
                st.session_state["df_options"] = pd.DataFrame(opt_rows)

    if st.button("🔄 Refresh option data"):
        st.session_state.pop("df_options", None)
        st.rerun()

    if "df_options" in st.session_state:
        df_opt = fill_missing_iv(st.session_state["df_options"], spot_price)
        st.session_state["df_options"] = df_opt

        # Add € columns next to each Greek
        for greek in ["Delta", "Gamma", "Vega", "Theta"]:
            df_opt[f"{greek} (€)"] = df_opt[greek].apply(
                lambda v: round(v * notional, 4) if v is not None else None
            )

        col_order = [
            "Maturity", "Delta Target", "Strike", "Type",
            "Bid", "Ask", "Last", "IV %", "IV Source",
            "Delta", "Delta (€)",
            "Gamma", "Gamma (€)",
            "Vega",  "Vega (€)",
            "Theta", "Theta (€)",
        ]

        # ── Filters ──────────────────────────────────────────────────────────
        f_mat, f_type, f_delta = st.columns(3)
        with f_mat:
            mat_options = sorted(df_opt["Maturity"].dropna().unique())
            selected_mats = st.multiselect(
                "Filter Maturity", options=mat_options, default=mat_options,
                format_func=_fmt_maturity,
            )
        with f_type:
            type_options = sorted(df_opt["Type"].dropna().unique())
            selected_types = st.multiselect(
                "Filter Type", options=type_options, default=type_options,
            )
        with f_delta:
            delta_options = sorted(df_opt["Delta Target"].dropna().unique(), key=_delta_sort_key)
            selected_deltas = st.multiselect(
                "Filter Delta Target", options=delta_options, default=delta_options,
            )

        df_display = df_opt[
            df_opt["Maturity"].isin(selected_mats)
            & df_opt["Type"].isin(selected_types)
            & df_opt["Delta Target"].isin(selected_deltas)
        ].copy()
        df_display["Maturity"] = df_display["Maturity"].map(_fmt_maturity)

        st.dataframe(
            df_display[[c for c in col_order if c in df_display.columns]],
            use_container_width=True,
            hide_index=True,
        )

        # ── Vol surface ────────────────────────────────────────────────────────
        st.subheader("Volatility Surface")
        explain(
            "A 3D view of **implied volatility (IV %)** across **Delta "
            "Target** and **Maturity**, built from the options chain above "
            "(13 delta targets from -30Δ to +30Δ, per maturity).\n\n"
            "The y-axis is the **Delta Target** bucket (-30Δ ... ATM ... "
            "+30Δ) rather than the raw strike — different maturities list "
            "different strike grids, so plotting against raw strike "
            "produces a disjointed, gappy surface. Delta Target is the same "
            "13-point grid for every maturity, so the surface is continuous.\n\n"
            "Normally IV isn't flat — it forms a 'smile' or 'skew' shape across "
            "delta targets, and a 'term structure' shape across maturities. This "
            "surface lets you see both at once. For a more detailed version "
            "with smile and term-structure charts, see the **Surface** tab."
        )
        surf = df_opt[df_opt["IV %"].notna() & df_opt["Delta Target"].notna()].copy()
        surf, dropped_mats = filter_liquid_maturities(surf)
        if dropped_mats:
            st.caption(
                "Excluded from surface (too few live quotes this close to "
                f"expiry): {', '.join(dropped_mats)}"
            )

        if not surf.empty:
            pivot = surf.pivot_table(
                values="IV %", index="Delta Target", columns="Maturity", aggfunc="mean"
            )
            pivot = pivot.reindex(sorted(pivot.index, key=_delta_sort_key))
            fig = go.Figure(go.Surface(
                z=pivot.values,
                x=list(pivot.columns),
                y=list(pivot.index),
                colorscale="Viridis",
                colorbar=dict(title="IV %", thickness=15),
                hovertemplate=(
                    "Maturity=%{x}<br>"
                    "Delta Target=%{y}<br>"
                    "IV=%{z:.2f}%<extra></extra>"
                ),
            ))
            fig.update_layout(
                height=520,
                title=f"{INDEX['name']} — Implied Volatility Surface",
                scene=dict(
                    xaxis_title="Maturity",
                    yaxis_title="Delta Target",
                    zaxis_title="IV (%)",
                    zaxis=dict(range=[0, surf["IV %"].max()]),
                ),
                margin=dict(l=0, r=0, t=40, b=0),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Vol surface requires IV % data — loading...")

    else:
        st.info("Options chain loading — first load can take a few minutes.")

    st.divider()

    # ── Component stocks ───────────────────────────────────────────────────────
    st.subheader(f"Eurostoxx 50 Components — {len(COMPONENTS)} stocks")
    explain(
        f"Live prices for the **{len(COMPONENTS)} individual stocks** that "
        f"make up the {INDEX['name']} index (e.g. LVMH, SAP, TotalEnergies...). "
        "The index level is essentially a weighted average of these stock "
        "prices, so this table shows what's actually moving the index "
        "underneath the hood."
    )
    with st.spinner("Loading component prices..."):
        comp_rows = get_component_spots(client, COMPONENTS)

    if comp_rows:
        df_comp = pd.DataFrame(comp_rows)
        for col in ["Last", "Bid", "Ask"]:
            df_comp[col] = df_comp[col].apply(lambda v: f"{v:,.2f}" if v else "—")
        st.dataframe(df_comp, use_container_width=True, hide_index=True)
    else:
        st.info("Component data loading...")

    st.divider()

    # ── Component deep-dive ────────────────────────────────────────────────────
    st.subheader("Component Deep-Dive")
    explain(
        "Pick one of the index's component stocks to see the same **spot "
        "price** and **price history** views shown above for the "
        f"{INDEX['name']} index itself, but for that single stock — "
        "useful to inspect what's driving (or dragging) the index."
    )

    comp_symbols = sorted(COMPONENTS.keys(), key=lambda s: COMPONENTS[s]["name"].lower())
    comp_labels = {s: f"{COMPONENTS[s]['name']} ({s})" for s in comp_symbols}
    selected_symbol = st.selectbox(
        "Stock", comp_symbols, format_func=lambda s: comp_labels[s],
    )
    comp_conid = COMPONENTS[selected_symbol]["conid"]
    comp_name = COMPONENTS[selected_symbol]["name"]

    with st.spinner(f"Loading {comp_name}..."):
        comp_spot = get_spot(client, comp_conid)
        if comp_spot.get("high") is None:
            # First snapshot for a conid often only returns "last" - the
            # rest of the fields populate once the subscription warms up.
            time.sleep(2)
            comp_spot = get_spot(client, comp_conid)

    cc1, cc2, cc3, cc4, cc5, cc6 = st.columns(6)
    comp_last  = comp_spot.get("last")
    comp_close = comp_spot.get("close")
    comp_delta = round(comp_last - comp_close, 2) if comp_last and comp_close else None

    cc1.metric("Last",  _fmt(comp_last), f"{comp_delta:+,.2f}" if comp_delta else None)
    cc2.metric("High",  _fmt(comp_spot.get("high")))
    cc3.metric("Low",   _fmt(comp_spot.get("low")))
    cc4.metric("Close", _fmt(comp_close))
    cc5.metric("Chg",   _fmt(comp_spot.get("chg")))
    cc6.metric("Chg %", f"{comp_spot.get('chg_p'):+.2f}%" if comp_spot.get("chg_p") else "—")

    with st.spinner(f"Loading {comp_name} history..."):
        comp_history = get_price_history(client, comp_conid, period=period, bar=bar)

    if comp_history:
        df_comp_hist = pd.DataFrame(comp_history)
        fig_comp_hist = go.Figure()
        fig_comp_hist.add_trace(go.Candlestick(
            x=df_comp_hist["date"],
            open=df_comp_hist["open"], high=df_comp_hist["high"],
            low=df_comp_hist["low"],  close=df_comp_hist["close"],
            name=comp_name,
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        ))
        df_comp_hist["ma50"] = df_comp_hist["close"].rolling(50).mean()
        fig_comp_hist.add_trace(go.Scatter(
            x=df_comp_hist["date"], y=df_comp_hist["ma50"],
            name="50-bar MA", line=dict(color="#ff9800", width=1.5, dash="dot"),
        ))
        fig_comp_hist.update_layout(
            height=420,
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
            margin=dict(l=0, r=0, t=20, b=0),
            legend=dict(orientation="h", y=1.02),
        )
        st.plotly_chart(fig_comp_hist, use_container_width=True)
    else:
        st.info(f"Historical data unavailable for {comp_name}.")

# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.header("⚠️ Risk")
    explain(
        "This tab is a **risk and pricing toolbox**, independent of live "
        "market data — you choose all the inputs yourself.\n\n"
        "- **Black-Scholes Pricer**: price a single option and see its Greeks\n"
        "- **Scenario Engine**: see how an option's P&L would change under "
        "different spot/volatility moves\n"
        "- **Portfolio Builder**: combine several option positions and see "
        "their combined (aggregated) Greeks and an estimated P&L"
    )

    spot_now = get_spot(client, INDEX["conid"])
    S_live   = float(spot_now.get("last") or spot_now.get("close") or 5000)

    # ── Black-Scholes Pricer ───────────────────────────────────────────────────
    st.subheader("🧮 Black-Scholes Pricer")
    explain(
        "Computes a theoretical option price using the **Black-Scholes "
        "formula**, from 5 inputs:\n\n"
        "- **S₀**: spot price of the underlying today\n"
        "- **K**: strike price of the option\n"
        "- **T**: time to maturity, in years (e.g. 0.25 ≈ 3 months)\n"
        "- **r**: risk-free interest rate\n"
        "- **σ (sigma)**: volatility — how much the underlying is expected "
        "to move\n\n"
        "The **Greeks** measure sensitivity: **Δ (Delta)** = price change per "
        "1-point spot move, **Γ (Gamma)** = how Delta itself changes, "
        "**ν (Vega)** = price change per 1% change in volatility, "
        "**θ (Theta)** = price change per day (time decay). The **(€)** "
        "values convert these into euros using the **Multiplier**."
    )
    st.caption("S = f(S₀, K, T, r, σ)   |   dV ≈ Δ·dS + ½Γ·dS² + ν·dσ + θ·dt")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    bs_S      = c1.number_input("Spot S₀",    value=round(S_live, 0), step=10.0)
    bs_K      = c2.number_input("Strike K",   value=float(round(S_live / 100) * 100), step=50.0)
    bs_T      = c3.number_input("Maturity T (yr)", value=0.25, min_value=0.01, step=0.05, format="%.2f")
    bs_r      = c4.number_input("Rate r (%)",  value=3.0,  step=0.25, format="%.2f") / 100
    bs_sigma  = c5.number_input("Vol σ (%)",   value=20.0, step=1.0,  format="%.1f") / 100
    bs_mult   = c6.number_input("Multiplier",  value=10,   step=1)

    col_call, col_put = st.columns(2)

    for opt_type, col in [("call", col_call), ("put", col_put)]:
        price = black_scholes(bs_S, bs_K, bs_T, bs_r, bs_sigma, opt_type)
        g     = greeks(bs_S, bs_K, bs_T, bs_r, bs_sigma, opt_type, bs_mult)
        col.markdown(f"**{'Call 📈' if opt_type=='call' else 'Put 📉'}**")
        col.metric("Price", f"{price:,.4f}")
        metrics_row = col.columns(4)
        metrics_row[0].metric("Δ Delta",  f"{g['delta']:+.4f}",  f"€ {g['dollar_delta']:+.2f}")
        metrics_row[1].metric("Γ Gamma",  f"{g['gamma']:.6f}",   f"€ {g['dollar_gamma']:+.2f}")
        metrics_row[2].metric("ν Vega",   f"{g['vega']:+.4f}",   f"€ {g['dollar_vega']:+.2f}")
        metrics_row[3].metric("θ Theta",  f"{g['theta']:+.4f}",  f"€ {g['dollar_theta']:+.2f}")

    st.divider()

    # ── Scenario Engine ────────────────────────────────────────────────────────
    st.subheader("📊 Scenario Engine — PnL Grid")
    explain(
        "Takes the option defined above (S₀, K, T, r, σ) and asks: "
        "**'what if the spot price and volatility change?'**\n\n"
        "- Each row/column combination is a **scenario**: spot moves by the "
        "'Spot shock' % and volatility moves by the 'Vol shock' %\n"
        "- **P&L (full)**: re-runs Black-Scholes with the shocked S and σ, "
        "then compares to the original price — the *exact* P&L\n"
        "- **P&L (Greeks)**: estimates the same P&L using only the "
        "Greeks (Δ, Γ, ν) — a fast linear/quadratic approximation\n"
        "- **Error**: the difference between the two — shows how good the "
        "Greeks approximation is, especially for larger moves\n\n"
        "The heatmap below is the full-repricing P&L: the **y-axis** is the "
        "spot shock, the **x-axis** is the vol shock, each cell shows the "
        "€ P&L for that combination, and the colorbar on the right is the "
        "legend — green = gains, red = losses, white ≈ €0 (today)."
    )
    st.caption("Full repricing vs Greeks approximation under spot × vol shocks")

    scen_type = st.radio("Option type", ["call", "put"], horizontal=True)

    spot_shocks = [-0.15, -0.10, -0.05, 0.0, +0.05, +0.10, +0.15]
    vol_shocks  = [-0.10, -0.05, 0.0, +0.05, +0.10]

    scenarios = scenario_grid(
        S=bs_S, K=bs_K, T=bs_T, r=bs_r, sigma=bs_sigma,
        option_type=scen_type, multiplier=bs_mult,
        spot_shocks=spot_shocks, vol_shocks=vol_shocks,
    )
    df_scen = pd.DataFrame(scenarios)

    st.markdown("**P&L (full repricing, €)**")
    pnl_grid = df_scen["P&L (full)"].to_numpy().reshape(len(spot_shocks), len(vol_shocks))
    fig_heat = go.Figure(go.Heatmap(
        z=pnl_grid,
        x=[f"{v:+.0%}" for v in vol_shocks],
        y=[f"{s:+.0%}" for s in spot_shocks],
        colorscale="RdYlGn",
        zmid=0,
        text=pnl_grid,
        texttemplate="%{text:+,.0f}",
        textfont=dict(size=11),
        colorbar=dict(title="P&L (€)"),
        hovertemplate="Spot shock %{y}, Vol shock %{x}<br>P&L = %{z:+,.2f} €<extra></extra>",
    ))
    fig_heat.update_layout(
        height=400,
        template="plotly_dark",
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis_title="Vol shock (Δσ, percentage points)",
        yaxis_title="Spot shock (%)",
    )
    st.plotly_chart(fig_heat, use_container_width=True)

    st.markdown("**Full scenario table**")
    st.dataframe(df_scen, use_container_width=True, hide_index=True)

    st.divider()

    # ── Greeks cheat-sheet ─────────────────────────────────────────────────────
    st.markdown("#### 🔑 Greeks cheat-sheet")
    st.caption("Quick reference for the columns in the portfolio table below")
    st.markdown(
        "| Greek | Symbol | What it measures | Quick read |\n"
        "|---|---|---|---|\n"
        "| Delta | Δ | € change in option value per **1-point move** in the underlying | "
        "Calls: 0 → 1, Puts: -1 → 0. At-the-money ≈ ±0.5 |\n"
        "| Gamma | Γ | How fast **Delta itself changes** as the spot moves | "
        "Highest near the money & close to expiry — your Delta estimate goes stale fastest here |\n"
        "| Vega | ν | € change in option value per **1% move in volatility** | "
        "Always positive for long options — higher vol = more valuable |\n"
        "| Theta | θ | € change in option value per **day that passes** | "
        "Usually negative for long options — the 'rent' you pay for holding it |\n"
        "| Rho | ρ | € change in option value per **1% move in interest rates** | "
        "Usually the smallest effect, especially for short-dated options |\n"
    )

    # ── Portfolio Builder ──────────────────────────────────────────────────────
    st.subheader("📋 Portfolio Builder")
    explain(
        "Build a small **portfolio of option positions** by hand and see "
        "how their risk adds up.\n\n"
        "- Fill in the form (type, strike, maturity, vol, quantity, "
        "multiplier) and click **➕ Add to portfolio** — each click adds one "
        "position to the table below\n"
        "- **Aggregated portfolio Greeks**: the sum of every position's € "
        "Greeks — this tells you the portfolio's overall sensitivity to "
        "spot (Δ), to changes in Δ itself (Γ), to volatility (ν), and to "
        "time passing (θ)\n"
        "- **Local P&L approximation**: drag the sliders to simulate a move "
        "in spot, volatility, or time, and see the estimated impact on the "
        "whole portfolio's value (using the Greeks, not full repricing)\n\n"
        "Use **🗑️ Clear portfolio** to start over."
    )
    st.caption("Add positions manually — Greeks aggregate automatically")

    if "portfolio" not in st.session_state:
        st.session_state.portfolio = []

    with st.form("add_position"):
        pc1, pc2, pc3, pc4, pc5, pc6, pc7 = st.columns(7)
        p_label = pc1.text_input("Label",    value="ESTX50 ATM C")
        p_type  = pc2.selectbox("Type",      ["call", "put"])
        p_K     = pc3.number_input("Strike K",    value=float(round(S_live / 100) * 100), step=50.0)
        p_T     = pc4.number_input("T (yr)",  value=0.25, step=0.05, format="%.2f")
        p_sigma = pc5.number_input("σ (%)",   value=20.0, step=1.0) / 100
        p_qty   = pc6.number_input("Qty",     value=1, step=1)
        p_mult  = pc7.number_input("Mult",    value=10, step=1)
        add     = st.form_submit_button("➕ Add to portfolio")

    if add:
        price = black_scholes(bs_S, p_K, p_T, bs_r, p_sigma, p_type)
        g     = greeks(bs_S, p_K, p_T, bs_r, p_sigma, p_type, p_mult)
        st.session_state.portfolio.append({
            "Label":  p_label,
            "Type":   p_type,
            "Strike": p_K,
            "T":      p_T,
            "σ":      f"{p_sigma:.1%}",
            "Qty":    p_qty,
            "Mult":   p_mult,
            "Price":  round(price, 4),
            "Δ":      g["delta"],
            "Γ":      g["gamma"],
            "ν":      g["vega"],
            "θ":      g["theta"],
            "$ Δ":    g["dollar_delta"] * p_qty,
            "$ Γ":    g["dollar_gamma"] * p_qty,
            "$ ν":    g["dollar_vega"]  * p_qty,
            "$ θ":    g["dollar_theta"] * p_qty,
            "_S":     bs_S, "_K": p_K, "_T": p_T,
            "_r":     bs_r, "_sigma": p_sigma, "_type": p_type, "_mult": p_mult,
        })

    if st.session_state.portfolio:
        if st.button("🗑️ Clear portfolio"):
            st.session_state.portfolio = []
            st.rerun()

        df_port = pd.DataFrame(st.session_state.portfolio)
        display_cols = ["Label","Type","Strike","T","σ","Qty","Mult","Price",
                        "Δ","Γ","ν","θ","$ Δ","$ Γ","$ ν","$ θ"]
        st.dataframe(df_port[display_cols], use_container_width=True, hide_index=True)

        # Aggregate Greeks
        st.markdown("**Aggregated portfolio Greeks**")
        ag1, ag2, ag3, ag4 = st.columns(4)
        ag1.metric("Total $ Δ", f"€ {df_port['$ Δ'].sum():+,.2f}")
        ag2.metric("Total $ Γ", f"€ {df_port['$ Γ'].sum():+,.2f}")
        ag3.metric("Total $ ν", f"€ {df_port['$ ν'].sum():+,.2f}")
        ag4.metric("Total $ θ", f"€ {df_port['$ θ'].sum():+,.2f}")

        # Portfolio PnL approximation
        st.markdown("**Local P&L approximation** — dV ≈ Δ·dS + ½Γ·dS² + ν·dσ + θ·dt")
        pa1, pa2, pa3 = st.columns(3)
        dS_input     = pa1.slider("Spot move dS (pts)", -500, 500, 0, step=10)
        dsigma_input = pa2.slider("Vol move dσ (%)",    -10,  10,  0, step=1) / 100
        dt_input     = pa3.slider("Time dt (days)",     0,    30,  1)

        total_pnl = sum(
            (row["Δ"] * dS_input
             + 0.5 * row["Γ"] * dS_input**2
             + row["ν"] * dsigma_input * 100
             + row["θ"] * dt_input) * row["Qty"] * row["Mult"]
            for row in st.session_state.portfolio
        )
        st.metric("Estimated portfolio P&L", f"€ {total_pnl:+,.2f}")
    else:
        st.info("Add positions above to build your portfolio.")

    st.divider()

    # ── Portfolio Backtest ─────────────────────────────────────────────────────
    st.subheader("📈 Portfolio Backtest")
    explain(
        "Replays your current portfolio (above) against the real "
        f"historical price of {INDEX['name']}: for each past trading day, "
        "'what would this exact portfolio be worth if the index had been "
        "at that day's level (with correspondingly more time to maturity), "
        "compared to its value today?'\n\n"
        "- **P&L (full)**: re-runs Black-Scholes — S = f(S₀, K, T, r, σ) — "
        "with the historical spot and adjusted maturity: the *exact* "
        "theoretical P&L\n"
        "- **P&L (Greeks)**: applies today's Greeks linearly to the "
        "realized spot move and elapsed time — dV ≈ Σ ∂F/∂x · dx: the fast "
        "approximation\n"
        "- **Error**: full minus approx — shows where the linear "
        "approximation breaks down for larger historical moves\n\n"
        "**Note**: volatility σ is held constant at each position's "
        "current value for every historical day, since IBKR doesn't "
        "provide historical implied vol — only spot-price and time-decay "
        "effects are backtested."
    )

    if st.session_state.portfolio:
        bt_period = st.select_slider(
            "Backtest lookback", options=["1m", "3m", "6m", "1y"], value="3m"
        )
        with st.spinner("Loading historical prices..."):
            bt_history = get_price_history(client, INDEX["conid"], period=bt_period, bar="1d")

        if bt_history:
            today_date = bt_history[-1]["date"]
            bt_rows = []
            for h in bt_history:
                S_i = h["close"]
                if S_i is None:
                    continue
                days_ago = (today_date - h["date"]).days

                pnl_full = pnl_approx = 0.0
                for pos in st.session_state.portfolio:
                    T_i     = pos["_T"] + days_ago / 365
                    V_i     = black_scholes(S_i,    pos["_K"], T_i,       pos["_r"], pos["_sigma"], pos["_type"])
                    V_today = black_scholes(S_live, pos["_K"], pos["_T"], pos["_r"], pos["_sigma"], pos["_type"])
                    pnl_full += (V_today - V_i) * pos["Qty"] * pos["Mult"]
                    pnl_approx += pnl_approximation(
                        pos["Δ"], pos["Γ"], pos["ν"], pos["θ"],
                        dS=S_live - S_i, d_sigma=0, dt=days_ago,
                        multiplier=pos["Mult"],
                    ) * pos["Qty"]

                bt_rows.append({
                    "Date": h["date"], "Spot": S_i,
                    "P&L (full)": round(pnl_full, 2),
                    "P&L (Greeks)": round(pnl_approx, 2),
                    "Error": round(pnl_full - pnl_approx, 2),
                })

            df_bt = pd.DataFrame(bt_rows)

            fig_bt = go.Figure()
            for col, color in [("P&L (full)", "#42a5f5"), ("P&L (Greeks)", "#ffa726"), ("Error", "#ef5350")]:
                fig_bt.add_trace(go.Scatter(
                    x=df_bt["Date"], y=df_bt[col], name=col,
                    mode="lines", line=dict(width=2, color=color),
                ))
            fig_bt.update_layout(
                height=380, template="plotly_dark",
                margin=dict(l=0, r=0, t=20, b=0),
                legend=dict(orientation="h", y=1.02),
                xaxis_title="Date", yaxis_title="Portfolio P&L (€)",
            )
            st.plotly_chart(fig_bt, use_container_width=True)
            st.dataframe(df_bt, use_container_width=True, hide_index=True)
        else:
            st.info("Historical data unavailable.")
    else:
        st.info("Add positions to the portfolio above to run a backtest.")

# ══════════════════════════════════════════════════════════════════════════════
with tab3:

    st.header("📤 Trading & Execution")
    explain(
        "This tab is a **mock-up of an order ticket and account view** — "
        "the layout is in place, but it is **not yet connected** to IBKR's "
        "order routing or account endpoints, so all values shown here are "
        "placeholders (`--`, `0.00`, empty tables). Sending an order will "
        "currently just show a warning instead of placing a real trade."
    )

    # Account Overview
    st.subheader("💰 Account Overview")
    explain(
        "Will eventually show your **live IBKR account balances**:\n\n"
        "- **Net Liquidation**: total account value (cash + positions)\n"
        "- **Buying Power**: how much you could still spend/trade\n"
        "- **Cash**: uninvested cash balance\n"
        "- **Margin Used**: how much of your buying power is currently "
        "tied up as collateral for open positions\n\n"
        "Currently shows `--` placeholders — not yet wired to IBKR."
    )

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Net Liquidation", "€ --")
    col2.metric("Buying Power", "€ --")
    col3.metric("Cash", "€ --")
    col4.metric("Margin Used", "€ --")

    st.divider()

    # Order Entry
    st.subheader("📝 Order Entry")
    explain(
        "A form to define an order, in the same shape a real broker ticket "
        "would use:\n\n"
        "- **Underlying**: which instrument to trade\n"
        "- **Side**: BUY or SELL\n"
        "- **Quantity**: number of contracts/shares\n"
        "- **Order Type**: MARKET (execute immediately at the current price) "
        "or LIMIT (only execute at your chosen price or better)\n"
        "- **Limit Price**: only shown for LIMIT orders\n\n"
        "Clicking **🚀 Send Order** does **not** place a real order yet — it "
        "just shows a warning, since order routing isn't connected."
    )

    c1, c2, c3, c4 = st.columns(4)

    symbol = c1.selectbox(
        "Underlying",
        [INDEX["symbol"]] if "symbol" in INDEX else [INDEX["name"]]
    )

    side = c2.selectbox(
        "Side",
        ["BUY", "SELL"]
    )

    qty = c3.number_input(
        "Quantity",
        min_value=1,
        value=1
    )

    order_type = c4.selectbox(
        "Order Type",
        ["MARKET", "LIMIT"]
    )

    limit_price = None

    if order_type == "LIMIT":
        limit_price = st.number_input(
            "Limit Price",
            value=float(S_live)
        )

    if st.button("🚀 Send Order"):
        st.warning("Order routing not connected yet.")

    st.divider()

    # Open Orders
    st.subheader("📋 Open Orders")
    explain(
        "Will list any **orders you've placed that haven't fully executed "
        "yet** — e.g. a LIMIT order still waiting for the price to be "
        "reached. Each row would show the order ID, symbol, side, "
        "quantity, type, and current status (e.g. Submitted, Filled, "
        "Cancelled).\n\n"
        "Currently empty — not yet wired to IBKR."
    )

    open_orders = pd.DataFrame(
        columns=[
            "Order ID",
            "Symbol",
            "Side",
            "Qty",
            "Type",
            "Status"
        ]
    )

    st.dataframe(
        open_orders,
        use_container_width=True,
        hide_index=True
    )

    st.divider()

    # Positions
    st.subheader("📊 Positions")
    explain(
        "Will list everything you currently **hold in your account** — "
        "for each position: symbol, quantity, average price you paid, "
        "current market price, and unrealized **PnL** (profit or loss if "
        "you closed it right now).\n\n"
        "Currently empty — not yet wired to IBKR."
    )

    positions = pd.DataFrame(
        columns=[
            "Symbol",
            "Qty",
            "Avg Price",
            "Market Price",
            "PnL"
        ]
    )

    st.dataframe(
        positions,
        use_container_width=True,
        hide_index=True
    )

    st.divider()

    # Risk Preview
    st.subheader("⚠️ Pre-Trade Risk")
    explain(
        "Will show how the order you're about to send would change your "
        "**portfolio's Greeks** (Δ, Γ, ν, θ) — i.e. a 'before you click "
        "send' risk check, so you can see the impact on your overall "
        "exposure before committing.\n\n"
        "Currently shows `0.00` placeholders — not yet wired to a live "
        "portfolio."
    )

    risk_col1, risk_col2, risk_col3, risk_col4 = st.columns(4)

    risk_col1.metric("Projected Δ", "0.00")
    risk_col2.metric("Projected Γ", "0.00")
    risk_col3.metric("Projected ν", "0.00")
    risk_col4.metric("Projected θ", "0.00")

    # ══════════════════════════════════════════════════════════════════════════════
with tab4:

    st.header("🌀 Volatility Surface Analytics")
    explain(
        "A deeper dive into the **implied volatility (IV)** of the options "
        "chain loaded in the **Data** tab (it reuses that data — open "
        "Data first if this tab looks empty).\n\n"
        "Implied volatility is the market's expectation of how much the "
        "underlying will move, *implied* by current option prices. This "
        "tab shows three classic views of it: a full **3D surface** "
        "(strike × maturity), a **smile** (IV across strikes for one "
        "maturity), and a **term structure** (ATM IV across maturities)."
    )

    if "df_options" not in st.session_state:
        spot_now = get_spot(client, INDEX["conid"])
        surface_spot = float(
            spot_now.get("last")
            or spot_now.get("close")
            or 5000
        )

        with st.spinner("Loading option chain for surface analytics..."):
            opt_rows = get_options_table(
                client, INDEX["conid"], INDEX["opt_months"], surface_spot
            )

        if opt_rows:
            st.session_state["df_options"] = fill_missing_iv(
                pd.DataFrame(opt_rows), surface_spot
            )

    if "df_options" not in st.session_state:
        st.warning(
            "Option chain still unavailable. Wait a few seconds, then refresh."
        )
        st.caption(
            f"Debug: spot={surface_spot:,.2f}, "
            f"option months={len(INDEX['opt_months'])}"
        )
        diag_rows = []
        for month in INDEX["opt_months"][:3]:
            strikes = get_strikes(client, INDEX["conid"], month)
            atm_strike = min(strikes, key=lambda k: abs(k - surface_spot)) if strikes else None
            call_conid = (
                get_option_conid(client, INDEX["conid"], month, atm_strike, "C")
                if atm_strike else None
            )
            put_conid = (
                get_option_conid(client, INDEX["conid"], month, atm_strike, "P")
                if atm_strike else None
            )
            diag_rows.append({
                "Maturity": month,
                "Strikes": len(strikes),
                "ATM Strike": atm_strike,
                "ATM Call conid": call_conid,
                "ATM Put conid": put_conid,
            })

        with st.expander("Option chain diagnostics"):
            st.dataframe(pd.DataFrame(diag_rows), use_container_width=True, hide_index=True)
    else:

        spot_now = get_spot(client, INDEX["conid"])
        surface_spot = float(
            spot_now.get("last")
            or spot_now.get("close")
            or 5000
        )

        df_surface = fill_missing_iv(
            st.session_state["df_options"], surface_spot
        )
        st.session_state["df_options"] = df_surface.copy()

        df_surface = df_surface[
            df_surface["IV %"].notna()
        ].copy()

        df_surface, dropped_mats = filter_liquid_maturities(df_surface)
        if dropped_mats:
            st.caption(
                "Excluded (too few live quotes this close to expiry): "
                f"{', '.join(dropped_mats)}"
            )

        if df_surface.empty:
            st.warning("No IV data available.")
            priced_rows = st.session_state["df_options"].apply(
                lambda row: _option_price(row) is not None, axis=1
            ).sum()
            st.caption(
                f"Rows loaded={len(st.session_state['df_options'])}, "
                f"rows with usable option price={priced_rows}. "
                "If usable prices are 0, IBKR is not returning option market data."
            )

        else:

            # --------------------------------------------------
            # 3D Volatility Surface
            # --------------------------------------------------

            st.subheader("🌀 3D Volatility Surface")
            explain(
                "Every option in the chain plotted as a 3D surface: "
                "**Delta Target** on one axis, **Maturity** on the other, "
                "and **implied volatility (IV %)** as the height/colour.\n\n"
                "The y-axis uses the **Delta Target** bucket (-30Δ ... ATM "
                "... +30Δ) instead of raw strike — each maturity lists a "
                "different strike grid, so a raw-strike axis produces a "
                "disjointed surface split into separate strike clusters. "
                "Delta Target is the same 13-point grid for every maturity, "
                "so the surface is continuous.\n\n"
                "If IV were constant, this would be a flat plane. In "
                "reality it usually curves — higher for far OTM deltas "
                "(the 'smile') and changes shape across maturities (the "
                "'term structure'). Drag to rotate, scroll to zoom."
            )

            maturities = sorted(
                df_surface["Maturity"].dropna().unique()
            )

            surface_points = df_surface[
                df_surface["Delta Target"].notna() & df_surface["IV %"].notna()
            ].copy()

            if (
                surface_points["Maturity"].nunique() >= 2
                and surface_points["Delta Target"].nunique() >= 2
            ):
                pivot_surface = surface_points.pivot_table(
                    values="IV %",
                    index="Delta Target",
                    columns="Maturity",
                    aggfunc="mean",
                )
                pivot_surface = pivot_surface.reindex(
                    sorted(pivot_surface.index, key=_delta_sort_key)
                )
                fig_surface = go.Figure(
                    go.Surface(
                        z=pivot_surface.values,
                        x=list(pivot_surface.columns),
                        y=list(pivot_surface.index),
                        colorscale="Viridis",
                        colorbar=dict(title="IV %", thickness=15),
                        hovertemplate=(
                            "Maturity=%{x}<br>"
                            "Delta Target=%{y}<br>"
                            "IV=%{z:.2f}%<extra></extra>"
                        ),
                    )
                )
            else:
                fig_surface = go.Figure(
                    go.Scatter3d(
                        x=surface_points["Maturity"],
                        y=surface_points["Delta Target"],
                        z=surface_points["IV %"],
                        mode="markers",
                        marker=dict(
                            size=5,
                            color=surface_points["IV %"],
                            colorscale="Viridis",
                            colorbar=dict(title="IV %", thickness=15),
                        ),
                        hovertemplate=(
                            "Maturity=%{x}<br>"
                            "Delta Target=%{y}<br>"
                            "IV=%{z:.2f}%<extra></extra>"
                        ),
                    )
                )

            fig_surface.update_layout(
                height=620,
                template="plotly_dark",
                title=f"{INDEX['name']} — Implied Volatility Surface",
                scene=dict(
                    xaxis_title="Maturity",
                    yaxis_title="Delta Target",
                    zaxis_title="IV (%)",
                    zaxis=dict(range=[0, surface_points["IV %"].max()]),
                    camera=dict(eye=dict(x=1.6, y=1.6, z=0.9)),
                ),
                margin=dict(l=0, r=0, t=45, b=0),
            )

            st.plotly_chart(fig_surface, use_container_width=True)

            st.divider()

            # --------------------------------------------------
            # Volatility Smile
            # --------------------------------------------------

            st.subheader("📈 Volatility Smile")
            explain(
                "For **one chosen maturity**, plots implied volatility (IV %) "
                "against **strike**, as separate **Put** and **Call** lines. "
                "The classic shape is a 'smile' (or 'skew') — IV is often "
                "higher for strikes far away from the current spot price "
                "than for at-the-money strikes, reflecting that the market "
                "prices in a higher chance of large moves than a simple "
                "constant-volatility model would predict.\n\n"
                "Around the **ATM strike**, both a Put and a Call quote "
                "exist — by put-call parity their implied vols should be "
                "very close but not always identical, which is why the two "
                "lines may diverge slightly there.\n\n"
                "Use **Select Maturity** to switch between expiries."
            )

            selected_mat = st.selectbox(
                "Select Maturity",
                maturities
            )

            mat_data = df_surface[df_surface["Maturity"] == selected_mat]

            fig_smile = go.Figure()

            for opt_type, color in [("Put", "#ef5350"), ("Call", "#42a5f5")]:
                side = mat_data[mat_data["Type"] == opt_type].sort_values("Strike")
                if not side.empty:
                    fig_smile.add_trace(
                        go.Scatter(
                            x=side["Strike"],
                            y=side["IV %"],
                            mode="lines+markers",
                            name=f"{opt_type} IV",
                            line=dict(color=color),
                        )
                    )

            fig_smile.update_layout(
                height=450,
                xaxis_title="Strike",
                yaxis_title="Implied Volatility (%)",
                template="plotly_dark",
                legend=dict(orientation="h", y=1.02),
            )

            st.plotly_chart(
                fig_smile,
                use_container_width=True
            )

            st.divider()

            # --------------------------------------------------
            # ATM Term Structure
            # --------------------------------------------------

            st.subheader("⏳ ATM Term Structure")
            explain(
                "For each maturity, takes the strike closest to the current "
                "spot (the **at-the-money / ATM** option) and averages the "
                "implied volatility of its **Put and Call** quotes, then "
                "plots that value. This is the **term structure of "
                "volatility** — it shows whether the market expects more "
                "turbulence in the near term or the long term.\n\n"
                "Averaging the put and call at each maturity gives two "
                "data points instead of one, so a single missing quote "
                "doesn't create a gap in the line.\n\n"
                "An upward-sloping line means longer-dated options are "
                "pricing in more uncertainty than near-term ones, and vice "
                "versa."
            )

            atm_points = []

            for maturity in maturities:

                temp = df_surface[
                    df_surface["Maturity"] == maturity
                ]

                if temp.empty:
                    continue

                nearest_strike = temp.loc[
                    (temp["Strike"] - surface_spot).abs().idxmin(), "Strike"
                ]

                atm_iv = temp.loc[temp["Strike"] == nearest_strike, "IV %"].mean()

                if pd.notna(atm_iv):
                    atm_points.append({
                        "Maturity": maturity,
                        "ATM IV": atm_iv
                    })

            df_term = pd.DataFrame(atm_points)

            if not df_term.empty:

                fig_term = go.Figure()

                fig_term.add_trace(
                    go.Scatter(
                        x=df_term["Maturity"],
                        y=df_term["ATM IV"],
                        mode="lines+markers",
                        name="ATM IV"
                    )
                )

                fig_term.update_layout(
                    height=450,
                    xaxis_title="Maturity",
                    yaxis_title="ATM IV (%)",
                    template="plotly_dark"
                )

                st.plotly_chart(
                    fig_term,
                    use_container_width=True
                )

            st.divider()

            # --------------------------------------------------
            # Surface Statistics
            # --------------------------------------------------

            st.subheader("📊 Surface Statistics")
            explain(
                "A quick numerical summary of the option chain used for the "
                "surface above:\n\n"
                "- **Quotes**: number of option contracts with usable IV "
                "data\n"
                "- **Maturities**: how many distinct expiry dates are "
                "covered\n"
                "- **Average IV / Max IV**: the mean and highest implied "
                "volatility across all those quotes\n\n"
                "The table below lists every individual quote that went "
                "into the surface, smile, and term structure charts."
            )

            c1, c2, c3, c4 = st.columns(4)

            c1.metric(
                "Quotes",
                len(df_surface)
            )

            c2.metric(
                "Maturities",
                df_surface["Maturity"].nunique()
            )

            c3.metric(
                "Average IV",
                f"{df_surface['IV %'].mean():.2f}%"
            )

            c4.metric(
                "Max IV",
                f"{df_surface['IV %'].max():.2f}%"
            )

            st.dataframe(
                df_surface[
                    [
                        "Maturity",
                        "Strike",
                        "Type",
                        "IV %",
                        "IV Source",
                    ]
                ],
                use_container_width=True,
                hide_index=True
            )
