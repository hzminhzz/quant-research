# Mechanical Premia Yen Squeeze: native ML4T audit

Date: 2026-10-14. Session: `mechanicalpremia-yen-squeeze-mvp-20261014`.

## Decision

**INCONCLUSIVE.** The registered native feature trial passed. The strategy trials did not run because the available files and broker details do not support a source-faithful FX simulation. This result does not reject the economic hypothesis. It does not validate the strategy. The session remains `EXPLORATORY` and `NOT_APPROVED`.

No 2025 or later market data was read. No market-data strategy backtest, cost stress, or performance calculation was run. No live order was sent. The final test remains protected.

## Frozen scope and source rules

The frozen session is `config/research_sessions/mechanicalpremia_yen_squeeze_mvp_20261014.yaml`. Its recorded frozen hash is `6a600d273b1e257d8dbad967a3f2ac4aeb5e3591166ded6bbb413ec77294a718`. The primary rule uses the original MQL5 code default of 20 H1 bars. The article prose says 500 bars. The 500-bar interpretation remains a separate registered trial.

The source audit states that the signal uses the last completed H1 ATR14, compares it with the upper median of 100 completed ATR values at sorted index 50, and uses prior completed-bar high/low channels. The source can submit both pending stop orders. It does not implement OCO. See [source parity audit](mechanicalpremia_yen_squeeze_source_parity_20261014.md).

## Method and skills

The installed versions were `ml4t-engineer 0.1.4`, `ml4t-backtest 0.1.7`, and `ml4t-diagnostic 0.1.6.post2`. The inspected signatures were:

- `compute_features(data, features, *, group_col=None, timestamp_col=None, assume_sorted=False)`.
- `Engine(feed, strategy, config=None, *, contract_specs=None, ...)`.
- `Strategy.on_data(self, timestamp, data, context, broker)`.
- Native order operations: `Broker.submit_order`, `update_order`, and `cancel_order`.

The full local skills were read before implementation. The verification for each selected procedure was:

| Skill | Invariant | Verification |
|---|---|---|
| `ml4t-compute-features` | Use registered ATR and Donchian features. Preserve time order and pair boundaries. | Native feature outputs were computed per pair. Deterministic 20/500 window checks passed. |
| `ml4t-validate-data` | Require unique timestamps, valid OHLC ranges, finite prices, and explicit timezone handling. | Both development snapshots passed uniqueness and OHLC checks. Incomplete H1 bars were excluded. GBPJPY source timezone remains unverified. |
| `ml4t-lookahead-bias` | Use a feature only after its H1 bar has closed. | Minute as-of joins had zero availability violations. Appending a future H1 bar did not change earlier features. |
| `ml4t-polars-patterns` | Sort timestamps. Do not fill missing market intervals. | H1 aggregation retained only hours with 60 unique minute rows. A gap test confirmed that an incomplete hour was dropped, not filled. |
| `ml4t-feature-validation` | Check warmup, independent windows, and future-append stability. | Tests checked ATR warmup, order-statistic warmup, 20 versus 500 channels, and future append stability. |
| `ml4t-run-backtest` | Orders must execute on a later eligible bar. Native fills and cash state must be inspected. | A synthetic native Engine test submitted a stop at one bar and verified its gap fill at the next bar open. No pair performance run was allowed. |
| `ml4t-cost-model` | Charge costs through native engine settings. Do not deduct costs outside fills. | No cost model was run because source spread, fees, and broker terms are unavailable. No custom PnL or cost calculation was added. |
| `ml4t-transaction-costs` | Use instrument-specific spread and slippage evidence before claiming cost survival. | The frozen 2/4/6 pip scenarios remain unrun. The OHLC snapshots contain no bid/ask or cost observations. |
| `ml4t-risk-metrics` | Report marked equity, drawdown, and risk metrics only from valid portfolio accounting. | No strategy metrics were calculated because JPY-to-account-currency treatment is unverified. Native synthetic Engine state was inspected only. |
| `ml4t-backtest-overfitting` | Retain every preregistered attempt. Do not infer DSR or PBO without valid trial returns. | All eight registered trials have terminal ledger records. No strategy return distribution exists, so no DSR, PBO, or Sharpe haircut is claimed. |

The implementation uses no handwritten ATR, Donchian, backtest loop, fill matcher, cash/PnL simulator, or performance metric calculator. The 100-observation threshold uses Polars `rolling_quantile(0.5, interpolation="higher")`, which selects order statistic 50 from 100 values. Native ATR NaN warmup values are converted to null for this rolling operation so the first threshold appears only after 100 finite ATR observations.

## Feature trial

Inputs were limited to the two frozen 2023–2024 Parquet snapshots:

| Pair | Minute rows | Complete H1 rows | Incomplete hours excluded | Finite ATR14 | Finite ATR100 upper median | 20/500 channel rows that differ | Causal violations |
|---|---:|---:|---:|---:|---:|---:|---:|
| USDJPY | 748,068 | 12,323 | 418 | 12,309 | 12,210 | 11,824 | 0 |
| GBPJPY | 744,864 | 11,750 | 723 | 11,736 | 11,637 | 11,251 | 0 |

The input SHA-256 values matched the frozen identities. The data audit found no duplicate timestamps, invalid high/low ordering, close outside the bar range, or non-finite OHLC rows. The H1 aggregation did not forward fill missing hours. Each feature became available at its H1 end time.

A follow-up run also checked exact minute alignment. Both snapshots had zero timestamps that were not aligned to a minute boundary. See [feature clock recheck](mechanicalpremia_yen_squeeze_feature_parity_recheck_20261014.json).

The library reports `atr` as TA-Lib compatible. Deterministic examples confirmed its 14-period warmup and constant-range output. The channel tests confirmed that 20- and 500-bar windows use different historical extrema. This verifies the library feature behavior and clock alignment. It does not prove the snapshots match the broker's H1 bars.

See [feature evidence](mechanicalpremia_yen_squeeze_feature_parity_20261014.json). The initial audit artifact [feature_parity.json](../../run_log/research_sessions/mechanicalpremia-yen-squeeze-mvp-20261014/artifacts/feature_parity.json) counted ATR NaN warmup values as non-null. It is preserved. The corrected artifact excludes non-finite warmup values and is the one linked to `FEATURE-PARITY`.

## Native execution capability checks

The synthetic `ml4t.backtest` checks established these limited capabilities:

- `NEXT_BAR` made the stop order eligible after the signal bar.
- A buy stop at 105 filled at a later bar's open of 110 when the market gapped over the trigger.
- The native fill stored its time, trigger, fill price, and `price_source="open"`.
- `Broker.update_order` changed a pending stop and `Broker.cancel_order` cancelled it.
- The `Order` type has no `expires_at` field. A strategy must cancel by clock through the native API.

These were controlled library capability tests. They do not establish broker parity or two-pair accounting. See [execution gate evidence](mechanicalpremia_yen_squeeze_execution_gates_20261014.json).

## Unresolved execution and data gates

- USDJPY historical source identity and broker mapping are not verified.
- GBPJPY timestamps were naive in the source lineage and were localized to UTC. This assumption is not certified.
- The snapshots contain OHLC, not historical bid/ask. The source checks BuyStop against ask and SellStop against bid. It also trails a long stop from bid and a short stop from ask.
- No broker contract size, tick value, point size, lot step, minimum lot, margin rule, account currency, or JPY conversion data is available. The source's 1% risk size cannot be reconciled.
- CADJPY is missing. The two-pair sample cannot test the registered three-pair hypothesis.
- The source can keep both opposite pending orders live. The native synthetic checks did not certify simultaneous trigger handling against this broker's semantics.
- The native Engine accepts multiple assets, but no verified FX conversion contract establishes shared USD/GBP/JPY cash, equity, or margin accounting.
- The 2/4/6 pip round-trip stress cannot be applied credibly without a native fee/spread mapping. Financing remains unknown.

These gates block `USDJPY-20`, `GBPJPY-20`, `TWO-PAIR-20`, `PROSE-500`, and the full `ACCOUNTING-AUDIT`. No performance metrics are available. No parameter selection occurred.

## Trial ledger

The report command regenerated the session report. It reports `BLOCKED`, `metrics_computed=false`, and `CADJPY:missing_prices`.

| Trial | CLI status | Scientific disposition |
|---|---|---|
| `SOURCE-PARITY` | completed | Source rule audit recorded; broker parity uncertified. |
| `DATA-ELIGIBILITY` | completed | Administrative record exists; eligibility remains inconclusive. |
| `FEATURE-PARITY` | completed | Native feature and causal clock checks passed on the two snapshots. |
| `USDJPY-20` | failed | Inconclusive; blocked before strategy execution. |
| `GBPJPY-20` | failed | Inconclusive; blocked before strategy execution. |
| `TWO-PAIR-20` | failed | Inconclusive; blocked before strategy execution. |
| `PROSE-500` | failed | Inconclusive; feature window distinguished, execution blocked. |
| `ACCOUNTING-AUDIT` | failed | Inconclusive; synthetic native behavior checked, broker accounting unresolved. |

The CLI only accepts `completed` and `failed` terminal statuses. For the five blocked attempts, `failed` records that the declared attempt could not be completed. The linked evidence records their research disposition as `INCONCLUSIVE`. It does not mean that a strategy performance result failed.

## Verification and next evidence needed

Command run:

```bash
.venv/bin/pytest -q tests/test_mechanicalpremia_yen_squeeze_native_20261014.py
```

Result: **9 passed**. Tests cover native ATR and channel examples, 20/500 distinction, upper-median indexing and warmup, complete-hour filtering, exact minute alignment, timezone requirements, causal feature availability, future-append stability, next-bar stop gap fills, stop updates, and pending-order cancellation.

To resume the blocked strategy trials, obtain verified broker symbol specifications and account currency rules, historical bid/ask or a validated execution source, GBPJPY timezone provenance, and development CADJPY data. Preserve the frozen spec and protected holdout. Do not treat this audit as trading approval.
