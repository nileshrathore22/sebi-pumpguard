# Design decisions

Each entry: the decision, why, and the alternative that was considered.

## D1. Dependency management: `pip` + `requirements.txt`
`requirements.txt` (runtime) and `requirements-dev.txt` (tooling) work with plain pip in Docker and CI.
`uv` is used only as a fast installer locally (`make install`); it reads the same files.
*Alternative:* uv lockfile. Rejected to keep one universally understood format.

## D2. Python 3.11 via uv-managed interpreter
The prompt requires 3.11+. The dev VM ships 3.10, so `uv python install 3.11` is used; Docker uses `python:3.11-slim`.

## D3. Structured JSON logging (stdlib only)
A small `JsonFormatter` avoids an extra dependency (structlog) and emits one JSON object per line,
with any `extra={...}` fields included. Easy to grep and to ship to a log store.

## D4. Idempotent ingestion via `INSERT ... ON CONFLICT DO NOTHING`
The unique `(symbol, date)` constraint is the source of truth. Re-running a job inserts only
missing days, so a re-run is a no-op. *Alternative:* `DO UPDATE` (overwrite with the latest
vendor values). Rejected for the MVP so stored history is immutable and audit-friendly; vendor
corrections can be handled by an explicit backfill.

## D5. Retry with exponential backoff, per-symbol isolation
Each symbol fetch is retried (1s, 2s, 4s ...) then, if it still fails, recorded in
`pipeline_runs.symbols_failed` while the rest of the universe continues. Run status is
`success`, `partial` or `failed`.

## D6. Benchmark modes: `official` vs `dry-run`
`official` accepts only complete rows with `verified=true`, non-synthetic symbols and an
`order_url` on sebi.gov.in. `dry-run` additionally accepts unverified rows (used for `SYNTH_`
fixtures) and every output is stamped DRY-RUN. The template ships with `verified=false` on all
rows, so no real-looking result can be produced until a human fills it in.

## D7. Synthetic demo universe
20 `SYNTH_` symbols (12 with an injected pump, 8 clean) generated deterministically
(seeded). Pump intensity varies (0.45-1.4) so some cases are deliberately hard and recall is
not trivially 100%. Random one-day "news" spikes in every series create realistic false
positives. Dev cases are in 2022 and test cases in 2023 (chronological split).

## D8. Features are relative to the symbol's own trailing history
Every feature is a z-score, ratio or return against the same symbol's preceding window. This
makes a pooled model meaningful across stocks with very different price and liquidity levels
(a 5x volume day means the same thing for a Rs 20 stock and a Rs 2,000 stock). Log-volume is
used for z-scores because raw volume is heavily right-skewed.

## D9. One pooled IsolationForest (not one model per symbol)
Features are already normalised against each symbol's own history (D8), so a single model
fit on all symbol-days learns what "normal relative behaviour" looks like across the universe.
*Why not per-symbol?* A symbol has roughly 250 days a year, too few to learn a stable
multi-dimensional density per stock, and per-symbol models would treat a stock that is
manipulated for long stretches as "normal". Pooling also gives one model version to audit.
*Trade-off:* sector-specific behaviour is not modelled; that is listed as future work.
Hyper-parameters: 300 trees, `max_samples=256` (the original paper's default),
`contamination="auto"` (we do not use sklearn's internal threshold), `random_state=42`.

## D10. Score = empirical percentile (0-100)
Raw anomaly values are mapped to the percentage of reference (training) days with a lower or
equal raw value. 99.5 means "more unusual than 99.5% of reference days". Every detector,
including the z-score rule, uses the same mapping, so thresholds are comparable. The logistic
baseline already outputs a probability, so its score is `100 * P(case window)`.

## D11. Threshold tuned on dev split only, enforced in code
`select_threshold` raises `TestSplitLeakageError` if it receives any non-dev period. It
maximises case-level F1 over a grid (fine-grained above 95), and breaks ties towards the higher
threshold (fewer alerts).

## D12. Baselines
(a) `zscore_rule`: trailing 20-day log-volume z-score, the classic exchange-surveillance
rule; (b) `logistic_regression`: standardised features, class-balanced, trained on dev-split
labels only (1 = inside a dev case window). If IsolationForest cannot beat (a), the extra
complexity is not justified, and the evaluation report will show that honestly.

## D13. Model fit cutoff (no temporal leakage into the model)
During backtesting every model is fit only on rows dated before
`min(test window_start) - pre_window_days`. So no model, unsupervised or supervised, sees
anything from the test period. For live scoring (dashboard / API) the model is refit on all
history up to the latest date, which is legitimate because it is only applied going forward.
