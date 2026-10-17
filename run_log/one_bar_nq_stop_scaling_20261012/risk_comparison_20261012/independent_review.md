# Independent B0 vs B2 risk analysis audit (2026-10-12)

Status: VERIFIED historical ledger arithmetic and reproducible bootstrap inputs; INCONCLUSIVE live-futures applicability.

- Completed source ledger comparison and reconciled 5,462 B0 trades (+$166,107.92) and 5,459 B2 trades (-$142,674.93) across the full observed sample. Both are stored native-Engine historical results, not new strategy trials.
- Corrected a significant analysis-only sign bug: the original hypothetical constant-exposure calculation divided by *signed* `quantity`, flipping short P&L signs. The corrected calculation scales trade P&L, planned risk, per-contract fees, and slippage by positive `10 / abs(quantity)` and verifies per-trade win signs and R multiples stay unchanged. It is an algebraic exercise, **not** a new native backtest. Corrected the B2 quantity medians to absolute MNQ counts.
- Reconciled same UTC entry-date period membership for both strategies. Preserved the initial buggy analysis and report separately under `superseded_signed_qty_bug/` for complete trial/report provenance.
- All four focused tests pass, including a signed-short P&L regression test; B2 and B0 original native ledgers and original promoted package remain unchanged. The primary paired block-bootstrap draws, Sharpe, Calmar, and historical win rates were not modified by the optional counterfactual bug fix.
- Limits: source is Dukascopy BID-only index CFD proxy and not CME NQ/MNQ; B2 annual shards have known GTC boundary leakage, a duplicate fill, 1-minute event ambiguities and delayed exits; realized trade-entry-date P&L is not a mark-to-market portfolio curve. All data are already observed through July 14, 2026. Bootstrap does not cover unseen regimes. No live readiness claim.
- User conclusion: B2's lower 2026 dollar loss is substantially due to lower point exposure with a wider stop and ~90% nominal risk deployment. But postlaunch B2 has worse win rate, profit factor, Sharpe and Calmar than B0; thus it is not an improved risk-adjusted strategy overall.

Main report: `docs/audit/one_bar_nq_b0_b2_risk_comparison_20261012.md`. Reproduce: `uv run --no-sync python run_log/one_bar_nq_stop_scaling_20261012/risk_comparison_20261012/analyze.py` followed by `uv run --no-sync python -m pytest -q tests/test_one_bar_nq_b0_b2_risk_20261012.py`.
