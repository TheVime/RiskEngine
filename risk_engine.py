from __future__ import annotations

"""
CHANGELOG
---------
v1.1 - 2026-09-21
    - Aggiunta calculate_narrative_factor_risk(): modella un rischio
      tematico/narrativo (es. "bolla AI") come fattore di rischio comune
      aggiuntivo, non derivabile dallo storico dei prezzi. Ogni asset ha
      un'esposizione al tema (0-1) e lo scenario ha una probabilità e una
      severità stimate qualitativamente (es. da analisi di notizie).
    - calculate_portfolio_metrics() ora accetta il parametro opzionale
      narrative_scenario per integrare questo fattore nella volatilità e
      nel rendimento atteso del portafoglio, mantenendo il comportamento
      precedente invariato quando il parametro è omesso (None).

v1.2 - 2026-09-22
    - Aggiunta simulate_efficient_frontier(): genera N portafogli con pesi
      casuali (distribuzione di Dirichlet) sugli stessi asset del
      portafoglio corrente e ne calcola rendimento atteso, volatilità e
      Sharpe ratio, usando la stessa formula di covarianza già impiegata
      da _portfolio_volatility() ma vettorizzata con np.einsum per gestire
      migliaia di portafogli in un'unica operazione. Serve ad alimentare
      il grafico "frontiera efficiente" nella UI (nuvola di portafogli +
      punto del portafoglio attuale), per mostrare visivamente se esistono
      allocazioni con rendimento/rischio migliori a parità di asset.
"""

from typing import Any, Iterable
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests

try:
    import yfinance as yf
except Exception:  # pragma: no cover - optional dependency
    yf = None


DEFAULT_AVERAGE_CORRELATION = 0.35

EUROPEAN_ISIN_FALLBACKS = {
    "IE00B4L5Y983": {
        "name": "iShares Core MSCI World UCITS ETF USD (Acc)",
        "ticker": "IWDA.L",
        "value": 10000,
        "expected_return": 0.08,
        "volatility": 0.15,
        "beta": 0.98,
        "exchange": "London",
        "asset_type": "ETF",
    },
    "IE00BK5BQT80": {
        "name": "iShares Core MSCI EM IMI UCITS ETF USD (Acc)",
        "ticker": "IEMG.L",
        "value": 10000,
        "expected_return": 0.09,
        "volatility": 0.18,
        "beta": 0.82,
        "exchange": "London",
        "asset_type": "ETF",
    },
}


def _normalize_percentage(value: Any) -> float:
    """Convert a value from percent format to decimal format when needed."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0

    if pd.isna(numeric):
        return 0.0

    if abs(numeric) > 1:
        return numeric / 100.0
    return numeric


def _risk_label(risk_score: float) -> str:
    if risk_score < 35:
        return "Basso"
    if risk_score < 60:
        return "Moderato"
    if risk_score < 80:
        return "Elevato"
    return "Molto elevato"


def _portfolio_volatility(weights: pd.Series, volatilities: pd.Series, avg_correlation: float) -> float:
    if weights.empty or weights.sum() == 0:
        return 0.0

    vol_values = volatilities.to_numpy(dtype=float)
    weight_values = weights.to_numpy(dtype=float)

    variance = 0.0
    for i in range(len(weight_values)):
        for j in range(len(weight_values)):
            corr = avg_correlation if i != j else 1.0
            variance += weight_values[i] * weight_values[j] * corr * vol_values[i] * vol_values[j]

    return float(np.sqrt(max(variance, 0.0)))


def _fetch_historical_returns(ticker: str) -> pd.Series:
    if not ticker or yf is None:
        return pd.Series(dtype=float)

    try:
        data = yf.download(
            ticker,
            period="5y",
            interval="1d",
            auto_adjust=True,
            progress=False,
            actions=False,
            threads=False,
        )
    except Exception:
        return pd.Series(dtype=float)

    if data.empty:
        return pd.Series(dtype=float)

    if isinstance(data.columns, pd.MultiIndex):
        close_columns = data.columns.get_level_values(0) == "Close"
        if not close_columns.any():
            return pd.Series(dtype=float)
        close = data.loc[:, close_columns].iloc[:, 0]
    else:
        if "Close" not in data.columns:
            return pd.Series(dtype=float)
        close = data["Close"]

    close = pd.to_numeric(close, errors="coerce").dropna()
    if close.empty:
        return pd.Series(dtype=float)

    returns = close.pct_change().dropna()
    return returns.astype(float)


def lookup_isin_to_asset(isin: str) -> dict[str, Any]:
    """Resolve a European ISIN into basic portfolio metadata using Yahoo Finance when available and a local fallback map for common ETFs."""
    if not isin or not isinstance(isin, str):
        return {}

    normalized_isin = isin.strip().upper()
    if not normalized_isin:
        return {}

    fallback = EUROPEAN_ISIN_FALLBACKS.get(normalized_isin)
    if fallback:
        return {
            "name": fallback["name"],
            "ticker": fallback["ticker"],
            "isin": normalized_isin,
            "value": fallback["value"],
            "expected_return": fallback["expected_return"],
            "volatility": fallback["volatility"],
            "beta": fallback["beta"],
            "exchange": fallback["exchange"],
            "asset_type": fallback["asset_type"],
        }

    if yf is None:
        return {}

    try:
        endpoint = f"https://query1.finance.yahoo.com/v1/finance/search?q={quote(normalized_isin)}"
        response = requests.get(endpoint, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code == 429:
            return {}
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return {}

    quotes = payload.get("quotes", []) if isinstance(payload, dict) else []
    if not quotes:
        return {}

    best_match = quotes[0]
    symbol = str(best_match.get("symbol", "")).strip()
    if not symbol:
        return {}

    ticker = yf.Ticker(symbol)
    try:
        info = ticker.fast_info or {}
    except Exception:
        info = {}

    try:
        history = ticker.history(period="5y", interval="1d", auto_adjust=True, actions=False)
    except Exception:
        history = pd.DataFrame()

    if not history.empty and "Close" in history.columns:
        close = pd.to_numeric(history["Close"], errors="coerce").dropna()
        if not close.empty and len(close) > 1:
            annualized_return = float((close.iloc[-1] / close.iloc[0]) ** (1 / max((len(close) / 252), 1 / 252)) - 1.0)
            volatility = float(close.pct_change().dropna().std(ddof=1) * np.sqrt(252))
        else:
            annualized_return = 0.0
            volatility = 0.0
    else:
        annualized_return = 0.0
        volatility = 0.0

    beta = float(info.get("beta", 1.0) or 1.0)
    if not np.isfinite(beta):
        beta = 1.0

    if annualized_return == 0.0:
        annualized_return = float(_normalize_percentage(info.get("trailingAnnualReturn", 0.0) or 0.0))
    if volatility == 0.0:
        volatility = float(_normalize_percentage(info.get("annualVolatility", 0.0) or 0.0))
    if volatility <= 0 and best_match.get("quoteType") == "ETF":
        volatility = 0.18

    return {
        "name": str(best_match.get("longname") or best_match.get("shortname") or symbol),
        "ticker": symbol,
        "isin": normalized_isin,
        "value": 10000,
        "expected_return": annualized_return,
        "volatility": volatility,
        "beta": beta,
        "exchange": best_match.get("exchDisp") or best_match.get("exchange") or "",
        "asset_type": str(best_match.get("quoteType") or "ETF").title(),
    }


def simulate_portfolio_scenarios(
    asset_rows: Iterable[dict[str, Any]] | pd.DataFrame,
    scenarios: int = 10000,
    horizon_days: int = 252,
    seed: int = 42,
    history_map: dict[str, pd.Series] | None = None,
) -> dict[str, Any]:
    """Simulate the portfolio using historical daily returns resampled from real market data."""

    if isinstance(asset_rows, pd.DataFrame):
        df = asset_rows.copy()
    else:
        df = pd.DataFrame(list(asset_rows))

    if df.empty or scenarios <= 0:
        return {
            "portfolio_value": 0.0,
            "expected_return": 0.0,
            "volatility": 0.0,
            "p05": 0.0,
            "p95": 0.0,
            "median": 0.0,
            "probability_loss": 0.0,
            "portfolio_return_distribution": np.array([], dtype=float),
            "historical_source": "Nessun asset disponibile",
        }

    for column in ["name", "value", "ticker", "expected_return", "volatility", "beta"]:
        if column not in df.columns:
            df[column] = 0.0 if column != "ticker" else ""

    df["name"] = df["name"].fillna("Asset").astype(str).str.strip()
    df["ticker"] = df["ticker"].fillna("").astype(str).str.strip().str.upper()
    df["value"] = pd.to_numeric(df["value"], errors="coerce").fillna(0.0)
    df["expected_return"] = pd.to_numeric(df["expected_return"], errors="coerce").fillna(0.0).apply(_normalize_percentage)
    df["volatility"] = pd.to_numeric(df["volatility"], errors="coerce").fillna(0.0).apply(_normalize_percentage)
    df["beta"] = pd.to_numeric(df["beta"], errors="coerce").fillna(1.0)
    df = df[(df["name"] != "") & (df["value"] > 0)].copy()

    if df.empty:
        return {
            "portfolio_value": 0.0,
            "expected_return": 0.0,
            "volatility": 0.0,
            "p05": 0.0,
            "p95": 0.0,
            "median": 0.0,
            "probability_loss": 0.0,
            "portfolio_return_distribution": np.array([], dtype=float),
            "historical_source": "Nessun asset con valore positivo",
        }

    total_value = float(df["value"].sum())
    weights = df["value"] / total_value

    if history_map is None:
        history_map = {}

    historical_returns: dict[str, pd.Series] = {}
    for ticker in df["ticker"].dropna().unique():
        if not ticker:
            continue
        if ticker in history_map:
            sample = pd.Series(history_map[ticker]).dropna()
        else:
            sample = _fetch_historical_returns(ticker)
        if not sample.empty:
            historical_returns[ticker] = sample.astype(float)

    rng = np.random.default_rng(seed)
    scenario_returns = np.zeros((scenarios, horizon_days), dtype=float)
    weight_values = weights.to_numpy(dtype=float)

    # Generate each asset's full scenario matrix with NumPy, then aggregate
    # assets and days in vectorized operations instead of nested Python loops.
    for asset_index, (_, row) in enumerate(df.iterrows()):
        ticker = str(row["ticker"]).strip().upper()
        if ticker and ticker in historical_returns and not historical_returns[ticker].empty:
            sample_values = historical_returns[ticker].to_numpy(dtype=float)
            sampled_indexes = rng.integers(0, len(sample_values), size=(scenarios, horizon_days))
            asset_returns = sample_values[sampled_indexes]
        else:
            asset_returns = rng.normal(
                loc=float(row["expected_return"]),
                scale=max(float(row["volatility"]), 0.01),
                size=(scenarios, horizon_days),
            )
            asset_returns = np.clip(asset_returns, -0.75, 0.75)

        scenario_returns += weight_values[asset_index] * asset_returns

    scenario_results = np.prod(1.0 + scenario_returns, axis=1) - 1.0

    summary = {
        "portfolio_value": total_value,
        "expected_return": float(np.mean(scenario_results)),
        "volatility": float(np.std(scenario_results, ddof=1)) if len(scenario_results) > 1 else 0.0,
        "p05": float(np.percentile(scenario_results, 5)),
        "p95": float(np.percentile(scenario_results, 95)),
        "median": float(np.median(scenario_results)),
        "probability_loss": float(np.mean(scenario_results < 0.0)),
        "portfolio_return_distribution": scenario_results,
        "historical_source": (
            "Yahoo Finance - daily historical returns resampled with replacement to build 10,000 scenarios"
            if historical_returns
            else "Fallback: returns estimated from user assumptions (historical source unavailable)"
        ),
    }

    return summary


def calculate_narrative_factor_risk(
    df: pd.DataFrame,
    weights: pd.Series,
    probability: float,
    severity: float,
) -> dict[str, float]:
    """Model a thematic/narrative risk (e.g. an "AI bubble") as an extra common risk factor.

    Historical-data models (VaR, resampled Monte Carlo) are blind to scenarios that have
    never occurred before, because they only reproduce the past. This function treats a
    narrative scenario as a single additional risk factor with:

    - a per-asset exposure (``narrative_exposure``, 0 = no exposure, 1 = fully exposed),
      set by the user for each asset based on real revenue/theme exposure;
    - a probability that the scenario materializes (qualitative estimate, e.g. informed
      by news flow analysis);
    - a severity: the return shock applied to a fully-exposed asset if the scenario does
      materialize (negative for an adverse scenario, e.g. -0.6 for a 60% drawdown).

    The theme is modeled as a simple two-outcome (Bernoulli-like) random variable X:
    X = severity with probability p, X = 0 otherwise. Its mean and variance are:

        factor_mean = p * severity
        factor_variance = p * (1 - p) * severity**2

    The portfolio's aggregate exposure to the theme is the weighted sum of per-asset
    exposures (B = sum(w_i * beta_i)). Under a single-factor model this contributes:

        expected_return_impact = B * factor_mean
        variance_contribution = B**2 * factor_variance

    to the portfolio's expected return and variance respectively. Additionally, the
    deterministic "if it happens" stress impact (ignoring probability) is B * severity,
    useful to show as a standalone stress-test figure alongside the probabilistic figures.

    Reference on single-factor / multi-factor risk models: Barra/MSCI risk model handbook,
    https://www.msci.com/documents/1296102/1339060/Barra_Risk_Model_Handbook.pdf
    """
    probability = min(max(float(probability), 0.0), 1.0)
    severity = float(severity)

    if "narrative_exposure" in df.columns:
        exposures = pd.to_numeric(df["narrative_exposure"], errors="coerce").fillna(0.0).clip(0.0, 1.0)
    else:
        exposures = pd.Series(np.zeros(len(df)), index=df.index)

    weight_values = weights.to_numpy(dtype=float)
    exposure_values = exposures.to_numpy(dtype=float)

    portfolio_exposure = float(np.dot(weight_values, exposure_values))

    factor_mean = probability * severity
    factor_variance = probability * (1.0 - probability) * (severity ** 2)

    expected_return_impact = portfolio_exposure * factor_mean
    variance_contribution = (portfolio_exposure ** 2) * factor_variance
    stressed_loss_if_realized = portfolio_exposure * severity

    return {
        "portfolio_exposure": portfolio_exposure,
        "probability": probability,
        "severity": severity,
        "expected_return_impact": expected_return_impact,
        "variance_contribution": variance_contribution,
        "stressed_loss_if_realized": stressed_loss_if_realized,
    }


def calculate_portfolio_metrics(
    asset_rows: Iterable[dict[str, Any]] | pd.DataFrame,
    risk_free_rate: float = 0.02,
    avg_correlation: float = DEFAULT_AVERAGE_CORRELATION,
    narrative_scenario: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Return portfolio metrics and asset-level contribution data.

    ``narrative_scenario``, if provided, is a dict with keys "probability" and
    "severity" describing a thematic risk scenario (see
    :func:`calculate_narrative_factor_risk`). Per-asset exposure to the theme is read
    from an optional "narrative_exposure" column in ``asset_rows`` (0 if absent).
    When ``narrative_scenario`` is None (default), behavior is unchanged from v1.0.
    """

    if isinstance(asset_rows, pd.DataFrame):
        df = asset_rows.copy()
    else:
        df = pd.DataFrame(list(asset_rows))

    if df.empty:
        empty = {
            "portfolio_value": 0.0,
            "expected_return": 0.0,
            "volatility": 0.0,
            "beta": 0.0,
            "sharpe": 0.0,
            "risk_score": 0.0,
            "risk_level": "Nessun asset",
            "asset_risk_contribution": pd.DataFrame(columns=["name", "value", "weight", "expected_return", "volatility", "beta", "risk_contribution_pct"]),
        }
        return empty

    required_columns = ["name", "value", "expected_return", "volatility", "beta", "narrative_exposure"]
    for column in required_columns:
        if column not in df.columns:
            df[column] = 0.0

    df["name"] = df["name"].fillna("Asset").astype(str).str.strip()
    df["value"] = pd.to_numeric(df["value"], errors="coerce").fillna(0.0)
    df["expected_return"] = pd.to_numeric(df["expected_return"], errors="coerce").fillna(0.0).apply(_normalize_percentage)
    df["volatility"] = pd.to_numeric(df["volatility"], errors="coerce").fillna(0.0).apply(_normalize_percentage)
    df["beta"] = pd.to_numeric(df["beta"], errors="coerce").fillna(1.0)
    df["narrative_exposure"] = (
        pd.to_numeric(df["narrative_exposure"], errors="coerce").fillna(0.0).apply(_normalize_percentage).clip(0.0, 1.0)
    )

    df = df[df["name"] != ""].copy()
    if df.empty:
        return calculate_portfolio_metrics([], risk_free_rate=risk_free_rate, avg_correlation=avg_correlation)

    total_value = float(df["value"].sum())
    if total_value <= 0:
        raise ValueError("Il valore totale del portafoglio deve essere maggiore di zero.")

    df["weight"] = df["value"] / total_value
    portfolio_return = float((df["weight"] * df["expected_return"]).sum())
    portfolio_beta = float((df["weight"] * df["beta"]).sum())
    portfolio_volatility = _portfolio_volatility(df["weight"], df["volatility"], avg_correlation)

    if portfolio_volatility > 0:
        sharpe = (portfolio_return - risk_free_rate) / portfolio_volatility
    else:
        sharpe = 0.0

    covariance_matrix = np.full((len(df), len(df)), avg_correlation, dtype=float)
    np.fill_diagonal(covariance_matrix, 1.0)
    volatilities = df["volatility"].to_numpy(dtype=float)
    covariance_matrix = covariance_matrix * np.outer(volatilities, volatilities)

    portfolio_variance = float(
        np.dot(df["weight"].to_numpy(dtype=float), np.dot(covariance_matrix, df["weight"].to_numpy(dtype=float)))
    )

    if portfolio_variance <= 0:
        risk_contribution = pd.Series(np.zeros(len(df)))
    else:
        marginal = np.dot(covariance_matrix, df["weight"].to_numpy(dtype=float))
        risk_contribution = (df["weight"].to_numpy(dtype=float) * marginal) / portfolio_variance

    df["risk_contribution_pct"] = np.clip(risk_contribution * 100.0, 0.0, 100.0)

    narrative_risk = None
    if narrative_scenario is not None:
        narrative_risk = calculate_narrative_factor_risk(
            df,
            df["weight"],
            probability=narrative_scenario.get("probability", 0.0),
            severity=narrative_scenario.get("severity", 0.0),
        )
        # Il fattore narrativo si somma alla varianza storica (assumendo indipendenza
        # tra il fattore tematico e i fattori già impliciti nella covarianza storica)
        # e sposta il rendimento atteso in base all'impatto probabilistico stimato.
        portfolio_variance_with_narrative = (portfolio_volatility ** 2) + narrative_risk["variance_contribution"]
        portfolio_volatility = float(np.sqrt(max(portfolio_variance_with_narrative, 0.0)))
        portfolio_return = portfolio_return + narrative_risk["expected_return_impact"]
        if portfolio_volatility > 0:
            sharpe = (portfolio_return - risk_free_rate) / portfolio_volatility

    risk_score = min(100.0, max(0.0, (portfolio_volatility * 100.0) * 1.6 + portfolio_beta * 15.0))
    risk_level = _risk_label(risk_score)

    summary = {
        "portfolio_value": total_value,
        "expected_return": portfolio_return,
        "volatility": portfolio_volatility,
        "beta": portfolio_beta,
        "sharpe": sharpe,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "asset_risk_contribution": df[["name", "value", "weight", "expected_return", "volatility", "beta", "risk_contribution_pct"]].copy(),
        "narrative_risk": narrative_risk,
    }

    return summary


def simulate_efficient_frontier(
    asset_rows: Iterable[dict[str, Any]] | pd.DataFrame,
    risk_free_rate: float = 0.02,
    avg_correlation: float = DEFAULT_AVERAGE_CORRELATION,
    num_portfolios: int = 3000,
    seed: int = 42,
) -> pd.DataFrame:
    """Simulate random portfolios over the same assets to sketch an efficient frontier.

    For each of ``num_portfolios`` random weight vectors (drawn from a symmetric
    Dirichlet distribution, so weights are non-negative and sum to 1) we compute
    the resulting expected return, volatility and Sharpe ratio, reusing the same
    weighted-covariance formula as :func:`_portfolio_volatility` — a constant
    average correlation off the diagonal, full variance on it — but fully
    vectorized with :func:`numpy.einsum` instead of looping in Python, so a few
    thousand portfolios are evaluated in a single pass.

    This does not solve for the mathematically optimal (mean-variance) frontier;
    it approximates it by dense random sampling, which is enough to visualize
    where the current allocation sits relative to other achievable combinations
    of the same assets. For the classical (Markowitz) formulation this
    approximates, see https://en.wikipedia.org/wiki/Modern_portfolio_theory
    and, for the Dirichlet sampling approach, https://numpy.org/doc/stable/reference/random/generated/numpy.random.Generator.dirichlet.html
    """
    if isinstance(asset_rows, pd.DataFrame):
        df = asset_rows.copy()
    else:
        df = pd.DataFrame(list(asset_rows))

    for column in ["name", "value", "expected_return", "volatility"]:
        if column not in df.columns:
            df[column] = 0.0

    df["name"] = df["name"].fillna("Asset").astype(str).str.strip()
    df["value"] = pd.to_numeric(df["value"], errors="coerce").fillna(0.0)
    df["expected_return"] = pd.to_numeric(df["expected_return"], errors="coerce").fillna(0.0).apply(_normalize_percentage)
    df["volatility"] = pd.to_numeric(df["volatility"], errors="coerce").fillna(0.0).apply(_normalize_percentage)
    df = df[(df["name"] != "") & (df["value"] > 0)].copy()

    if len(df) < 2 or num_portfolios <= 0:
        return pd.DataFrame(columns=["expected_return", "volatility", "sharpe"])

    expected_returns = df["expected_return"].to_numpy(dtype=float)
    volatilities = df["volatility"].to_numpy(dtype=float)

    # Stessa struttura di covarianza di _portfolio_volatility(): correlazione
    # media costante fuori dalla diagonale, varianza piena sulla diagonale.
    correlation_matrix = np.full((len(df), len(df)), avg_correlation, dtype=float)
    np.fill_diagonal(correlation_matrix, 1.0)
    covariance_matrix = correlation_matrix * np.outer(volatilities, volatilities)

    rng = np.random.default_rng(seed)
    random_weights = rng.dirichlet(np.ones(len(df)), size=num_portfolios)

    portfolio_returns = random_weights @ expected_returns
    # einsum calcola, per ogni riga i di random_weights, w_i @ Cov @ w_i^T
    # in un colpo solo, senza costruire una matrice (num_portfolios x num_portfolios).
    portfolio_variances = np.einsum("ij,jk,ik->i", random_weights, covariance_matrix, random_weights)
    portfolio_volatilities = np.sqrt(np.clip(portfolio_variances, 0.0, None))

    with np.errstate(divide="ignore", invalid="ignore"):
        sharpe_ratios = np.where(
            portfolio_volatilities > 0,
            (portfolio_returns - risk_free_rate) / portfolio_volatilities,
            0.0,
        )

    return pd.DataFrame(
        {
            "expected_return": portfolio_returns,
            "volatility": portfolio_volatilities,
            "sharpe": sharpe_ratios,
        }
    )


def calculate_bond_metrics(
    face_value: float = 1000.0,
    coupon_rate: float = 0.05,
    years_to_maturity: float = 5.0,
    market_price: float | None = None,
    annual_yield: float | None = None,
    frequency: int = 2,
) -> dict[str, float]:
    """Estimate bond metrics such as YTM, Macaulay duration and modified duration."""
    face_value = float(face_value)
    coupon_rate = float(coupon_rate)
    years_to_maturity = float(max(years_to_maturity, 0.0))
    frequency = max(int(frequency), 1)
    if market_price is None:
        market_price = face_value
    market_price = float(market_price)

    coupon_payment = face_value * coupon_rate / frequency
    periods = max(int(round(years_to_maturity * frequency)), 1)

    if annual_yield is None:
        annual_yield = max(0.0, coupon_rate + ((face_value - market_price) / max(years_to_maturity * face_value, 1.0)))

    ytm = float(max(annual_yield, 0.0))
    if market_price > 0 and face_value > 0 and years_to_maturity > 0:
        ytm_guess = ytm
        for _ in range(200):
            discount_rate = ytm_guess / frequency
            pv = 0.0
            for period_index in range(1, periods + 1):
                cash_flow = coupon_payment if period_index < periods else coupon_payment + face_value
                pv += cash_flow / ((1.0 + discount_rate) ** period_index)
            derivative = 0.0
            for period_index in range(1, periods + 1):
                cash_flow = coupon_payment if period_index < periods else coupon_payment + face_value
                derivative -= period_index * cash_flow / ((1.0 + discount_rate) ** (period_index + 1))
            derivative *= 1.0 / frequency
            if abs(pv - market_price) < 1e-9:
                break
            if abs(derivative) < 1e-12:
                break
            ytm_guess = ytm_guess - (pv - market_price) / derivative
            if ytm_guess < 0:
                ytm_guess = 0.0
        ytm = max(0.0, ytm_guess)

    yield_per_period = ytm / frequency
    pv_cash_flows = []
    total_present_value = 0.0
    for period_index in range(1, periods + 1):
        cash_flow = coupon_payment if period_index < periods else coupon_payment + face_value
        pv = cash_flow / ((1.0 + yield_per_period) ** period_index)
        total_present_value += pv
        pv_cash_flows.append((period_index, pv))

    macaulay_duration = 0.0
    if total_present_value > 0:
        for period_index, pv in pv_cash_flows:
            macaulay_duration += (period_index / frequency) * pv
        macaulay_duration /= total_present_value

    modified_duration = 0.0
    if yield_per_period > -1.0:
        modified_duration = macaulay_duration / (1.0 + yield_per_period)

    convexity = 0.0
    if abs(yield_per_period) < 1.0:
        convexity_total = 0.0
        for period_index, pv in pv_cash_flows:
            cash_flow = coupon_payment if period_index < periods else coupon_payment + face_value
            convexity_total += (period_index * (period_index + 1) * cash_flow) / ((1.0 + yield_per_period) ** (period_index + 2))
        convexity = convexity_total / total_present_value

    return {
        "face_value": face_value,
        "market_price": market_price,
        "coupon_payment": coupon_payment,
        "coupon_rate": coupon_rate,
        "yield_to_maturity": ytm,
        "macaulay_duration_years": macaulay_duration,
        "modified_duration_years": modified_duration,
        "convexity": convexity,
        "price_from_yield": total_present_value,
    }


def simulate_compound_growth(
    principal: float = 10000.0,
    annual_rate: float = 0.06,
    years: float = 10.0,
    contribution_per_year: float = 0.0,
    contribution_frequency: str = "annual",
    inflation_rate: float = 0.02,
    tax_rate: float = 0.23,
    compounding_periods: int = 12,
) -> dict[str, float | list[dict[str, float]]]:
    """Project a compounded investment value adjusted for taxes and inflation."""
    principal = float(principal)
    annual_rate = float(_normalize_percentage(annual_rate))
    inflation_rate = abs(float(_normalize_percentage(inflation_rate)))
    tax_rate = min(max(float(tax_rate), 0.0), 1.0)
    years = max(float(years), 0.0)
    compounding_periods = max(int(compounding_periods), 1)

    contribution_frequency = str(contribution_frequency).lower()
    if contribution_frequency.startswith("month"):
        contribution_amount = contribution_per_year
        contribution_interval = 1
    elif contribution_frequency.startswith("quarter"):
        contribution_amount = contribution_per_year
        contribution_interval = max(1, int(round(compounding_periods / 4.0)))
    else:
        contribution_amount = contribution_per_year
        contribution_interval = compounding_periods

    period_rate = annual_rate / compounding_periods
    total_periods = int(round(years * compounding_periods))

    balance = principal
    total_contributions = principal
    yearly_history: list[dict[str, float]] = []

    for period_index in range(1, total_periods + 1):
        balance *= 1.0 + period_rate

        if contribution_amount > 0 and period_index % contribution_interval == 0:
            balance += contribution_amount
            total_contributions += contribution_amount

        if period_index % compounding_periods == 0 or period_index == total_periods:
            year_number = period_index / compounding_periods
            year_label = int(np.ceil(year_number)) if year_number > 0 else 0
            gross_gain = max(balance - total_contributions, 0.0)
            tax_due = gross_gain * tax_rate
            after_tax_value = balance - tax_due
            real_value = after_tax_value / ((1.0 + inflation_rate) ** max(year_number, 0.0)) if year_number > 0 else after_tax_value
            yearly_history.append(
                {
                    "year": int(year_label),
                    "nominal_value": balance,
                    "after_tax_value": after_tax_value,
                    "real_value_after_inflation": real_value,
                }
            )

    if years <= 0:
        yearly_history = []

    balance = yearly_history[-1]["nominal_value"] if yearly_history else principal
    gross_gain = max(balance - total_contributions, 0.0)
    tax_due = gross_gain * tax_rate
    net_after_tax = balance - tax_due
    discounted_for_inflation = net_after_tax / ((1.0 + inflation_rate) ** years) if years > 0 else net_after_tax
    real_gain_after_inflation = discounted_for_inflation - principal

    return {
        "principal": principal,
        "total_contributions": total_contributions,
        "final_value_nominal": balance,
        "after_tax_value": net_after_tax,
        "real_value_after_inflation": discounted_for_inflation,
        "real_gain_after_inflation": real_gain_after_inflation,
        "tax_due": tax_due,
        "inflation_adjusted_rate": ((discounted_for_inflation / principal) ** (1.0 / max(years, 1.0)) - 1.0) if principal > 0 and years > 0 else 0.0,
        "yearly_history": yearly_history,
    }
