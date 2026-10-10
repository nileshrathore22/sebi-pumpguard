# Architecture

```
                 ┌──────────────┐   daily 18:30 IST (mon-fri)
 yfinance / ───▶ │  scheduler   │── ingest ──▶ price_history (immutable, ON CONFLICT DO NOTHING)
 synthetic       │ (APScheduler)│── score  ──▶ anomaly_scores (+ feature snapshot) ──▶ alerts
                 └──────────────┘
                         │                         ┌────────────┐
                         ▼                         │   Redis    │ cache (TTL) + rate-limit counters
 ┌─────────────┐   ┌───────────┐   HTTP/JSON  ┌────┴──────┐     └────────────┘
 │ Streamlit   │──▶│  FastAPI  │◀────────────▶│ PostgreSQL│
 │ dashboard   │   │   (api)   │              └───────────┘
 └─────────────┘   └───────────┘
                         │
                         ▼
        features ─▶ detector (decides) ─▶ score 0-100 ─▶ LangGraph explainer (explains only)
```

## Layers (`app/`)

| Package | Responsibility | Key rule |
|---|---|---|
| `ingestion/` | fetch OHLCV (Yahoo `.NS` or synthetic), retry with backoff, per-symbol isolation, benchmark CSV validation | `official` mode rejects unverified / synthetic cases |
| `features/` | 10 strictly trailing features per (symbol, day) | uses only rows ≤ t; tested by mutating future rows |
| `detection/` | pooled IsolationForest + z-score rule + logistic baseline; percentile score; threshold tuning | tuning raises `TestSplitLeakageError` on non-dev periods |
| `evaluation/` | backtest, negative controls, P/R/F1/FPR, bootstrap CIs, report | model fit only before the first test pre-window |
| `explain/` | LangGraph `load_score_payload → draft_explanation → grounding_check → format_response` | LLM sees only the precomputed payload; any ungrounded number/date or banned term → template fallback |
| `api/` | routers, schemas, uniform errors, rate limiting | every response carries the disclaimer (body + `X-PumpGuard-Disclaimer` header) |
| `cache/` | Redis JSON cache; in-memory fallback if Redis is down | fails open |
| `jobs.py`, `scheduler.py` | ingest → score → alert pipeline shared by CLI and scheduler | |

## Data model

`stocks`, `price_history (symbol,date unique)`, `sebi_cases`, `anomaly_scores (symbol,as_of_date,model_version unique; feature_snapshot JSON)`, `alerts`, `pipeline_runs`. Migrations: `app/db/alembic/`.

## Live scoring vs backtest

* **Backtest** (`app/evaluation`): the model is fit only on data before the first test pre-window, thresholds are tuned on dev cases, and metrics are reported on test cases. This is the number that goes in the report.
* **Live scoring** (`app/jobs.py`): the model is refit on all stored history, and the dev-tuned IsolationForest threshold from the latest backtest artifact is used to raise alerts. Live scores are percentiles relative to the whole history and are for monitoring only.

## Containers (`docker-compose.yml`)

`postgres`, `redis` → `api` (runs `alembic upgrade head`, seeds the synthetic demo if the DB is empty, then uvicorn) → `scheduler` and `dashboard`. All have healthchecks, and dependents wait for `service_healthy`.
