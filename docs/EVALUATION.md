# Evaluation

## 1. Features

All features are computed per symbol, per trading day D, from rows with date <= D only.
"prev-N" means the N trading days *before* D (the baseline is shifted by one day so D is not
part of its own baseline). Notation: `V` volume, `C` close, `H` high, `L` low,
`r_t = ln(C_t / C_{t-1})`.

| Feature | Formula | Intuition |
|---|---|---|
| `vol_z20` | `(ln(1+V_D) - mean_prev20(ln(1+V))) / std_prev20(ln(1+V))` | Volume surge vs last month |
| `vol_z60` | same with a 60-day baseline | Volume surge vs last quarter |
| `ret_1d`, `ret_3d`, `ret_5d` | `C_D / C_{D-k} - 1` | Short-horizon price run-up |
| `vp_divergence` | `ln(V_D / median_prev20(V)) - ln(1 + 100*abs(ret_1d))` | Volume that is out of proportion to the price move (churning / wash-trade signature) |
| `range_expansion` | `((H-L)/C)_D / mean_prev20((H-L)/C)` | Intraday range blow-out |
| `volatility_ratio` | `std(r over D-4..D) / std(r over D-59..D)` | Short-term volatility vs medium-term |
| `turnover_rel_median` | `(C*V)_D / median_prev60(C*V)` | Rupee turnover vs normal |
| `consec_up_days` | number of consecutive days ending at D with `C_t > C_{t-1}` | Sustained one-way price push |

The first 60 trading days of each symbol are warm-up and produce no features.
Enforced by `tests/test_features.py::test_no_lookahead_mutating_future_rows` (mutates every row
after D and asserts all features at <= D are bit-identical) and
`test_truncated_history_gives_same_features`.

<!-- RESULTS:START -->
### Latest backtest (dry-run)

> **DRY-RUN on synthetic `SYNTH_` fixtures. These numbers say nothing about real SEBI cases.**

- Model fit cutoff (no data on/after this date used for fitting): `2022-12-23`
- Cases: dev=6, test=6; controls: dev=12, test=12; verified cases: 0

| Detector | Threshold (dev) | Dev F1 | Test precision | Test recall | Test F1 | Test FPR | Median lead (days) |
|---|---|---|---|---|---|---|---|
| `isolation_forest` | 97.05 | 0.923 | 0.667 [0.50, 0.86] | 1.000 [1.00, 1.00] | 0.800 [0.67, 0.93] | 0.250 [0.08, 0.50] | 1.0 |
| `zscore_rule` | 98.30 | 0.857 | 0.400 [0.20, 0.62] | 0.667 [0.33, 1.00] | 0.500 [0.25, 0.71] | 0.500 [0.25, 0.75] | 0.0 |
| `logistic_regression` | 93.00 | 0.923 | 0.750 [0.55, 1.00] | 1.000 [1.00, 1.00] | 0.857 [0.71, 1.00] | 0.167 [0.00, 0.42] | 0.0 |

95% bootstrap confidence intervals in brackets (stratified, 1000 resamples).

Warnings:
- only 0 verified cases (< 15); results are not statistically meaningful - DRY-RUN on unverified/synthetic data
<!-- RESULTS:END -->

## 2. Backtest protocol

1. **Cases.** Each benchmark case has a symbol, a manipulation window `[window_start, window_end]`
   taken from the SEBI order, and a `split` (`dev` or `test`). Use a chronological split: older
   cases are `dev`, newer ones are `test`.
2. **Scoring.** Every trading day from `window_start - 45 calendar days` (the pre-window) to
   `window_end` is scored.
3. **Detection.** A case counts as detected if the score is at or above the threshold on any day
   inside the window. **Lead time** = days from `window_start` to the first flag. We also record
   whether the stock was already flagged in the pre-window.
4. **Negative controls.** For each case, up to 2 other symbols over the same calendar dates.
   A symbol qualifies only if it has no case of its own within 60 days of that period, and
   symbols in the same sector or market-cap band are preferred. A control that crosses the
   threshold is a false positive.
5. **Metrics on the test split.** Precision = TP/(TP+FP), recall = TP/(TP+FN),
   F1, false-positive rate = FP/(FP+TN). 95% confidence intervals come from 1000
   stratified bootstrap resamples (cases and controls resampled separately, fixed seed).
6. **Detectors compared.** `isolation_forest` (primary), `zscore_rule`,
   `logistic_regression`. Each one gets its own dev-tuned threshold.

Commands: `make backtest` (synthetic, dry run), `make backtest-official` (verified cases in the
DB), or `POST /evaluate/backtest`. Artifacts are written to `artifacts/backtest_<mode>.json` and
`artifacts/backtest_<mode>_periods.csv`.

## 3. Bias audit

| Risk | How it is prevented | Enforced by |
|---|---|---|
| Look-ahead in features | Rolling windows are trailing only. Baselines are shifted by one day. No `center=True`, negative shifts, back-fill or whole-series statistics. | `tests/test_features.py::test_no_lookahead_mutating_future_rows`, `test_truncated_history_gives_same_features` |
| Model trained on test-period data | All models are fit only on rows before `fit_cutoff = min(test window_start) - pre_window` | `tests/test_evaluation.py::test_fit_cutoff_precedes_test_period`, `test_threshold_unaffected_by_test_split_data` |
| Threshold tuned on test cases | `select_threshold` raises `TestSplitLeakageError` if it receives any non-dev period. Thresholds are applied unchanged to test. | `tests/test_detection.py::test_threshold_refuses_test_split`, `tests/test_evaluation.py::test_threshold_unaffected_by_test_labels` |
| Supervised baseline sees test labels | Labels are built only from `split == "dev"` cases, and only for training rows | `app/evaluation/backtest.py::dev_labels` |
| Fabricated or unverified cases presented as real | `official` mode accepts only `verified=true` rows linking to sebi.gov.in and never accepts `SYNTH_`. Synthetic results are stamped DRY-RUN. | `tests/test_benchmark.py`, `tests/test_evaluation.py::test_cli_refuses_synthetic_official` |
| Too few cases | A warning is printed and stored with the result when there are fewer than 15 verified cases | `run_backtest` warnings, `test_backtest_end_to_end` |

**Known remaining biases (not solved, stated honestly):**
- **Selection bias.** SEBI orders cover cases that were caught. Undetected schemes may look different.
- **Window labels.** SEBI's investigation windows are approximate, so lead-time numbers inherit that uncertainty.
- **Controls may be contaminated.** A control stock may itself have had undiscovered manipulation, which biases the false-positive rate upwards.
- **Survivorship bias.** Delisted or suspended stocks may be missing from yfinance.
- **Small sample.** With around 15-20 cases the confidence intervals are wide, and any comparison between detectors must be read with the intervals.
