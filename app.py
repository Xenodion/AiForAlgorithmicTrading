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
)
from src.analytics.pricer import black_scholes, greeks, scenario_grid, implied_volatility

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


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

# ── Auto-refresh every 30 s ────────────────────────────────────────────────────
st_autorefresh(interval=30_000, key="autorefresh")

# ── Header ─────────────────────────────────────────────────────────────────────
st.title("📈 Volatility Infrastructure Platform")
st.caption(
    f"**{INDEX['name']}** · conid {INDEX['conid']} · "
    f"{len(INDEX['opt_months'])} option months · "
    f"{len(COMPONENTS)} components resolved"
)

tab1, tab2, tab3, tab4 = st.tabs(
    ["📊 Données", "⚠️ Risques", "📤 Ordres", "🌀 Surface"]
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
    with st.spinner("Loading futures..."):
        fut_rows = get_futures_prices(client, INDEX["conid"], INDEX["fut_months"])

    if fut_rows:
        df_fut = pd.DataFrame(fut_rows)
        for col in ["Last", "Bid", "Ask"]:
            df_fut[col] = df_fut[col].apply(lambda v: f"{v:,.2f}" if v else "—")
        st.dataframe(df_fut, use_container_width=True, hide_index=True)
    else:
        st.info("Futures data unavailable — retrying on next refresh.")

    st.divider()

    # ── Options chain ──────────────────────────────────────────────────────────
    st.subheader("Options Chain — -30Δ / ATM / +30Δ")
    spot_price = float(last or close or 0)

    with st.spinner("Loading options (may take up to 60 s on first load)..."):
        opt_rows = get_options_table(
            client, INDEX["conid"], INDEX["opt_months"], spot_price
        )

    if opt_rows:
        df_opt = pd.DataFrame(opt_rows)
        df_opt = fill_missing_iv(df_opt, spot_price)

        st.session_state["df_options"] = df_opt

        # Add € columns next to each Greek
        for greek in ["Delta", "Gamma", "Vega", "Theta"]:
            df_opt[f"{greek} (€)"] = df_opt[greek].apply(
                lambda v: round(v * notional, 4) if v is not None else None
            )

        col_order = [
            "Maturity", "Strike", "Type",
            "Bid", "Ask", "Last", "IV %", "IV Source",
            "Delta", "Delta (€)",
            "Gamma", "Gamma (€)",
            "Vega",  "Vega (€)",
            "Theta", "Theta (€)",
        ]
        st.dataframe(
            df_opt[[c for c in col_order if c in df_opt.columns]],
            use_container_width=True,
            hide_index=True,
        )

        # ── Vol surface ────────────────────────────────────────────────────────
        st.subheader("Volatility Surface")
        surf = df_opt[df_opt["IV %"].notna() & df_opt["Strike"].notna()].copy()

        if not surf.empty:
            pivot = surf.pivot_table(
                values="IV %", index="Strike", columns="Maturity", aggfunc="mean"
            )
            fig = go.Figure(go.Surface(
                z=pivot.values,
                x=list(pivot.columns),
                y=list(pivot.index),
                colorscale="Viridis",
                colorbar=dict(title="IV %", thickness=15),
            ))
            fig.update_layout(
                height=520,
                title=f"{INDEX['name']} — Implied Volatility Surface",
                scene=dict(
                    xaxis_title="Maturity",
                    yaxis_title="Strike",
                    zaxis_title="IV (%)",
                ),
                margin=dict(l=0, r=0, t=40, b=0),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Vol surface requires IV % data — loading...")

    else:
        st.info("Options chain loading — this takes ~60 s on first load.")

    st.divider()

    # ── Component stocks ───────────────────────────────────────────────────────
    st.subheader(f"Eurostoxx 50 Components — {len(COMPONENTS)} stocks")
    with st.spinner("Loading component prices..."):
        comp_rows = get_component_spots(client, COMPONENTS)

    if comp_rows:
        df_comp = pd.DataFrame(comp_rows)
        for col in ["Last", "Bid", "Ask"]:
            df_comp[col] = df_comp[col].apply(lambda v: f"{v:,.2f}" if v else "—")
        st.dataframe(df_comp, use_container_width=True, hide_index=True)
    else:
        st.info("Component data loading...")

# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.header("⚠️ Risques")

    spot_now = get_spot(client, INDEX["conid"])
    S_live   = float(spot_now.get("last") or spot_now.get("close") or 5000)

    # ── Black-Scholes Pricer ───────────────────────────────────────────────────
    st.subheader("🧮 Black-Scholes Pricer")
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

    # Pivot: rows = spot shock, columns = vol shock, values = P&L (full)
    pivot = df_scen.pivot_table(
        values="P&L (full)", index="Spot shock", columns="Vol shock", aggfunc="sum"
    )
    st.markdown("**P&L (full repricing, €)**")
    st.dataframe(
        pivot.style.background_gradient(cmap="RdYlGn", axis=None),
        use_container_width=True,
    )

    st.markdown("**Full scenario table**")
    st.dataframe(df_scen, use_container_width=True, hide_index=True)

    st.divider()

    # ── Portfolio Builder ──────────────────────────────────────────────────────
    st.subheader("📋 Portfolio Builder")
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

# ══════════════════════════════════════════════════════════════════════════════
with tab3:

    st.header("📤 Trading & Execution")

    # Account Overview
    st.subheader("💰 Account Overview")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Net Liquidation", "€ --")
    col2.metric("Buying Power", "€ --")
    col3.metric("Cash", "€ --")
    col4.metric("Margin Used", "€ --")

    st.divider()

    # Order Entry
    st.subheader("📝 Order Entry")

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

    risk_col1, risk_col2, risk_col3, risk_col4 = st.columns(4)

    risk_col1.metric("Projected Δ", "0.00")
    risk_col2.metric("Projected Γ", "0.00")
    risk_col3.metric("Projected ν", "0.00")
    risk_col4.metric("Projected θ", "0.00")

    # ══════════════════════════════════════════════════════════════════════════════
with tab4:

    st.header("🌀 Volatility Surface Analytics")

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

            maturities = sorted(
                df_surface["Maturity"].dropna().unique()
            )

            surface_points = df_surface[
                df_surface["Strike"].notna() & df_surface["IV %"].notna()
            ].copy()

            if (
                surface_points["Maturity"].nunique() >= 2
                and surface_points["Strike"].nunique() >= 2
            ):
                pivot_surface = surface_points.pivot_table(
                    values="IV %",
                    index="Strike",
                    columns="Maturity",
                    aggfunc="mean",
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
                            "Strike=%{y}<br>"
                            "IV=%{z:.2f}%<extra></extra>"
                        ),
                    )
                )
            else:
                fig_surface = go.Figure(
                    go.Scatter3d(
                        x=surface_points["Maturity"],
                        y=surface_points["Strike"],
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
                            "Strike=%{y}<br>"
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
                    yaxis_title="Strike",
                    zaxis_title="IV (%)",
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

            selected_mat = st.selectbox(
                "Select Maturity",
                maturities
            )

            smile = (
                df_surface[
                    df_surface["Maturity"] == selected_mat
                ]
                .sort_values("Strike")
            )

            fig_smile = go.Figure()

            fig_smile.add_trace(
                go.Scatter(
                    x=smile["Strike"],
                    y=smile["IV %"],
                    mode="lines+markers",
                    name="IV Smile"
                )
            )

            fig_smile.update_layout(
                height=450,
                xaxis_title="Strike",
                yaxis_title="Implied Volatility (%)",
                template="plotly_dark"
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

            atm_points = []

            for maturity in maturities:

                temp = df_surface[
                    df_surface["Maturity"] == maturity
                ]

                if temp.empty:
                    continue

                idx = (
                    temp["Strike"] - surface_spot
                ).abs().idxmin()

                atm_row = temp.loc[idx]

                atm_points.append({
                    "Maturity": maturity,
                    "ATM IV": atm_row["IV %"]
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
