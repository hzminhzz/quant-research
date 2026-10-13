# M8 cash-session v5 reporting failure

Session `m8_n8_dukascopy_us_cash_30m_v5` passed frozen-spec, permit, and feature-proof preflight. Native `ml4t-backtest` completed the declared 1x, 2x, and 3x scenarios. The worker then failed before persisting fills or equity because scenario audit evidence omitted its `status` key, while the report assembler required it. The terminal attempt and failed trial remain recorded. No outcome metrics were published or used for a decision; no holdout or live order was accessed.

The v6 code change serializes audit status and reason code. It also adds descriptive annual net return and PnL from the scheduled daily equity series. This is an implementation correction under the same single preregistered strategy and cost-stress trial; it is not a parameter search. v1 through v5 failures remain counted in the preregistration history. v5's in-memory native execution is a process-engineering attempt and is not treated as a second strategy trial.
