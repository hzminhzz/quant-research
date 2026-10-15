# Milkman Trades — available-data native ML4T feature implementation

Date: 2026-10-14
Scope: **feature engineering only**. Final research state: EXPLORATORY / NOT_APPROVED. No native broker backtest, trade ledger, portfolio PnL, deployment or evaluation holdout access in this work unit.

## Research decision

The user confirms there is no available point-in-time stock history. To avoid blocking the price-mechanism studies, research six **separately labeled index-CFD adaptations** on existing canonical data. No claim is made that index CFD prices, broker tick volume, bid/ask dynamics, execution quality, or constituent exposure reproduce US-listed stocks, options, or CME futures.

Source-to-feature contract: `config/milkman_source_to_cfd_features_20261014.yaml`.

### Actual installed APIs

- `ml4t-engineer 0.1.4`, `compute_features(data, features, *, group_col=None, timestamp_col=None, assume_sorted=False)`.
- `ml4t-backtest 0.1.7`, `ml4t-data 0.1.0b14`, `ml4t-models 0.1.4`.
- Native indicator catalog has 120 entries; relevant supported indicators: `trange`, `sma`, `ema`, `atr`, `stddev`, `bollinger_bands`. The implemented module invokes the native engine for supported indicators.
- Local deterministic rule extensions only: ER15 ratio, causal 80th percentile, no-touch session flag, Phase grey compression algebra, locked-box state, source-specific calendar joins.

## Implemented files

- `src/strategies/milkman_native_features.py`: six candidate feature functions, plus prior-daily EMA gate and close-confirmed box prototype.
- `tests/test_milkman_native_features_20261014.py`: adversarial and synthetic numerical-oracle tests; ten passing at report time.
- `scripts/probe_milkman_index_features_20261014.py`: read-only canonical data feature probe. Run with `uv run --no-sync python -m scripts.probe_milkman_index_features_20261014`.
- `config/milkman_source_to_cfd_features_20261014.yaml`: frozen feature contract, eight source HTML hashes, four public ZIP hashes, source/adaptation differences.
- `docs/audit/milkman_six_intake_20261014.md`: earlier source inventory and research risks.

## Verified canonical source coverage in feature probe

| Input | Source | Observations | Evaluation window |
| --- | --- | ---: | --- |
| NQ alias raw | `index_minute_NQ` Dukascopy CFD | 83,835 minutes | 2021 Jan-Mar |
| ES alias raw | `index_minute_ES` Dukascopy CFD | 83,835 minutes | 2021 Jan-Mar |
| ES daily session series | `index_minute_ES` aggregation | 1,034 days | 2019-01-02 through 2022-12-30 |

The daily loader's midnight UTC timestamp is a session **label**, not market availability. The feature probe replaces it with the 17:00 ET CFD session-close availability timestamp before native daily/monthly feature calls. All inputs used are pre-2025. No stock/option data was fetched.

## Feature probe: observation counts, NOT trades

| Candidate | Verified feature observation |
| --- | --- |
| Morning Dip NQ CFD | 2,520 qualifying clock-window 3-minute bars; 1,809 ER<=0.35 observations; 2,520 ATR-valid after full-tape warmup |
| Legend's Buy Day ES CFD | 63 completed full-Globex session bars; 3 fresh-three-down setup observations |
| Legend's EMA NQ CFD | 1,614 valid 15-minute RTH bars, 63 daily setups evaluated, 3 causal no-touch strong-trend setups; **40-session percentile probe only**, not production 252-session threshold |
| Bilbo Box v2 underlying NQ CFD | 878 extended-hour hourly bars, 285 grey observations, 1 close-confirmed breakout proxy after previous-day EMA and 10–15 ET clock gate |
| Swing GG ES CFD | 1,034 daily observations; 712 with completed-prior-month ATR14 and pivot rails |
| Daily Bilbo ES CFD | 1,034 daily bars, 344 grey observations, 29 close-confirmed breakout proxies |

**These counts are not author replication counts, executions, filled trades, edge tests or independent economic results.** Some input periods differ by candidate because intraday prototypes use 2021 Q1 and daily prototypes use 2019–2022.

## Numerical/causal verification

- Ten unit tests passed. Tests cover native feature integration, ER/SMA-based ATR, fresh three-down state, warmup, future-price perturbation, previous-session percentile, month rail lag, hourly one-shot box, strict daily-EMA gate requirements, and independent pandas Phase-flag oracle after 200-bar seed convergence.
- The independent pandas Phase oscillator reference agrees with native grey flags after the declared 200-bar synthetic warmup; original source pandas seed and TA-Lib/native seed differ early, so exact bar-for-bar author parity is **not claimed**.
- An initial probe returned zero intraday bars because Polars i8 hour multiplication overflowed. The code now widens hours/minutes to i32 before converting to minutes, and nonzero bar counts were verified.
- A first probe incorrectly restricted ER/ATR history to entry hours. It now builds full 24-hour-ish CFD 3-minute feature tape first, then filters to eligible 10:00–12:00 ET (09:00–11:00 CT) signal clock.
- Incomplete 15-minute RTH sessions cannot form an EMA setup (26 complete bars required).
- The 2025-2026 allocation study was not opened, rerun, or modified.

## Important remaining differences and gates

1. **Morning Dip** — original needs real NQ 1-second futures prices and price-through-limit fills. 1-minute CFD data can compute setup features but not exact fills.
2. **Legend's Buy Day** — the correct full Globex feature clock has been prototyped. Exact 18:00 ET entry and 09:30 ET exit requires minute-event `ml4t.backtest.Engine` execution and a same-session fill audit.
3. **Legend's EMA** — original 2008–2026 percentile is future-contaminated. The frozen CFD feature contract uses a lagged 252-session 80th percentile. The probe uses 40 lagged sessions to demonstrate the API on 2021 Q1; it is NOT the full frozen threshold trial.
4. **Bilbo Box v2** — author code's breakout-high criterion disagrees with its written close-above-high rule. Our prototype uses the stated close-confirmed variant. It is signal-only, and all options PnL is BLOCKED_DATA.
5. **Swing Golden Gate** — true month-long open/arm/complete logic and ordered stop/target fills still require event-driven native broker implementation. Existing daily level features do not imply completed trades.
6. **Daily Bilbo** — the CFD state engine uses close-confirmed breakout *observations*. Original strategy's resting stop and gap-sensitive fills need a separate native broker model. Single-index CFD is not a PIT stock-universe replication.
7. **Portfolio diversification** — no native marked-equity ledgers yet; no valid incremental portfolio impact can be estimated.
8. **Source packages** — HTML/ZIP hashes recorded from direct retrieval. Only the Bilbo public `box_signals.py` was inspected in depth during this unit; all packages need complete reference-code reading and explicit feature/fill parity before exact replication claims.

Next authorized scope may use the frozen feature variants as inputs to explicitly registered development-only native broker trials. No optimizer/parameter search is authorized, and no strategy is promoted.
