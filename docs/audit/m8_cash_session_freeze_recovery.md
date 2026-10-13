# M8 cash-session freeze recovery

The first cash-session freeze used session ID
`m8_n8_dukascopy_us_cash_30m_v1` and frozen hash
`da79321ce4fde66f0263963662bb8baf35ff0f865c4c737732b26d082825e827`.
Its session file audit passed. The permit preflight returned `BLOCKED` with
`Multiplier evidence is not linked from the frozen session.` No attempt was
created. No signal count, native execution, or performance result was produced.

The session is immutable. The corrected freeze uses a new session ID and adds
the existing normalized multiplier evidence to its evidence list. This is a
preflight correction. It does not change the strategy, source data, calendar,
cost assumptions, trial count, or selection rule.
