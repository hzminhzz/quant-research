# ATS-5 — deterministic account-rule replay (2026-10-16)

## Qualification boundary

**Engineering fixtures passed; no real FTMO account is qualified, approved or routable.** This package is a pure policy evaluator, not a broker/account service, FTMO API connector, order router, cash transfer application or account purchase tool. The existing legacy `src/ftmo_simulator.py` is intentionally unchanged; its fee, phase and probability assumptions are not treated as an authority.

Selected scope: **FTMO CFD 2-Step public objectives, as inspected 2026-10-16**. The normalized source file is `ats5_ftmo_public_20261016.json`. It is an *extracted review candidate*, not a signed capture or an account binding. Public pages may have changed before retrieval, and the exact publication and effective dates are not known. Account-created dates do **not** establish rule-version applicability.

Official sources:
- https://ftmo.com/en/trading-objectives/ — 2-Step 10% challenge / 5% verification profit targets, >=4 distinct Prague-calendar days with an opened position, static maximum overall equity-loss 10% of original simulated capital, daily equity floor at local midnight balance minus 5% of initial simulated capital; continuous intraday compliance.
- https://ftmo.com/en/2-step-challenge/ — phase descriptions, up-to-90% rewards (not an assured account-specific split), refundable challenge fee (no price assumed).
- https://ftmo.com/en/faq/i-have-successfully-passed-what-to-do-now/ — external phase reviews and identity/account agreement required after evaluation.
- https://ftmo.com/en/blog/watch-out-for-open-losses/ — intraday floating equity violation remains a violation despite later recovery.

`Europe/Prague` is the IANA approximation to FTMO's 00:00 CE(S)T / Prague-local calendar; tzdata version affects UTC reset conversion. An account agreement should confirm the required calendar. The rulebook stores **unknown**, not speculative, funded reward fraction, payout waiting period, pricing, refund eligibility, news restrictions, automation, account-specific grandfathering, amendment start, restrictions, tax, and transfer behavior. `mark_max_age_seconds=0` intentionally permits only same-instant marks for observed equity at open positions. Every source still requires external assessment of full mark coverage.

## Interfaces

`src.account_rules.rule_from_dict` parses a captured rulebook, preserving explicit null values rather than inventing limits. `replay(account, versions, events)` returns immutable `AccountDecision` snapshots and a portable `ReplayCursor`. `replay_chunk(..., cursor=...)` deterministically resumes an identical bound history. `semantic_diff(old, new, accounts)` describes changed numeric semantics and explicitly assigned account cohorts affected after the amendment. Public source metadata alone does not invalidate economic outputs.

Events use UTC-offset timestamps and a sequence within same timestamps, plus stable unique event IDs. **Callers must order events; the evaluator never silently sorts**. Duplicates with byte-identical normalized content are ignored; conflicts and out-of-order entries are errors. The replay synthesizes local-midnight resets and effective term assignments between events. The input `coverage` is an independent declaration by a trusted producer, not something the replay can verify from sparse event observations. Unknown or missing mark continuity produces `INCONCLUSIVE`. A threshold breach is latched irreversibly regardless of eventual recovery. Historical snapshots retain original term references.

The scope of `eligible_for_shadow` is a fail-closed *policy evidence flag*, **not** a routing grant or capital authorization. Public rulebooks always deny it. Synthetic account agreement fixtures should never be treated as actual account permissions.

Cash classification: balance/equity are simulated account measures; `owner_fee_paid` is cash paid by the account owner; `owner_fee_refund_received` and `reward_received` are external cash actually confirmed received. Gross pending/deducted rewards are hypothetical until receipt. `owner_net_cash` equals actually received less actually paid. Losses theoretically absorbed by a program are excluded.

Supported synthetic cases: static floor, daily reset with Prague DST, trailing floor with running high-water, equity floating PnL, mark-age failure, multi-phase evaluation with externally confirmed transition, payouts with approved/debited/received stages, withdrawals, account fees, manual term amendment, grandfathering, replay across chunks, duplicate conflict and semantic diff. **Trailing-model rules, account deposits, payouts and withdrawal floor interactions are synthetic engineering protocols, not claimed FTMO terms.**

Constraints:
- This is an observation-time state machine, **not a certified continuous equity recorder**. Intrabar breaches cannot be inferred from daily OHLC or end-of-day outcomes; callers must supply complete ordered equity marks and provider integrity attestations.
- A synthetic `phase_advanced` event represents external phase approval; no conversion to funded status occurs automatically. Each phase starts with new simulated capital as explicitly modeled.
- Floating PnL is aggregate account PnL; event-producing reconciler must supply net marks without double-booking fees or swaps.
- Any changed timestamp/order/schema/event value invalidates a cursor digest or requires replay from the start. Cursor contains all prior event identity hashes and is not compact; no journal storage or live cursor persistence is implemented.
- Source raw page hash and extraction hash remain absent in the sample: exact unaltered official page content has not been committed as immutable evidence, and publication/effective date are unknown.
- Phase/reset accounting and disputed grandfathering require program-by-program account agreement review, plus independent real event streams, before operational qualification.
- Production router authorization, firm-specific instrument/news/copying constraints, real payouts/fees, timezone/TZDB pinning and state serialization formats are deliberately not claimed qualified.

## Reproduction

Run in the repository virtual environment:

```shell
python -m pytest tests/test_ats5_account_rules.py -q -n 0
python -m ruff check src/account_rules.py tests/test_ats5_account_rules.py
```

Pure reproduction example:

```python
import json
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
from src.account_rules import (
    AccountBinding, AccountEvent, TermAssignment,
    rule_from_dict, replay,
)
r = rule_from_dict(json.loads(Path(
    "docs/architecture/trading_system/ats5_ftmo_public_20261016.json"
).read_text()))
start = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
account = AccountBinding(
    "EXAMPLE-NOT-A-REAL-ACCOUNT", r.program_id, start,
    Decimal("100000"), "challenge",
    (TermAssignment(start, r.version_id, "UNVERIFIED_PUBLIC_TERMS"),),
)
event = AccountEvent("demo-observation", start, 1, "observation")
result = replay(account, {r.version_id: r}, (event,))
assert result.last.eligible_for_shadow is False
assert result.last.state == "INCONCLUSIVE"
```

The synthetic fixtures in `tests/test_ats5_account_rules.py` use independently specified expected monetary floors and state outcomes, not outputs generated by the same engine. No protected history, live credentials or production orders were used.
