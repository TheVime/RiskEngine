// CHANGELOG
// ---------
// v1.0 - 2026-09-23
//     - Prima versione C++. In Python il fetch dei dati usa yfinance (che
//       non ha equivalente C++) più una chiamata diretta con `requests`
//       all'endpoint di ricerca di Yahoo Finance. Qui entrambe le vie
//       passano per chiamate HTTP dirette con libcurl:
//         - ricerca simbolo:   https://query1.finance.yahoo.com/v1/finance/search?q=...
//         - storico prezzi:    https://query1.finance.yahoo.com/v8/finance/chart/{ticker}
//       Documentazione libcurl (easy interface):
//       https://curl.se/libcurl/c/libcurl-easy.html
//       Documentazione nlohmann/json: https://json.nlohmann.me/
#pragma once

#include <string>
#include <vector>

#include "risk_engine/types.hpp"

namespace risk_engine {

// Scarica ~5 anni di chiusure giornaliere per `ticker` da Yahoo Finance e ne
// calcola i rendimenti percentuali giorno su giorno. Ritorna un vettore
// vuoto in caso di errore di rete, ticker sconosciuto o dati insufficienti
// (mai eccezioni per errori di rete: equivalente del "return pd.Series()"
// nei blocchi try/except di _fetch_historical_returns() in Python).
std::vector<double> fetch_historical_daily_returns(const std::string& ticker);

// Risolve un ISIN europeo in metadati di base per un asset. Prova prima la
// mappa di fallback locale (stessi due ETF hardcoded del Python), poi la
// ricerca live su Yahoo Finance. found=false se non si trova nulla
// (equivalente del dict vuoto {} restituito da lookup_isin_to_asset() in
// Python).
AssetLookupResult lookup_isin_to_asset(const std::string& isin);

} // namespace risk_engine
