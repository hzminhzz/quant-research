# ATS-3 Gate 1: Strategy-to-Order Attribution Report

## 1. Strategy Identity & Configuration

- **Strategy ID**: `donchian_btc`
- **Class**: `DonchianBTCStrategy` (`promote/donchian_btc/src/independent_seven_native_features.py` wrapped by `scripts/run_bybit_demo_monitored_session.py`)
- **Strategy Source**: `promote/donchian_btc/strategy.yaml`
- **Strategy SHA-256**: `bc5e0bf4f070a21eba3be0d2dd839bcb895e36a7047f3fd8d468a368bbc4be4e`
- **Instrument**: `BTC/USDT:USDT` (Bybit Linear Perpetual)
- **Bar Cadence**: 1-minute (`1m`)
- **Warm-start Evidence**:
  - `bybit-demo-monitored-session.log` records: `2026-10-15 09:11:27,480 [INFO] bybit_demo_session: Connecting BybitClient to fetch 250 historical candles for warm-start...` and `09:11:30,216 [INFO] Warm-start history loaded: 250 bars`.
  - **Factual Limitation**: The inspected log records local time `09:11` without an explicit UTC offset in the log formatter; exact candle boundary timestamps for the 250 warm-up bars were not printed in the session log.
- **Risk Configuration**:
  - `max_order_shares`: `0.01` BTC
  - `max_order_value`: `1000.0` USDT
  - `max_position_shares`: `0.02` BTC
  - `max_position_value`: `2000.0` USDT
  - `max_total_exposure`: `5000.0` USDT

---

## 2. Reconstructed Decision-to-Fill Sequence

The continuous monitored session ran on 2026-10-15. Strategy features computed with 9 Donchian channels and 60-bar volatility targeting.

### Pre-Session Preflight Order
- **Timestamp**: `2026-10-15T07:11:05.345972+00:00`
- **Intent**: SafeBroker sequence `93` | SQLite Intent `01M4Z6CY4856JA4GYTQE6YECN8`
- **Order Submission**: SafeBroker sequence `94`
- **Provider Order ID**: `a98518a2-3b5b-40b1-bd5c-155026998bae`
- **Side / Type / Qty**: Buy 0.01 BTC Market
- **Fill**: 0.01 BTC @ 80,882.3 USDT (Time: `1792048265463` ms)
- **Fee**: -0.44485240 USDT
- **Position Effect**: Established opening inventory of +0.01 BTC prior to Bar #1.

---

### Decision #1 (Bar #1)
- **Market Bar**: Bar #1 @ `2026-10-15T07:12:00+00:00` | Close: 80852.2, High: 80904.4, Low: 80840.1 (History: 251 bars)
- **Strategy Signal**: `target_exposure` = `-0.4444`, `avg_dir` = `-0.222`, `vol_lev` = `2.00`
- **Intended Exposure**: `target_pct` = `-0.444`, `target_qty` = `-0.0200` BTC, `current` = `+0.0100` BTC, `delta` = `-0.0100` BTC (bounded by `max_order_shares` 0.01)
- **Order Intent**: SafeBroker sequence `108` (`2026-10-15T07:12:05.670432+00:00`) | SQLite Intent `01M4Z6ES1E6CWM4SGY4RKHZ4QH`
- **Risk Admission**: Passed all limits (order value ~808.52 USDT <= 1000.0, position within cap)
- **Route**: SafeBroker -> BybitLiveBroker -> Bybit V5 Linear REST
- **Order Submission**: SafeBroker sequence `109`
- **Provider Order ID**: `5cb2ac55-1af9-4a9b-8c56-3ddead79a708`
- **Fill Details**: Exec ID `2a5f9730-86b2-4d7a-a437-d250c60f1ad9` @ 80,854.5 USDT | Filled Qty: 0.01 BTC (Time: `1792048325795` ms)
- **Commission**: -0.44470000 USDT
- **Realized PnL**: -0.27800000 USDT (closed initial +0.01 BTC long bought at 80882.3)
- **Account Effect**: Net position reduced to `0.00` BTC. Cash adjusted by realized PnL and fee.

---

### Bars #2 to #4 (Hold / No Trade)
- **Bars**: 07:13:00 to 07:15:00 UTC | Close 80913.6 -> 80928.3 -> 80926.7
- **Signals**: `target_exposure` = `0.0000`, `current` = `0.0000`, `delta` = `0.0000`
- **Action**: Zero delta; no order intents staged or submitted.

---

### Decision #2 (Bar #5)
- **Market Bar**: Bar #5 @ `2026-10-15T07:16:00+00:00` | Close: 80977.1, High: 80986.9, Low: 80920.9 (History: 255 bars)
- **Strategy Signal**: `target_exposure` = `+0.4444`, `avg_dir` = `+0.222`, `vol_lev` = `2.00`
- **Intended Exposure**: `target_pct` = `+0.444`, `target_qty` = `+0.0200` BTC, `current` = `0.0000` BTC, `delta` = `+0.0100` BTC (bounded by `max_order_shares` 0.01)
- **Order Intent**: SafeBroker sequence `110` (`2026-10-15T07:16:05.197055+00:00`) | SQLite Intent `01M4Z6P2YHMJ6STXK0BFH7MFWX`
- **Risk Admission**: Passed all limits (order value ~809.77 USDT <= 1000.0)
- **Route**: SafeBroker -> BybitLiveBroker -> Bybit V5 Linear REST
- **Order Submission**: SafeBroker sequence `111`
- **Provider Order ID**: `5af29df4-16d8-47a6-a05e-adca2da666c9`
- **Fill Details**: Exec ID `e90098f9-4679-4d87-b956-6218ad5aa7f8` @ 80,978.8 USDT | Filled Qty: 0.01 BTC (Time: `1792048565310` ms)
- **Commission**: -0.44538340 USDT
- **Realized PnL**: 0.0 USDT (new opening leg)
- **Account Effect**: Net position increased to `+0.01` BTC.

---

### Decision #3 (Bar #6)
- **Market Bar**: Bar #6 @ `2026-10-15T07:17:00+00:00` | Close: 80961.4, High: 81005.0, Low: 80961.4 (History: 256 bars)
- **Strategy Signal**: `target_exposure` = `+0.4444`, `avg_dir` = `+0.222`, `vol_lev` = `2.00`
- **Intended Exposure**: `target_pct` = `+0.444`, `target_qty` = `+0.0200` BTC, `current` = `+0.0100` BTC, `delta` = `+0.0100` BTC
- **Order Intent**: SafeBroker sequence `112` (`2026-10-15T07:17:05.706602+00:00`) | SQLite Intent `01M4Z6QY1M3YP180CWTGWD411A`
- **Risk Admission**: Passed all limits (position becomes +0.02 BTC == `max_position_shares` 0.02)
- **Route**: SafeBroker -> BybitLiveBroker -> Bybit V5 Linear REST
- **Order Submission**: SafeBroker sequence `113`
- **Provider Order ID**: `a7619836-8d58-4026-89d6-906bfdc3aff5`
- **Fill Details**: Exec ID `348b61ad-c335-430c-ab24-2c0bc133282b` @ 80,998.0 USDT | Filled Qty: 0.01 BTC (Time: `1792048625827` ms)
- **Commission**: -0.44548900 USDT
- **Realized PnL**: 0.0 USDT (second opening leg)
- **Account Effect**: Net position increased to `+0.02` BTC. Average entry = (80978.8 + 80998.0) / 2 = `80988.4` USDT.

---

### Bars #7 to #15 (Capped at Position Limit)
- **Bars**: 07:18:00 to 07:26:00 UTC | Close 80994.0 -> 81112.6
- **Signals**: `target_exposure` expanded from `+0.4444` to `+1.3333`.
- **Constraint**: Target position capped by `min(0.02, max(-0.02, equity * pct / price))` at `+0.0200` BTC. Current position was already `+0.0200` BTC; `delta` = `0.0000`.
- **Action**: Zero delta; no further orders submitted. Position preserved at +0.02 BTC through session completion.

---

## 3. Discrepancies and Missing Information

1. **Unresolved Historical Incident (SafeBroker Sequence 7)**:
   - At `2026-10-15T06:16:46.177989+00:00`, an `order_submission_intent` was journaled during preflight setup. No corresponding record exists in the SQLite intent journal or on the provider. It is treated as an isolated aborted preflight attempt and preserved as genuinely unknown (`INTENT_TERMINAL_REASON_NOT_RECORDED`).

2. **Missing Ex-Ante Research Baseline**:
   - **Limitation**: While the live Donchian strategy logic matches `promote/donchian_btc`, no frozen, preregistered simulation baseline artifact for the *identical live window* was generated before observing live market outcomes.
   - **Integrity Statement**: We do NOT retrospectively fabricate a matching baseline. This limitation is formally acknowledged.

3. **Prospective Verification Procedure (PVP)**:
   For future operational reviews:
   - Step 1: Pre-register the simulation run using `scripts/run_bybit_demo_monitored_session.py` with identical seed/warm-up data in `--shadow` or ex-ante paper mode, writing a signed baseline manifest to `run_log/baselines/`.
   - Step 2: Concurrently execute the monitored session.
   - Step 3: Compare bar-by-bar signals, decision triggers, fill slippage, and fee variances against the preregistered baseline manifest.

---

## 4. Gate 1 Evaluation

- **Status**: **PARTIALLY ATTRIBUTED (Documented Limitation)**
- **Audit Basis**: Decisions #1, #2, #3, pre-session preflight, fills, and account balances are completely attributed. Ex-ante frozen baseline was not linked, and seq 7 remains an isolated unverified historical incident.
