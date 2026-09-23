// CHANGELOG
// ---------
// v1.0 - 2026-09-23
//     - Prima versione C++, porting di test_risk_engine.py con doctest
//       (https://github.com/doctest/doctest). I due test che in Python
//       usano `monkeypatch` per simulare le risposte di rete di Yahoo
//       Finance (test_lookup_isin_to_asset_maps_a_realistic_isin e
//       test_lookup_isin_uses_fallback_when_yahoo_is_rate_limited) sono
//       sostituiti da un singolo test sulla mappa di fallback locale
//       (europea, hardcoded), che non richiede rete: verificare il vero
//       fetch da Yahoo qui richiederebbe un test di integrazione con
//       accesso a Internet, fuori dallo scopo di uno unit test.
#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cmath>
#include <map>

#include "risk_engine/market_data.hpp"
#include "risk_engine/risk_engine.hpp"

using namespace risk_engine;

TEST_CASE("calculate_portfolio_metrics calcola valori attesi") {
    std::vector<Asset> assets = {
        {"ETF", "", 60000, 8.0, 12.0, 1.0, 0.0},
        {"Bond", "", 40000, 3.0, 5.0, 0.3, 0.0},
    };

    const auto result = calculate_portfolio_metrics(assets, 0.02);

    CHECK(result.portfolio_value == doctest::Approx(100000.0));
    CHECK(result.expected_return > 0.0);
    CHECK(result.volatility > 0.0);
    CHECK(result.beta > 0.0);
    CHECK(!result.risk_level.empty());
    CHECK(result.risk_score >= 0.0);
}

TEST_CASE("un portafoglio vuoto ha metriche a zero") {
    const auto result = calculate_portfolio_metrics({});

    CHECK(result.portfolio_value == doctest::Approx(0.0));
    CHECK(result.expected_return == doctest::Approx(0.0));
    CHECK(result.volatility == doctest::Approx(0.0));
    CHECK(result.risk_score == doctest::Approx(0.0));
}

TEST_CASE("gli input in percentuale vengono normalizzati") {
    std::vector<Asset> assets = {{"Stock", "", 1000, 10, 20, 1.2, 0.0}};

    const auto result = calculate_portfolio_metrics(assets);
    CHECK(result.expected_return == doctest::Approx(0.1).epsilon(1e-6));
    CHECK(result.volatility == doctest::Approx(0.2).epsilon(1e-6));
}

TEST_CASE("la simulazione usa i campioni storici quando disponibili") {
    std::map<std::string, std::vector<double>> history_map = {
        {"ASSET1", {0.01, -0.02, 0.03, 0.04, -0.01, 0.02, 0.01, -0.03, 0.02, 0.05}},
        {"ASSET2", {0.005, -0.01, 0.02, 0.015, 0.01, -0.02, 0.03, 0.005, -0.01, 0.02}},
    };
    std::vector<Asset> assets = {
        {"Asset 1", "ASSET1", 60000, 8.0, 12.0, 1.0, 0.0},
        {"Asset 2", "ASSET2", 40000, 3.0, 5.0, 0.3, 0.0},
    };

    const auto result = simulate_portfolio_scenarios(assets, 200, 10, 7, history_map);

    CHECK(result.portfolio_return_distribution.size() == 200);
    CHECK(!result.historical_source.empty());
    CHECK(result.portfolio_value == doctest::Approx(100000.0));
    CHECK(result.probability_loss >= 0.0);
    CHECK(result.probability_loss <= 1.0);
}

TEST_CASE("l'ISIN europeo di fallback viene risolto senza rete") {
    const auto match = lookup_isin_to_asset("IE00B4L5Y983");

    CHECK(match.found);
    CHECK(match.ticker == "IWDA.L");
    CHECK(match.name == "iShares Core MSCI World UCITS ETF USD (Acc)");
    CHECK(match.value == doctest::Approx(10000));
    CHECK(match.beta > 0.0);
    CHECK(match.volatility > 0.0);
}

TEST_CASE("un fattore narrativo a esposizione zero non ha effetto") {
    std::vector<double> weights = {0.6, 0.4};
    std::vector<double> exposures = {0.0, 0.0};

    const auto result = calculate_narrative_factor_risk(weights, exposures, 0.2, -0.6);

    CHECK(result.portfolio_exposure == doctest::Approx(0.0));
    CHECK(result.variance_contribution == doctest::Approx(0.0));
    CHECK(result.expected_return_impact == doctest::Approx(0.0));
    CHECK(result.stressed_loss_if_realized == doctest::Approx(0.0));
}

TEST_CASE("un fattore narrativo a esposizione piena rispetta la teoria") {
    // Un solo asset, interamente esposto al tema: il portafoglio eredita
    // esattamente media e varianza della variabile Bernoulli-like del fattore.
    std::vector<double> weights = {1.0};
    std::vector<double> exposures = {1.0};
    const double probability = 0.25, severity = -0.5;

    const auto result = calculate_narrative_factor_risk(weights, exposures, probability, severity);

    const double expected_mean = probability * severity;
    const double expected_variance = probability * (1 - probability) * severity * severity;

    CHECK(result.portfolio_exposure == doctest::Approx(1.0));
    CHECK(result.expected_return_impact == doctest::Approx(expected_mean));
    CHECK(result.variance_contribution == doctest::Approx(expected_variance));
    CHECK(result.stressed_loss_if_realized == doctest::Approx(severity));
}

TEST_CASE("un fattore narrativo scala con l'esposizione parziale") {
    // Portafoglio diversificato: solo metà del valore è esposto al tema.
    std::vector<double> weights = {0.5, 0.5};
    std::vector<double> exposures = {1.0, 0.0};

    const auto result = calculate_narrative_factor_risk(weights, exposures, 0.3, -0.7);

    CHECK(result.portfolio_exposure == doctest::Approx(0.5));
    CHECK(result.stressed_loss_if_realized == doctest::Approx(0.5 * -0.7));
}

TEST_CASE("lo scenario narrativo aumenta il rischio del portafoglio") {
    std::vector<Asset> assets = {
        {"AI Stock", "", 50000, 15.0, 25.0, 1.3, 1.0},
        {"Bond", "", 50000, 3.0, 5.0, 0.3, 0.0},
    };

    const auto baseline = calculate_portfolio_metrics(assets);
    const auto stressed = calculate_portfolio_metrics(assets, 0.02, 0.35, NarrativeScenario{0.3, -0.6});

    // Lo scenario narrativo, applicato a un asset esposto, deve aumentare la
    // volatilità e ridurre il rendimento atteso rispetto al caso base.
    CHECK(stressed.volatility > baseline.volatility);
    CHECK(stressed.expected_return < baseline.expected_return);
    REQUIRE(stressed.narrative_risk.has_value());
    CHECK(stressed.narrative_risk->portfolio_exposure == doctest::Approx(0.5));
}

TEST_CASE("senza scenario narrativo il risultato è invariato") {
    std::vector<Asset> assets = {
        {"ETF", "", 60000, 8.0, 12.0, 1.0, 0.0},
        {"Bond", "", 40000, 3.0, 5.0, 0.3, 0.0},
    };

    const auto result = calculate_portfolio_metrics(assets);
    CHECK(!result.narrative_risk.has_value());
}

TEST_CASE("la frontiera efficiente restituisce una riga per portafoglio") {
    std::vector<Asset> assets = {
        {"ETF", "", 60000, 8.0, 12.0, 1.0, 0.0},
        {"Bond", "", 40000, 3.0, 5.0, 1.0, 0.0},
    };

    const auto frontier = simulate_efficient_frontier(assets, 0.02, 0.35, 500, 1);

    CHECK(frontier.size() == 500);
    for (const auto& point : frontier) {
        CHECK(point.volatility >= 0.0);
        // Con solo due asset (rendimenti 3% e 8%), nessun portafoglio pesato
        // positivamente può avere un rendimento fuori da questo intervallo.
        CHECK(point.expected_return >= 0.03);
        CHECK(point.expected_return <= 0.08);
    }
}

TEST_CASE("la frontiera efficiente è riproducibile con lo stesso seed") {
    std::vector<Asset> assets = {
        {"ETF", "", 60000, 8.0, 12.0, 1.0, 0.0},
        {"Bond", "", 40000, 3.0, 5.0, 1.0, 0.0},
    };

    const auto first = simulate_efficient_frontier(assets, 0.02, 0.35, 100, 7);
    const auto second = simulate_efficient_frontier(assets, 0.02, 0.35, 100, 7);

    REQUIRE(first.size() == second.size());
    for (size_t i = 0; i < first.size(); ++i) {
        CHECK(first[i].expected_return == doctest::Approx(second[i].expected_return));
        CHECK(first[i].volatility == doctest::Approx(second[i].volatility));
    }
}

TEST_CASE("la frontiera efficiente richiede almeno due asset") {
    std::vector<Asset> assets = {{"ETF", "", 60000, 8.0, 12.0, 1.0, 0.0}};
    const auto result = simulate_efficient_frontier(assets);
    CHECK(result.empty());
}

TEST_CASE("le metriche obbligazionarie e la crescita composta sono ragionevoli") {
    const auto bond = calculate_bond_metrics(1000.0, 0.05, 5.0, 950.0, std::nullopt, 2);
    CHECK(bond.yield_to_maturity > 0.0);
    CHECK(bond.macaulay_duration_years > 0.0);
    CHECK(bond.modified_duration_years > 0.0);

    const auto growth = simulate_compound_growth(10000.0, 0.06, 10.0, 1200.0, "annual", 0.02, 0.23, 12);
    CHECK(growth.final_value_nominal > growth.principal);
    CHECK(growth.real_value_after_inflation > 0.0);
    CHECK(growth.after_tax_value > 0.0);
}

TEST_CASE("la crescita composta ammette tassi negativi e anni frazionari") {
    const auto negative_growth = simulate_compound_growth(10000.0, -0.10, 5.0, 0.0, "annual", 0.02, 0.0, 12);
    CHECK(negative_growth.final_value_nominal < negative_growth.principal);

    const auto fractional_years = simulate_compound_growth(10000.0, 0.08, 2.5, 0.0, "annual", 0.0, 0.0, 12);
    const double expected = 10000.0 * std::pow(1.0 + 0.08 / 12.0, 2.5 * 12.0);
    CHECK(fractional_years.final_value_nominal == doctest::Approx(expected).epsilon(1e-6));
}

TEST_CASE("il contributo annuale non viene aggiunto mensilmente") {
    const auto annual = simulate_compound_growth(10000.0, 0.0, 2.0, 1200.0, "annual", 0.0, 0.0, 12);
    const auto monthly = simulate_compound_growth(10000.0, 0.0, 2.0, 1200.0, "monthly", 0.0, 0.0, 12);

    CHECK(annual.final_value_nominal > 10000.0);
    CHECK(monthly.final_value_nominal > annual.final_value_nominal);
    CHECK(annual.total_contributions == doctest::Approx(10000.0 + 1200.0 + 1200.0));
}
