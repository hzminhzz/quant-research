# Spec: 25 research-qualified time-series sleeves from *Advanced Futures Trading Strategies*, evaluated per asset class

> ALIGN artifact. WHAT/WHY end-state — never HOW. Durable contract; the
> `decompose` step decomposes this into milestones/issues without asking the user
> anything. Every section must be verifiable. No TODO/??? placeholders.
>
> Source material: `Advanced Futures Trading Strategies` (Robert Carver), 30
> numbered strategies + 4 tactics. Book states 30 fully tested strategies.

## Objective

A strictly additive time-series research route exists that can express a
per-instrument forecast, its scaling, a volatility target, per-instrument risk
allocation and portfolio combination; 25 declarative sleeve specifications cover
book strategies 1–23 and 26–27 and are each evaluated in a separate asset-class
run (indices, gold, crypto); and a combined portfolio built only from qualified
sleeves exists with its own native backtest and multiple-testing evidence. Every
one of the 30 book items has a written terminal disposition.

## Why

Today 28 of the 30 book strategies cannot be expressed at all: the only
executable spec (`src/engine/spec_parser.py::CandidateSpec`) is a
cross-sectional dollar-neutral basket, `src/engine/signal_allocator.py` ranks one
signal across symbols, and `src/oracle/stage2_diagnostic.py` computes
cross-sectional Spearman IC. Book strategies 1–18 and 21–30 are time-series,
per-instrument forecast strategies with volatility targeting and portfolio
combination. Additionally `src/engine/funnel.py:244` and `src/workbench.py:200`
hard-fail Stage 3 on every index and metals vault (`execution_qualified: false`),
so native PnL is unreachable on two of the three target asset classes. Without
this work the book yields no testable, deployable strategy and the repository
cannot answer whether any of it works on indices, gold or crypto.

## Acceptance criteria

1. **Time-series spec form exists and is strictly additive.** A declarative spec
   kind can express: per-instrument forecast, forecast scaling, volatility
   target, per-instrument risk allocation, and portfolio combination. Validating
   an invalid spec rejects it before any market data is read.
2. **Atomic pre-reservation failure.** A rejected or failed spec validation,
   cost qualification or gate evaluation before holdout reservation writes no
   partial artifacts, records no gate verdict, and consumes no protected-read
   claim; the only durable record is the rejected attempt entry. Once the
   single protected-read claim has been reserved (criterion 12), it remains
   consumed even if the read crashes or fails; a failed protected read is
   reported as such and is never retried.
3. **All 25 sleeve specs are present and frozen.** Each of strategies 1–23 and
   26–27 has a declarative spec with a recorded spec hash and a predeclared
   asset-class compatibility declaration. The compatibility matrix covers all 25
   variants; every declared variant×class pair carries a one-line economic
   justification; no run exists for an undeclared pair.
4. **All 30 book items have a terminal disposition.** Each is exactly one of
   `QUALIFIED`, `FALSIFIED`, `BLOCKED(<reason>)`, `DIAGNOSTIC` (#24),
   `PORTFOLIO_MODE` (#25), `BLOCKED_MULTILEG` (#28, #29),
   `BLOCKED_NO_CONTRACT_CURVE` (#30). No book item is silently absent.
5. **Sleeve casefile.** Every sleeve run emits a casefile containing: feature
   proof (input hash, output hash, provider versions, causal cutoff comparisons),
   cost assumption record, carry assumption record, per-class gate table,
   terminal disposition, and code/data/vault hashes.
6. **Reproducible verdicts.** Re-running a frozen spec against the same vault
   reproduces identical gate verdicts and identical DSR input series hashes.
7. **No pooled cross-class PnL.** Every PnL, Sharpe, drawdown and DSR metric is
   labelled with its asset class and symbol set. Cross-class summaries aggregate
   evidence; no single return series mixes classes.
8. **Per-class DSR.** For each asset class, DSR is computed over that class's
   aligned trial-return set — every variant declared compatible with the class,
   including failed, abandoned and retried trials, plus declared prior trials in
   that class's selection family — and the exact input set is listed in the
   casefile. DSR is never computed over a 25-member all-class family and never
   over unaligned or manufactured return series.
9. **Cost and carry.** Every run declares nonzero commission, spread and
   slippage one-way. Carry is a hashed sidecar derived from a named rate curve
   with documented formula, tenor mapping and sign convention; the convention is
   covered by a sign test (positive rate charges longs, pays shorts). Results
   include a 2× carry-magnitude stress and a ±100 bp parallel curve-shift stress.
   Any sleeve whose financing is `UNKNOWN_NOT_MODELLED` cannot have disposition
   `QUALIFIED`. Zero-shaped `carry_rate` placeholders are never interpreted as
   observed zero financing.
10. **Gate semantics.** A sleeve is `QUALIFIED` for a class only if all seven
    hold on that class's evidence: (a) train net Sharpe > 0; (b) validation net
    Sharpe ≥ 0.30 at a 10% annualized volatility target; (c) validation net
    Sharpe ≥ 0.5 × train net Sharpe; (d) net Sharpe > 0 at 2× modeled costs;
    (e) validation maximum drawdown ≤ 25% at the 10% volatility target (train
    drawdown is reported diagnostically, not capped); (f) time-series rank
    correlation of the sleeve forecast against the forward return at the
    declared label horizon has Newey–West t ≥ 2.0 in train, with lags equal to
    the label horizon; (g) the class-level DSR computed per criterion 8 is
    ≥ 0.95. A sleeve cannot be `QUALIFIED` in any class whose family DSR fails,
    regardless of its own metrics.
11. **Combined portfolio.** A combined-portfolio object exists, built only from
    `QUALIFIED` sleeves under an inclusion and weighting rule frozen before
    composition; it has its own native backtest evidence and its own DSR over
    its declared class return sets. Including a non-qualified sleeve is a spec
    error, not a discretionary choice.
12. **One protected read, for the portfolio.** Exactly one protected-window read
    is consumed, by the combined portfolio, after the inclusion rule and all
    spec hashes freeze. The claim is reserved before reading. No sleeve
    consumes a protected read.
13. **Existing v1 behavior unchanged.** Every existing v1 candidate YAML parses
    to the same spec hash; `Workbench` public method signatures and semantics,
    factory stage semantics, promoted strategy packages, and all
    `tests/test_dual_mode_*.py` plus promoted tests pass unmodified.
14. **Trial accounting.** Every run, failure, abandonment and retry is appended
    to the trial ledger. A gate or parameter change made before a run is a
    predeclared variation; the same change after observing outcomes is a new
    trial and invalidates the prior verdict.

## In scope

- A new declarative time-series spec kind and its validation rules.
- A time-series execution/portfolio construction path reusing the shared feature
  compiler and native backtest internals.
- 25 sleeve specs for book strategies 1–23 and 26–27, each with a predeclared
  asset-class compatibility declaration.
- Cost/carry qualification for index, gold and crypto price sources, with carry
  materialized as an explicit modeled sidecar.
- Per-class gate evaluation, per-class DSR, sleeve casefiles.
- A combined portfolio object built under a frozen inclusion/weighting rule.
- One protected-window read for that portfolio.
- Written dispositions for #24 (diagnostic), #25 (portfolio mode), #28/#29
  (multi-leg blocked), #30 (contract-curve blocked).

## Out of scope

- Live orders, broker credentials, paper-trading harness, venue mapping, release
  manifests. Research qualification never grants deployment approval; status
  remains `NOT_APPROVED`.
- Multi-leg spread/triplet execution (#28, #29) and calendar/term-structure
  trading (#30) — blocked, not implemented here.
- FX as a deployment target. FX vaults may inform model carry but no sleeve
  claims FX deployability.
- Pooled cross-class PnL or a cross-class DSR family.
- Any change to v1 cross-sectional semantics, thresholds, or artifacts.
- New external data acquisition beyond materializing the existing local store.
- Portfolio optimisation beyond the book's #25 construction mode.
- Any claim that index/metals quotes are exchange-certified futures contracts.

## Constraints

- **Vault root.** `data/vault/markets_20261015/` — the live code default
  (`scripts/quant.py:61`, `src/engine/event_protocol.py:493`,
  `src/research_control/research_inbox_queue.py:401`). Protected partitions are
  produced by trusted ingestion with `quant.py materialize-markets
  --include-protected`; the current checkout holds `development/` only, and the
  architecture document's `market_prices_20261015` is an example path that this
  spec supersedes in favor of the code default.
- **Asset classes and symbols.** Indices: DAX, ES, EUSIDXEUR, HK33, NIKKEI225,
  NQ. Gold: XAUUSD, XAGUSD (plus `commodity_daily_GOLD` only where granularity
  and semantics are declared). Crypto: Binance USDT perpetuals with funding
  sidecars. FX is referenced only as carry/model context.
- **Cadence.** 1h is the primary cadence (`forex_1h`, `index_1h`, `metals_1h`);
  1m is allowed per sleeve where the book's horizon requires it, recorded in the
  casefile. Cross-cadence comparability is not claimed.
- **Native stack pinned.** `ml4t-backtest==0.1.7`, `ml4t-engineer==0.1.4`,
  `ml4t-diagnostic==0.1.6.post2`, `ml4t-data==0.1.0b14`. Private lifecycle seams
  require requalification if the version changes.
- **Carry integration is required work, not existing capability.** The installed
  `ml4t-backtest` 0.1.7 `Engine` has no `funding_df`; the only sanctioned
  mechanism in this repo is the per-instance pre-order cash hook in
  `src/engine/backtest_runner.py::_funding_hook`, which currently requires
  `timestamp, symbol, funding_rate, mark_price` events backed by a funding
  sidecar (`DataVault.load_funding`). Index and metals vaults carry no funding
  table, so the modeled-carry sidecar and its adapter must be built and its
  accounting reconciled; this spec does not assume that route already works for
  non-crypto sources.
- **Carry transformation semantics.** Handoff direction is defined, not implied:
  for spot/CFD-style price proxies the modeled rate is applied as a cashflow
  equal to `-quantity × price × rate`, so a positive rate charges longs and pays
  shorts, using the tenor implied by the settlement cadence. For any instrument
  whose simulated series already embeds financing (continuous futures), an
  additional carry cashflow is prohibited as double-charging. The applied
  transformation, its source curve (`bonds_daily_US10Y`/`US2Y` or an explicitly
  named alternative), tenor mapping and per-instrument sign are recorded per
  sleeve.
- **Development-only until the portfolio read.** Sleeve research may read only
  certified development partitions; the sole protected access is acceptance
  criterion 12.
- **Results are assumptions, not venue execution.** Modeled spread, slippage,
  commission and carry remain declared assumptions with unknown financing
  disclosed.

## Environment / prior art

- Cross-sectional runtime: `src/engine/spec_parser.py`, `feature_compiler.py`,
  `signal_allocator.py`, `backtest_runner.py`, `funnel.py`; `src/workbench.py`;
  `src/oracle/stage2_diagnostic.py`; `src/data_vault/`.
- Native feature catalog: `ml4t-engineer` exposes 120 primitives including
  `ema`, `ewma_volatility`, `atr`, `donchian_channels`, `adx`, `macd`, `mom`,
  `roc`, `higher_moments`, `sar`, `percentile_rank_features` — most book
  primitives are native; forecast scaling, volatility targeting and carry
  composites are extensions under ADR 0002.
- Feature boundary: `docs/adr/0002-engineer-first-feature-boundary.md`;
  causal proof: `src/oracle/causal_truncation.py`.
- Data materialization and semantics:
  `docs/architecture/dual_mode_20261015/market_materialization.md`;
  `src/data_vault/market_materializer.py`.
- Prior art for per-instrument trend outside the factory:
  `research_programs/gold_fx_trend_20261015.py` (native Engine, ROC60, monthly
  rebalance). Promoted-but-not-approved precedents:
  `promote/{one_bar_nq_30m,donchian_btc,rsi_30_50_spy,mechanicalpremia_us500_us100}`.
- Existing candidate examples: `config/candidates/*.yaml`; crypto panels under
  `data/processed/*_1h.parquet` with funding in
  `/home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_funding_*`.
- Trial ledger and evidence conventions: `run_log/trial_ledger.jsonl`,
  `src/engine/common.py::append_trial`, `run_log/validation_status.json`
  (`NOT_APPROVED`).

## Existing surface (must not break)

Verified against the live checkout:

- `CandidateSpec` v1 schema and defaults (`src/engine/spec_parser.py`) —
  including `schema_version`, field validation and `spec_hash` stability for
  every existing YAML.
- `src/workbench.py` public methods: `load`, `features`, `train_colab`, `ic`,
  `backtest`, `export_yaml` — signatures and behavior, including the
  `INCONCLUSIVE_STAGE_3` price-only gate.
- `src/engine/feature_compiler.py::compile_and_verify` and
  `point_in_time_universe` semantics.
- `src/engine/signal_allocator.py::allocate` cross-sectional target weights.
- `src/oracle/stage2_diagnostic.py::stage2` gate semantics.
- `src/engine/backtest_runner.py::run_native` version pin and native accounting
  invariants; the existing funding hook behavior for crypto.
- `src/engine/funnel.py` stage receipts and holdout reservation semantics.
- `tests/test_dual_mode_*.py`, `tests/test_promoted_*.py`,
  `tests/test_inbox_research_vertical_slice.py`, `tests/test_research_handoff.py`,
  and the managed feature-policy check.
- `promote/*` packages and their recorded status; `run_log/` history is
  append-only and is never rewritten.

## Open questions

- **Per-variant compatibility content and per-sleeve cadence.** Decision rule:
  the compatibility matrix and cadence table are authored as work-unit artifacts
  under the economic-justification rule in acceptance criterion 3, reviewed
  against the available symbol sets and data semantics, and frozen (hashed)
  before any sleeve run. Owner: research lead. Deferred — does not block
  planning.
- **Carry curve choice for gold.** Decision rule: use the explicitly named curve
  with the documented transformation; if no defensible tenor/lease proxy exists,
  the sleeve's disposition is `BLOCKED(<reason>)` rather than a zero-carry
  assumption. Owner: research lead. Deferred — does not block planning.
