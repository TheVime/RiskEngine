# RiskEngine

RiskEngine is a lightweight Streamlit application for analysing investment portfolio risk.

## Features

- Add and edit assets with value, ticker, expected return, volatility and beta
- Search for and add European ETFs and other listed instruments by ISIN
- Calculate portfolio value, expected return, volatility, beta and Sharpe ratio
- Display each asset's contribution to portfolio risk
- Estimate bond yield to maturity, Macaulay duration, modified duration and convexity
- Simulate compound growth adjusted for inflation and taxes
- Run historical portfolio scenarios using real daily market data from Yahoo Finance

## Run locally

Install Python 3.11 or newer, clone the repository and open a terminal in the project directory.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

### Ubuntu or macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open http://localhost:8501 in your browser.

If Ubuntu does not provide the virtual-environment module, install it first:

```bash
sudo apt update
sudo apt install -y python3-venv
```

## Run with Docker

### Build from a local checkout

```bash
docker build -t riskengine .
docker run -d \
  --name riskengine \
  --restart unless-stopped \
  -p 8501:8501 \
  riskengine
```

### Build automatically from GitHub with Docker Compose

From any directory containing the `docker-compose.yml` file:

```bash
docker compose up --build -d
```

The Compose configuration uses `https://github.com/TheVime/RiskEngine.git#main`
as its build context. Docker therefore downloads the latest `main` branch before
building the image. The application is then available at:

```text
http://localhost:8501
```

The Compose setup also:

- restarts the container automatically unless it is manually stopped
- exposes port `8501`
- stores the `/data` volume in a persistent Docker volume named `riskengine_data`

Useful Compose commands:

```bash
docker compose logs -f
docker compose ps
docker compose restart
docker compose down
```

The application uses historical market data when available. Yahoo Finance can
occasionally rate-limit or fail to identify an instrument; in that case the app
uses its configured fallback logic or the assumptions entered by the user.
