# Promoted strategy routing

The directories below are all active in the research-promotion shortlist. Promotion means the user selected the historical strategy for ongoing research; it is NOT automatically permission for live trading. Keep promotion status separate from research limitations and broker-execution approval.

| Candidate | Promotion | Live approval |
| --- | --- | --- |
| one_bar_nq_30m (B0) | PROMOTED_FOR_FURTHER_RESEARCH | NOT_APPROVED |
| donchian_btc | PROMOTED_FOR_FURTHER_RESEARCH | NOT_APPROVED |
| rsi_30_50_spy | PROMOTED_FOR_FURTHER_RESEARCH | NOT_APPROVED |
| mechanicalpremia_us500_us100 | PROMOTED_FOR_FURTHER_RESEARCH | NOT_APPROVED |

For One-bar NQ, B0 (50-point protective stop, illustrative one-NQ equivalent) is the **retained, user-approved research-promotion version**. Do NOT replace or retire it because the tested stop alternatives were not improvements. The independent percentage-stop and ATR/MNQ B2 experiments remain unadopted in run_log/ and docs/audit/. Read `promote/one_bar_nq_30m/AGENTS.md` to avoid confusing these variants.

Before changing a promoted strategy, read its README.md, STATUS.md, strategy.yaml, latest root audit and applicable AGENTS.md. Preserve the baseline, past trials, source identities and all failures. Do not alter user-approved promotion status without a new explicit user decision.
