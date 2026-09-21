from __future__ import annotations

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from risk_engine import (
    calculate_bond_metrics,
    calculate_portfolio_metrics,
    lookup_isin_to_asset,
    simulate_compound_growth,
    simulate_portfolio_scenarios,
)


st.set_page_config(
    page_title="RiskEngine",
    page_icon="📈",
    layout="wide",
    menu_items={"Get help": None, "Report a bug": None, "About": None},
)


@st.cache_data(ttl="15m", max_entries=8, show_spinner=False)
def run_cached_simulation(
    assets: pd.DataFrame, scenarios: int, horizon_days: int, seed: int
) -> dict:
    """Cache identical simulations so reruns do not repeat the same calculation."""
    return simulate_portfolio_scenarios(
        assets, scenarios=scenarios, horizon_days=horizon_days, seed=seed
    )


ASSET_COLUMNS = {
    "name": "Asset",
    "ticker": "Ticker",
    "value": "Valore (€)",
    "expected_return": "Rendimento atteso (%)",
    "volatility": "Volatilità (%)",
    "beta": "Beta",
    "narrative_exposure": "Esposizione tema (%)",
}


if "assets" not in st.session_state:
    st.session_state.assets = pd.DataFrame(
        columns=["name", "ticker", "value", "expected_return", "volatility", "beta", "narrative_exposure"]
    )


st.title("RiskEngine")
st.caption("Analisi del rischio di portafoglio con dati storici reali e simulazioni quantitative")

with st.sidebar:
    st.header("Impostazioni")
    risk_free_rate = st.number_input(
        "Tasso risk-free (%)", min_value=0.0, max_value=20.0, value=2.5, step=0.1
    ) / 100.0
    avg_correlation = st.slider("Correlazione media tra asset", 0.0, 1.0, 0.35, 0.05)
    st.caption("Il tema dell'app si gestisce dal menu ⋮ di Streamlit.")
    with st.expander("Scenario narrativo", expanded=False):
        narrative_enabled = st.checkbox("Includi scenario narrativo", value=False)
        narrative_scenario = None
        if narrative_enabled:
            narrative_probability = st.slider("Probabilità stimata", 0.0, 1.0, 0.25, 0.05)
            narrative_severity = st.slider(
                "Perdita se lo scenario si verifica (%)", -100.0, 0.0, -50.0, 5.0
            )
            narrative_scenario = {
                "probability": narrative_probability,
                "severity": narrative_severity / 100.0,
            }


with st.container(border=True):
    st.subheader("Aggiungi ETF o obbligazione")
    st.caption("Cerca uno strumento europeo inserendo il suo codice ISIN.")
    with st.form("isin_form", clear_on_submit=True):
        isin_input = st.text_input("Codice ISIN", label_visibility="visible")
        isin_submitted = st.form_submit_button("Cerca e aggiungi", type="primary")

    if isin_submitted:
        if not isin_input.strip():
            st.warning("Inserisci un codice ISIN.")
        else:
            match = lookup_isin_to_asset(isin_input)
            if not match:
                st.warning("Nessun risultato trovato. Prova un ISIN europeo valido.")
            else:
                current_assets = st.session_state.assets.copy()
                current_assets.loc[len(current_assets)] = {
                    "name": match["name"],
                    "ticker": match["ticker"],
                    "value": match["value"],
                    "expected_return": match["expected_return"] * 100,
                    "volatility": match["volatility"] * 100,
                    "beta": match["beta"],
                    "narrative_exposure": 0.0,
                }
                st.session_state.assets = current_assets
                st.success(f"Aggiunto {match['name']} ({match['ticker']}).")


edited_assets = st.data_editor(
    st.session_state.assets,
    column_config={
        "name": st.column_config.TextColumn("Asset", width="large"),
        "ticker": st.column_config.TextColumn("Ticker", width="medium"),
        "value": st.column_config.NumberColumn("Valore (€)", min_value=0, format="€ %d"),
        "expected_return": st.column_config.NumberColumn(
            "Rendimento atteso (%)", min_value=-100.0, max_value=100.0, step=0.1
        ),
        "volatility": st.column_config.NumberColumn(
            "Volatilità (%)", min_value=0.0, max_value=100.0, step=0.1
        ),
        "beta": st.column_config.NumberColumn("Beta", min_value=0.0, max_value=5.0, step=0.1),
        "narrative_exposure": st.column_config.NumberColumn(
            "Esposizione tema (%)", min_value=0.0, max_value=100.0, step=5.0
        ),
    },
    num_rows="dynamic",
    hide_index=True,
    width="stretch",
)
st.session_state.assets = edited_assets


try:
    portfolio = calculate_portfolio_metrics(
        st.session_state.assets,
        risk_free_rate=risk_free_rate,
        avg_correlation=avg_correlation,
        narrative_scenario=narrative_scenario,
    )
except ValueError as exc:
    st.warning(str(exc))
    st.stop()


summary = portfolio
risk_calculation_df = summary["asset_risk_contribution"].copy()
risk_df = risk_calculation_df.copy()
risk_df["ticker"] = risk_df["name"].map(
    st.session_state.assets.set_index("name")["ticker"].to_dict()
).fillna("")
risk_df["weight"] = (risk_df["weight"] * 100).round(2)
risk_df["risk_contribution_pct"] = risk_df["risk_contribution_pct"].round(2)
risk_df["expected_return"] = (risk_df["expected_return"] * 100).round(2)
risk_df["volatility"] = (risk_df["volatility"] * 100).round(2)


def render_kpis() -> None:
    with st.container(horizontal=True):
        st.metric("Valore totale", f"€ {summary['portfolio_value']:,.0f}", border=True)
        st.metric("Rendimento atteso", f"{summary['expected_return'] * 100:.2f}%", border=True)
        st.metric("Volatilità", f"{summary['volatility'] * 100:.2f}%", border=True)
        st.metric("Sharpe", f"{summary['sharpe']:.2f}", border=True)


def render_risk_advice() -> None:
    risk_text = (
        f"Livello di rischio: {summary['risk_level']} | "
        f"Score: {summary['risk_score']:.1f}/100 | Beta: {summary['beta']:.2f}"
    )
    if summary["risk_score"] < 35:
        st.success(risk_text)
    elif summary["risk_score"] < 60:
        st.info(risk_text)
    elif summary["risk_score"] < 80:
        st.warning(risk_text)
    else:
        st.error(risk_text)

    advice = {
        "Basso": "Volatilità contenuta e buona diversificazione riducono la probabilità di perdite estreme.",
        "Moderato": "Il portafoglio può oscillare nel medio termine, ma il livello di rischio resta generalmente gestibile.",
        "Elevato": "La sensibilità ai movimenti di mercato può produrre oscillazioni e perdite più marcate.",
    }
    st.caption(advice.get(summary["risk_level"], "La concentrazione e la volatilità rendono il portafoglio vulnerabile agli shock di mercato."))


def render_risk_formula() -> None:
    if risk_calculation_df.empty:
        st.info("Inserisci almeno un asset per visualizzare il calcolo.")
        return

    weights = risk_calculation_df["weight"].to_numpy(dtype=float)
    volatilities = risk_calculation_df["volatility"].to_numpy(dtype=float)
    variance = sum(
        weights[i] * weights[j] * volatilities[i] * volatilities[j]
        * (1.0 if i == j else avg_correlation)
        for i in range(len(weights))
        for j in range(len(weights))
    )

    st.markdown("**Formula utilizzata**")
    st.latex(r"\sigma_p = \sqrt{\sum_i\sum_j w_i w_j \sigma_i \sigma_j \rho_{ij}}")
    st.caption("La volatilità combina peso, volatilità di ogni asset e correlazione media.")
    formula_table = risk_calculation_df[["name", "weight", "volatility"]].copy()
    formula_table["weight"] = (formula_table["weight"] * 100).round(2).map(lambda value: f"{value:.2f}%")
    formula_table["volatility"] = (formula_table["volatility"] * 100).round(2).map(lambda value: f"{value:.2f}%")
    st.dataframe(
        formula_table.rename(columns={"name": "Asset", "weight": "Peso", "volatility": "Volatilità"}),
        hide_index=True,
        width="stretch",
    )
    formula_cols = st.columns(3)
    formula_cols[0].metric("Varianza", f"{variance:.2f}")
    formula_cols[1].metric("Volatilità calcolata", f"{np.sqrt(max(variance, 0.0)) * 100:.2f}%")
    formula_cols[2].metric("Correlazione media", f"{avg_correlation:.2f}")
    st.latex(r"\text{Score} = \min(100,\max(0, 1.6 \times \sigma_p(\%) + 15 \times \beta_p))")
    st.caption(
        f"Score = 1,6 × {summary['volatility'] * 100:.2f} + 15 × {summary['beta']:.2f} "
        f"= {summary['risk_score']:.2f}/100. Sharpe = {summary['sharpe']:.2f}."
    )


dashboard_tab, montecarlo_tab, risk_tab = st.tabs(
    ["Dashboard", "Simulazione Monte Carlo", "Rischio del portafoglio"]
)

with dashboard_tab:
    render_kpis()
    st.subheader("Portafoglio")
    if risk_df.empty:
        st.info("Il portafoglio è vuoto. Aggiungi un ETF, un'obbligazione tramite ISIN o inserisci un asset nella tabella.")
    else:
        chart_col, table_col = st.columns([1, 1.4])
        with chart_col:
            with st.container(border=True):
                st.markdown("**Allocazione per asset**")
                allocation = st.session_state.assets[["name", "value"]].copy()
                allocation["value"] = pd.to_numeric(allocation["value"], errors="coerce").fillna(0.0)
                allocation["value"] = allocation["value"].round(2)
                allocation = allocation[allocation["value"] > 0].rename(
                    columns={"name": "asset", "value": "value_eur"}
                )
                pie = alt.Chart(allocation).mark_arc(innerRadius=105).encode(
                    theta=alt.Theta("value_eur:Q", title="Valore"),
                    color=alt.Color(
                        "asset:N",
                        legend=alt.Legend(title=None, labelLimit=0, columns=1),
                    ),
                    tooltip=[
                        alt.Tooltip("asset:N", title="Asset"),
                        alt.Tooltip("value_eur:Q", title="Valore (€)", format=",.2f"),
                    ],
                ).properties(height=360)
                st.altair_chart(pie, width="stretch", theme=None)
        with table_col:
            with st.container(border=True):
                st.markdown("**Asset nel portafoglio**")
                portfolio_table = risk_df[["name", "value", "weight", "ticker"]].rename(
                    columns={
                        "name": "Asset",
                        "value": "Valore (€)",
                        "weight": "Allocazione (%)",
                        "ticker": "Ticker",
                    }
                )
                st.dataframe(portfolio_table, hide_index=True, width="stretch")

with montecarlo_tab:
    st.subheader("Simulazione Monte Carlo")
    st.caption("Genera scenari annuali usando rendimenti storici giornalieri, quando disponibili.")
    scenario_count = st.slider(
        "Numero di scenari",
        min_value=500,
        max_value=10000,
        value=5000,
        step=500,
        help="Un numero più basso è più veloce; un numero più alto rende la stima più stabile.",
    )
    if st.button(f"Simula {scenario_count:,} scenari", type="primary"):
        with st.status("Calcolo degli scenari in corso...", expanded=False) as status:
            try:
                simulation = run_cached_simulation(
                    st.session_state.assets, scenarios=scenario_count, horizon_days=252, seed=42
                )
                status.update(label="Simulazione completata", state="complete")
            except Exception as exc:  # pragma: no cover - runtime only
                status.update(label="Simulazione non riuscita", state="error")
                st.error(f"Impossibile generare la simulazione storica: {exc}")
                simulation = None

        if simulation is not None:
            sim_cols = st.columns(4)
            sim_cols[0].metric("Rendimento atteso", f"{simulation['expected_return'] * 100:.2f}%")
            sim_cols[1].metric("P5", f"{simulation['p05'] * 100:.2f}%")
            sim_cols[2].metric("P95", f"{simulation['p95'] * 100:.2f}%")
            sim_cols[3].metric("Probabilità di perdita", f"{simulation['probability_loss'] * 100:.2f}%")
            st.caption(simulation["historical_source"])
            distribution = pd.DataFrame(
                {"Rendimento totale": simulation["portfolio_return_distribution"]}
            )
            histogram = alt.Chart(distribution).mark_bar().encode(
                x=alt.X(
                    "Rendimento totale:Q",
                    bin=alt.Bin(maxbins=30),
                    title="Rendimento totale",
                    axis=alt.Axis(format=".2f"),
                ),
                y=alt.Y("count():Q", title="Occorrenze"),
                tooltip=[
                    alt.Tooltip("Rendimento totale:Q", title="Rendimento", format=".2f"),
                    alt.Tooltip("count():Q", title="Occorrenze", format=".2f"),
                ],
            ).properties(height=360)
            st.altair_chart(histogram, width="stretch")

with risk_tab:
    render_kpis()
    render_risk_formula()
    st.subheader("Profilo e consigli")
    render_risk_advice()

    if not risk_df.empty:
        st.subheader("Contributo al rischio per asset")
        risk_table = risk_df[
            ["name", "value", "weight", "expected_return", "volatility", "beta", "risk_contribution_pct"]
        ].rename(
            columns={
                "name": "Asset",
                "value": "Valore (€)",
                "weight": "Allocazione (%)",
                "expected_return": "Rendimento atteso (%)",
                "volatility": "Volatilità (%)",
                "beta": "Beta",
                "risk_contribution_pct": "Contributo al rischio (%)",
            }
        )
        st.dataframe(risk_table, hide_index=True, width="stretch")
        risk_chart = alt.Chart(
            risk_df.rename(columns={"name": "Asset", "risk_contribution_pct": "Contributo al rischio (%)"})
        ).mark_bar().encode(
            x=alt.X("Asset:N", sort="-y", title="Asset"),
            y=alt.Y(
                "Contributo al rischio (%):Q",
                title="Contributo al rischio (%)",
                axis=alt.Axis(format=".2f"),
            ),
            color=alt.Color("Asset:N", legend=None),
            tooltip=[
                "Asset:N",
                alt.Tooltip("Contributo al rischio (%):Q", format=".2f"),
            ],
        ).properties(height=320)
        st.altair_chart(risk_chart, width="stretch")

    with st.expander("Scenario narrativo", expanded=False):
        st.caption("I parametri dello scenario narrativo sono disponibili nella barra laterale.")
        if portfolio.get("narrative_risk") is not None:
            nr = portfolio["narrative_risk"]
            st.info(
                f"Esposizione complessiva: {nr['portfolio_exposure'] * 100:.1f}% | "
                f"Impatto stimato: {nr['stressed_loss_if_realized'] * 100:.1f}%"
            )

    with st.expander("Analisi obbligazioni", expanded=False):
        bond_col1, bond_col2, bond_col3 = st.columns(3)
        with bond_col1:
            bond_face_value = st.number_input("Valore nominale (€)", min_value=100.0, value=1000.0, step=10.0)
            bond_coupon = st.number_input("Cedola annua (%)", min_value=0.0, max_value=30.0, value=5.0, step=0.1) / 100.0
        with bond_col2:
            bond_years = st.number_input("Anni alla scadenza", min_value=0.5, value=5.0, step=0.5)
            bond_market_price = st.number_input("Prezzo di mercato (€)", min_value=0.0, value=950.0, step=10.0)
        with bond_col3:
            bond_frequency = st.selectbox("Pagamento cedole", [1, 2, 4, 12], index=1)
            bond_annual_yield = st.number_input("YTM desiderato (%)", min_value=0.0, max_value=30.0, value=0.0, step=0.1) / 100.0
        bond_metrics = calculate_bond_metrics(
            face_value=bond_face_value,
            coupon_rate=bond_coupon,
            years_to_maturity=bond_years,
            market_price=bond_market_price,
            annual_yield=bond_annual_yield if bond_annual_yield > 0 else None,
            frequency=bond_frequency,
        )
        st.dataframe(
            pd.DataFrame([{
                "YTM (%)": bond_metrics["yield_to_maturity"] * 100,
                "Duration Macaulay": bond_metrics["macaulay_duration_years"],
                "Duration modificata": bond_metrics["modified_duration_years"],
                "Convessità": bond_metrics["convexity"],
                "Prezzo teorico": bond_metrics["price_from_yield"],
            }]),
            hide_index=True,
            width="stretch",
        )

    with st.expander("Crescita composta", expanded=False):
        compound_col1, compound_col2, compound_col3 = st.columns(3)
        with compound_col1:
            sim_principal = st.number_input("Capitale iniziale (€)", min_value=0.0, value=10000.0, step=500.0)
            sim_annual_rate = st.number_input("Rendimento annuo (%)", -50.0, 50.0, 6.0, 0.5) / 100.0
        with compound_col2:
            sim_years = st.number_input("Anni", min_value=1.0, value=10.0, step=1.0)
            sim_contribution = st.number_input("Contributo annuale (€)", min_value=0.0, value=1200.0, step=100.0)
        with compound_col3:
            sim_inflation = st.number_input("Inflazione (%)", 0.0, 20.0, 2.0, 0.1) / 100.0
            sim_tax = st.number_input("Aliquota fiscale (%)", 0.0, 60.0, 23.0, 1.0) / 100.0
        compound_result = simulate_compound_growth(
            principal=sim_principal,
            annual_rate=sim_annual_rate,
            years=sim_years,
            contribution_per_year=sim_contribution,
            contribution_frequency="annual",
            inflation_rate=sim_inflation,
            tax_rate=sim_tax,
            compounding_periods=12,
        )
        result_cols = st.columns(4)
        result_cols[0].metric("Valore nominale", f"€ {compound_result['final_value_nominal']:,.0f}")
        result_cols[1].metric("Dopo tasse", f"€ {compound_result['after_tax_value']:,.0f}")
        result_cols[2].metric("Valore reale", f"€ {compound_result['real_value_after_inflation']:,.0f}")
        result_cols[3].metric("Rendimento reale", f"{compound_result['inflation_adjusted_rate'] * 100:.2f}%")
        annual_df = pd.DataFrame(compound_result["yearly_history"])
        if not annual_df.empty:
            annual_chart_data = annual_df.melt(
                id_vars=["year"],
                value_vars=["nominal_value", "real_value_after_inflation"],
                var_name="serie",
                value_name="valore",
            )
            annual_chart_data["valore"] = annual_chart_data["valore"].round(2)
            annual_chart_data["serie"] = annual_chart_data["serie"].map(
                {
                    "nominal_value": "Valore nominale",
                    "real_value_after_inflation": "Valore reale dopo inflazione",
                }
            )
            annual_chart = alt.Chart(annual_chart_data).mark_line(point=True, strokeWidth=2).encode(
                x=alt.X("year:Q", title="Anno", axis=alt.Axis(format="d")),
                y=alt.Y("valore:Q", title="Valore (€)", axis=alt.Axis(format=".2f")),
                color=alt.Color("serie:N", title=None),
                tooltip=[
                    alt.Tooltip("year:Q", title="Anno", format="d"),
                    alt.Tooltip("serie:N", title="Serie"),
                    alt.Tooltip("valore:Q", title="Valore (€)", format=".2f"),
                ],
            ).properties(height=320)
            st.altair_chart(annual_chart, width="stretch")
