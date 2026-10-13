# M6 Dukascopy CFD managed research migration — October 13, 2026

**Disposition: Historical mechanical parity verified; no new alpha approval.**

## Exact data identity

- Source: Dukascopy USATECH.IDX/USD CFD index/quote price proxy, stored as `DUK_USATECH`.
- SHA-256: `4ce2efcf496fb77d936d12d866ef5ed5d1e1869879a6b30434a1d0232bb75425`.
- Source rows: 243,444. Vendor `volume` is broker tick/quote proxy, **not CME traded volume**.
- Development Jan–June 2026: 103 eligible, complete XNYS cash sessions, 41,715 one-minute bars; 20 calendar/session exclusions. Strict 08:30–15:14 CT real bar opens; no 15:55 candle or imaginary liquidation.
- Preserved original frozen source session and run logs. New managed session/config are **separate declarations**; existing research evidence is not reclassified as unseen.
- July/Aug 2026 have been historically reviewed; no September source coverage and no permission to open the prospective November holdout. This is not live CFD, CME contract, nor futures execution qualification.

## Mechanical parity (direct pinned VPS test)

`tests/test_dukascopy_real_parity.py` copies pinned source into a temporary isolated test root, freezes a separate synthetic parity session in that temporary root, and uses the real M2 -> M3 FeatureProof -> M4 RunPermit -> M6 native Engine path. Historical source and evidence are read only.

- Native `ml4t-engineer` ADX14, approved 08:30 CT quote-volume VWAP, last-5 high, last-20 low: zero maximal absolute difference from historical 243,444-row native computation.
- Independent ADX oracle startup Wilder seed was corrected. The prior reference had 46 transient early-warmup mismatches (max 1.336); it had failed closed before repair.
- Full cash-session selection exactly matches old source workflow: 103 accepted, 20 exclusions.
- Nine complete B1/B2/B3 native `ml4t-backtest` replays, gross / base / stress, independently reconciled signal timestamps, price/ADX/VWAP/TP/SL signal inputs, native fill timestamps/order types/sides/quantities/prices/commissions/slippage and native trade entry/exit/time/PnL against **immutable previously observed artifacts**.
- Exact installed backtest version required: `0.1.7`. Native `LegalLimitFillExecutor` suppresses adverse resting sell-LIMIT slippage only; engine still owns execution, cash, positions and siblings.
- Explicit stop-before-limit native order submission, real 15:14 CT forced market liquidation; native simulated OCO is **not live atomic broker OCO**.

## Open limitations and correct interpretation

- `HISTORICAL_SIMULATION_ONLY`; `NOT_APPROVED` for live/production. The illustrative `$20/point` multiplier, `$2.50/side`, and 0.25/0.50 point cost-stress are **not qualified Dukascopy CFD broker contract and fee terms**.
- No future/unseen holdout accesses, no edge claims or parameter tuning. Gross/base/stress legacy parity does not establish positive expected returns, capacity or genuine fill queue position.
- Original 15:55 CME-clock variant remains distinct; the Dukascopy-specific exit is 15:14 CT as originally registered.
- `src/research_control/run_permit.py` now checks the presence of a real timestamped **exit bar open**, not merely a calculated feature availability clock. This prevents phantom time eligibility.
- External raw-data fixture remains excluded from mandatory fresh-clone CI, but can be reproduced on the canonical VPS with `pytest -m data tests/test_dukascopy_real_parity.py`.

## Research authority

Original source session: `config/research_sessions/vwap_pullback_adx_dukascopy_20261012_v1.yaml`; frozen `run_log/research_sessions/vwap_pullback_adx_dukascopy_20261012_v1/frozen_spec.json`. Original audit and source manifests under `run_log/vwap_pullback_adx_dukascopy_20261012_v1/`. New managed declarations: `config/research_contract_dukascopy_managed_v2.yaml` and `config/research_sessions/vwap_pullback_adx_dukascopy_managed_v2.yaml`.

**Verdict:** Engineering and historical numerical parity, not economic or execution approval.
