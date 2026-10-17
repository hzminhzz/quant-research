# Cross-sectional funding carry + exhaustion MVP

**Decision: REJECT.**

## Diagnostic gate
- Development: 2020-06-01 to 2023-12-31. 2024+ not accessed.
- Matched decision-panel rows: 25,395.
- Decision dates: 654.
- Eligible 48h basket cycles: 488.
- Candidate mean rank IC: 0.015643.
- Candidate HAC t-stat: 1.463.
- Candidate IC IR: 0.05718769646583172.
- Baseline mean rank IC: 0.03152322552965052.
- Baseline HAC t-stat: 4.082515470044467.

## Decision reasons
- point-in-time matched universe falls below 40
- candidate HAC t-stat 1.463 < 2.0

## Integrity
- Native ml4t.engineer ROCP(24) and ATR(24) are used per symbol.
- Rank IC and HAC statistics use ml4t.diagnostic.
- The point-in-time universe uses only trailing 720 completed 1h bars.
- 00:00 funding events are accepted only if observed by 00:01; fills are labeled from 01:00 next-hour open.
- This runner does not load any 2024+ price or funding partition.
- No custom backtest simulator is used.
