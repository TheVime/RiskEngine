# RiskEngine (porting C++)

Porting in C++ del progetto Python [TheVime/RiskEngine](https://github.com/TheVime/RiskEngine):
un'app di analisi del rischio di portafoglio (rendimento atteso, volatilità, beta, Sharpe,
scenari Monte Carlo, frontiera efficiente simulata, calcolo obbligazioni e crescita composta).

## Struttura del progetto

```
RiskEngineCpp/
├── CMakeLists.txt
├── include/risk_engine/
│   ├── types.hpp        # struct (Asset, PortfolioMetrics, BondMetrics, ...)
│   ├── risk_engine.hpp  # firme delle funzioni di calcolo
│   └── market_data.hpp  # firme del fetch dati (ISIN lookup, storico prezzi)
├── src/
│   ├── risk_engine.cpp  # porting di risk_engine.py (motore di calcolo)
│   ├── market_data.cpp  # porting della parte yfinance/requests
│   └── main.cpp         # porting "a schermo" di app.py (dashboard desktop)
└── tests/
    └── test_risk_engine.cpp  # porting di test_risk_engine.py (doctest)
```

## Corrispondenza con il progetto Python

| Python (originale)                          | C++ (questo progetto)                          |
|----------------------------------------------|-------------------------------------------------|
| `risk_engine.py` (calcolo, NumPy/Pandas)      | `src/risk_engine.cpp` — porting 1:1              |
| `yfinance` + `requests` (dati di mercato)     | `src/market_data.cpp` — libcurl + nlohmann/json  |
| `app.py` (interfaccia Streamlit)              | `src/main.cpp` — dashboard Dear ImGui + ImPlot   |
| `test_risk_engine.py` (pytest)                | `tests/test_risk_engine.cpp` — doctest           |

**Streamlit non ha un equivalente diretto in C++**, quindi la UI è stata ricostruita da zero
come applicazione desktop (finestra nativa via GLFW + OpenGL), non come pagina web. La
corrispondenza è per sezione/funzione (stessi tab Dashboard / Monte Carlo / Rischio, stessi
controlli), non pixel-per-pixel. Allo stesso modo `yfinance` (libreria Python senza
equivalente C++) è stata sostituita da chiamate dirette agli endpoint pubblici di Yahoo
Finance via [libcurl](https://curl.se/libcurl/c/libcurl-easy.html), con parsing JSON via
[nlohmann/json](https://json.nlohmann.me/).

Differenze intenzionali rispetto all'originale (documentate anche nei commenti del codice):

- il generatore di numeri casuali è `std::mt19937_64` invece del PCG64 di NumPy: la
  riproducibilità a parità di seed vale all'interno di questo programma, non byte-per-byte
  rispetto all'output Python;
- il beta di un asset trovato via ricerca ISIN è impostato a `1.0` di default: l'endpoint
  di ricerca di Yahoo (`/v1/finance/search`) non include un beta pronto all'uso come fa
  `yfinance`, e l'endpoint che lo fornirebbe (`quoteSummary`) richiede un token di
  autenticazione ("crumb") lato Yahoo;
- i due test Python che simulano le risposte di rete con `monkeypatch` sono sostituiti da
  un unico test sulla mappa di fallback locale (ETF europei hardcoded), che non richiede
  rete — testare il vero fetch da Yahoo richiederebbe un test di integrazione online.

## Dipendenze

Scaricate automaticamente da CMake (`FetchContent`), quindi non servono passi manuali:

- [nlohmann/json](https://github.com/nlohmann/json) — parsing JSON
- [doctest](https://github.com/doctest/doctest) — framework di unit test
- [GLFW](https://www.glfw.org/) — finestra e contesto OpenGL
- [Dear ImGui](https://github.com/ocornut/imgui) — widget della UI
- [ImPlot](https://github.com/epezent/implot) — grafici (barre, scatter, gauge a torta)

Da installare a livello di sistema:

- Un compilatore C++20 e CMake ≥ 3.20
- **libcurl** (header di sviluppo): `libcurl4-openssl-dev` su Debian/Ubuntu
- Per la GUI: librerie di sviluppo OpenGL/X11 (su Debian/Ubuntu:
  `libgl1-mesa-dev libx11-dev libxrandr-dev libxinerama-dev libxcursor-dev libxi-dev`)

```bash
# Debian/Ubuntu
sudo apt-get install -y build-essential cmake libcurl4-openssl-dev \
    libgl1-mesa-dev libx11-dev libxrandr-dev libxinerama-dev libxcursor-dev libxi-dev
```

## Build

```bash
mkdir build && cd build
cmake ..
cmake --build . -j
```

Se le librerie di sviluppo OpenGL/X11 non sono disponibili (es. build headless/CI), la GUI
può essere disattivata; libreria e test si costruiscono comunque:

```bash
cmake -DRISKENGINE_BUILD_GUI=OFF ..
```

## Eseguire

```bash
./build/risk_engine_tests   # unit test (doctest)
./build/risk_engine_gui     # dashboard desktop (richiede un ambiente grafico)
```

## Verificato in questo ambiente

Il progetto è stato compilato e i test sono stati eseguiti in questo ambiente sandbox
(senza display grafico): libreria, test (16/16 test superati) e binario `risk_engine_gui`
compilano ed eseguono il link senza errori. Il rendering effettivo della finestra
non è stato verificato qui per assenza di un server grafico (X11/Wayland) — va controllato
su una macchina con ambiente desktop.
