// CHANGELOG
// ---------
// v1.0 - 2026-09-23
//     - Prima versione C++, porting 1:1 di risk_engine.py (Python) v1.2.
//       Ogni funzione qui sotto corrisponde alla funzione Python omonima;
//       le differenze di comportamento (se presenti) sono documentate nel
//       commento della relativa implementazione in risk_engine.cpp.
#pragma once

#include <map>
#include <optional>
#include <string>
#include <vector>

#include "risk_engine/types.hpp"

namespace risk_engine {

// Porta un valore da formato percentuale a formato decimale quando serve
// (se |value| > 1 viene diviso per 100). Equivalente di _normalize_percentage().
double normalize_percentage(double value);

// Etichetta testuale della fascia di rischio. Equivalente di _risk_label().
std::string risk_label(double risk_score);

// Volatilità di portafoglio con correlazione media costante fuori dalla
// diagonale. Equivalente di _portfolio_volatility().
double portfolio_volatility(const std::vector<double>& weights,
                             const std::vector<double>& volatilities,
                             double avg_correlation);

// Modella un rischio tematico/narrativo come fattore di rischio comune
// aggiuntivo. Vedi il commento esteso in risk_engine.cpp e
// https://www.msci.com/documents/1296102/1339060/Barra_Risk_Model_Handbook.pdf
// Equivalente di calculate_narrative_factor_risk().
NarrativeRiskResult calculate_narrative_factor_risk(const std::vector<double>& weights,
                                                     const std::vector<double>& narrative_exposures,
                                                     double probability,
                                                     double severity);

// Metriche di portafoglio (rendimento, volatilità, beta, Sharpe, risk score)
// e contributo al rischio per singolo asset. Equivalente di
// calculate_portfolio_metrics(). Lancia std::invalid_argument se il valore
// totale del portafoglio non è positivo (equivalente del ValueError Python).
PortfolioMetrics calculate_portfolio_metrics(std::vector<Asset> assets,
                                              double risk_free_rate = 0.02,
                                              double avg_correlation = 0.35,
                                              const std::optional<NarrativeScenario>& narrative_scenario = std::nullopt);

// Campiona num_portfolios portafogli a pesi casuali (Dirichlet) sugli stessi
// asset per disegnare una frontiera efficiente approssimata. Equivalente di
// simulate_efficient_frontier(). Vedi
// https://en.wikipedia.org/wiki/Modern_portfolio_theory
std::vector<FrontierPoint> simulate_efficient_frontier(std::vector<Asset> assets,
                                                        double risk_free_rate = 0.02,
                                                        double avg_correlation = 0.35,
                                                        int num_portfolios = 3000,
                                                        unsigned seed = 42);

// Metriche di un'obbligazione (YTM, duration di Macaulay, duration
// modificata, convessità) via ricerca di Newton sul prezzo. Equivalente di
// calculate_bond_metrics(). Se market_price è nullopt, si usa face_value; se
// annual_yield è nullopt, viene stimato e poi raffinato numericamente.
BondMetrics calculate_bond_metrics(double face_value = 1000.0,
                                    double coupon_rate = 0.05,
                                    double years_to_maturity = 5.0,
                                    std::optional<double> market_price = std::nullopt,
                                    std::optional<double> annual_yield = std::nullopt,
                                    int frequency = 2);

// Proietta la crescita composta di un capitale con contributi periodici,
// tasse sul guadagno e inflazione. Equivalente di simulate_compound_growth().
CompoundGrowthResult simulate_compound_growth(double principal = 10000.0,
                                               double annual_rate = 0.06,
                                               double years = 10.0,
                                               double contribution_per_year = 0.0,
                                               const std::string& contribution_frequency = "annual",
                                               double inflation_rate = 0.02,
                                               double tax_rate = 0.23,
                                               int compounding_periods = 12);

// Simulazione Monte Carlo del portafoglio su horizon_days giorni,
// ricampionando (bootstrap) i rendimenti storici giornalieri quando
// disponibili in history_map, altrimenti generandoli da una normale con i
// parametri dichiarati dall'utente. Equivalente di
// simulate_portfolio_scenarios().
MonteCarloResult simulate_portfolio_scenarios(std::vector<Asset> assets,
                                               int scenarios = 10000,
                                               int horizon_days = 252,
                                               unsigned seed = 42,
                                               const std::map<std::string, std::vector<double>>& history_map = {});

} // namespace risk_engine
