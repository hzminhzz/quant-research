# M8 cash-session v3 metric failure

V3 froze the cash-session rule and the corrected runner command. Attempt
`67e2d592-4d19-44f9-973b-600c60a2114a` started the native engine. The first
scenario returned an in-memory native result and passed through the independent
fill/cash audit. Daily metric construction then failed because
`cash_session_dates` asked `exchange_calendars` for January 1, 2020, before its
first XNAS/XNYS session on January 2.

The exception stopped the run before scenario outputs or metrics were written.
The attempt ledger is terminal `FAILED`, and the v3 trial record links the
runner's failure report. The separate
`run_log/m8/n8/cash_session/results/67e2d592-4d19-44f9-973b-600c60a2114a/metric_calendar_failure.json`
records that an in-memory native result existed. Do not recover performance
claims from it. This is a calendar bounds bug, not a strategy decision.

The correction clips daily metric dates to the installed calendar's first and
last sessions and respects the half-open evaluation end. A regression test
covers the full 2020-2024 boundary. The corrected run requires a new freeze.
