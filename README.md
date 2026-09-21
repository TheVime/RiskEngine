# RiskEngine

RiskEngine is a lightweight portfolio risk analysis app for investment assets.

Features:
- Add or edit assets with value, ticker, expected return, volatility, and beta
- Search and add assets by European ISIN (ETF and other listed instruments)
- Calculate portfolio value, expected return, total volatility, beta, and Sharpe ratio
- Show the risk contribution of each asset
- Analyse bond duration (Macaulay and modified) and approximate YTM
- Simulate compound growth adjusted for inflation and taxes
- Simulate 10,000 scenarios using real historical daily returns from Yahoo Finance

Quick start (local):
1. Install Python 3.11 or newer.
2. Clone the repository and open a terminal in the project directory.
3. Create a virtual environment:
   - Windows PowerShell:
     `cd C:\percorso\RiskEngine`
     `python -m venv .venv`
   - Ubuntu/macOS: `python3 -m venv .venv`
4. Activate the virtual environment:
   - Windows PowerShell: `.\\.venv\\Scripts\\Activate.ps1`
   - Ubuntu/macOS: `source .venv/bin/activate`
5. Install the dependencies: `python -m pip install -r requirements.txt`
6. Start the app: `python -m streamlit run app.py`
7. Open http://localhost:8501 in your browser.

Il file si chiama **`requirements.txt`** (con la `s` finale). Se PowerShell segnala
che il file non esiste, verifica di essere nella cartella del progetto con
`Get-Location` e usa `Get-ChildItem requirements.txt`.
Se compare un errore `ModuleNotFoundError`, assicurati di aver attivato `.venv` e
ripeti `python -m pip install -r requirements.txt`; avvia poi Streamlit con lo
stesso interprete usando `python -m streamlit run app.py`.

On Ubuntu, if `venv` is not available, install it first with
`sudo apt update && sudo apt install -y python3-venv`.

Docker quick start:
1. docker build -t riskengine .
2. docker run -d --name riskengine -p 8501:8501 riskengine

Or with Docker Compose:
1. docker compose up --build -d

The app opens a browser window where you can insert your assets and review the resulting portfolio risk profile. The scenario simulation is based on historical market data for the selected tickers, resampled to generate 10,000 realistic outcomes.
