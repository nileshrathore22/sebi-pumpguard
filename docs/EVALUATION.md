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
_No backtest has been run yet. Run `make backtest`._
<!-- RESULTS:END -->
