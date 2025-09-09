# XGuard-Xion

**XGuard-Xion** is an open-source, stateless InfoSec-safe validator for Xion wallet addresses and Real World Asset (RWA) contracts using FastAPI.

## Features

- Validate any Xion wallet address (balance, tx count, failed txs, anomaly flag).
- Transparent AI/heuristic risk scoring (score 0–100).
- SQLite metrics logging (timestamp, address, duration, score, status).
- `/metrics` endpoint for validation stats.
- `/rwa/assets` endpoint fetches live RWA contract data (CosmWasm).
- `/iso/pain001.xml` endpoint exports results in ISO 20022 XML format.
- Simple dark mode web UI with neon green and orange accents.
- Security middleware: headers, input validation, rate limit (no PII, no keys).

## Directory Structure

```
/app.py                # FastAPI entrypoint
/xion_handler.py       # Wallet validation with 3 fallback RPC/REST endpoints
/risk_engine.py        # AI/heuristic risk scoring (transparent)
/rwa_handler.py        # CosmWasm smart-query for live RWA contracts
/iso_export.py         # ISO 20022 XML export (pain.001, pacs.008)
/metrics.py            # SQLite logging: timestamp, address, duration, score, status
/utils.py              # Helpers + fallback rotation
/templates/index.html  # Dark UI, dashboard
/static/style.css      # Dark + neon green/orange accents
/static/Xguard-logo.png# Logo placeholder
/requirements.txt
/README.md
/LICENSE
```

## Install & Run

Python 3.9+ recommended.

```bash
pip install -r requirements.txt
uvicorn app:app --reload
```
Visit [http://localhost:8000](http://localhost:8000)

## Disclaimer

- MVP only. No financial advice.
- Stateless, no private keys or user data stored.
- RWA data accuracy depends on upstream CosmWasm contracts.
- ISO export for experimentation only.

MIT License.