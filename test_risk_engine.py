import math

import pandas as pd

from risk_engine import (
    calculate_bond_metrics,
    calculate_narrative_factor_risk,
    calculate_portfolio_metrics,
    lookup_isin_to_asset,
    simulate_compound_growth,
    simulate_efficient_frontier,
    simulate_portfolio_scenarios,
)


def test_portfolio_metrics_calculate_expected_values():
    assets = [
        {"name": "ETF", "value": 60000, "expected_return": 8.0, "volatility": 12.0, "beta": 1.0},
        {"name": "Bond", "value": 40000, "expected_return": 3.0, "volatility": 5.0, "beta": 0.3},
    ]

    result = calculate_portfolio_metrics(assets, risk_free_rate=0.02)

    assert result["portfolio_value"] == 100000.0
    assert result["expected_return"] > 0.0
    assert result["volatility"] > 0.0
    assert result["beta"] > 0.0
    assert "risk_level" in result
    assert result["risk_score"] >= 0.0


def test_empty_portfolio_has_zero_metrics():
    result = calculate_portfolio_metrics([])

    assert result["portfolio_value"] == 0.0
    assert result["expected_return"] == 0.0
    assert result["volatility"] == 0.0
    assert result["risk_score"] == 0.0


def test_percentage_inputs_are_normalized():
    assets = [
        {"name": "Stock", "value": 1000, "expected_return": 10, "volatility": 20, "beta": 1.2},
    ]

    result = calculate_portfolio_metrics(assets)
    assert math.isclose(result["expected_return"], 0.1, rel_tol=1e-6)
    assert math.isclose(result["volatility"], 0.2, rel_tol=1e-6)


def test_simulation_uses_historical_return_samples():
    history_map = {
        "ASSET1": pd.Series([0.01, -0.02, 0.03, 0.04, -0.01, 0.02, 0.01, -0.03, 0.02, 0.05]),
        "ASSET2": pd.Series([0.005, -0.01, 0.02, 0.015, 0.01, -0.02, 0.03, 0.005, -0.01, 0.02]),
    }
    assets = [
        {"name": "Asset 1", "ticker": "ASSET1", "value": 60000, "expected_return": 8.0, "volatility": 12.0, "beta": 1.0},
        {"name": "Asset 2", "ticker": "ASSET2", "value": 40000, "expected_return": 3.0, "volatility": 5.0, "beta": 0.3},
    ]

    result = simulate_portfolio_scenarios(assets, scenarios=200, horizon_days=10, seed=7, history_map=history_map)

    assert len(result["portfolio_return_distribution"]) == 200
    assert "historical_source" in result
    assert result["portfolio_value"] == 100000.0
    assert result["probability_loss"] >= 0.0
    assert result["probability_loss"] <= 1.0


def test_lookup_isin_to_asset_maps_a_realistic_isin(monkeypatch):
    def fake_get(url, timeout, headers=None):
        class DummyResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "quotes": [
                        {
                            "symbol": "IWDA.L",
                            "shortname": "iShares Core MSCI World",
                            "longname": "iShares Core MSCI World UCITS ETF USD (Acc)",
                            "exchange": "LSE",
                            "exchDisp": "London",
                            "quoteType": "ETF",
                        }
                    ]
                }

        return DummyResponse()

    class DummyTicker:
        fast_info = {"beta": 0.98, "annualVolatility": 15.0}

        @staticmethod
        def history(period, interval, auto_adjust, actions):
            return pd.DataFrame({"Close": [100.0, 105.0, 110.0, 118.0]})

    monkeypatch.setattr("risk_engine.requests.get", fake_get)
    monkeypatch.setattr("risk_engine.yf.Ticker", lambda symbol: DummyTicker())

    match = lookup_isin_to_asset("IE00B4L5Y983")

    assert match["ticker"] == "IWDA.L"
    assert match["name"] == "iShares Core MSCI World UCITS ETF USD (Acc)"
    assert match["value"] == 10000
    assert match["beta"] > 0.0
    assert match["volatility"] > 0.0


def test_lookup_isin_uses_fallback_when_yahoo_is_rate_limited(monkeypatch):
    def fake_get(url, timeout, headers=None):
        class DummyResponse:
            status_code = 429

            def raise_for_status(self):
                raise RuntimeError("Too Many Requests")

        return DummyResponse()

    monkeypatch.setattr("risk_engine.requests.get", fake_get)
    match = lookup_isin_to_asset("IE00B4L5Y983")

    assert match["ticker"] == "IWDA.L"
    assert match["name"] == "iShares Core MSCI World UCITS ETF USD (Acc)"


def test_narrative_factor_risk_zero_exposure_has_no_effect():
    df = pd.DataFrame({"narrative_exposure": [0.0, 0.0]})
    weights = pd.Series([0.6, 0.4])

    result = calculate_narrative_factor_risk(df, weights, probability=0.2, severity=-0.6)

    assert result["portfolio_exposure"] == 0.0
    assert result["variance_contribution"] == 0.0
    assert result["expected_return_impact"] == 0.0
    assert result["stressed_loss_if_realized"] == 0.0


def test_narrative_factor_risk_full_exposure_matches_theory():
    # Un solo asset, interamente esposto al tema: il portafoglio eredita
    # esattamente media e varianza della variabile Bernoulli-like del fattore.
    df = pd.DataFrame({"narrative_exposure": [1.0]})
    weights = pd.Series([1.0])
    probability, severity = 0.25, -0.5

    result = calculate_narrative_factor_risk(df, weights, probability=probability, severity=severity)

    expected_mean = probability * severity
    expected_variance = probability * (1 - probability) * severity ** 2

    assert math.isclose(result["portfolio_exposure"], 1.0)
    assert math.isclose(result["expected_return_impact"], expected_mean)
    assert math.isclose(result["variance_contribution"], expected_variance)
    assert math.isclose(result["stressed_loss_if_realized"], severity)


def test_narrative_factor_risk_scales_with_partial_exposure():
    # Portafoglio diversificato: solo metà del valore è esposto al tema.
    df = pd.DataFrame({"narrative_exposure": [1.0, 0.0]})
    weights = pd.Series([0.5, 0.5])

    result = calculate_narrative_factor_risk(df, weights, probability=0.3, severity=-0.7)

    assert math.isclose(result["portfolio_exposure"], 0.5)
    assert math.isclose(result["stressed_loss_if_realized"], 0.5 * -0.7)


def test_portfolio_metrics_with_narrative_scenario_increases_risk():
    assets = [
        {
            "name": "AI Stock",
            "value": 50000,
            "expected_return": 15.0,
            "volatility": 25.0,
            "beta": 1.3,
            "narrative_exposure": 1.0,
        },
        {
            "name": "Bond",
            "value": 50000,
            "expected_return": 3.0,
            "volatility": 5.0,
            "beta": 0.3,
            "narrative_exposure": 0.0,
        },
    ]

    baseline = calculate_portfolio_metrics(assets)
    stressed = calculate_portfolio_metrics(
        assets,
        narrative_scenario={"probability": 0.3, "severity": -0.6},
    )

    # Lo scenario narrativo, applicato a un asset esposto, deve aumentare la
    # volatilità e ridurre il rendimento atteso rispetto al caso base.
    assert stressed["volatility"] > baseline["volatility"]
    assert stressed["expected_return"] < baseline["expected_return"]
    assert stressed["narrative_risk"] is not None
    assert math.isclose(stressed["narrative_risk"]["portfolio_exposure"], 0.5)


def test_portfolio_metrics_without_narrative_scenario_is_unchanged():
    assets = [
        {"name": "ETF", "value": 60000, "expected_return": 8.0, "volatility": 12.0, "beta": 1.0},
        {"name": "Bond", "value": 40000, "expected_return": 3.0, "volatility": 5.0, "beta": 0.3},
    ]

    result = calculate_portfolio_metrics(assets)
    assert result["narrative_risk"] is None


def test_efficient_frontier_returns_one_row_per_portfolio():
    assets = [
        {"name": "ETF", "value": 60000, "expected_return": 8.0, "volatility": 12.0},
        {"name": "Bond", "value": 40000, "expected_return": 3.0, "volatility": 5.0},
    ]

    frontier = simulate_efficient_frontier(assets, num_portfolios=500, seed=1)

    assert len(frontier) == 500
    assert (frontier["volatility"] >= 0.0).all()
    # Con solo due asset (rendimenti 3% e 8%), nessun portafoglio pesato
    # positivamente può avere un rendimento fuori da questo intervallo.
    assert frontier["expected_return"].between(0.03, 0.08).all()


def test_efficient_frontier_is_reproducible_with_same_seed():
    assets = [
        {"name": "ETF", "value": 60000, "expected_return": 8.0, "volatility": 12.0},
        {"name": "Bond", "value": 40000, "expected_return": 3.0, "volatility": 5.0},
    ]

    first = simulate_efficient_frontier(assets, num_portfolios=100, seed=7)
    second = simulate_efficient_frontier(assets, num_portfolios=100, seed=7)

    pd.testing.assert_frame_equal(first, second)


def test_efficient_frontier_needs_at_least_two_assets():
    result = simulate_efficient_frontier(
        [{"name": "ETF", "value": 60000, "expected_return": 8.0, "volatility": 12.0}]
    )

    assert result.empty


def test_bond_metrics_and_compound_growth_are_reasonable():
    bond = calculate_bond_metrics(face_value=1000.0, coupon_rate=0.05, years_to_maturity=5.0, market_price=950.0, frequency=2)
    assert bond["yield_to_maturity"] > 0.0
    assert bond["macaulay_duration_years"] > 0.0
    assert bond["modified_duration_years"] > 0.0

    growth = simulate_compound_growth(
        principal=10000.0,
        annual_rate=0.06,
        years=10.0,
        contribution_per_year=1200.0,
        inflation_rate=0.02,
        tax_rate=0.23,
        compounding_periods=12,
    )
    assert growth["final_value_nominal"] > growth["principal"]
    assert growth["real_value_after_inflation"] > 0.0
    assert growth["after_tax_value"] > 0.0
