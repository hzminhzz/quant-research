# Plain Cross-Sectional Binance Funding — 2024–2025 Decay Validation

**Session:** `crypto_xs_plain_funding_decay_validation_20261015_v1`  
**Classification:** VALIDATION / NOT APPROVED  
**Terminal decision:** **REJECT**  
**Frozen decay taxonomy:** **STRUCTURAL_DECAY**  
**Mechanism diagnosis:** **FUNDING CARRY ALIVE / PRICE ALPHA DECAYED / SINGLE-NAME SHORT-SQUEEZE FATAL**

## Executive conclusion

The original hypothesis that a more mature crypto market no longer offers meaningful cross-sectional perpetual-funding opportunities is **not supported**.

Funding opportunities did not compress in 2024–2025. They became larger by several direct measures:

- top-5 minus bottom-5 trailing-24h funding spread: **1.60x** the frozen 2022–2023 mature reference;
- cross-sectional funding standard deviation: **1.73x** the reference;
- trailing-funding → next-48h funding persistence Rank IC: **1.01x** the reference;
- unit-notional realized 48h carry: **1.42x** the reference;
- corrected native realized funding before insolvency: approximately **36.75% annualized on average gross**, about **80.2%** of the 2022–2023 reference yield.

The part that decayed is the **price-predictive component**:

- 2024 48h price Rank IC: **0.02231**;
- 2025 48h price Rank IC: **0.00332**;
- combined 2024–2025 IC: **0.01286**, HAC t-stat **1.20**, p **0.231**;
- latest 12-month rolling IC: approximately **0.00309**.

The unchanged equal-notional portfolio also has a fatal concentration/tail-risk defect. A MYXUSDT short squeeze drives account equity below zero on **2025-09-08 19:00 UTC**. The same insolvency timestamp appears in the funding-aware base arm and in the no-funding arm, so funding accounting is not the cause of bankruptcy.

Therefore:

> **The funding edge did not disappear. The old price-reversion edge weakened sharply, and the unchanged portfolio construction is not survivable against modern single-name crypto squeeze risk.**

## Research-control status

The 2024–2025 validation contract was frozen before opening validation forward returns or portfolio PnL.

Frozen specification SHA256:

`f16dc1cc2415ebeb196a3332ccb7cfba276755376cd46be26fd6ae234047f203`

Frozen validation runner SHA256:

`798e1b549f8be49c74379ddf4b5c5167f1dd7344e5756e189714d4dfa312e51a`

The frozen runner file remained unchanged after validation outcomes were opened.

The protected **2026 final-test period remains sealed**. No 2026 price, funding, mark, label, signal or portfolio observation was read.

## Frozen strategy

The strategy was not optimized for 2024–2025.

- Signal: negative trailing-24h sum of actual Binance USD-M funding events.
- Universe: causal 720-hour price history; at least one funding event in trailing 24h; top 40 by trailing-720h close × base-volume.
- Rebalance: every 48 hours on the original 2020-06-01 anchor.
- Long: five lowest-funding names, +10% target each.
- Short: five highest-funding names, -10% target each.
- Target gross: 1.0.
- Target dollar net: 0.0.
- Fill: native ML4T NEXT_BAR at next 01:00 open.
- Base friction: 5 bps commission + 4 bps slippage per side.
- Stress friction: 2× base.
- No Kelly scaling, stop-loss, volatility overlay or post-result risk control was introduced.

Pre-outcome execution qualification verified **10,514 / 10,514** required decision/fill/close/final-flatten symbol-time keys.

## Data and official funding marks

Bounded source data:

| Period | Price rows | Price symbols | Funding rows | Funding symbols |
|---|---:|---:|---:|---:|
| Dec 2023 warmup | 134,711 | 184 | 19,910 | 181 |
| 2024 | 1,934,068 | 280 | 321,901 | 276 |
| 2025 | 3,286,858 | 480 | 702,990 | 479 |

Funding cadence has materially changed: 2025 contains **557,018 non-8h funding events**, so the actual-event trailing-24h implementation remains necessary.

The frozen validation baskets require:

- **364** decision cycles;
- **40** names at every cycle;
- **219** distinct selected symbols;
- **42,943** held-position funding events;
- **941** symbol-month mark-price partitions.

All **42,943 / 42,943** held funding events resolve to an official Binance event-minute mark OPEN. No prior-minute fallback is required.

The Binance public monthly archive was available for 940/941 required symbol-months. The valid Unicode perpetual `币安人生USDT` November 2025 archive path returned 404, while Binance exchangeInfo identified the contract as a trading perpetual and official `/fapi/v1/markPriceKlines` returned the full historical month. That month was acquired from official paginated REST:

- 43,200 one-minute mark rows;
- 2025-11-01 00:00 through 2025-11-30 23:59 UTC;
- each REST page response hash preserved;
- no universe modification.

Compact validation mark evidence:

- mark panel SHA256: `94c67b44541723a4aa064aea9456ae0ae2953669b5c7a0aafa3b85a76e562865`
- event-mark SHA256: `7b1846ab45478c1d9ea506e216a63e8787b80dd572a35ba89d6671c8fc22aea7`
- source-manifest SHA256: `97495c505c21964b5ec3d13bda4918eb2e0429858c92368d76f36ba768bef14b`

The frozen research-session input audit returned **PASS**.

## Price-predictive decay

Frozen mature reference (2022–2023):

- mean Rank IC: **0.02399**.

Untouched 2024–2025 validation:

| Period | Mean 48h Rank IC | HAC t-stat | Positive IC share |
|---|---:|---:|---:|
| 2024 | **0.02231** | 1.676 | 52.46% |
| 2025 | **0.00332** | 0.197 | 51.38% |
| Combined | **0.01286** | **1.200** | **51.92%** |

Combined IC retains only **53.6%** of the 2022–2023 mature reference.

The important regime break is 2025. The factor's cross-sectional price prediction is essentially zero:

- 2025 IC: **0.0033**;
- latest 12-month rolling IC: **0.0031**.

Thus there is strong evidence that the historical **price-reversion component has decayed**.

## Funding opportunity did not decay

Frozen 2022–2023 mature reference:

- mean top5-bottom5 24h funding spread: **0.002730**;
- mean cross-sectional funding std: **0.001314**;
- mean funding IQR: **0.000321**.

2024–2025:

- mean top5-bottom5 spread: **0.004379** → **1.60x reference**;
- cross-sectional std: **0.002273** → **1.73x reference**;
- IQR: **0.000256** → **0.80x reference**.

Annual funding spread:

| Year | Mean top5-bottom5 trailing-24h funding |
|---|---:|
| 2024 | 0.001417 |
| 2025 | **0.007374** |

The 2025 opportunity set is more extreme, not more compressed.

## Direct funding-persistence forensic

To avoid portfolio-equity feedback, funding persistence was also measured purely in rate space using the exact frozen baskets.

### 2022–2023 reference

- trailing funding → forward-48h funding Rank IC: **0.8055**;
- mean ex-ante unit-notional carry: **0.001365 / 24h**;
- mean realized unit-notional carry: **0.002117 / 48h**;
- positive realized-carry cycles: **99.18%**.

### 2024–2025 validation

- funding persistence Rank IC: **0.8111**;
- mean ex-ante carry: **0.002189 / 24h**;
- mean realized carry: **0.003015 / 48h**;
- positive realized-carry cycles: **99.18%**.

Ratios to 2022–2023:

- funding persistence: **1.007x**;
- ex-ante carry: **1.604x**;
- realized carry: **1.424x**.

This directly falsifies a simple "funding carry disappeared as crypto matured" explanation.

## Price-only portfolio failure

The native no-funding validation arm is valid independently of the funding-helper bug described below.

Result:

- total return: **-95.05%**;
- daily Sharpe: **-0.856**;
- first negative equity: **2025-09-08 19:00 UTC**;
- 2024 return: **-55.58%**;
- 2025 return: **-88.85%**.

The no-funding account itself crosses below zero at exactly the same timestamp as the corrected funding-aware account.

This confirms that the fatal event is fundamentally a **price/tail-risk failure**, not an error in funding-transfer accounting.

## Corrected funding-aware native path

### Base costs

The corrected funding-aware portfolio:

- first equity <= 0: **2025-09-08 19:00 UTC**;
- equity at first insolvency: approximately **-$1,986**;
- minimum simulated equity: **-$57,995**;
- end-of-data equity: **-$13,960**;
- final open positions: 10;
- funding cashflow through first insolvency: **+$32,675**.

Because native target-weight rebalancing refuses new orders when account value is nonpositive, the account cannot execute the later rebalance/flatten while it remains insolvent. This inability to flatten is therefore an **economic consequence of bankruptcy**, not missing market data.

Before first insolvency:

- average gross exposure: approximately **$52,656**;
- annualized realized funding yield on average gross: **36.75%**;
- frozen 2022–2023 reference: **45.80%**;
- retained funding-yield ratio: **80.2%**.

Again, funding carry remains economically substantial up to the point the price path destroys the account.

### 2× costs

The corrected 2×-cost portfolio independently becomes insolvent at the same timestamp:

- first negative equity: **2025-09-08 19:00 UTC**;
- minimum equity: **-$43,324**;
- end-of-data equity: **-$10,443**.

Thus failure is not sensitive to the base execution-cost assumption.

## MYXUSDT tail event

The fatal path is highly concentrated in MYXUSDT.

MYX was repeatedly selected by the unchanged cross-sectional funding signal during July–October 2025.

Examples of trailing-24h funding:

- 2025-09-05: +0.006396 → target SHORT;
- 2025-09-07: +0.009684 → target SHORT;
- 2025-09-09: -0.031146 → target would flip LONG;
- 2025-09-11: -0.118648;
- 2025-09-13: -0.130857.

But the account is already insolvent on **September 8**, one day before the target flip.

A large MYX short entered around **$1.08** persists into a violent squeeze:

- historical MYX high in the validation data: **$18.65**;
- MYX mark around first insolvency: approximately **$11.03**;
- residual short quantity: approximately **-3,238.9**;
- MYX notional at the insolvency funding event: approximately **$35.7k**.

This single short had expanded dramatically relative to the intended +/−10% target risk.

### Side mismatch is consequence, not cause

Corrected base funding ledger:

- total funding events: 35,196;
- actual-side match with intended basket: **98.60%**;
- first nonpositive equity: **2025-09-08 19:00**;
- first intended/actual side mismatch: **2025-09-09 02:00**.

Therefore the account becomes insolvent **before** any side mismatch occurs.

After insolvency, the native broker cannot rebalance the now-negative account when the signal switches MYX from short to long. That creates stale-short funding losses:

- funding before insolvency: **+$32,675**;
- funding after insolvency: **-$43,436**;
- MYX funding after insolvency alone: **-$44,861**;
- total MYX funding: **-$42,672**.

These post-insolvency funding losses must not be interpreted as evidence that the funding factor became intrinsically negative. They are downstream consequences of the price-driven bankruptcy and frozen stale position.

## Technical validation-attempt audit

The first validation execution imported `funding_events_by_hour()` from the old 2020–2023 MVP module. That helper hard-coded the development date window and therefore applied zero funding events to 2024–2025.

This was discovered before accepting portfolio results.

The invalid attempt remains preserved at:

`run_log/research_sessions/crypto_xs_plain_funding_decay_validation_20261015_v1/validation/`

The following outputs from it remain scientifically valid because they do not depend on funding-event cash mutation:

- IC diagnostics;
- funding-opportunity diagnostics;
- no-funding native arm.

Funding-aware PnL from that attempt is invalid.

A separate execution-fix amendment records the defect and correction:

`run_log/research_sessions/crypto_xs_plain_funding_decay_validation_20261015_v1/execution_fix1_amendment.json`

The frozen runner itself was not modified. The corrected diagnostic only replaced the stale 2020–2023 funding-event extraction window with the already-frozen 2024–2025 validation window.

## Frozen terminal classification

The frozen validation contract required the unchanged portfolio to retain positive economics after base and 2× costs.

It does not.

Both corrected funding-aware arms become insolvent, and the no-funding arm crosses negative equity at the same event.

Therefore the formal frozen result is:

**REJECT — STRUCTURAL_DECAY**

This label refers to **survivability of the unchanged strategy**, not to disappearance of perpetual funding carry.

The more precise mechanism diagnosis is:

> **FUNDING_CARRY_ALIVE / PRICE_ALPHA_DECAYED / SINGLE-NAME_SHORT-SQUEEZE_FATAL**

## Independent verification

A separate verifier recomputed:

- combined and annual Rank IC;
- funding-spread ratio;
- base, double-cost and no-funding insolvency timestamps;
- funding before/after insolvency;
- pre-insolvency normalized funding yield;
- rate-space funding persistence and carry ratios;
- ordering of insolvency before side mismatch;
- protected-period timestamp bounds.

Independent verification result:

- decision: **REJECT**;
- decay classification: **STRUCTURAL_DECAY**;
- 2024 IC: **0.02231**;
- 2025 IC: **0.00332**;
- funding-spread ratio: **1.604x**;
- unit-notional realized-carry ratio: **1.424x**;
- funding-persistence ratio: **1.007x**;
- pre-insolvency funding yield: **36.75% annualized**;
- all verification checks: **PASS**.

Evidence:

- `run_log/research_sessions/crypto_xs_plain_funding_decay_validation_20261015_v1/validation_final/terminal_decision.json`
- `run_log/research_sessions/crypto_xs_plain_funding_decay_validation_20261015_v1/validation_final/independent_verification.json`
- `run_log/research_sessions/crypto_xs_plain_funding_decay_validation_20261015_v1/decay_forensics/funding_persistence_summary.json`
- `run_log/research_sessions/crypto_xs_plain_funding_decay_validation_20261015_v1/decay_forensics/native_funding_path_audit.json`

## What this means for subsequent research

Do **not** conclude that perpetual funding alpha disappeared.

The evidence instead supports three statements:

1. **Funding carry survives and remains large.**
2. **The price-reversion component weakened severely, especially in 2025.**
3. **Equal-notional uncapped single-name short exposure is not survivable.**

The next research problem is therefore **portfolio risk construction**, not signal discovery and not a relaxed performance threshold.

Any next trial should be a new preregistered session. 2024–2025 is now observed research data and cannot be reused as untouched validation. The final 2026 period remains sealed until the new risk/sizing contract is fully frozen.
