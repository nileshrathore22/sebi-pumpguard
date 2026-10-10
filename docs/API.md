# API

Interactive docs: `http://localhost:8000/docs`. Every JSON body includes `disclaimer`, and every response has an `X-PumpGuard-Disclaimer` header.

| Method | Path | Purpose | Cache |
|---|---|---|---|
| GET | `/health` | DB + cache status (exempt from rate limit) | – |
| GET | `/stocks` | list of stored symbols | – |
| GET | `/stocks/{symbol}/score?as_of=YYYY-MM-DD` | latest (or as-of) score, threshold, top features, explanation | TTL |
| GET | `/stocks/{symbol}/history?start=&end=` | OHLCV + daily score | TTL |
| GET | `/cases?split=dev\|test&verified=true\|false` | benchmark cases | – |
| GET | `/cases/{case_id}/replay?detector=isolation_forest\|zscore_rule\|logistic_regression` | day-by-day replay of a case | TTL |
| POST | `/evaluate/backtest` | run the backtest | TTL |
| GET | `/alerts?limit=50` | recent alerts with explanations | – |

## Examples

```bash
curl -s localhost:8000/stocks/SYNTH_09/score | jq
curl -s -X POST localhost:8000/evaluate/backtest -H 'content-type: application/json' \
  -d '{"source":"synthetic","mode":"dry-run","n_bootstrap":500}' | jq .result.warnings
```

`/stocks/{symbol}/score` response (abridged):

```json
{
  "symbol": "SYNTH_02", "as_of_date": "2023-12-21", "score": 99.34, "threshold": 97.05,
  "flagged": true, "model_version": "iforest-pooled-v1",
  "top_features": [{"feature": "turnover_rel_median", "value": 4.5, "robust_z": 10.0}],
  "explanation": "On 2023-12-21, SYNTH_02 received an anomaly risk score of 99.3 out of 100 ...",
  "explanation_path": "fallback",
  "disclaimer": "PumpGuard outputs statistical anomaly risk scores ..."
}
```

`POST /evaluate/backtest` body: `source` (`synthetic`|`db`), `mode` (`dry-run`|`official`), `n_bootstrap` (50–2000), `include_periods` (bool). `synthetic` + `official` → 400. No eligible cases → 409.

## Errors

The same shape is used for every error:

```json
{"error": {"code": 404, "message": "no anomaly score for NOPE"}, "disclaimer": "..."}
```

Codes: 400 bad input, 404 unknown symbol/case, 409 not enough data/cases, 422 validation, 429 rate limit (`Retry-After` header), 500 internal.

## Rate limiting

Fixed window per client IP, `RATE_LIMIT_PER_MINUTE` (default 60), with counters stored in Redis. If Redis is unreachable the limiter fails open and the cache becomes in-process.
