// CHANGELOG
// ---------
// v1.0 - 2026-09-23
//     - Prima versione C++. Porting 1:1 della logica di calcolo di
//       risk_engine.py (Python, v1.2) in RiskEngine
//       (https://github.com/TheVime/RiskEngine). Le formule, le costanti
//       (DEFAULT_AVERAGE_CORRELATION, soglie di risk_label, ecc.) e l'ordine
//       delle operazioni sono stati mantenuti identici all'originale per
//       riprodurne il comportamento numerico. Le uniche differenze
//       intenzionali sono:
//         * il generatore di numeri casuali è std::mt19937_64 invece del
//           PCG64 di NumPy: la riproducibilità a parità di seed vale
//           all'interno di questo programma, non byte-per-byte rispetto a
//           Python;
//         * gli errori di validazione sono std::invalid_argument invece di
//           ValueError.
//       Riferimenti alle formule usate, per approfondire:
//         - Modern Portfolio Theory (varianza di portafoglio):
//           https://en.wikipedia.org/wiki/Modern_portfolio_theory
//         - Bond duration/convexity:
//           https://en.wikipedia.org/wiki/Bond_duration
//         - Fattore di rischio narrativo a singolo fattore (ispirato ai
//           modelli multi-fattore Barra/MSCI):
//           https://www.msci.com/documents/1296102/1339060/Barra_Risk_Model_Handbook.pdf

#include "risk_engine/risk_engine.hpp"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <random>
#include <stdexcept>

namespace risk_engine {

namespace {

// Percentile "lineare" identico al default di numpy.percentile(): interpola
// linearmente tra i due valori adiacenti nell'array ordinato.
double percentile(std::vector<double> values, double p) {
    if (values.empty()) return 0.0;
    std::sort(values.begin(), values.end());
    const double rank = (p / 100.0) * static_cast<double>(values.size() - 1);
    const auto lower = static_cast<size_t>(std::floor(rank));
    const auto upper = static_cast<size_t>(std::ceil(rank));
    if (lower == upper) return values[lower];
    const double fraction = rank - static_cast<double>(lower);
    return values[lower] + (values[upper] - values[lower]) * fraction;
}

double median(std::vector<double> values) { return percentile(std::move(values), 50.0); }

double mean(const std::vector<double>& values) {
    if (values.empty()) return 0.0;
    return std::accumulate(values.begin(), values.end(), 0.0) / static_cast<double>(values.size());
}

// Deviazione standard campionaria (ddof=1, come np.std(..., ddof=1)).
double sample_stdev(const std::vector<double>& values) {
    if (values.size() < 2) return 0.0;
    const double m = mean(values);
    double sum_sq = 0.0;
    for (double v : values) sum_sq += (v - m) * (v - m);
    return std::sqrt(sum_sq / static_cast<double>(values.size() - 1));
}

// Campiona un vettore di pesi non-negativi che sommano a 1 da una
// distribuzione di Dirichlet simmetrica (alpha=1 per ogni componente),
// generando n variabili Gamma(1,1) indipendenti (= esponenziali di media 1)
// e normalizzandole per la loro somma. Equivalente di
// numpy.random.Generator.dirichlet(np.ones(n)). Vedi
// https://numpy.org/doc/stable/reference/random/generated/numpy.random.Generator.dirichlet.html
std::vector<double> sample_dirichlet_uniform(size_t n, std::mt19937_64& rng) {
    std::exponential_distribution<double> exp_dist(1.0);
    std::vector<double> weights(n);
    double total = 0.0;
    for (size_t i = 0; i < n; ++i) {
        weights[i] = exp_dist(rng);
        total += weights[i];
    }
    if (total > 0.0) {
        for (double& w : weights) w /= total;
    }
    return weights;
}

} // namespace

double normalize_percentage(double value) {
    if (!std::isfinite(value)) return 0.0;
    if (std::abs(value) > 1.0) return value / 100.0;
    return value;
}

std::string risk_label(double risk_score) {
    if (risk_score < 35.0) return "Basso";
    if (risk_score < 60.0) return "Moderato";
    if (risk_score < 80.0) return "Elevato";
    return "Molto elevato";
}

double portfolio_volatility(const std::vector<double>& weights,
                             const std::vector<double>& volatilities,
                             double avg_correlation) {
    const double weight_sum = std::accumulate(weights.begin(), weights.end(), 0.0);
    if (weights.empty() || weight_sum == 0.0) return 0.0;

    double variance = 0.0;
    for (size_t i = 0; i < weights.size(); ++i) {
        for (size_t j = 0; j < weights.size(); ++j) {
            const double corr = (i != j) ? avg_correlation : 1.0;
            variance += weights[i] * weights[j] * corr * volatilities[i] * volatilities[j];
        }
    }
    return std::sqrt(std::max(variance, 0.0));
}

NarrativeRiskResult calculate_narrative_factor_risk(const std::vector<double>& weights,
                                                     const std::vector<double>& narrative_exposures,
                                                     double probability,
                                                     double severity) {
    probability = std::min(std::max(probability, 0.0), 1.0);

    double portfolio_exposure = 0.0;
    for (size_t i = 0; i < weights.size() && i < narrative_exposures.size(); ++i) {
        portfolio_exposure += weights[i] * narrative_exposures[i];
    }

    const double factor_mean = probability * severity;
    const double factor_variance = probability * (1.0 - probability) * severity * severity;

    NarrativeRiskResult result;
    result.portfolio_exposure = portfolio_exposure;
    result.probability = probability;
    result.severity = severity;
    result.expected_return_impact = portfolio_exposure * factor_mean;
    result.variance_contribution = portfolio_exposure * portfolio_exposure * factor_variance;
    result.stressed_loss_if_realized = portfolio_exposure * severity;
    return result;
}

PortfolioMetrics calculate_portfolio_metrics(std::vector<Asset> assets,
                                              double risk_free_rate,
                                              double avg_correlation,
                                              const std::optional<NarrativeScenario>& narrative_scenario) {
    // Normalizzazione dei campi, identica a quella applicata riga per riga
    // in Python prima di qualunque calcolo.
    std::vector<Asset> filtered;
    filtered.reserve(assets.size());
    for (auto& asset : assets) {
        if (asset.name.empty()) continue;
        asset.expected_return = normalize_percentage(asset.expected_return);
        asset.volatility = normalize_percentage(asset.volatility);
        asset.narrative_exposure = std::min(std::max(normalize_percentage(asset.narrative_exposure), 0.0), 1.0);
        filtered.push_back(asset);
    }

    PortfolioMetrics result;
    if (filtered.empty()) {
        result.risk_level = "Nessun asset";
        return result;
    }

    double total_value = 0.0;
    for (const auto& a : filtered) total_value += a.value;
    if (total_value <= 0.0) {
        throw std::invalid_argument("Il valore totale del portafoglio deve essere maggiore di zero.");
    }

    std::vector<double> weights, volatilities, betas, expected_returns, narrative_exposures;
    weights.reserve(filtered.size());
    volatilities.reserve(filtered.size());
    betas.reserve(filtered.size());
    expected_returns.reserve(filtered.size());
    narrative_exposures.reserve(filtered.size());
    for (const auto& a : filtered) {
        weights.push_back(a.value / total_value);
        volatilities.push_back(a.volatility);
        betas.push_back(a.beta);
        expected_returns.push_back(a.expected_return);
        narrative_exposures.push_back(a.narrative_exposure);
    }

    double portfolio_return = 0.0, portfolio_beta = 0.0;
    for (size_t i = 0; i < filtered.size(); ++i) {
        portfolio_return += weights[i] * expected_returns[i];
        portfolio_beta += weights[i] * betas[i];
    }
    double vol = portfolio_volatility(weights, volatilities, avg_correlation);
    double sharpe = (vol > 0.0) ? (portfolio_return - risk_free_rate) / vol : 0.0;

    // Matrice di covarianza: correlazione media costante fuori diagonale,
    // varianza piena in diagonale, scalata per outer(vol, vol).
    const size_t n = filtered.size();
    std::vector<std::vector<double>> covariance(n, std::vector<double>(n, 0.0));
    for (size_t i = 0; i < n; ++i) {
        for (size_t j = 0; j < n; ++j) {
            const double corr = (i == j) ? 1.0 : avg_correlation;
            covariance[i][j] = corr * volatilities[i] * volatilities[j];
        }
    }

    double portfolio_variance = 0.0;
    std::vector<double> marginal(n, 0.0);
    for (size_t i = 0; i < n; ++i) {
        for (size_t j = 0; j < n; ++j) {
            marginal[i] += covariance[i][j] * weights[j];
        }
        portfolio_variance += weights[i] * marginal[i];
    }

    std::vector<double> risk_contribution_pct(n, 0.0);
    if (portfolio_variance > 0.0) {
        for (size_t i = 0; i < n; ++i) {
            const double contribution = (weights[i] * marginal[i]) / portfolio_variance * 100.0;
            risk_contribution_pct[i] = std::min(std::max(contribution, 0.0), 100.0);
        }
    }

    std::optional<NarrativeRiskResult> narrative_risk;
    if (narrative_scenario.has_value()) {
        narrative_risk = calculate_narrative_factor_risk(weights, narrative_exposures,
                                                          narrative_scenario->probability,
                                                          narrative_scenario->severity);
        // Il fattore narrativo si somma alla varianza storica (assumendo
        // indipendenza tra il fattore tematico e i fattori già impliciti
        // nella covarianza storica) e sposta il rendimento atteso in base
        // all'impatto probabilistico stimato.
        const double variance_with_narrative = vol * vol + narrative_risk->variance_contribution;
        vol = std::sqrt(std::max(variance_with_narrative, 0.0));
        portfolio_return += narrative_risk->expected_return_impact;
        if (vol > 0.0) sharpe = (portfolio_return - risk_free_rate) / vol;
    }

    const double risk_score = std::min(100.0, std::max(0.0, vol * 100.0 * 1.6 + portfolio_beta * 15.0));

    result.portfolio_value = total_value;
    result.expected_return = portfolio_return;
    result.volatility = vol;
    result.beta = portfolio_beta;
    result.sharpe = sharpe;
    result.risk_score = risk_score;
    result.risk_level = risk_label(risk_score);
    result.narrative_risk = narrative_risk;

    result.asset_risk_contribution.reserve(n);
    for (size_t i = 0; i < n; ++i) {
        AssetRiskContribution row;
        row.name = filtered[i].name;
        row.ticker = filtered[i].ticker;
        row.value = filtered[i].value;
        row.weight = weights[i];
        row.expected_return = expected_returns[i];
        row.volatility = volatilities[i];
        row.beta = betas[i];
        row.risk_contribution_pct = risk_contribution_pct[i];
        result.asset_risk_contribution.push_back(std::move(row));
    }

    return result;
}

std::vector<FrontierPoint> simulate_efficient_frontier(std::vector<Asset> assets,
                                                        double risk_free_rate,
                                                        double avg_correlation,
                                                        int num_portfolios,
                                                        unsigned seed) {
    std::vector<Asset> filtered;
    for (auto& asset : assets) {
        if (asset.name.empty() || asset.value <= 0.0) continue;
        asset.expected_return = normalize_percentage(asset.expected_return);
        asset.volatility = normalize_percentage(asset.volatility);
        filtered.push_back(asset);
    }

    if (filtered.size() < 2 || num_portfolios <= 0) return {};

    const size_t n = filtered.size();
    std::vector<double> expected_returns(n), volatilities(n);
    for (size_t i = 0; i < n; ++i) {
        expected_returns[i] = filtered[i].expected_return;
        volatilities[i] = filtered[i].volatility;
    }

    std::vector<std::vector<double>> covariance(n, std::vector<double>(n, 0.0));
    for (size_t i = 0; i < n; ++i) {
        for (size_t j = 0; j < n; ++j) {
            const double corr = (i == j) ? 1.0 : avg_correlation;
            covariance[i][j] = corr * volatilities[i] * volatilities[j];
        }
    }

    std::mt19937_64 rng(seed);
    std::vector<FrontierPoint> frontier;
    frontier.reserve(static_cast<size_t>(num_portfolios));

    for (int p = 0; p < num_portfolios; ++p) {
        const std::vector<double> w = sample_dirichlet_uniform(n, rng);

        double ret = 0.0;
        for (size_t i = 0; i < n; ++i) ret += w[i] * expected_returns[i];

        double variance = 0.0;
        for (size_t i = 0; i < n; ++i) {
            double row_sum = 0.0;
            for (size_t j = 0; j < n; ++j) row_sum += covariance[i][j] * w[j];
            variance += w[i] * row_sum;
        }
        const double vol = std::sqrt(std::max(variance, 0.0));
        const double sharpe = (vol > 0.0) ? (ret - risk_free_rate) / vol : 0.0;

        frontier.push_back({ret, vol, sharpe});
    }

    return frontier;
}

BondMetrics calculate_bond_metrics(double face_value,
                                    double coupon_rate,
                                    double years_to_maturity,
                                    std::optional<double> market_price,
                                    std::optional<double> annual_yield,
                                    int frequency) {
    years_to_maturity = std::max(years_to_maturity, 0.0);
    frequency = std::max(frequency, 1);
    const double resolved_market_price = market_price.value_or(face_value);

    const double coupon_payment = face_value * coupon_rate / frequency;
    const int periods = std::max(static_cast<int>(std::llround(years_to_maturity * frequency)), 1);

    double ytm = annual_yield.value_or(
        std::max(0.0, coupon_rate + (face_value - resolved_market_price) /
                                         std::max(years_to_maturity * face_value, 1.0)));
    ytm = std::max(ytm, 0.0);

    if (resolved_market_price > 0.0 && face_value > 0.0 && years_to_maturity > 0.0) {
        double ytm_guess = ytm;
        for (int iteration = 0; iteration < 200; ++iteration) {
            const double discount_rate = ytm_guess / frequency;
            double pv = 0.0, derivative = 0.0;
            for (int period_index = 1; period_index <= periods; ++period_index) {
                const double cash_flow = (period_index < periods) ? coupon_payment : coupon_payment + face_value;
                pv += cash_flow / std::pow(1.0 + discount_rate, period_index);
                derivative -= period_index * cash_flow / std::pow(1.0 + discount_rate, period_index + 1);
            }
            derivative *= 1.0 / frequency;
            if (std::abs(pv - resolved_market_price) < 1e-9) break;
            if (std::abs(derivative) < 1e-12) break;
            ytm_guess -= (pv - resolved_market_price) / derivative;
            if (ytm_guess < 0.0) ytm_guess = 0.0;
        }
        ytm = std::max(0.0, ytm_guess);
    }

    const double yield_per_period = ytm / frequency;
    std::vector<std::pair<int, double>> pv_cash_flows;
    double total_present_value = 0.0;
    for (int period_index = 1; period_index <= periods; ++period_index) {
        const double cash_flow = (period_index < periods) ? coupon_payment : coupon_payment + face_value;
        const double pv = cash_flow / std::pow(1.0 + yield_per_period, period_index);
        total_present_value += pv;
        pv_cash_flows.emplace_back(period_index, pv);
    }

    double macaulay_duration = 0.0;
    if (total_present_value > 0.0) {
        for (const auto& [period_index, pv] : pv_cash_flows) {
            macaulay_duration += (static_cast<double>(period_index) / frequency) * pv;
        }
        macaulay_duration /= total_present_value;
    }

    double modified_duration = 0.0;
    if (yield_per_period > -1.0) modified_duration = macaulay_duration / (1.0 + yield_per_period);

    double convexity = 0.0;
    if (std::abs(yield_per_period) < 1.0 && total_present_value > 0.0) {
        double convexity_total = 0.0;
        for (int period_index = 1; period_index <= periods; ++period_index) {
            const double cash_flow = (period_index < periods) ? coupon_payment : coupon_payment + face_value;
            convexity_total += (period_index * (period_index + 1) * cash_flow) /
                                std::pow(1.0 + yield_per_period, period_index + 2);
        }
        convexity = convexity_total / total_present_value;
    }

    BondMetrics result;
    result.face_value = face_value;
    result.market_price = resolved_market_price;
    result.coupon_payment = coupon_payment;
    result.coupon_rate = coupon_rate;
    result.yield_to_maturity = ytm;
    result.macaulay_duration_years = macaulay_duration;
    result.modified_duration_years = modified_duration;
    result.convexity = convexity;
    result.price_from_yield = total_present_value;
    return result;
}

CompoundGrowthResult simulate_compound_growth(double principal,
                                               double annual_rate,
                                               double years,
                                               double contribution_per_year,
                                               const std::string& contribution_frequency,
                                               double inflation_rate,
                                               double tax_rate,
                                               int compounding_periods) {
    annual_rate = normalize_percentage(annual_rate);
    inflation_rate = std::abs(normalize_percentage(inflation_rate));
    tax_rate = std::min(std::max(tax_rate, 0.0), 1.0);
    years = std::max(years, 0.0);
    compounding_periods = std::max(compounding_periods, 1);

    int contribution_interval;
    if (contribution_frequency.rfind("month", 0) == 0) {
        contribution_interval = 1;
    } else if (contribution_frequency.rfind("quarter", 0) == 0) {
        contribution_interval = std::max(1, static_cast<int>(std::llround(compounding_periods / 4.0)));
    } else {
        contribution_interval = compounding_periods;
    }

    const double period_rate = annual_rate / compounding_periods;
    const int total_periods = static_cast<int>(std::llround(years * compounding_periods));

    double balance = principal;
    double total_contributions = principal;
    std::vector<CompoundGrowthYearPoint> yearly_history;

    for (int period_index = 1; period_index <= total_periods; ++period_index) {
        balance *= 1.0 + period_rate;

        if (contribution_per_year > 0.0 && period_index % contribution_interval == 0) {
            balance += contribution_per_year;
            total_contributions += contribution_per_year;
        }

        if (period_index % compounding_periods == 0 || period_index == total_periods) {
            const double year_number = static_cast<double>(period_index) / compounding_periods;
            const int year_label = (year_number > 0.0) ? static_cast<int>(std::ceil(year_number)) : 0;
            const double gross_gain = std::max(balance - total_contributions, 0.0);
            const double tax_due = gross_gain * tax_rate;
            const double after_tax_value = balance - tax_due;
            const double real_value = (year_number > 0.0)
                                           ? after_tax_value / std::pow(1.0 + inflation_rate, year_number)
                                           : after_tax_value;
            yearly_history.push_back({year_label, balance, after_tax_value, real_value});
        }
    }

    if (years <= 0.0) yearly_history.clear();

    balance = yearly_history.empty() ? principal : yearly_history.back().nominal_value;
    const double gross_gain = std::max(balance - total_contributions, 0.0);
    const double tax_due = gross_gain * tax_rate;
    const double net_after_tax = balance - tax_due;
    const double discounted_for_inflation =
        (years > 0.0) ? net_after_tax / std::pow(1.0 + inflation_rate, years) : net_after_tax;
    const double real_gain_after_inflation = discounted_for_inflation - principal;

    CompoundGrowthResult result;
    result.principal = principal;
    result.total_contributions = total_contributions;
    result.final_value_nominal = balance;
    result.after_tax_value = net_after_tax;
    result.real_value_after_inflation = discounted_for_inflation;
    result.real_gain_after_inflation = real_gain_after_inflation;
    result.tax_due = tax_due;
    result.inflation_adjusted_rate =
        (principal > 0.0 && years > 0.0) ? (std::pow(discounted_for_inflation / principal, 1.0 / std::max(years, 1.0)) - 1.0)
                                          : 0.0;
    result.yearly_history = std::move(yearly_history);
    return result;
}

MonteCarloResult simulate_portfolio_scenarios(std::vector<Asset> assets,
                                               int scenarios,
                                               int horizon_days,
                                               unsigned seed,
                                               const std::map<std::string, std::vector<double>>& history_map) {
    MonteCarloResult result;

    std::vector<Asset> filtered;
    for (auto& asset : assets) {
        if (asset.name.empty() || asset.value <= 0.0) continue;
        asset.expected_return = normalize_percentage(asset.expected_return);
        asset.volatility = normalize_percentage(asset.volatility);
        std::transform(asset.ticker.begin(), asset.ticker.end(), asset.ticker.begin(), ::toupper);
        filtered.push_back(asset);
    }

    if (filtered.empty() || scenarios <= 0) {
        result.historical_source = "Nessun asset disponibile";
        return result;
    }

    double total_value = 0.0;
    for (const auto& a : filtered) total_value += a.value;

    std::vector<double> weights(filtered.size());
    for (size_t i = 0; i < filtered.size(); ++i) weights[i] = filtered[i].value / total_value;

    bool used_history = false;
    std::mt19937_64 rng(seed);

    std::vector<double> scenario_results(static_cast<size_t>(scenarios), 0.0);
    std::vector<double> scenario_returns(static_cast<size_t>(scenarios) * static_cast<size_t>(horizon_days), 0.0);

    for (size_t asset_index = 0; asset_index < filtered.size(); ++asset_index) {
        const auto& asset = filtered[asset_index];
        auto history_it = asset.ticker.empty() ? history_map.end() : history_map.find(asset.ticker);
        const bool has_history = history_it != history_map.end() && !history_it->second.empty();
        if (has_history) used_history = true;

        std::uniform_int_distribution<size_t> bootstrap_dist(0, has_history ? history_it->second.size() - 1 : 0);
        std::normal_distribution<double> normal_dist(asset.expected_return, std::max(asset.volatility, 0.01));

        for (int s = 0; s < scenarios; ++s) {
            for (int d = 0; d < horizon_days; ++d) {
                double r;
                if (has_history) {
                    r = history_it->second[bootstrap_dist(rng)];
                } else {
                    r = std::min(std::max(normal_dist(rng), -0.75), 0.75);
                }
                scenario_returns[static_cast<size_t>(s) * horizon_days + d] += weights[asset_index] * r;
            }
        }
    }

    for (int s = 0; s < scenarios; ++s) {
        double product = 1.0;
        for (int d = 0; d < horizon_days; ++d) {
            product *= 1.0 + scenario_returns[static_cast<size_t>(s) * horizon_days + d];
        }
        scenario_results[static_cast<size_t>(s)] = product - 1.0;
    }

    int loss_count = 0;
    for (double r : scenario_results) {
        if (r < 0.0) ++loss_count;
    }

    result.portfolio_value = total_value;
    result.expected_return = mean(scenario_results);
    result.volatility = sample_stdev(scenario_results);
    result.p05 = percentile(scenario_results, 5.0);
    result.p95 = percentile(scenario_results, 95.0);
    result.median = median(scenario_results);
    result.probability_loss = static_cast<double>(loss_count) / static_cast<double>(scenario_results.size());
    result.portfolio_return_distribution = std::move(scenario_results);
    result.historical_source =
        used_history ? "Yahoo Finance - rendimenti storici giornalieri ricampionati per generare gli scenari"
                     : "Fallback: rendimenti stimati dalle ipotesi utente (dati storici non disponibili)";
    return result;
}

} // namespace risk_engine
