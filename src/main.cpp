// CHANGELOG
// ---------
// v1.0 - 2026-09-23
//     - Prima versione C++. Porting "a schermo" di app.py (Streamlit) su
//       Dear ImGui (https://github.com/ocornut/imgui) + ImPlot
//       (https://github.com/epezent/implot) con backend GLFW + OpenGL3.
//       Streamlit non ha equivalente C++, quindi la corrispondenza è per
//       sezione/funzione, non pixel-per-pixel:
//         st.sidebar                      -> pannello "Parametri globali" a sinistra
//         st.radio sezioni                -> tab bar (Dashboard / Monte Carlo / Rischio)
//         st.data_editor (tabella asset)  -> tabella ImGui editabile riga per riga
//         st.altair_chart (donut/gauge)   -> ImPlot::PlotPieChart
//         st.altair_chart (barre/scatter) -> ImPlot::PlotBars / PlotScatter
//         st.metric                       -> testo formattato in un box
//       Riferimento API: https://github.com/ocornut/imgui/wiki/Getting-Started
//       e https://github.com/epezent/implot/blob/master/implot_demo.cpp

#include <GLFW/glfw3.h>
// Funzioni GL "core" di basso livello (glClear, glViewport, glClearColor)
// usate solo per pulire il framebuffer prima di disegnare la UI di ImGui:
// non serve un loader come GLAD, sono nell'ABI di libGL su Linux/macOS/Windows.
#if defined(__APPLE__)
#include <OpenGL/gl.h>
#else
#include <GL/gl.h>
#endif
#include <imgui.h>
#include <imgui_impl_glfw.h>
#include <imgui_impl_opengl3.h>
#include <implot.h>

#include <algorithm>
#include <cstdio>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include "risk_engine/market_data.hpp"
#include "risk_engine/risk_engine.hpp"

using namespace risk_engine;

namespace {

// Stato globale dell'app: equivalente di st.session_state + i widget
// dei parametri globali nella sidebar di app.py.
struct AppState {
    std::vector<Asset> assets;

    double risk_free_rate = 2.5;   // in %, come lo slider st.number_input di Python
    double avg_correlation = 0.35;

    bool narrative_enabled = false;
    double narrative_probability = 0.25;
    double narrative_severity_pct = -50.0; // %

    char isin_input[32] = "";
    std::string isin_message;
    ImVec4 isin_message_color = ImVec4(0.6f, 0.6f, 0.6f, 1.0f);

    int current_section = 0; // 0=Dashboard, 1=Monte Carlo, 2=Rischio

    int mc_scenario_count = 5000;
    bool mc_has_result = false;
    MonteCarloResult mc_result;

    int frontier_count = 3000;

    // Calcolatore obbligazioni.
    double bond_face_value = 1000.0;
    double bond_coupon_pct = 5.0;
    double bond_years = 5.0;
    double bond_market_price = 950.0;
    int bond_frequency_index = 1; // 0=1,1=2,2=4,3=12
    double bond_desired_ytm_pct = 0.0;

    // Crescita composta.
    double cg_principal = 10000.0;
    double cg_annual_rate_pct = 6.0;
    int cg_years = 10;
    double cg_contribution = 1200.0;
    double cg_inflation_pct = 2.0;
    double cg_tax_pct = 23.0;
};

std::optional<NarrativeScenario> narrative_scenario_from_state(const AppState& state) {
    if (!state.narrative_enabled) return std::nullopt;
    return NarrativeScenario{state.narrative_probability, state.narrative_severity_pct / 100.0};
}

const ImVec4 kColorLow(0.13f, 0.77f, 0.37f, 1.0f);      // #22C55E
const ImVec4 kColorModerate(0.22f, 0.74f, 0.97f, 1.0f); // #38BDF8
const ImVec4 kColorElevated(0.95f, 0.66f, 0.23f, 1.0f); // #F2A93B
const ImVec4 kColorHigh(0.95f, 0.37f, 0.36f, 1.0f);     // #F25F5C
const ImVec4 kColorNeutral(0.29f, 0.33f, 0.42f, 1.0f);  // #4B5563

ImVec4 color_for_risk_level(const std::string& level) {
    if (level == "Basso") return kColorLow;
    if (level == "Moderato") return kColorModerate;
    if (level == "Elevato") return kColorElevated;
    if (level == "Molto elevato") return kColorHigh;
    return kColorNeutral;
}

// Equivalente di render_kpis() in Python: 4 metriche in riga.
void render_kpis(const PortfolioMetrics& summary) {
    ImGui::Text("Valore totale: EUR %.0f", summary.portfolio_value);
    ImGui::SameLine(0, 40);
    ImGui::Text("Rendimento atteso: %.2f%%", summary.expected_return * 100.0);
    ImGui::SameLine(0, 40);
    ImGui::Text("Volatilita': %.2f%%", summary.volatility * 100.0);
    ImGui::SameLine(0, 40);
    ImGui::Text("Sharpe: %.2f", summary.sharpe);
}

// Equivalente di render_hero_card(): valore totale in grande + delta colorato.
void render_hero_card(const PortfolioMetrics& summary) {
    const double delta = summary.expected_return * 100.0;
    const ImVec4 delta_color = (delta >= 0.0) ? kColorLow : kColorHigh;

    ImGui::BeginChild("hero_card", ImVec2(0, 90), true);
    ImGui::TextDisabled("Valore totale del portafoglio");
    ImGui::SetWindowFontScale(1.6f);
    ImGui::Text("EUR %.0f", summary.portfolio_value);
    ImGui::SetWindowFontScale(1.0f);
    ImGui::TextColored(delta_color, "%+.2f%% rendimento atteso", delta);
    ImGui::SameLine();
    ImGui::TextDisabled(" | Sharpe %.2f | Volatilita' %.2f%%", summary.sharpe, summary.volatility * 100.0);
    ImGui::EndChild();
}

// Equivalente di render_allocation_card(): barra segmentata + legenda + tabella pesi.
void render_allocation_card(const PortfolioMetrics& summary) {
    std::vector<AssetRiskContribution> allocation;
    for (const auto& row : summary.asset_risk_contribution) {
        if (row.value > 0.0) allocation.push_back(row);
    }
    if (allocation.empty()) return;

    ImGui::BeginChild("allocation_card", ImVec2(0, 60 + 26.0f * static_cast<float>(allocation.size())), true);
    ImGui::Text("Portafoglio - EUR %.0f", summary.portfolio_value);

    if (ImPlot::BeginPlot("##allocation_bar", ImVec2(-1, 40),
                           ImPlotFlags_NoLegend | ImPlotFlags_NoMouseText | ImPlotFlags_CanvasOnly)) {
        ImPlot::SetupAxes(nullptr, nullptr, ImPlotAxisFlags_NoDecorations, ImPlotAxisFlags_NoDecorations);
        ImPlot::SetupAxisLimits(ImAxis_X1, 0, 100, ImGuiCond_Always);
        ImPlot::SetupAxisLimits(ImAxis_Y1, 0, 1, ImGuiCond_Always);
        double cursor = 0.0;
        for (const auto& row : allocation) {
            const double width = row.weight * 100.0;
            const double xs[2] = {cursor, cursor + width};
            const double ys[2] = {0.5, 0.5};
            ImPlot::PlotBars("##seg", xs, ys, 1, width);
            cursor += width;
        }
        ImPlot::EndPlot();
    }

    if (ImGui::BeginTable("allocation_table", 3, ImGuiTableFlags_RowBg | ImGuiTableFlags_SizingStretchProp)) {
        ImGui::TableSetupColumn("Asset");
        ImGui::TableSetupColumn("Peso (%)");
        ImGui::TableSetupColumn("Valore (EUR)");
        ImGui::TableHeadersRow();
        for (const auto& row : allocation) {
            ImGui::TableNextRow();
            ImGui::TableSetColumnIndex(0);
            ImGui::TextUnformatted(row.name.c_str());
            ImGui::TableSetColumnIndex(1);
            ImGui::Text("%.1f%%", row.weight * 100.0);
            ImGui::TableSetColumnIndex(2);
            ImGui::Text("%.0f", row.value);
        }
        ImGui::EndTable();
    }
    ImGui::EndChild();
}

// Equivalente di render_risk_gauge(): donut del punteggio di rischio 0-100.
void render_risk_gauge(const PortfolioMetrics& summary) {
    const double score = summary.risk_score;
    ImGui::BeginGroup();
    if (ImPlot::BeginPlot("##risk_gauge", ImVec2(160, 160),
                           ImPlotFlags_NoLegend | ImPlotFlags_NoMouseText | ImPlotFlags_Equal | ImPlotFlags_CanvasOnly)) {
        ImPlot::SetupAxes(nullptr, nullptr, ImPlotAxisFlags_NoDecorations, ImPlotAxisFlags_NoDecorations);
        static const char* labels[2] = {"Rischio", "Resto"};
        double values[2] = {score, std::max(100.0 - score, 0.0)};
        ImPlot::PlotPieChart(labels, values, 2, 0.5, 0.5, 0.4, "");
        ImPlot::EndPlot();
    }
    ImGui::EndGroup();
    ImGui::SameLine();
    ImGui::BeginGroup();
    ImGui::SetWindowFontScale(1.4f);
    ImGui::Text("%.0f", score);
    ImGui::SetWindowFontScale(1.0f);
    ImGui::SameLine();
    ImGui::TextDisabled("/100");
    ImGui::Text("Livello di rischio: %s", summary.risk_level.c_str());
    ImGui::EndGroup();
}

// Equivalente di render_risk_advice(): banner colorato + consiglio testuale.
void render_risk_advice(const PortfolioMetrics& summary) {
    const ImVec4 color = color_for_risk_level(summary.risk_level);
    ImGui::TextColored(color, "Livello di rischio: %s | Score: %.1f/100 | Beta: %.2f", summary.risk_level.c_str(),
                        summary.risk_score, summary.beta);

    static const std::vector<std::pair<std::string, std::string>> advice = {
        {"Basso", "Volatilita' contenuta e buona diversificazione riducono la probabilita' di perdite estreme."},
        {"Moderato", "Il portafoglio puo' oscillare nel medio termine, ma il rischio resta generalmente gestibile."},
        {"Elevato", "La sensibilita' ai movimenti di mercato puo' produrre oscillazioni e perdite piu' marcate."},
    };
    std::string text = "La concentrazione e la volatilita' rendono il portafoglio vulnerabile agli shock di mercato.";
    for (const auto& [level, message] : advice) {
        if (level == summary.risk_level) {
            text = message;
            break;
        }
    }
    ImGui::TextWrapped("%s", text.c_str());
}

// Equivalente di render_risk_formula(): riepilogo della formula di volatilita'.
void render_risk_formula(const PortfolioMetrics& summary, double avg_correlation) {
    if (summary.asset_risk_contribution.empty()) {
        ImGui::TextDisabled("Inserisci almeno un asset per visualizzare il calcolo.");
        return;
    }
    ImGui::TextWrapped("Formula: sigma_p = sqrt( sum_i sum_j w_i w_j sigma_i sigma_j rho_ij )");
    ImGui::Text("Volatilita' calcolata: %.2f%%   Correlazione media: %.2f", summary.volatility * 100.0, avg_correlation);
    ImGui::Text("Score = 1.6 x %.2f + 15 x %.2f = %.2f/100   Sharpe = %.2f", summary.volatility * 100.0, summary.beta,
                summary.risk_score, summary.sharpe);
}

// Tabella editabile degli asset, equivalente di st.data_editor().
void render_asset_table(AppState& state) {
    if (ImGui::BeginTable("asset_editor", 8,
                           ImGuiTableFlags_Borders | ImGuiTableFlags_RowBg | ImGuiTableFlags_SizingStretchProp)) {
        ImGui::TableSetupColumn("Asset");
        ImGui::TableSetupColumn("Ticker");
        ImGui::TableSetupColumn("Valore (EUR)");
        ImGui::TableSetupColumn("Rend. atteso (%)");
        ImGui::TableSetupColumn("Volatilita' (%)");
        ImGui::TableSetupColumn("Beta");
        ImGui::TableSetupColumn("Esp. tema (%)");
        ImGui::TableSetupColumn("");
        ImGui::TableHeadersRow();

        int row_to_delete = -1;
        for (size_t i = 0; i < state.assets.size(); ++i) {
            Asset& asset = state.assets[i];
            ImGui::PushID(static_cast<int>(i));
            ImGui::TableNextRow();

            ImGui::TableSetColumnIndex(0);
            char name_buf[64];
            std::snprintf(name_buf, sizeof(name_buf), "%s", asset.name.c_str());
            ImGui::SetNextItemWidth(-1);
            if (ImGui::InputText("##name", name_buf, sizeof(name_buf))) asset.name = name_buf;

            ImGui::TableSetColumnIndex(1);
            char ticker_buf[16];
            std::snprintf(ticker_buf, sizeof(ticker_buf), "%s", asset.ticker.c_str());
            ImGui::SetNextItemWidth(-1);
            if (ImGui::InputText("##ticker", ticker_buf, sizeof(ticker_buf))) asset.ticker = ticker_buf;

            ImGui::TableSetColumnIndex(2);
            ImGui::SetNextItemWidth(-1);
            ImGui::InputDouble("##value", &asset.value, 0, 0, "%.0f");

            ImGui::TableSetColumnIndex(3);
            ImGui::SetNextItemWidth(-1);
            ImGui::InputDouble("##ret", &asset.expected_return, 0, 0, "%.2f");

            ImGui::TableSetColumnIndex(4);
            ImGui::SetNextItemWidth(-1);
            ImGui::InputDouble("##vol", &asset.volatility, 0, 0, "%.2f");

            ImGui::TableSetColumnIndex(5);
            ImGui::SetNextItemWidth(-1);
            ImGui::InputDouble("##beta", &asset.beta, 0, 0, "%.2f");

            ImGui::TableSetColumnIndex(6);
            ImGui::SetNextItemWidth(-1);
            ImGui::InputDouble("##narrative", &asset.narrative_exposure, 0, 0, "%.1f");

            ImGui::TableSetColumnIndex(7);
            if (ImGui::SmallButton("X")) row_to_delete = static_cast<int>(i);

            ImGui::PopID();
        }
        ImGui::EndTable();

        if (row_to_delete >= 0) state.assets.erase(state.assets.begin() + row_to_delete);
    }

    if (ImGui::Button("+ Aggiungi riga vuota")) {
        state.assets.push_back(Asset{"Nuovo asset", "", 0.0, 0.0, 0.0, 1.0, 0.0});
    }
}

// Equivalente della card "Aggiungi ETF o obbligazione" con ricerca ISIN.
void render_isin_form(AppState& state) {
    ImGui::TextUnformatted("Aggiungi ETF o obbligazione");
    ImGui::TextDisabled("Cerca uno strumento europeo inserendo il suo codice ISIN.");
    ImGui::SetNextItemWidth(220);
    ImGui::InputText("##isin", state.isin_input, sizeof(state.isin_input));
    ImGui::SameLine();
    if (ImGui::Button("Cerca e aggiungi")) {
        const std::string isin = state.isin_input;
        if (isin.empty()) {
            state.isin_message = "Inserisci un codice ISIN.";
            state.isin_message_color = kColorElevated;
        } else {
            const AssetLookupResult match = lookup_isin_to_asset(isin);
            if (!match.found) {
                state.isin_message = "Nessun risultato trovato. Prova un ISIN europeo valido.";
                state.isin_message_color = kColorElevated;
            } else {
                Asset asset;
                asset.name = match.name;
                asset.ticker = match.ticker;
                asset.value = match.value;
                asset.expected_return = match.expected_return * 100.0;
                asset.volatility = match.volatility * 100.0;
                asset.beta = match.beta;
                asset.narrative_exposure = 0.0;
                state.assets.push_back(asset);
                state.isin_message = "Aggiunto " + match.name + " (" + match.ticker + ").";
                state.isin_message_color = kColorLow;
                state.isin_input[0] = '\0';
            }
        }
    }
    if (!state.isin_message.empty()) ImGui::TextColored(state.isin_message_color, "%s", state.isin_message.c_str());
}

void render_sidebar(AppState& state) {
    ImGui::TextUnformatted("Parametri globali");
    ImGui::Separator();
    float risk_free = static_cast<float>(state.risk_free_rate);
    if (ImGui::SliderFloat("Tasso risk-free (%)", &risk_free, 0.0f, 20.0f, "%.1f")) state.risk_free_rate = risk_free;
    float correlation = static_cast<float>(state.avg_correlation);
    if (ImGui::SliderFloat("Correlazione media", &correlation, 0.0f, 1.0f, "%.2f")) state.avg_correlation = correlation;

    ImGui::Separator();
    ImGui::Checkbox("Includi scenario narrativo", &state.narrative_enabled);
    if (state.narrative_enabled) {
        float probability = static_cast<float>(state.narrative_probability);
        if (ImGui::SliderFloat("Probabilita' stimata", &probability, 0.0f, 1.0f, "%.2f")) state.narrative_probability = probability;
        float severity = static_cast<float>(state.narrative_severity_pct);
        if (ImGui::SliderFloat("Perdita se si verifica (%)", &severity, -100.0f, 0.0f, "%.0f")) state.narrative_severity_pct = severity;
    }
}

void render_dashboard_tab(AppState& state, const PortfolioMetrics& summary) {
    render_hero_card(summary);
    ImGui::Spacing();
    ImGui::TextUnformatted("Portafoglio");
    if (summary.asset_risk_contribution.empty()) {
        ImGui::TextDisabled(
            "Il portafoglio e' vuoto. Aggiungi un ETF/obbligazione tramite ISIN o inserisci un asset nella tabella.");
    } else {
        render_allocation_card(summary);
    }
}

void render_monte_carlo_tab(AppState& state) {
    ImGui::TextUnformatted("Simulazione Monte Carlo");
    ImGui::TextDisabled("Genera scenari annuali usando rendimenti storici giornalieri, quando disponibili.");
    ImGui::SliderInt("Numero di scenari", &state.mc_scenario_count, 500, 10000);

    char button_label[64];
    std::snprintf(button_label, sizeof(button_label), "Simula %d scenari", state.mc_scenario_count);
    if (ImGui::Button(button_label)) {
        state.mc_result = simulate_portfolio_scenarios(state.assets, state.mc_scenario_count, 252, 42, {});
        state.mc_has_result = true;
    }

    if (state.mc_has_result) {
        const auto& sim = state.mc_result;
        ImGui::Text("Rendimento atteso: %.2f%%", sim.expected_return * 100.0);
        ImGui::SameLine(0, 30);
        ImGui::Text("P5: %.2f%%", sim.p05 * 100.0);
        ImGui::SameLine(0, 30);
        ImGui::Text("P95: %.2f%%", sim.p95 * 100.0);
        ImGui::SameLine(0, 30);
        ImGui::Text("Probabilita' di perdita: %.2f%%", sim.probability_loss * 100.0);
        ImGui::TextDisabled("%s", sim.historical_source.c_str());

        if (!sim.portfolio_return_distribution.empty()) {
            constexpr int kBins = 30;
            const auto [min_it, max_it] =
                std::minmax_element(sim.portfolio_return_distribution.begin(), sim.portfolio_return_distribution.end());
            double lo = *min_it, hi = *max_it;
            if (hi <= lo) hi = lo + 1e-6;
            std::vector<double> counts(kBins, 0.0);
            std::vector<double> centers(kBins, 0.0);
            const double bin_width = (hi - lo) / kBins;
            for (int b = 0; b < kBins; ++b) centers[b] = lo + bin_width * (b + 0.5);
            for (double v : sim.portfolio_return_distribution) {
                int bin = static_cast<int>((v - lo) / bin_width);
                bin = std::clamp(bin, 0, kBins - 1);
                counts[bin] += 1.0;
            }
            if (ImPlot::BeginPlot("Distribuzione dei rendimenti", ImVec2(-1, 320))) {
                ImPlot::SetupAxes("Rendimento totale", "Occorrenze");
                ImPlot::PlotBars("Scenari", centers.data(), counts.data(), kBins, bin_width * 0.9);
                ImPlot::EndPlot();
            }
        }
    }
}

void render_efficient_frontier(AppState& state, const PortfolioMetrics& summary) {
    if (!ImGui::CollapsingHeader("Frontiera efficiente (simulata)")) return;
    ImGui::TextWrapped(
        "Nuvola di portafogli generati con pesi casuali sugli stessi asset in portafoglio, per confrontare rischio "
        "e rendimento con l'allocazione attuale (marker rosso).");
    if (state.assets.size() < 2) {
        ImGui::TextDisabled("Servono almeno due asset per generare la frontiera efficiente.");
        return;
    }
    ImGui::SliderInt("Numero di portafogli simulati", &state.frontier_count, 500, 8000);
    const auto frontier = simulate_efficient_frontier(state.assets, state.risk_free_rate / 100.0,
                                                       state.avg_correlation, state.frontier_count, 42);
    if (frontier.empty()) {
        ImGui::TextDisabled("Non e' stato possibile generare la frontiera con i dati correnti.");
        return;
    }
    std::vector<double> vols(frontier.size()), rets(frontier.size());
    for (size_t i = 0; i < frontier.size(); ++i) {
        vols[i] = frontier[i].volatility * 100.0;
        rets[i] = frontier[i].expected_return * 100.0;
    }
    const double current_vol = summary.volatility * 100.0;
    const double current_ret = summary.expected_return * 100.0;

    if (ImPlot::BeginPlot("Frontiera efficiente", ImVec2(-1, 380))) {
        ImPlot::SetupAxes("Volatilita' (%)", "Rendimento atteso (%)");
        ImPlot::PlotScatter("Portafogli simulati", vols.data(), rets.data(), static_cast<int>(vols.size()));
        ImPlot::SetNextMarkerStyle(ImPlotMarker_Diamond, 8, ImVec4(0.95f, 0.37f, 0.36f, 1.0f));
        ImPlot::PlotScatter("Portafoglio attuale", &current_vol, &current_ret, 1);
        ImPlot::EndPlot();
    }
    ImGui::TextDisabled(
        "Punti piu' in alto a sinistra = rendimento maggiore a parita' (o minore) di rischio. Nuvola campionata, "
        "non ottimo matematico di Markowitz.");
}

void render_bond_calculator(AppState& state) {
    if (!ImGui::CollapsingHeader("Analisi obbligazioni")) return;
    static const int frequencies[4] = {1, 2, 4, 12};
    static const char* frequency_labels[4] = {"1 (annuale)", "2 (semestrale)", "4 (trimestrale)", "12 (mensile)"};

    ImGui::InputDouble("Valore nominale (EUR)", &state.bond_face_value, 0, 0, "%.0f");
    ImGui::InputDouble("Cedola annua (%)", &state.bond_coupon_pct, 0, 0, "%.2f");
    ImGui::InputDouble("Anni alla scadenza", &state.bond_years, 0, 0, "%.1f");
    ImGui::InputDouble("Prezzo di mercato (EUR)", &state.bond_market_price, 0, 0, "%.0f");
    ImGui::Combo("Pagamento cedole", &state.bond_frequency_index, frequency_labels, 4);
    ImGui::InputDouble("YTM desiderato (%, 0 = calcolato)", &state.bond_desired_ytm_pct, 0, 0, "%.2f");

    std::optional<double> desired_yield;
    if (state.bond_desired_ytm_pct > 0.0) desired_yield = state.bond_desired_ytm_pct / 100.0;

    const auto bond = calculate_bond_metrics(state.bond_face_value, state.bond_coupon_pct / 100.0, state.bond_years,
                                              state.bond_market_price, desired_yield,
                                              frequencies[state.bond_frequency_index]);
    ImGui::Separator();
    ImGui::Text("YTM: %.2f%%", bond.yield_to_maturity * 100.0);
    ImGui::Text("Duration Macaulay: %.2f anni", bond.macaulay_duration_years);
    ImGui::Text("Duration modificata: %.2f", bond.modified_duration_years);
    ImGui::Text("Convessita': %.2f", bond.convexity);
    ImGui::Text("Prezzo teorico: EUR %.2f", bond.price_from_yield);
}

void render_compound_growth(AppState& state) {
    if (!ImGui::CollapsingHeader("Crescita composta")) return;

    ImGui::InputDouble("Capitale iniziale (EUR)", &state.cg_principal, 0, 0, "%.0f");
    ImGui::InputDouble("Rendimento annuo (%)", &state.cg_annual_rate_pct, 0, 0, "%.2f");
    ImGui::InputInt("Anni", &state.cg_years);
    state.cg_years = std::max(state.cg_years, 1);
    ImGui::InputDouble("Contributo annuale (EUR)", &state.cg_contribution, 0, 0, "%.0f");
    ImGui::InputDouble("Inflazione (%)", &state.cg_inflation_pct, 0, 0, "%.2f");
    ImGui::InputDouble("Aliquota fiscale (%)", &state.cg_tax_pct, 0, 0, "%.2f");

    const auto result = simulate_compound_growth(state.cg_principal, state.cg_annual_rate_pct / 100.0,
                                                  static_cast<double>(state.cg_years), state.cg_contribution, "annual",
                                                  state.cg_inflation_pct / 100.0, state.cg_tax_pct / 100.0, 12);

    ImGui::Separator();
    ImGui::Text("Valore nominale: EUR %.0f", result.final_value_nominal);
    ImGui::SameLine(0, 30);
    ImGui::Text("Dopo tasse: EUR %.0f", result.after_tax_value);
    ImGui::SameLine(0, 30);
    ImGui::Text("Valore reale: EUR %.0f", result.real_value_after_inflation);
    ImGui::SameLine(0, 30);
    ImGui::Text("Rendimento reale: %.2f%%", result.inflation_adjusted_rate * 100.0);

    if (!result.yearly_history.empty()) {
        std::vector<double> years, nominal, real;
        years.reserve(result.yearly_history.size());
        nominal.reserve(result.yearly_history.size());
        real.reserve(result.yearly_history.size());
        for (const auto& point : result.yearly_history) {
            years.push_back(point.year);
            nominal.push_back(point.nominal_value);
            real.push_back(point.real_value_after_inflation);
        }
        if (ImPlot::BeginPlot("Andamento nel tempo", ImVec2(-1, 300))) {
            ImPlot::SetupAxes("Anno", "Valore (EUR)");
            ImPlot::PlotLine("Valore nominale", years.data(), nominal.data(), static_cast<int>(years.size()));
            ImPlot::PlotLine("Valore reale dopo inflazione", years.data(), real.data(), static_cast<int>(years.size()));
            ImPlot::EndPlot();
        }
    }
}

void render_risk_tab(AppState& state, const PortfolioMetrics& summary) {
    render_kpis(summary);
    ImGui::Spacing();
    ImGui::TextUnformatted("Profilo e consigli");
    render_risk_gauge(summary);
    render_risk_advice(summary);
    ImGui::Spacing();
    render_risk_formula(summary, state.avg_correlation);

    if (!summary.asset_risk_contribution.empty()) {
        ImGui::Spacing();
        ImGui::TextUnformatted("Contributo al rischio per asset");
        if (ImGui::BeginTable("risk_contribution_table", 4, ImGuiTableFlags_RowBg | ImGuiTableFlags_SizingStretchProp)) {
            ImGui::TableSetupColumn("Asset");
            ImGui::TableSetupColumn("Allocazione (%)");
            ImGui::TableSetupColumn("Volatilita' (%)");
            ImGui::TableSetupColumn("Contributo al rischio (%)");
            ImGui::TableHeadersRow();
            for (const auto& row : summary.asset_risk_contribution) {
                ImGui::TableNextRow();
                ImGui::TableSetColumnIndex(0);
                ImGui::TextUnformatted(row.name.c_str());
                ImGui::TableSetColumnIndex(1);
                ImGui::Text("%.2f", row.weight * 100.0);
                ImGui::TableSetColumnIndex(2);
                ImGui::Text("%.2f", row.volatility * 100.0);
                ImGui::TableSetColumnIndex(3);
                ImGui::Text("%.2f", row.risk_contribution_pct);
            }
            ImGui::EndTable();
        }

        std::vector<double> indices(summary.asset_risk_contribution.size());
        std::vector<double> contributions(summary.asset_risk_contribution.size());
        for (size_t i = 0; i < summary.asset_risk_contribution.size(); ++i) {
            indices[i] = static_cast<double>(i);
            contributions[i] = summary.asset_risk_contribution[i].risk_contribution_pct;
        }
        if (ImPlot::BeginPlot("Contributo al rischio (%)", ImVec2(-1, 260))) {
            ImPlot::SetupAxes("Asset", "Contributo (%)");
            ImPlot::PlotBars("##contrib", indices.data(), contributions.data(), static_cast<int>(indices.size()), 0.6);
            ImPlot::EndPlot();
        }
    }

    if (summary.narrative_risk.has_value()) {
        ImGui::Spacing();
        const auto& narrative = *summary.narrative_risk;
        ImGui::TextWrapped("Scenario narrativo - Esposizione complessiva: %.1f%% | Impatto stimato: %.1f%%",
                            narrative.portfolio_exposure * 100.0, narrative.stressed_loss_if_realized * 100.0);
    }

    ImGui::Spacing();
    render_efficient_frontier(state, summary);
    render_bond_calculator(state);
    render_compound_growth(state);
}

} // namespace

int main() {
    if (!glfwInit()) {
        std::fprintf(stderr, "Impossibile inizializzare GLFW.\n");
        return 1;
    }

    const char* glsl_version = "#version 130";
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 0);

    GLFWwindow* window = glfwCreateWindow(1280, 800, "RiskEngine", nullptr, nullptr);
    if (!window) {
        std::fprintf(stderr, "Impossibile creare la finestra GLFW.\n");
        glfwTerminate();
        return 1;
    }
    glfwMakeContextCurrent(window);
    glfwSwapInterval(1);

    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImPlot::CreateContext();
    ImGui::StyleColorsDark();

    ImGui_ImplGlfw_InitForOpenGL(window, true);
    ImGui_ImplOpenGL3_Init(glsl_version);

    AppState state;

    while (!glfwWindowShouldClose(window)) {
        glfwPollEvents();

        ImGui_ImplOpenGL3_NewFrame();
        ImGui_ImplGlfw_NewFrame();
        ImGui::NewFrame();

        ImGui::SetNextWindowPos(ImVec2(0, 0));
        ImGui::SetNextWindowSize(ImGui::GetIO().DisplaySize);
        ImGui::Begin("RiskEngine", nullptr,
                      ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoCollapse |
                          ImGuiWindowFlags_NoTitleBar);

        ImGui::TextUnformatted("RiskEngine");
        ImGui::TextDisabled("Analisi del rischio di portafoglio con dati storici reali e simulazioni quantitative");
        ImGui::Separator();

        ImGui::BeginChild("sidebar", ImVec2(280, 0), true);
        render_sidebar(state);
        ImGui::EndChild();
        ImGui::SameLine();

        ImGui::BeginChild("main_area", ImVec2(0, 0), false);
        ImGui::BeginChild("isin_form", ImVec2(0, 90), true);
        render_isin_form(state);
        ImGui::EndChild();

        ImGui::TextUnformatted("Asset in portafoglio");
        render_asset_table(state);
        ImGui::Spacing();

        PortfolioMetrics summary;
        bool has_error = false;
        std::string error_message;
        try {
            summary = calculate_portfolio_metrics(state.assets, state.risk_free_rate / 100.0, state.avg_correlation,
                                                   narrative_scenario_from_state(state));
        } catch (const std::invalid_argument& ex) {
            has_error = true;
            error_message = ex.what();
        }

        if (has_error) {
            ImGui::TextColored(kColorElevated, "%s", error_message.c_str());
        } else if (ImGui::BeginTabBar("sections")) {
            if (ImGui::BeginTabItem("Dashboard")) {
                render_dashboard_tab(state, summary);
                ImGui::EndTabItem();
            }
            if (ImGui::BeginTabItem("Monte Carlo")) {
                render_monte_carlo_tab(state);
                ImGui::EndTabItem();
            }
            if (ImGui::BeginTabItem("Rischio")) {
                render_risk_tab(state, summary);
                ImGui::EndTabItem();
            }
            ImGui::EndTabBar();
        }
        ImGui::EndChild();

        ImGui::End();

        ImGui::Render();
        int display_w, display_h;
        glfwGetFramebufferSize(window, &display_w, &display_h);
        glViewport(0, 0, display_w, display_h);
        glClearColor(0.09f, 0.10f, 0.12f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());
        glfwSwapBuffers(window);
    }

    ImGui_ImplOpenGL3_Shutdown();
    ImGui_ImplGlfw_Shutdown();
    ImPlot::DestroyContext();
    ImGui::DestroyContext();
    glfwDestroyWindow(window);
    glfwTerminate();
    return 0;
}
