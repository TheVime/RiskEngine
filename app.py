from __future__ import annotations

# CHANGELOG
# ---------
# v1.1 - 2026-09-22
#     - Tema scuro applicato via .streamlit/config.toml (vedi quel file per
#       i colori) invece che con CSS custom, cosi' i colori restano coerenti
#       anche nei widget nativi di Streamlit e nei grafici Altair (che
#       ereditano automaticamente la palette del tema quando non si passa
#       theme=None a st.altair_chart). Vedi:
#       https://docs.streamlit.io/develop/concepts/configuration/theming
#     - Aggiunto render_risk_gauge(): gauge circolare del punteggio di
#       rischio (0-100), colorato in base alla fascia di rischio, per dare
#       un colpo d'occhio immediato oltre al testo di render_risk_advice().
#     - Aggiunta sezione "Frontiera efficiente (simulata)" nel tab Rischio:
#       nuvola di portafogli generati con simulate_efficient_frontier() e
#       marcatore del portafoglio attuale, per confrontare visivamente
#       rischio/rendimento con altre allocazioni possibili sugli stessi asset.
#     - CHART_PALETTE centralizza i colori categoriali usati nei grafici che
#       impostano esplicitamente theme=None (es. il donut di allocazione),
#       cosi' restano coerenti con chartCategoricalColors del tema anche li'.
# v1.1.1 - 2026-09-22
#     - Fix: il changelog sopra era scritto come stringa "bandone" (bare
#       string) invece che come commento. Streamlit ha una funzione
#       chiamata "magic": qualunque espressione non assegnata a una
#       variabile, nello script principale lanciato con `streamlit run`,
#       viene automaticamente passata a st.write() e mostrata in pagina.
#       Una docstring piazzata dopo `from __future__ import annotations`
#       non conta come vera docstring del modulo (che deve essere la primissima
#       istruzione del file) quindi veniva "catturata" dalla magic e
#       renderizzata come testo markdown in cima alla pagina, sopra
#       st.title(). Per questo sembrava che grafici e tabelle si fossero
#       spostati: in realtà erano sempre al loro posto (tab Dashboard),
#       solo spinti più in basso da questo blocco di testo indesiderato.
#       Ora è un commento `#`, quindi non viene mai eseguito né mostrato.
#       Doc ufficiale sulla magic: https://docs.streamlit.io/develop/api-reference/write-magic/magic
# v1.2 - 2026-09-22
#     - Ridisegnato il tab Dashboard in stile "card" (ispirato a una
#       dashboard di net worth): render_hero_card() mostra il valore totale
#       in grande con il rendimento atteso come delta colorato (verde/rosso);
#       render_allocation_card() sostituisce il vecchio donut + tabella con
#       una barra orizzontale segmentata (mark_bar impilato), una riga di
#       legenda con pallino colorato per asset, e una tabella con una mini
#       progress bar sul peso (st.column_config.ProgressColumn).
#     - Nota: niente linea di trend nella hero card. RiskEngine non tiene
#       uno storico di valore nel tempo (non è un tracker di transazioni),
#       quindi disegnare un trend sarebbe stato inventare dati.

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from risk_engine import (
    calculate_bond_metrics,
    calculate_portfolio_metrics,
    lookup_isin_to_asset,
    simulate_compound_growth,
    simulate_efficient_frontier,
    simulate_portfolio_scenarios,
)


st.set_page_config(
    page_title="RiskEngine",
    page_icon="📈",
    layout="wide",
    menu_items={"Get help": None, "Report a bug": None, "About": None},
)

# Stessa palette di theme.chartCategoricalColors in .streamlit/config.toml.
# Tenerle sincronizzate manualmente: i grafici con theme=None (vedi il donut
# di allocazione qui sotto) non ereditano il tema nativo di Streamlit, quindi
# la palette va passata esplicitamente per restare coerenti col resto della UI.
CHART_PALETTE = [
    "#5B8DEF", "#00C2A8", "#F2A93B", "#F25F5C",
    "#9B5DE5", "#4C6EF5", "#2ED9C3", "#FFD166",
]

# Colori per fascia di rischio (usati dal gauge e in futuro da altri
# elementi), coerenti con i colori semantici già usati da
# st.success/info/warning/error in render_risk_advice().
RISK_BAND_COLORS = {
    "Nessun asset": "#4B5563",
    "Basso": "#22C55E",
    "Moderato": "#38BDF8",
    "Elevato": "#F2A93B",
    "Molto elevato": "#F25F5C",
}


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
    st.header("Navigazione")
    current_section = st.radio(
        "Sezione",
        ["Dashboard", "Monte Carlo", "Rischio"],
        index=0,
        label_visibility="collapsed",
    )

    st.divider()
    st.caption("Parametri globali")
    risk_free_rate = st.number_input(
        "Tasso risk-free (%)", min_value=0.0, max_value=20.0, value=2.5, step=0.1
    ) / 100.0
    avg_correlation = st.slider("Correlazione media tra asset", 0.0, 1.0, 0.35, 0.05)

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
asset_lookup = st.session_state.assets[["name", "ticker"]].copy()
asset_lookup["ticker"] = asset_lookup["ticker"].fillna("").astype(str).str.strip()

risk_df = risk_calculation_df.copy()
if "ticker" not in risk_df.columns:
    risk_df["ticker"] = ""

risk_df = risk_df.merge(asset_lookup, on="name", how="left")
if "ticker_x" in risk_df.columns and "ticker_y" in risk_df.columns:
    risk_df["ticker"] = risk_df["ticker_y"].fillna(risk_df["ticker_x"]).fillna("")
    risk_df = risk_df.drop(columns=["ticker_x", "ticker_y"])
else:
    risk_df["ticker"] = risk_df.get("ticker", "").fillna("")

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


def render_hero_card() -> None:
    """Card "hero" in stile dashboard di net worth: valore totale in grande +
    rendimento atteso colorato come delta, dentro un container con bordo
    (che eredita l'angolo arrotondato da theme.baseRadius nel config.toml).

    A differenza di una dashboard di net worth reale (es. l'app "Maybe" da
    cui è preso lo stile), qui non esiste uno storico di valore nel tempo —
    RiskEngine calcola metriche sullo stato attuale del portafoglio, non
    tiene un registro di transazioni. Per questo non disegniamo una linea di
    trend: mostrarne una inventata sarebbe fuorviante. Doc su st.container:
    https://docs.streamlit.io/develop/api-reference/layout/st.container
    """
    delta = summary["expected_return"] * 100
    delta_color = "#22C55E" if delta >= 0 else "#F25F5C"
    with st.container(border=True):
        st.caption("Valore totale del portafoglio")
        st.markdown(f"## € {summary['portfolio_value']:,.0f}")
        st.markdown(
            f"<span style='color:{delta_color}; font-weight:600;'>"
            f"{delta:+.2f}% rendimento atteso</span>"
            f"<span style='color:#9AA1AE;'> · Sharpe {summary['sharpe']:.2f} · "
            f"Volatilità {summary['volatility'] * 100:.2f}%</span>",
            unsafe_allow_html=True,
        )


def render_allocation_card() -> None:
    """Card di allocazione in stile "Assets" della dashboard di riferimento:
    una barra orizzontale segmentata (un mark_bar impilato su una sola riga)
    al posto del donut, una riga di legenda con pallino colorato + percentuale
    per asset, e una tabella con una mini progress bar per il peso — ottenuta
    con st.column_config.ProgressColumn, che disegna nativamente una barra
    proporzionale nella cella senza dover generare immagini o HTML custom.
    Doc: https://docs.streamlit.io/develop/api-reference/data/st.column_config/st.column_config.progresscolumn
    """
    allocation = risk_df[["name", "value", "weight"]].copy()
    allocation = allocation[allocation["value"] > 0].reset_index(drop=True)
    if allocation.empty:
        return

    colors = [CHART_PALETTE[i % len(CHART_PALETTE)] for i in range(len(allocation))]
    color_by_name = dict(zip(allocation["name"], colors))

    with st.container(border=True):
        st.markdown(f"**Portafoglio** · € {summary['portfolio_value']:,.0f}")

        segmented_bar = alt.Chart(allocation).mark_bar(cornerRadius=6, height=18).encode(
            x=alt.X("value:Q", stack="normalize", axis=None, title=None),
            color=alt.Color(
                "name:N",
                scale=alt.Scale(domain=list(allocation["name"]), range=colors),
                legend=None,
            ),
            order=alt.Order("value:Q", sort="descending"),
            tooltip=[
                alt.Tooltip("name:N", title="Asset"),
                alt.Tooltip("weight:Q", title="Peso (%)", format=".1f"),
            ],
        ).properties(height=28)
        st.altair_chart(segmented_bar, width="stretch", theme=None)

        legend_html = " &nbsp;&nbsp; ".join(
            f"<span style='color:{color_by_name[row.name_]}'>●</span> {row.name_} "
            f"<span style='color:#9AA1AE;'>{row.weight:.0f}%</span>"
            for row in allocation.rename(columns={"name": "name_"}).itertuples()
        )
        st.markdown(f"<div style='font-size:0.85rem;'>{legend_html}</div>", unsafe_allow_html=True)
        st.write("")

        table = allocation.rename(columns={"name": "Nome", "weight": "Peso", "value": "Valore"})
        st.dataframe(
            table[["Nome", "Peso", "Valore"]],
            column_config={
                "Peso": st.column_config.ProgressColumn(
                    "Peso", format="%.1f%%", min_value=0, max_value=100
                ),
                "Valore": st.column_config.NumberColumn("Valore", format="€ %.0f"),
            },
            hide_index=True,
            width="stretch",
        )


def render_risk_gauge() -> None:
    """Gauge circolare (donut) del punteggio di rischio 0-100.

    Implementato come due fette di un mark_arc: una colorata (score) e una
    "resto" a bassa visibilità che riempie il cerchio fino a 100. Il numero
    non è disegnato nel grafico (per evitare la complessità di sovrapporre
    due chart Altair con st.altair_chart) ma renderizzato a fianco con
    st.markdown. Per il pattern del donut/arc in Altair, vedi la sezione
    "Radial chart" della documentazione: https://altair-viz.github.io/gallery/radial_chart.html
    """
    score = float(summary["risk_score"])
    color = RISK_BAND_COLORS.get(summary["risk_level"], "#4B5563")

    gauge_data = pd.DataFrame(
        {"category": ["Rischio", "Resto"], "value": [score, max(100.0 - score, 0.0)]}
    )
    base = alt.Chart(gauge_data).encode(
        theta=alt.Theta("value:Q", stack=True, sort=None),
        order=alt.Order("value:Q", sort="descending"),
    )
    arc = base.mark_arc(innerRadius=62, outerRadius=90, cornerRadius=6).encode(
        color=alt.Color(
            "category:N",
            scale=alt.Scale(domain=["Rischio", "Resto"], range=[color, "#262B36"]),
            legend=None,
        ),
        tooltip=alt.value(None),
    )
    gauge = arc.properties(height=200, width=200)

    gauge_col, label_col = st.columns([1, 2])
    with gauge_col:
        st.altair_chart(gauge, width="content", theme=None)
    with label_col:
        st.markdown(f"### {score:.0f}<span style='color:#9AA1AE; font-size:1rem;'>/100</span>", unsafe_allow_html=True)
        st.caption(f"Livello di rischio: **{summary['risk_level']}**")


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


if current_section == "Dashboard":
    render_hero_card()
    st.subheader("Portafoglio")
    if risk_df.empty:
        st.info("Il portafoglio è vuoto. Aggiungi un ETF, un'obbligazione tramite ISIN o inserisci un asset nella tabella.")
    else:
        render_allocation_card()

elif current_section == "Monte Carlo":
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
            distribution = simulation["portfolio_return_distribution"]
            histogram_counts, histogram_edges = np.histogram(distribution, bins=30)
            histogram_data = pd.DataFrame(
                {
                    "bin_start": histogram_edges[:-1],
                    "bin_end": histogram_edges[1:],
                    "bin_center": (histogram_edges[:-1] + histogram_edges[1:]) / 2,
                    "occurrences": histogram_counts,
                }
            )
            histogram_data["interval"] = histogram_data.apply(
                lambda row: (
                    f"{row['bin_start'] * 100:.2f}% - "
                    f"{row['bin_end'] * 100:.2f}%"
                ),
                axis=1,
            )
            histogram = alt.Chart(histogram_data).mark_bar(size=22).encode(
                x=alt.X(
                    "bin_center:Q",
                    title="Rendimento totale",
                    axis=alt.Axis(format=".2%"),
                ),
                y=alt.Y("occurrences:Q", title="Occorrenze", axis=alt.Axis(format="d")),
                tooltip=[
                    alt.Tooltip("interval:N", title="Intervallo"),
                    alt.Tooltip("occurrences:Q", title="Occorrenze", format="d"),
                ],
            ).properties(height=360)
            st.altair_chart(histogram, width="stretch")

else:
    render_kpis()
    st.subheader("Profilo e consigli")
    render_risk_gauge()
    render_risk_advice()
    render_risk_formula()

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

    with st.expander("Frontiera efficiente (simulata)", expanded=False):
        st.caption(
            "Nuvola di portafogli generati con pesi casuali sugli stessi asset in portafoglio, "
            "per confrontare rischio e rendimento con l'allocazione attuale (diamante rosso)."
        )
        if len(st.session_state.assets) < 2:
            st.info("Servono almeno due asset per generare la frontiera efficiente.")
        else:
            frontier_scenarios = st.slider(
                "Numero di portafogli simulati", 500, 8000, 3000, 500, key="frontier_scenarios"
            )
            frontier = simulate_efficient_frontier(
                st.session_state.assets,
                risk_free_rate=risk_free_rate,
                avg_correlation=avg_correlation,
                num_portfolios=frontier_scenarios,
            )
            if frontier.empty:
                st.info("Non è stato possibile generare la frontiera con i dati correnti.")
            else:
                current_point = pd.DataFrame(
                    {
                        "expected_return": [summary["expected_return"]],
                        "volatility": [summary["volatility"]],
                        "label": ["Portafoglio attuale"],
                    }
                )
                cloud = alt.Chart(frontier).mark_circle(opacity=0.35, size=28).encode(
                    x=alt.X("volatility:Q", title="Volatilità", axis=alt.Axis(format=".1%")),
                    y=alt.Y("expected_return:Q", title="Rendimento atteso", axis=alt.Axis(format=".1%")),
                    color=alt.Color("sharpe:Q", title="Sharpe", scale=alt.Scale(scheme="turbo")),
                    tooltip=[
                        alt.Tooltip("expected_return:Q", title="Rendimento", format=".2%"),
                        alt.Tooltip("volatility:Q", title="Volatilità", format=".2%"),
                        alt.Tooltip("sharpe:Q", title="Sharpe", format=".2f"),
                    ],
                )
                current_marker = alt.Chart(current_point).mark_point(
                    shape="diamond", size=240, filled=True, color="#F25F5C", stroke="white", strokeWidth=1.5
                ).encode(
                    x="volatility:Q",
                    y="expected_return:Q",
                    tooltip=[
                        alt.Tooltip("label:N", title=""),
                        alt.Tooltip("expected_return:Q", title="Rendimento", format=".2%"),
                        alt.Tooltip("volatility:Q", title="Volatilità", format=".2%"),
                    ],
                )
                frontier_chart = (cloud + current_marker).properties(height=380).interactive()
                st.altair_chart(frontier_chart, width="stretch")
                st.caption(
                    "Punti più in alto a sinistra = rendimento maggiore a parità (o minore) di rischio. "
                    "Nota: è una nuvola campionata, non l'ottimo matematico di Markowitz."
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
            sim_years = st.number_input("Anni", min_value=1, value=10, step=1)
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
