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
