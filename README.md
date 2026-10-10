# PumpGuard

PumpGuard flags **statistically anomalous price-volume behaviour** in Indian small/mid-cap stocks, which is the quantitative signature of pump-and-dump schemes. It validates itself **retrospectively** against SEBI enforcement cases and uses an LLM **only to explain** scores that have already been computed.

> PumpGuard outputs statistical anomaly risk scores for research and education only. A high score is not an accusation of wrongdoing and is not investment advice or a buy/sell signal.

## 5-minute quickstart

Requirements: Docker with Compose v2. No API keys needed.

```bash
git clone <this repo> && cd pumpguard
cp .env.example .env        # optional; defaults work
make up                     # postgres, redis, api, scheduler, dashboard
```

The first start takes about 1–2 minutes. The API migrates the DB and seeds a **synthetic** demo universe (`SYNTH_01…SYNTH_20`, 12 with injected pump patterns).

* Dashboard: http://localhost:8501. Pages: stock score gauge + price/volume chart with flags, benchmark case replay, backtest metrics, alerts.
* API docs: http://localhost:8000/docs. Try `curl localhost:8000/stocks/SYNTH_09/score`.

Developer loop (Python 3.11 via [uv](https://github.com/astral-sh/uv)):

```bash
make install     # .venv + dev deps
make lint typecheck test
make backtest    # dry-run backtest on synthetic fixtures -> artifacts/
```

## How it works

1. **Ingest** daily OHLCV from Yahoo Finance (`SYMBOL.NS`), or generate synthetic data. Ingestion is idempotent, retries with exponential backoff, and a failing symbol does not stop the others.
2. **Features** (10, strictly trailing, relative to each stock's own history): volume z-scores (20/60 d), 1/3/5-day returns, volume-price divergence, range and volatility expansion, turnover vs median, consecutive up-days. A test mutates future rows and checks that past features do not change.
3. **Detect** with one pooled IsolationForest. The score is the empirical percentile (0–100) and comes with the top contributing features. Baselines: a z-score rule and a logistic regression trained on dev cases only.
4. **Evaluate** retrospectively. Cases are split chronologically into dev and test, the threshold is tuned only on dev (enforced in code), and precision/recall/F1/FPR on test come with bootstrap 95% CIs, lead time, and matched negative-control periods.
5. **Explain** with a LangGraph flow: payload → draft → grounding check → format. Every number or date in the text must come from the payload, and words like "manipulation", "fraud" or "guarantee" are rejected. Any failure, or no API key, falls back to a deterministic template.

Docs: [architecture](docs/ARCHITECTURE.md) · [API](docs/API.md) · [evaluation & bias audit](docs/EVALUATION.md) · [design decisions](docs/DECISIONS.md) · [runbook](docs/RUNBOOK.md) · [plan](docs/PLAN.md)

## Current status of the evaluation

The repository ships with **no real SEBI cases**. `data/benchmark/cases_template.csv` contains empty placeholder rows only. All numbers you see in the demo come from a **synthetic dry run**, and every output that uses them is labelled as such. To produce the official result, add 15–20 verified cases (see [runbook](docs/RUNBOOK.md#adding-real-sebi-cases-human-step)) and run `make backtest-official`. Below 15 verified cases, every report carries a "not statistically meaningful" warning.

## What this project does NOT claim

* It does **not** detect manipulation, fraud or intent. It measures how unusual a day's price-volume behaviour is relative to history. Many legitimate events (results, news, index inclusion, corporate actions) also look unusual.
* A high score is **not** an accusation, **not** evidence, and **not** a buy/sell signal.
* It is **not** a real-time surveillance system. It works on end-of-day data.
* Synthetic results are **not** evidence of real-world performance. Only an official backtest on verified SEBI cases is.
* With only 15–20 cases, the confidence intervals are wide, so treat point estimates with caution.
* SEBI cases are a biased sample of schemes that were *caught*. Undetected schemes and non-enforced pumps are absent, which biases recall estimates (see the bias audit in [EVALUATION.md](docs/EVALUATION.md#3-bias-audit)).
* The LLM never sees raw market data and never decides anything. It rephrases already computed numbers, and its output is checked.

## Repository layout

```
app/            ingestion, features, detection, evaluation, explain, api, cache, db, jobs, scheduler
dashboard/      Streamlit app (talks to the API only)
config/         universe.yaml (stock list, needs human confirmation)
data/benchmark/ cases_template.csv (real cases, human-filled), synthetic_cases.csv (SYNTH_ fixtures)
docker/         Dockerfile + API entrypoint
docs/           architecture, API, evaluation, decisions, runbook
tests/          pytest suite (leakage, threshold-split, grounding, API, ingestion, ...)
```
