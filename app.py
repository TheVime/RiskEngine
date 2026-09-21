from __future__ import annotations

"""
CHANGELOG
---------
v1.1 - 2026-09-21
    - Aggiunta la colonna "narrative_exposure" alla tabella asset e una
      sezione "Scenario narrativo" per configurare probabilita' e severita'
      di un rischio tematico (es. bolla AI) non presente nello storico
      prezzi. Il risultato viene passato a calculate_portfolio_metrics()
      tramite il nuovo parametro narrative_scenario.
"""

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


st.set_page_config(page_title="RiskEngine", page_icon="📈", layout="wide")


DEFAULT_ASSETS = [
    {"name": "ETF MSCI World", "ticker": "SPY", "value": 20000, "expected_return": 8.0, "volatility": 12.0, "beta": 1.0, "narrative_exposure": 10.0},
    {"name": "Obbligazioni Governative", "ticker": "BND", "value": 15000, "expected_return": 3.5, "volatility": 5.0, "beta": 0.3, "narrative_exposure": 0.0},
    {"name": "Tech Growth", "ticker": "QQQ", "value": 12000, "expected_return": 13.5, "volatility": 22.0, "beta": 1.4, "narrative_exposure": 70.0},
    {"name": "Real Estate", "ticker": "VNQ", "value": 9000, "expected_return": 7.2, "volatility": 10.5, "beta": 0.9, "narrative_exposure": 0.0},
]


if "assets" not in st.session_state:
    st.session_state.assets = pd.DataFrame(DEFAULT_ASSETS)

st.title("RiskEngine")
st.caption("Analisi del rischio di portafoglio con simulazione basata su dati storici reali")

with st.sidebar:
    st.header("Configurazione")
    theme_choice = st.selectbox(
        "Tema",
        options=["Sistema", "Chiaro", "Scuro"],
        index=2,
        help="Scegli se seguire il tema del sistema operativo oppure usare sempre chiaro o scuro.",
    )
    risk_free_rate = st.number_input("Tasso risk-free (%)", min_value=0.0, max_value=20.0, value=2.5, step=0.1) / 100.0
    avg_correlation = st.slider("Correlazione media tra asset", 0.0, 1.0, 0.35, 0.05)
    st.markdown("Dati storici: Yahoo Finance / returns giornalieri storici")

    st.subheader("Aggiungi asset via ISIN")
    isin_input = st.text_input("ISIN", placeholder="ad esempio IE00B4L5Y983")
    if st.button("Cerca e aggiungi", use_container_width=True):
        if not isin_input.strip():
            st.warning("Inserisci un ISIN valido.")
        else:
            match = lookup_isin_to_asset(isin_input)
            if not match:
                st.warning("Nessun risultato trovato per questo ISIN. Prova un ticker o un ISIN europeo valido.")
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
                st.success(f"Aggiunto {match['name']} ({match['ticker']}) dal lookup ISIN.")

if theme_choice == "Scuro":
    theme_css = """
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
            background: #0b1220;
            color: #e5e7eb;
            color-scheme: dark;
        }
        [data-testid="stSidebar"] { background: #111827; }
        [data-testid="stHeader"] { background: rgba(11, 18, 32, 0.96); }
        .stDataFrame, [data-testid="stDataFrame"], [data-testid="stTable"],
        [data-testid="stVegaLiteChart"], [data-testid="stArrowVegaLiteChart"],
        [data-testid="stDeckGlJsonChart"], [data-testid="stGraph"] {
            background: #111827 !important;
            border-radius: 0.75rem;
            color: #e5e7eb !important;
        }
        [data-testid="stDataFrame"] [role="grid"],
        [data-testid="stDataFrame"] [role="gridcell"],
        [data-testid="stDataFrame"] [role="columnheader"] {
            background: #111827 !important;
            color: #e5e7eb !important;
        }
        [data-testid="stVegaLiteChart"] svg,
        [data-testid="stArrowVegaLiteChart"] svg,
        [data-testid="stGraph"] svg,
        .stChart svg,
        .stVegaLiteChart svg {
            background: #111827 !important;
        }
        [data-testid="stVegaLiteChart"] svg text,
        [data-testid="stArrowVegaLiteChart"] svg text,
        [data-testid="stGraph"] svg text,
        .stChart svg text,
        .stVegaLiteChart svg text {
            fill: #e5e7eb !important;
            stroke: #e5e7eb !important;
            color: #e5e7eb !important;
        }
    """
elif theme_choice == "Sistema":
    theme_css = """
        @media (prefers-color-scheme: dark) {
            .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
                background: #0b1220;
                color: #e5e7eb;
                color-scheme: dark;
            }
            [data-testid="stSidebar"] { background: #111827; }
            [data-testid="stHeader"] { background: rgba(11, 18, 32, 0.96); }
            .stDataFrame, [data-testid="stDataFrame"], [data-testid="stTable"],
            [data-testid="stVegaLiteChart"], [data-testid="stArrowVegaLiteChart"],
            [data-testid="stDeckGlJsonChart"], [data-testid="stGraph"] {
                background: #111827 !important;
                border-radius: 0.75rem;
                color: #e5e7eb !important;
            }
            [data-testid="stVegaLiteChart"] svg,
            [data-testid="stArrowVegaLiteChart"] svg,
            [data-testid="stGraph"] svg,
            .stChart svg,
            .stVegaLiteChart svg {
                background: #111827 !important;
            }
            [data-testid="stVegaLiteChart"] svg text,
            [data-testid="stArrowVegaLiteChart"] svg text,
            [data-testid="stGraph"] svg text,
            .stChart svg text,
            .stVegaLiteChart svg text {
                fill: #e5e7eb !important;
                stroke: #e5e7eb !important;
                color: #e5e7eb !important;
            }
        }
        @media (prefers-color-scheme: light) {
            .stApp { background: #f5f7fb; }
            [data-testid="stSidebar"] { background: #eaf1fb; }
            .stDataFrame, [data-testid="stDataFrame"], [data-testid="stTable"],
            [data-testid="stVegaLiteChart"], [data-testid="stArrowVegaLiteChart"],
            [data-testid="stDeckGlJsonChart"], [data-testid="stGraph"] {
                background: #ffffff !important;
                border-radius: 0.75rem;
            }
        }
    """
else:
    theme_css = """
        .stApp { background: #f5f7fb; }
        [data-testid="stSidebar"] { background: #eaf1fb; }
        .stDataFrame, [data-testid="stDataFrame"], [data-testid="stTable"],
        [data-testid="stVegaLiteChart"], [data-testid="stArrowVegaLiteChart"],
        [data-testid="stDeckGlJsonChart"], [data-testid="stGraph"] {
            background: #ffffff !important;
            border-radius: 0.75rem;
        }
    """

st.markdown(f"<style>{theme_css}</style>", unsafe_allow_html=True)

edited_assets = st.data_editor(
    st.session_state.assets,
    column_config={
        "name": st.column_config.TextColumn("Asset", width="large"),
        "ticker": st.column_config.TextColumn("Ticker", width="medium"),
        "value": st.column_config.NumberColumn("Valore (€)", min_value=0, format="€ %d"),
        "expected_return": st.column_config.NumberColumn("Rendimento atteso (%)", min_value=-100.0, max_value=100.0, step=0.1),
        "volatility": st.column_config.NumberColumn("Volatilità (%)", min_value=0.0, max_value=100.0, step=0.1),
        "beta": st.column_config.NumberColumn("Beta", min_value=0.0, max_value=5.0, step=0.1),
        "narrative_exposure": st.column_config.NumberColumn(
            "Esposizione tema (%)",
            min_value=0.0,
            max_value=100.0,
            step=5.0,
            help="Quanto questo asset è esposto al tema/scenario narrativo definito sotto (es. bolla AI). 0% = nessuna esposizione, 100% = esposizione totale.",
        ),
    },
    num_rows="dynamic",
    hide_index=True,
    use_container_width=True,
)

st.session_state.assets = edited_assets

st.subheader("Scenario narrativo (rischio tematico)")
st.caption(
    "Modella un rischio che non è ancora nello storico dei prezzi (es. una bolla AI): "
    "imposta l'esposizione di ogni asset al tema nella colonna 'Esposizione tema (%)' "
    "qui sopra, poi stima probabilità e severità dello scenario qui sotto."
)
narrative_enabled = st.checkbox("Includi lo scenario narrativo nel calcolo del rischio", value=False)

narrative_scenario = None
if narrative_enabled:
    narr_col1, narr_col2 = st.columns(2)
    with narr_col1:
        narrative_probability = st.slider(
            "Probabilità stimata dello scenario",
            min_value=0.0,
            max_value=1.0,
            value=0.25,
            step=0.05,
            help="Stima qualitativa, ad es. basata su frequenza e tono delle notizie sul tema.",
        )
    with narr_col2:
        narrative_severity = st.slider(
            "Severità se lo scenario si realizza (%)",
            min_value=-100.0,
            max_value=0.0,
            value=-50.0,
            step=5.0,
            help="Shock di rendimento per un asset con esposizione 100% al tema, se lo scenario si materializza.",
        ) / 100.0
    narrative_scenario = {"probability": narrative_probability, "severity": narrative_severity}

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

if portfolio.get("narrative_risk") is not None:
    nr = portfolio["narrative_risk"]
    st.info(
        f"Esposizione complessiva del portafoglio al tema: {nr['portfolio_exposure'] * 100:.1f}% | "
        f"Se lo scenario si realizza, impatto stimato: {nr['stressed_loss_if_realized'] * 100:.1f}% "
        f"({nr['stressed_loss_if_realized'] * portfolio['portfolio_value']:,.0f}) | "
        f"Contributo atteso alla varianza (ponderato per probabilità): {nr['variance_contribution']:.5f}"
    )

summary = portfolio
risk_df = summary["asset_risk_contribution"].copy()
risk_df["weight"] = (risk_df["weight"] * 100).round(2)
risk_df["risk_contribution_pct"] = risk_df["risk_contribution_pct"].round(2)
risk_df["expected_return"] = (risk_df["expected_return"] * 100).round(2)
risk_df["volatility"] = (risk_df["volatility"] * 100).round(2)

cols = st.columns(4)
cols[0].metric("Valore totale", f"€ {summary['portfolio_value']:,.0f}")
cols[1].metric("Rendimento atteso", f"{summary['expected_return'] * 100:.2f}%")
cols[2].metric("Volatilità portafoglio", f"{summary['volatility'] * 100:.2f}%")
cols[3].metric("Sharpe", f"{summary['sharpe']:.2f}")

st.subheader("Profilo di rischio")

risk_text = (
    f"Livello di rischio: {summary['risk_level']} | Score: {summary['risk_score']:.1f}/100 | Beta portafoglio: {summary['beta']:.2f}"
)
if summary["risk_score"] < 35:
    st.success(risk_text)
elif summary["risk_score"] < 60:
    st.info(risk_text)
elif summary["risk_score"] < 80:
    st.warning(risk_text)
else:
    st.error(risk_text)

if summary["risk_level"] == "Basso":
    st.caption("Rischio basso: il portafoglio è molto diversificato, con volatilità contenuta e beta vicino a 1. In generale le perdite estreme sono meno probabili.")
elif summary["risk_level"] == "Moderato":
    st.caption("Rischio moderato: la volatilità e il beta indicano un livello di variabilità medio, quindi il portafoglio può oscillare ma resta gestibile nel medio termine.")
elif summary["risk_level"] == "Elevato":
    st.caption("Rischio elevato: il portafoglio è sensibile a oscillazioni di mercato e a asset più volatili. Le perdite in fasi negative possono essere più marcate.")
else:
    st.caption("Rischio molto elevato: la combinazione di beta, volatilità e esposizione concentrata rende il portafoglio particolarmente vulnerabile a shock di mercato.")

st.subheader("Analisi obbligazioni")
with st.container():
    bond_col1, bond_col2, bond_col3 = st.columns(3)
    with bond_col1:
        bond_face_value = st.number_input("Valore nominale (€)", min_value=100.0, value=1000.0, step=10.0)
        bond_coupon = st.number_input("Cedola annua (%)", min_value=0.0, max_value=30.0, value=5.0, step=0.1) / 100.0
    with bond_col2:
        bond_years = st.number_input("Anni alla scadenza", min_value=0.5, value=5.0, step=0.5)
        bond_market_price = st.number_input("Prezzo di mercato (€)", min_value=0.0, value=950.0, step=10.0)
    with bond_col3:
        bond_frequency = st.selectbox("Pagamento cedole", options=[1, 2, 4, 12], index=1)
        bond_annual_yield = st.number_input("YTM desiderato (%)", min_value=0.0, max_value=30.0, value=0.0, step=0.1) / 100.0

    bond_metrics = calculate_bond_metrics(
        face_value=bond_face_value,
        coupon_rate=bond_coupon,
        years_to_maturity=bond_years,
        market_price=bond_market_price,
        annual_yield=bond_annual_yield if bond_annual_yield > 0 else None,
        frequency=bond_frequency,
    )

    bond_metrics_df = pd.DataFrame(
        [
            {
                "YTM": bond_metrics["yield_to_maturity"] * 100,
                "Duration (Mac.):": bond_metrics["macaulay_duration_years"],
                "Duration (Mod.):": bond_metrics["modified_duration_years"],
                "Convexity": bond_metrics["convexity"],
                "Prezzo teorico": bond_metrics["price_from_yield"],
            }
        ]
    )
    st.dataframe(bond_metrics_df, use_container_width=True)

st.subheader("Simulatore di crescita composta")
with st.container():
    sim_col1, sim_col2, sim_col3 = st.columns(3)
    with sim_col1:
        sim_principal = st.number_input("Capitale iniziale (€)", min_value=0.0, value=10000.0, step=500.0)
        sim_annual_rate = st.number_input("Rendimento annuo (%)", min_value=-50.0, max_value=50.0, value=6.0, step=0.5) / 100.0
    with sim_col2:
        sim_years = st.number_input("Anni", min_value=1.0, value=10.0, step=1.0)
        sim_contribution = st.number_input("Contributo annuale (€)", min_value=0.0, value=1200.0, step=100.0)
    with sim_col3:
        sim_inflation = st.number_input("Inflazione (%)", min_value=0.0, max_value=20.0, value=2.0, step=0.1) / 100.0
        sim_tax = st.number_input("Aliquota fiscale (%)", min_value=0.0, max_value=60.0, value=23.0, step=1.0) / 100.0

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

    sim_cols = st.columns(4)
    sim_cols[0].metric("Valore nominale finale", f"€ {compound_result['final_value_nominal']:,.0f}")
    sim_cols[1].metric("Valore netto dopo tasse", f"€ {compound_result['after_tax_value']:,.0f}")
    sim_cols[2].metric("Valore reale dopo inflazione", f"€ {compound_result['real_value_after_inflation']:,.0f}")
    sim_cols[3].metric("Rendimento reale medio", f"{compound_result['inflation_adjusted_rate'] * 100:.2f}%")

    annual_df = pd.DataFrame(compound_result["yearly_history"])
    if not annual_df.empty:
        annual_df["year"] = annual_df["year"].astype(int)
        annual_chart = alt.Chart(annual_df).transform_fold(
            fold=["nominal_value", "real_value_after_inflation"],
            as_=["serie", "valore"],
        ).mark_line(point=True, strokeWidth=2).encode(
            x=alt.X("year:Q", title="Anno", sort="ascending"),
            y=alt.Y("valore:Q", title="Valore (€)"),
            color=alt.Color(
                "serie:N",
                title=None,
                scale=alt.Scale(domain=["nominal_value", "real_value_after_inflation"], range=["#5eead4", "#60a5fa"]),
            ),
            tooltip=["year:Q", "serie:N", "valore:Q"],
        ).properties(height=360)
        st.altair_chart(annual_chart, use_container_width=True)

simulation = None
if st.button("Simula 10.000 scenari con dati storici reali", use_container_width=True):
    try:
        simulation = simulate_portfolio_scenarios(st.session_state.assets, scenarios=10000, horizon_days=252, seed=42)
    except Exception as exc:  # pragma: no cover - runtime only
        st.error(f"Impossibile generare la simulazione storica: {exc}")

if simulation is not None:
    st.subheader("Simulazione storica del portafoglio")
    st.caption(simulation["historical_source"])

    sim_cols = st.columns(4)
    sim_cols[0].metric("Rendimento atteso simulato", f"{simulation['expected_return'] * 100:.2f}%")
    sim_cols[1].metric("P5 (peggiore 5%)", f"{simulation['p05'] * 100:.2f}%")
    sim_cols[2].metric("P95 (migliore 5%)", f"{simulation['p95'] * 100:.2f}%")
    sim_cols[3].metric("Prob. di perdita", f"{simulation['probability_loss'] * 100:.2f}%")

    dist = pd.DataFrame({"Rendimento totale": simulation["portfolio_return_distribution"]})
    hist_chart = alt.Chart(dist).mark_bar().encode(
        x=alt.X("Rendimento totale:Q", bin=alt.Bin(maxbins=30), title="Rendimento totale"),
        y=alt.Y("count():Q", title="Occorrenze"),
        tooltip=["count():Q"],
    ).properties(height=360)
    st.altair_chart(hist_chart, use_container_width=True)

st.subheader("Contributo al rischio per asset")

if not risk_df.empty:
    st.dataframe(
        risk_df[["name", "value", "weight", "expected_return", "volatility", "beta", "risk_contribution_pct"]].rename(
            columns={
                "name": "Asset",
                "value": "Valore",
                "weight": "Allocazione (%)",
                "expected_return": "Rendimento atteso (%)",
                "volatility": "Volatilità (%)",
                "beta": "Beta",
                "risk_contribution_pct": "Contributo al rischio (%)",
            }
        ),
        use_container_width=True,
    )

    chart_df = risk_df[["name", "weight", "risk_contribution_pct"]].rename(
        columns={"weight": "Allocazione (%)", "risk_contribution_pct": "Contributo al rischio (%)"}
    ).sort_values("Contributo al rischio (%)", ascending=False)
    risk_chart = alt.Chart(chart_df).mark_bar().encode(
        x=alt.X("name:N", sort="-y", title="Asset"),
        y=alt.Y("Contributo al rischio (%):Q", title="Contributo al rischio (%)"),
        color=alt.Color("name:N", legend=None),
        tooltip=["name:N", "Contributo al rischio (%):Q"],
    ).properties(height=360)
    st.altair_chart(risk_chart, use_container_width=True)
    st.caption("Il grafico mostra il peso di ciascun asset nel rischio complessivo del portafoglio.")
else:
    st.info("Aggiungi almeno un asset per calcolare il rischio del portafoglio.")

st.subheader("Asset più rilevanti")
if not risk_df.empty:
    top_risk = risk_df.sort_values("risk_contribution_pct", ascending=False).head(3)
    for _, asset in top_risk.iterrows():
        st.markdown(
            f"- **{asset['name']}**: contributo al rischio {asset['risk_contribution_pct']:.2f}% "
            f"su un peso del {asset['weight']:.2f}%"
        )
