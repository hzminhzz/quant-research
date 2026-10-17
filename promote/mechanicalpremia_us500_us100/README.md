# Mechanical Premia C3 — US500 + US100 research candidate

**Selection:** Retained as the preferred exploratory candidate after the three-universe comparison. This package **does not** approve paper or live deployment. The original strategy implementation and its historical results remain unchanged. The user selected this candidate for further controlled research on 2026-10-14.

## Start here

Open [the standalone HTML tearsheet](reports/C3_US500_US100_Strategy_and_Portfolio_Tearsheet_2013_2026.html). It shows (1) H1 breakout alone, (2) D1 mean reversion alone, then (3) both sleeves in the same native ML4T portfolio. The frozen case specification is [config/research_session.yaml](config/research_session.yaml). See [STATUS.md](STATUS.md) for scientific approval and [research_next.md](research_next.md) before any change.

## Frozen strategy baseline

- **Instrument proxies:** Dukascopy US500 (`index_minute_ES`) and US100 (`index_minute_NQ`), BID-only CFD minute quotes.
- **Direction:** Long-only. There are **no short trades** in these historical rules.
- **H1 signal:** Completed hourly close above upper Bollinger Band(40, 2), with ATR(14) below its 100-bar rank median. A trailing 2× ATR exit follows the H1 sleeve.
- **D1 signal:** Completed daily close above EMA(100); ATR(20) below its 100-bar median; Bollinger Band(10, 3) percent-B below 0.20. Exit when percent-B exceeds 0.80. ATR sizes the D1 order but is **not a broker stop**.
- **Risk sizing:** At entry, target a **nominal 1% of current account equity as aggregate account-risk budget**. Allocate 23.36% of that budget to H1 and 76.64% to D1 in the combined portfolio. Split each sleeve budget equally across the two indices. Thus each new H1 position initially budgets 0.1168% of account equity and each new D1 position budgets 0.3832%, subject to available capacity and gross-notional constraints. Standalone H1 or D1 receives a full 1% aggregate nominal budget, split 0.5% per index. These are **position-sizing assumptions**, not hard drawdown guarantees or fixed contracts.
- **Direct modeled costs:** 1bp commission and 2bps slippage **per side**; user-observed sensitivity at 1.5× and 2×. True BID/ASK spreads, overnight CFD financing and contract point-value execution remain unverified.
- **Execution:** Native `ml4t.backtest.Engine`, with `ml4t.engineer.compute_features`; signal on complete H1/D1 bar, order no earlier than next minute. Original H1 initial protective stop attaches after fill observation, leaving a known first-minute gap. Price/session equivalence to MT5 is not certified.

## Frozen result snapshot, 2013–2026 YTD

All returns below are **synthetic price-unit research measurements**. The annual native accounts use a common `100,000`-unit simulation base to normalize results. Each year starts separately. Position quantities still adapt to current equity, ATR and a nominal 1% risk budget within each run. Hypothetical compounding of the annual returns is **not** a continuous invested-account backtest.

| Measure | H1 standalone | D1 standalone | Combined source-weighted |
| --- | ---: | ---: | ---: |
| Closed trades (long/short) | 1,347 (1,347/0) | 58 (58/0) | 1,405 (1,405/0) |
| Win rate | 36.97% | 84.48% | 38.93% |
| Net profit factor, closed trades | 1.06 | 8.07 | 1.55 |
| Closed-trade net PnL (synthetic units) | +12,155.83 | +56,321.96 | +40,746.42 |
| Illustrative linked annual ROI | +11.36% | +74.15% | +50.15% |
| Illustrative linked max drawdown | −13.91% | −10.25% | −7.83% |
| Illustrative linked daily Sharpe | 0.18 | 0.86 | 0.75 |
| Illustrative linked Calmar (linked annualized rate / linked DD) | 0.06 | 0.40 | 0.38 |

The standalone sleeves have **different position sizes** from the combined portfolio. Their PnLs cannot be summed to construct the combined account. A year-end marked position can affect annual equity without appearing among closed-trade PnL. The 2026 sample stops on October 11, 2026.

## Package layout

| Path | Use |
| --- | --- |
| `reports/C3_US500_US100_Strategy_and_Portfolio_Tearsheet_2013_2026.html` | **Exact revised report** sent to the user. |
| `reports/three_candidate_summary.json` | Native 252-cell three-candidate summary; C3 preferred for research, not execution. |
| `reports/all_annual_metrics.csv` | The complete C1/C2/C3 annual metrics table. |
| `reports/linked_roi_diagnostics.json` | Illustrative annual-linked equity metrics and explicit warnings. |
| `src/` | Frozen C3 native ML4T adapter and runner, copied byte-for-byte. |
| `tests/` | C3 point-in-time, universe and allocation regression test snapshot. |
| `scripts/` | Existing batch/three-candidate reporting helper snapshots. They **do not regenerate the redesigned HTML byte-for-byte**; it is a preserved report snapshot. |
| `audits/` | Original frozen hypothesis and H1 broker-parity audit. |
| `config/`, `provenance/` | Frozen session specification, source identities and package manifest. |

Canonical high-volume native ledger (not duplicated): `run_log/research_sessions/mechanicalpremia-us500-us100-2013-2026-v1/yearly_native/`. Comparable C1/C2 runs are in their respective original session folders. Canonical Dukascopy Parquet data is outside this repo under `/home/quant/dev/quant/ml4t-data/.data/store/`.

Re-run the root original test (without changing its frozen identity):

`uv run python -m pytest -q tests/test_mechanicalpremia_us2_2013_2026_v1.py`

The root scripts in `scripts/` are the proven import paths of the package snapshots. The copied `src/` files are snapshots for review and branching; do not assume they are independently importable without the repository.

## Scientific boundary

C3 was chosen **after inspecting C1 and C2 results** on 2013–2026 YTD observations. Historical performance is discovery evidence, not fresh OOS. This package is **PROMOTED_FOR_FURTHER_RESEARCH** only. Existing session status remains `NOT_APPROVED`, and changes must create a new session and report all attempted trials, including negative results.

Before production claims, correct source timing / H1 stop parity, verify the point value and lot mapping, true broker spread/financing, and build a continuous multi-year equity ledger with carried positions. Do not change historical parameters in place to improve an already-seen Sharpe.
