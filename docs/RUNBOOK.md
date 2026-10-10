# Runbook

## Start / stop

```bash
make up        # build + start postgres, redis, api, scheduler, dashboard
make logs      # follow logs
make down      # stop (data kept in the pgdata volume)
docker compose down -v   # stop and wipe the database
```

On first start the API container migrates the DB and seeds the synthetic demo (`SEED_DEMO=true`, only if `stocks` is empty). This takes about 30–60 s, and the dashboard waits for the API healthcheck.

## Local development without Docker for the app

```bash
make install                              # .venv with Python 3.11 (needs uv)
docker run -d --name pg -e POSTGRES_USER=pumpguard -e POSTGRES_PASSWORD=pumpguard \
  -e POSTGRES_DB=pumpguard -p 5432:5432 postgres:16-alpine
docker run -d --name redis -p 6379:6379 redis:7-alpine
make migrate seed
.venv/bin/uvicorn app.main:app --reload
API_URL=http://localhost:8000 .venv/bin/streamlit run dashboard/app.py
```

## Adding real SEBI cases (human step)

1. Fill `data/benchmark/cases_template.csv`, one row per case, using only information you have checked against the SEBI order:
   `case_id, symbol (bare NSE ticker), window_start, window_end (YYYY-MM-DD, the period the order says the price/volume was affected), order_reference, order_url (must be on sebi.gov.in), description, label, verified=true, split (dev|test)`.
   Put the older ~60% of cases in `dev` and the most recent ~40% in `test`.
2. `make validate-cases`. This must print `ACCEPTABLE` (needs ≥15 verified cases).
3. `docker compose exec api python -m app.cli load-cases --mode official`
4. Add the case symbols to `config/universe.yaml`, set `DATA_SOURCE=yahoo`, then run
   `docker compose exec api python -m app.cli ingest` and `... score`.
5. `docker compose exec api python -m app.cli backtest --source db --mode official` writes `artifacts/backtest_official.json`, and the API then uses its dev-tuned threshold.

## Real market data

Set `DATA_SOURCE=yahoo` in `.env`. The scheduler ingests the universe every weekday at 18:30 IST. A symbol that fails is retried with exponential backoff and recorded in `pipeline_runs.symbols_failed`, and the other symbols continue. Run status is `success`, `partial` or `failed`.

## LLM explanations (optional)

`LLM_PROVIDER=openai`, `LLM_API_KEY=...`, plus optionally `LLM_BASE_URL`/`LLM_MODEL` for any OpenAI-compatible endpoint. Without a key the deterministic template is used. The `explanation_path` field shows which one produced the text.

## Troubleshooting

| Symptom | Check |
|---|---|
| dashboard says "Cannot reach the API" | `docker compose ps`; api healthcheck; `docker compose logs api` |
| `/health` shows `cache: false` | Redis down. The API keeps working with an in-process cache. |
| `/health` shows `status: degraded` | Postgres unreachable or `DATABASE_URL` wrong |
| 404 on `/stocks/X/score` | X not ingested or not yet scored: run `ingest` then `score` |
| 409 on official backtest | no verified cases loaded (see above) |
