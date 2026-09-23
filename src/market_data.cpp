// CHANGELOG
// ---------
// v1.0 - 2026-09-23
//     - Prima versione C++. Vedi market_data.hpp per il confronto con
//       l'originale Python (yfinance + requests).
#include "risk_engine/market_data.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <curl/curl.h>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

namespace risk_engine {

namespace {

size_t write_callback(char* ptr, size_t size, size_t nmemb, void* userdata) {
    auto* buffer = static_cast<std::string*>(userdata);
    buffer->append(ptr, size * nmemb);
    return size * nmemb;
}

// Esegue una GET HTTP e ritorna il body come stringa, o stringa vuota in
// caso di errore di rete o status diverso da 200 — non lancia mai
// eccezioni per problemi di rete, cosi' i chiamanti si comportano come i
// blocchi try/except di risk_engine.py. Doc:
// https://curl.se/libcurl/c/libcurl-easy.html
std::string http_get(const std::string& url) {
    CURL* curl = curl_easy_init();
    if (!curl) return "";

    std::string response_body;
    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_callback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response_body);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 20L);
    curl_easy_setopt(curl, CURLOPT_USERAGENT, "Mozilla/5.0");

    const CURLcode res = curl_easy_perform(curl);
    long status_code = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status_code);
    curl_easy_cleanup(curl);

    if (res != CURLE_OK || status_code != 200) return "";
    return response_body;
}

std::string url_encode(const std::string& value) {
    CURL* curl = curl_easy_init();
    if (!curl) return value;
    char* encoded = curl_easy_escape(curl, value.c_str(), static_cast<int>(value.size()));
    std::string result = encoded ? std::string(encoded) : value;
    if (encoded) curl_free(encoded);
    curl_easy_cleanup(curl);
    return result;
}

// Stessa mappa di fallback hardcoded di EUROPEAN_ISIN_FALLBACKS in Python.
const std::map<std::string, AssetLookupResult>& european_isin_fallbacks() {
    static const std::map<std::string, AssetLookupResult> fallbacks = [] {
        std::map<std::string, AssetLookupResult> map;

        AssetLookupResult world;
        world.found = true;
        world.name = "iShares Core MSCI World UCITS ETF USD (Acc)";
        world.ticker = "IWDA.L";
        world.value = 10000;
        world.expected_return = 0.08;
        world.volatility = 0.15;
        world.beta = 0.98;
        world.exchange = "London";
        world.asset_type = "ETF";
        map["IE00B4L5Y983"] = world;

        AssetLookupResult em;
        em.found = true;
        em.name = "iShares Core MSCI EM IMI UCITS ETF USD (Acc)";
        em.ticker = "IEMG.L";
        em.value = 10000;
        em.expected_return = 0.09;
        em.volatility = 0.18;
        em.beta = 0.82;
        em.exchange = "London";
        em.asset_type = "ETF";
        map["IE00BK5BQT80"] = em;

        return map;
    }();
    return fallbacks;
}

} // namespace

std::vector<double> fetch_historical_daily_returns(const std::string& ticker) {
    if (ticker.empty()) return {};

    const std::string url =
        "https://query1.finance.yahoo.com/v8/finance/chart/" + url_encode(ticker) + "?range=5y&interval=1d";
    const std::string body = http_get(url);
    if (body.empty()) return {};

    json payload;
    try {
        payload = json::parse(body);

        const auto& result = payload.at("chart").at("result");
        if (!result.is_array() || result.empty()) return {};
        const auto& first = result.at(0);
        const auto& indicators = first.at("indicators");

        std::vector<double> closes;
        if (indicators.contains("adjclose") && !indicators.at("adjclose").empty()) {
            const auto& raw = indicators.at("adjclose").at(0).at("adjclose");
            closes.reserve(raw.size());
            for (const auto& v : raw) closes.push_back(v.is_null() ? std::nan("") : v.get<double>());
        } else {
            const auto& raw = indicators.at("quote").at(0).at("close");
            closes.reserve(raw.size());
            for (const auto& v : raw) closes.push_back(v.is_null() ? std::nan("") : v.get<double>());
        }

        std::vector<double> valid_closes;
        for (double c : closes) {
            if (std::isfinite(c)) valid_closes.push_back(c);
        }
        if (valid_closes.size() < 2) return {};

        std::vector<double> returns;
        returns.reserve(valid_closes.size() - 1);
        for (size_t i = 1; i < valid_closes.size(); ++i) {
            if (valid_closes[i - 1] != 0.0) {
                returns.push_back((valid_closes[i] - valid_closes[i - 1]) / valid_closes[i - 1]);
            }
        }
        return returns;
    } catch (const json::exception&) {
        return {};
    }
}

AssetLookupResult lookup_isin_to_asset(const std::string& isin) {
    std::string normalized = isin;
    normalized.erase(normalized.begin(),
                      std::find_if(normalized.begin(), normalized.end(), [](unsigned char c) { return !std::isspace(c); }));
    normalized.erase(std::find_if(normalized.rbegin(), normalized.rend(),
                                   [](unsigned char c) { return !std::isspace(c); })
                          .base(),
                      normalized.end());
    std::transform(normalized.begin(), normalized.end(), normalized.begin(), ::toupper);

    if (normalized.empty()) return {};

    const auto& fallbacks = european_isin_fallbacks();
    if (auto it = fallbacks.find(normalized); it != fallbacks.end()) {
        AssetLookupResult result = it->second;
        result.isin = normalized;
        return result;
    }

    const std::string search_url = "https://query1.finance.yahoo.com/v1/finance/search?q=" + url_encode(normalized);
    const std::string body = http_get(search_url);
    if (body.empty()) return {};

    json payload;
    try {
        payload = json::parse(body);
    } catch (const json::exception&) {
        return {};
    }

    if (!payload.contains("quotes") || !payload.at("quotes").is_array() || payload.at("quotes").empty()) {
        return {};
    }

    const auto& best_match = payload.at("quotes").at(0);
    const std::string symbol = best_match.value("symbol", "");
    if (symbol.empty()) return {};

    const std::vector<double> returns = fetch_historical_daily_returns(symbol);

    double annualized_return = 0.0;
    double volatility = 0.0;
    if (!returns.empty()) {
        // Rendimento totale annualizzato sul periodo scaricato e volatilità
        // annualizzata dai rendimenti giornalieri (sqrt(252) * deviazione
        // standard) — stessa idea di lookup_isin_to_asset() in Python.
        double product = 1.0;
        for (double r : returns) product *= (1.0 + r);
        const double years = static_cast<double>(returns.size()) / 252.0;
        annualized_return = (years > 0.0) ? std::pow(product, 1.0 / years) - 1.0 : 0.0;

        double mean = 0.0;
        for (double r : returns) mean += r;
        mean /= static_cast<double>(returns.size());
        double sum_sq = 0.0;
        for (double r : returns) sum_sq += (r - mean) * (r - mean);
        const double stdev = (returns.size() > 1) ? std::sqrt(sum_sq / static_cast<double>(returns.size() - 1)) : 0.0;
        volatility = stdev * std::sqrt(252.0);
    }

    const std::string quote_type = best_match.value("quoteType", "ETF");
    if (volatility <= 0.0 && quote_type == "ETF") volatility = 0.18;

    AssetLookupResult result;
    result.found = true;
    result.name = best_match.value("longname", best_match.value("shortname", symbol));
    result.ticker = symbol;
    result.isin = normalized;
    result.value = 10000;
    result.expected_return = annualized_return;
    result.volatility = volatility;
    // Nota: a differenza di yfinance, l'endpoint di ricerca non espone un
    // beta pronto all'uso; senza l'endpoint quoteSummary (che richiede un
    // "crumb" di autenticazione lato Yahoo) usiamo il default 1.0, come fa
    // anche il codice Python quando fast_info non lo contiene.
    result.beta = 1.0;
    result.exchange = best_match.value("exchDisp", best_match.value("exchange", ""));
    std::string asset_type = quote_type.empty() ? "ETF" : quote_type;
    if (!asset_type.empty()) asset_type[0] = static_cast<char>(std::toupper(static_cast<unsigned char>(asset_type[0])));
    result.asset_type = asset_type;
    return result;
}

} // namespace risk_engine
