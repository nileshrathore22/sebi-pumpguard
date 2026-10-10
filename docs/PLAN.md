# PumpGuard build plan

Phase-by-phase checklist. Each phase ends with tests + lint green and a conventional commit.

| Phase | Scope | Status |
|---|---|---|
| 0 | Scaffold: layout, env config, JSON logging, Makefile, pre-commit, CI | done |
| 1 | Data layer: SQLAlchemy models, Alembic, idempotent ingestion with retry/backoff, per-symbol failure isolation, universe.yaml, benchmark loader/validator | done |
| 2 | Strictly trailing feature engineering + leakage test | done |
| 3 | Detection: pooled IsolationForest, z-score rule + logistic baselines, 0-100 score, top features, dev-only threshold | done |
| 4 | Evaluation: backtest runner, negative controls, P/R/F1/FPR + bootstrap CIs, bias audit, CLI + API | done |
| 5 | Explanation: LangGraph agent with grounding check, template fallback | todo |
| 6 | API (FastAPI), Redis caching, rate limiting, Streamlit dashboard with case replay | todo |
| 7 | Docker/compose with healthchecks, scheduler, docs, CI green | todo |
| 8 | (stretch) social-signal module behind a feature flag | not started |

## Human-in-the-loop items

1. Fill `data/benchmark/cases_template.csv` with real, verified SEBI cases (`make validate-cases`).
2. Confirm the stock universe in `config/universe.yaml`.
3. (Optional) Provide `LLM_API_KEY` and set `LLM_PROVIDER=openai`.
