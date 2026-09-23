// CHANGELOG
// ---------
// v1.0 - 2026-09-23
//     - Prima versione C++: struct che sostituiscono i dict/pd.DataFrame
//       usati in risk_engine.py (Python). Ogni campo corrisponde 1:1 a una
//       colonna o a una chiave del dizionario originale.
#pragma once

#include <optional>
#include <string>
#include <vector>

namespace risk_engine {

// Equivalente di una riga di asset_rows in risk_engine.py (dict o riga di
// DataFrame). I campi expected_return/volatility/narrative_exposure possono
// essere passati sia in percentuale (es. 8.0) sia in forma decimale (0.08):
// vengono normalizzati internamente da normalize_percentage(), esattamente
// come fa _normalize_percentage() in Python.
struct Asset {
    std::string name;
    std::string ticker;
    double value = 0.0;
    double expected_return = 0.0;
    double volatility = 0.0;
    double beta = 1.0;
    double narrative_exposure = 0.0;
};

// Riga di output di calculate_portfolio_metrics()["asset_risk_contribution"].
struct AssetRiskContribution {
    std::string name;
    std::string ticker;
    double value = 0.0;
    double weight = 0.0;
    double expected_return = 0.0;
    double volatility = 0.0;
    double beta = 0.0;
    double risk_contribution_pct = 0.0;
};

// Parametro opzionale narrative_scenario di calculate_portfolio_metrics().
struct NarrativeScenario {
    double probability = 0.0;
    double severity = 0.0;
};

// Valore di ritorno di calculate_narrative_factor_risk().
struct NarrativeRiskResult {
    double portfolio_exposure = 0.0;
    double probability = 0.0;
    double severity = 0.0;
    double expected_return_impact = 0.0;
    double variance_contribution = 0.0;
    double stressed_loss_if_realized = 0.0;
};

// Valore di ritorno di calculate_portfolio_metrics().
struct PortfolioMetrics {
    double portfolio_value = 0.0;
    double expected_return = 0.0;
    double volatility = 0.0;
    double beta = 0.0;
    double sharpe = 0.0;
    double risk_score = 0.0;
    std::string risk_level;
    std::vector<AssetRiskContribution> asset_risk_contribution;
    std::optional<NarrativeRiskResult> narrative_risk; // nullopt = "None" in Python
};

// Una riga della "nuvola" di simulate_efficient_frontier().
struct FrontierPoint {
    double expected_return = 0.0;
    double volatility = 0.0;
    double sharpe = 0.0;
};

// Valore di ritorno di calculate_bond_metrics().
struct BondMetrics {
    double face_value = 0.0;
    double market_price = 0.0;
    double coupon_payment = 0.0;
    double coupon_rate = 0.0;
    double yield_to_maturity = 0.0;
    double macaulay_duration_years = 0.0;
    double modified_duration_years = 0.0;
    double convexity = 0.0;
    double price_from_yield = 0.0;
};

// Una riga di yearly_history in simulate_compound_growth().
struct CompoundGrowthYearPoint {
    int year = 0;
    double nominal_value = 0.0;
    double after_tax_value = 0.0;
    double real_value_after_inflation = 0.0;
};

// Valore di ritorno di simulate_compound_growth().
struct CompoundGrowthResult {
    double principal = 0.0;
    double total_contributions = 0.0;
    double final_value_nominal = 0.0;
    double after_tax_value = 0.0;
    double real_value_after_inflation = 0.0;
    double real_gain_after_inflation = 0.0;
    double tax_due = 0.0;
    double inflation_adjusted_rate = 0.0;
    std::vector<CompoundGrowthYearPoint> yearly_history;
};

// Valore di ritorno di simulate_portfolio_scenarios().
struct MonteCarloResult {
    double portfolio_value = 0.0;
    double expected_return = 0.0;
    double volatility = 0.0;
    double p05 = 0.0;
    double p95 = 0.0;
    double median = 0.0;
    double probability_loss = 0.0;
    std::vector<double> portfolio_return_distribution;
    std::string historical_source;
};

// Valore di ritorno di lookup_isin_to_asset(); found=false equivale al
// dict vuoto {} restituito da Python quando non trova nulla.
struct AssetLookupResult {
    bool found = false;
    std::string name;
    std::string ticker;
    std::string isin;
    double value = 0.0;
    double expected_return = 0.0;
    double volatility = 0.0;
    double beta = 1.0;
    std::string exchange;
    std::string asset_type;
};

} // namespace risk_engine
