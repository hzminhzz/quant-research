# M8 cash-session v4 metric failure

Attempt `471ee061-0ae4-4d96-a8c2-60dece7d4401` started the native engine and
created the first scenario result. The independent audit path then compared the
installed `PortfolioAnalysis` maximum drawdown with an oracle that included an
initial cash point. The installed library computes cumulative returns from the
first sampled return and does not add that initial point. The mismatch stopped
the run before scenario outputs or metrics were written.

The trial record is terminal `failed`. The saved report does not contain
performance metrics, fills, or equity. No holdout data or live orders were
used. The source inspection showed the installed `max_drawdown` algorithm. A
synthetic return test now checks the independent oracle against that API. The
cash-session strategy and cost plan did not change. A new freeze is required
because the verification code changed.
