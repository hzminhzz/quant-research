# Matthiola 20-USDT XGBRanker — mission verdict

**Source:** `matthiola0/ml-cross-sectional` (MIT), notebook 05, BTC robustness appendix.
**Contract:** [`matthiola_source_contract.md`](matthiola_source_contract.md)
**Reproduction evidence:** [`matthiola_g1_g2_reproduction.md`](matthiola_g1_g2_reproduction.md)
**Runners:** `research_programs/matthiola/{run_repro,run_signal,run_purged,oracle_build,run_perturb}.py`
**Upstream code:** vendored byte-identical in `research_programs/matthiola/upstream/`
**Data:** Binance spot daily via the upstream ccxt loader, 2018-01-01→2025-07-30,
20/20 symbols, parquet SHA-256 `17b634ade176422c363f6b69b9456e35956caf913c4f6f0577211d9e6e5cf324`

> **Headline correction to the inbox digest.** The inbox `thesis.yaml` frames this as a
> 20-name Binance USDT study. The source's *primary* experiment is 502 S&P 500
> constituents, 2015–2025. The crypto panel is a **robustness appendix**. This mission
> tests the appendix, not the paper.

---

## Verdict: **NOT ACCEPTED**

The mission's acceptance clause is: *accepted only if G1 reproduces, G6's independent
implementation agrees, and G7 shows the conclusion surviving all five perturbations.*

G1 **passed**. G6 **passed**. **G7 failed** — the edge does not survive the
trade-concentration and liquidity-floor perturbations. By the mission's own rule the
result is not accepted, and G8 was therefore not run (see below).

---

## Gate results

| Gate | Result | Key numbers |
| --- | --- | --- |
| **G0** contract + tape | **PASS** | 14 source files hash-pinned; 46,079 rows, 20/20 symbols, 2018-01-01→2025-07-30 |
| **G1** reproduce | **PASS** (IC) / residual on XGB Sharpe | IC-IR: XGB **0.188** vs reported 0.18 (Δ 0.008); naive_ew **−0.386** vs −0.39 (Δ 0.004). Shape: naive_ew **−0.224** vs −0.22 (Δ 0.004); XGB 0.861 vs 0.74 (Δ 0.121, diagnosed) |
| **G2** clock truth | **PASS** | daily bar stamped at **bar start**, `close` = last print before 24:00 UTC, `volume` = base units; **funding N/A** (spot); decision/entry same-print coincidence identified |
| **G3** signal before model | **PASS** | 6/12 features positive IC; **0/12 reach HAC t > 2**; n_eff **48.6–208.4** (not 1,096); best positive `ret_126d` IC 0.0425, HAC t **1.35** vs naive t 4.60 |
| **G4** cost ceiling | **PASS** (cost not binding) | cost 182–396 bps/yr vs gross quintile spreads 790–3,862 bps/yr; **significance**, not cost, is the constraint |
| **G5** purged walk-forward | **PASS** | XGB purged: IC-IR **0.269**, HAC t **2.794**, n_eff 80.8, ann net **17.1%**, Sharpe **0.728**, MDD **−40.2%**, turnover 1.25. `lag1` entry: Sharpe **0.863** |
| **G6** independent implementation | **PASS** (engine-level) | Polars vs pandas: all 14 columns agree with max abs diff **3.5e-11**, zero NaN mismatches, `all_agree_1e9 = true` |
| **G7** adversarial perturbations | **FAIL** | see table below; **FRAGILE** |
| **G8** native Engine simulation | **NOT RUN** — blocked | see below |
| **G9** provenance gate | **PASS** | `verify_provenance` in `ResearchFunnel.run`; 9 tests |

### G5 resolves the G1 residual

Purging 21 label-days at each train/test boundary *raises* IC-IR (0.188 → 0.269) and
*lower* Sharpe (0.861 → 0.728). **0.728 against a reported 0.74 is a Δ of 0.012.**
So the source's headline is reproduced by the causally-cleaner variant, and my
unpurged 0.861 was the outlier — most plausibly `xgboost 3.4.1` vs the source's
unpinned version, plus data vintage. `naive_ew` is identical under both variants,
which is the expected sanity check because it has no fit.

---

## G7 — the gate that failed

Stationary block bootstrap (block 21, 2,000 draws) on daily net returns.

| Perturbation | ann net | Sharpe | 95% CI | CI excludes 0 |
| --- | ---: | ---: | --- | :---: |
| baseline (purged XGB, 10 bps/leg, 5 quintiles, 20 names) | 17.1% | **0.728** | [0.089, 1.335] | yes (barely) |
| P1 entry at `close(t+1)` | 20.4% | 0.863 | [0.249, 1.434] | yes |
| P2 drop best 5% of **days** | −33.1% | −2.187 | [−2.736, −1.627] | yes |
| **P3 drop best 5% of trades (2 of 36 months)** | 5.6% | **0.347** | [−0.139, 0.820] | **no** |
| P4 cost 5 bps/leg | 17.6% | 0.744 | [0.110, 1.352] | yes |
| P4 cost 20 bps/leg | 16.1% | 0.696 | [0.057, 1.307] | yes |
| **P5 universe floor: top-10 median ADV** | 5.6% | **0.329** | [−0.308, 0.956] | **no** |
| P6 terciles | 12.0% | 0.684 | [0.083, 1.265] | yes |
| P6 deciles | 16.6% | 0.595 | [−0.0003, 1.131] | no (borderline) |

**Reading.**

- **Robust to the clock.** Delaying entry one day *improves* Sharpe (0.728 → 0.863).
  The edge is not a same-close artefact. This is the strongest positive finding.
- **Robust to costs.** 5→20 bps per leg costs only 0.05 Sharpe. The source's +0.74 is
  not a cost-modelling illusion.
- **Not robust to concentration.** Removing the best 5% of *trades* (2 of 36 months)
  takes Sharpe to 0.347 with a CI spanning zero. The measured edge lives in a minority
  of rebalances.
- **Not robust to liquidity.** Restricting to the 10 highest-ADV names (BTC, ETH, SOL,
  XRP, BNB, DOGE, AVAX, ADA, NEAR, LINK) takes Sharpe to 0.329, CI spanning zero.
  Roughly two-thirds of the edge sits in the less-liquid half of the basket — the same
  direction as the source's own note that `naive_ew` fails precisely because the
  hand-crafted factor signs are wrong in crypto.
- **P2 is reported for completeness but is not a fair test.** Deleting the best 5% of
  *daily* returns mechanically drives any Sharpe-0.73 strategy negative (the top 5% of
  days contributes more than the whole mean). P3 is the correct form of "drop the best
  5% of trades" and is the one that drives the verdict.

---

## G8 — not run, specific blocker

The gate asks for `ml4t.backtest.Engine` on the frozen spec. That requires a canonical
`DataVault`, and `PanelBuilder` is **store-based** (`PanelBuilder(store, output)`).

The ml4t store has **no Binance spot OHLCV family**:
`ls -d .../store/*spot*` → none; the only consolidated OHLCV families are
`crypto_futures_ohlcv_1h_BINANCE_UM_PERP`, `crypto_futures_ohlcv_1m_HYPERLIQUID_XYZ_PERP`,
`crypto_futures_ohlcv_1m_LIGHTER_USDC_PERP`.

The source trades Binance **spot daily**. Compiling a vault for it would require new
spot ingestion code, which is out of scope. **Named blocker: no `crypto_spot_ohlcv_*`
family in the ml4t store.** Independently of that blocker, G8 is moot for the
acceptance decision because G7 already failed.

---

## What would change the verdict

The mission's independence requirement was met only at the **engine** level (Polars vs
pandas), not the **author** level: the subagent dispatched for a fully independent
implementation could not run (provider usage limit). A second, unaffiliated
implementation of the feature panel and the walk-forward is the missing witness.

The two substantive attacks a reviewer should now demand:

1. **Concentration decomposition.** Is the 2023–2024 performance a small number of
   idiosyncratic moves (e.g. one token's squeeze) or a repeatable cross-sectional
   effect? This is the question P3 raises and does not answer.
2. **Beta neutralisation for crypto.** `vol_20d`, `vol_60d` and `size_adv_60` carry the
   largest |HAC t| (3.31, 2.80, 2.41) and all point *long high-vol, long illiquid* — the
   opposite of the equity low-vol anomaly, i.e. a beta/high-vol premium. The source runs
   a sector/beta neutralisation for equities (notebook 06) and does **not** do the crypto
   analogue. Until that is run, "XGB beats naive_ew in crypto" may be "XGB learned to
   buy beta while the handmade baseline did not".

---

## Reproduce

```bash
.venv/bin/python research_programs/matthiola/run_repro.py    # G1  (~160 s, fetches tape)
.venv/bin/python research_programs/matthiola/run_signal.py   # G3/G4 (~280 s)
.venv/bin/python research_programs/matthiola/run_purged.py   # G5  (~620 s)
.venv/bin/python research_programs/matthiola/oracle_build.py # G6  (~3 s)
.venv/bin/python research_programs/matthiola/run_perturb.py  # G7  (~9 s)
.venv/bin/pytest tests/test_provenance_gate.py -q            # G9
```

Requires `xgboost` (added at 3.4.1 — the upstream `model.py` imports it at module scope).

---

# Follow-up: where the edge actually comes from

Runner: `research_programs/matthiola/run_followup.py` · output: `followup_output/`
Inputs: the G5 purged scores and raw tape; nothing refitted except a per-date
cross-sectional OLS residual.

## Q1 — concentration

| Measure | Value |
| --- | ---: |
| Total net PnL over 2022–2024 (weight units, gross = 2) | 2.104 |
| **November 2024 alone** | **0.984 (46.8% of the whole result)** |
| Top 3 months (2024-11, 2023-01, 2022-07) | **69.9%** |
| Negative months | 18 of 43 |
| **Top 3 symbols (XLM, NEAR, XRP)** | **83.4% of gross contribution** |
| Largest loser | SOL −0.725 |

Per-symbol gross contribution: XLM +0.653, NEAR +0.592, XRP +0.586, ALGO +0.515,
BTC +0.239, … SOL −0.725, UNI −0.405.

**This is not a cross-sectional factor.** It is a concentrated long bet on three
altcoins, half of which was realised in the November 2024 post-election rally.

## Q2 — beta neutralisation (the crypto analogue of the source's notebook 06)

Rolling 60-day beta of each symbol against the equal-weight basket, lagged one day,
then a per-date cross-sectional OLS of score on [1, beta]; the residual is the
neutralised score.

Mean cross-sectional rank correlation between score and beta: **−0.325** — the ranker
systematically short-loads beta.

| Variant | mean IC | IC-IR | HAC t | n_eff | ann net | Sharpe | 95% CI | drop best 2 mo | top-10 ADV |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| raw | 0.0742 | **0.269** | **2.794** | 80.8 | 17.1% | **0.728** | [0.089, 1.335] | 0.347 | 0.127 |
| beta-neutral | 0.0256 | **0.109** | **1.285** | 120.4 | 9.8% | **0.507** | [−0.114, 1.176] | 0.051 | 0.234 |

- **IC-IR survival: 40%.** Roughly 60% of the cross-sectional information is beta.
- The residual is **not statistically significant** (HAC t 1.285 against 2.794).
- The Sharpe CI now **spans zero**, and removing two months collapses it to 0.051.

## Consequence for the source claim

The source's "+0.18 IC-IR, +0.74 net Sharpe" on the 20-name BTC universe reproduces
arithmetically (this mission: 0.269 / 0.728 purged) but does **not** represent a
generalizable cross-sectional edge. It is 60% market beta, 83% three coins, and 47%
one month. The source runs sector+beta neutralisation for equities and not for crypto;
running it removes the statistical significance.

**This is the substantive answer, and it is stronger than the G7 verdict alone:**
the appendix result is a reproducible computation, not a strategy.
