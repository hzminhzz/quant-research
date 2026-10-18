# AdaptiveTrend H6 with monthly filtered 70/30 crypto basket

**SOURCE_CAPTURE_ONLY / descriptive author transcription; no local economic tests.**

**Original:** Duc Bui and Thanh Nguyen, [AdaptiveTrend (2026)](https://arxiv.org/html/2602.11708), Sections 3–6. The source gives 6h return-momentum threshold entries, ATR-relative trailing stop, monthly ranking of top-15 market-cap assets for longs and bottom-K_S for shorts, preceding-month grid and Sharpe acceptance of 1.3/1.7, and 70/30 long/short equal weights within each leg. Long stop is monotonically ratcheted; full mirror short-stop implementation is not in the quoted algorithm. The short universe size K_S is unspecified in examined text; do not substitute a value.

**Source-reported unverified tests:** 150+ Binance perpetual contracts, 2021-2024 data, reported development 2021 and OOS 2022-2024; claimed net Sharpe 2.41 and MDD -12.7%. These results are author claims, NOT independently checked; paper Figure 1 says 2022–October 2025 despite the formal experiment ending December 2024, a source-internal date inconsistency. The paper uses 4 bps taker and models slippage and funding *costs*, not funding-based signals.

**Scientific issues:** Same-bar entry at P_t in pseudocode; PIT capitalizations and all historically tradable/delisted futures; selection from prior-month Sharpe optimization; purported margin/capacity of short small-caps; original 8h financing timestamp semantics; full fill clock. Sharpe may be sensitive to trading frictions; no diagnosis performed here. Not a source-backed 1h adaptation—native original decisions are 6h.

**Novelty:** the interaction of per-asset lookback/stop tuning, monthly risk-adjusted eligibility and asymmetric risk allocation, not a new RSI or feature-name sweep. Future ATS multi-contract support is UNKNOWN/BLOCKED_PROTOCOL until independently qualified.

**Prop portability UNKNOWN:** allowed crypto pairs, two-sided legs, leverage, daily loss caps, margin, weekends, financing and order settlement. No orders, empirical trials, ATS runner access or protected reads.
