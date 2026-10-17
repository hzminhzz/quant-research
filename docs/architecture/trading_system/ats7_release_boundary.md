# ATS7 release boundary

## Scope and owners

ATS7 binds a frozen native ML4T Strategy to an explicitly permitted environment.
It does not select a strategy, create order authority, or extend ATS6 synthetic
grants into trading permissions. Native ML4T Live 0.1.2 / SafeBroker own execution,
risk limits, positions, virtual cash, and their persistence. The existing Bybit
connector owns provider transport and its pending/unknown intent journal. ATS3
owns the read-only accounting projection. ReleaseJournal owns only release
identity, causal decision identity, control history, and outcome uncertainty.

The first risk domain supports one account and one exclusive native writer.
External execution uses a fixed canonical directory, independent of the
strategy's supplied namespace. Multiple accounts, account transfer, strategy
migration with existing exposure, and concurrent portfolio writers are not
qualified. A new account or release cannot silently replace an occupied domain.

## Environment boundary

| Environment | Execution owner | Authority |
|---|---|---|
| LOCAL_PAPER | Native VirtualPortfolio, with an exact LocalNoEffectsBroker placeholder | Permitted synthetic engineering; no account credentials |
| PROVIDER_DEMO | Exact existing Bybit broker/client, Demo endpoint and authenticated UID | Separate independent qualification and operator authorization |
| LIVE | Separate real-capital qualification | Closed for this mission; no live orders authorized |

The actual operating strategy is `src.release_probe.SyntheticCycle`. Its exact
native Strategy class is used by both the finite lifecycle and public-feed
paper engine. It opens 0.001 synthetic BTC on even UTC minute closes and closes
on odd minute closes. It has no economic thesis and must never be counted as an
economically eligible strategy.

The historical Donchian candidate is a daily Binance-perpetual strategy. The
previous Demo script recreated a different 1-minute exposure rule and sizing
policy; its operational results do not qualify the original research identity.
No substitute strategy was optimized or promoted to satisfy this mission.

## Identity and authority

ReleaseManifest is strict, frozen, versioned, and canonically hashed. It binds
source files, installed package versions, strategy parameters and timing,
portfolio composition, instruments and contract increments, account and
environment, endpoint, risk limits, evidence, cost/data/calendar policy,
operations, account-term source/effective time, and expiry.

Critical source and risk changes are checked again before a new effect.
Strategy parameters and feed identity/configuration are checked at the native
entry point. Runtime configuration changes cannot silently enlarge limits.
The running local service also has read-only code/dependency mounts.

For external environments, ExternalAuthority requires two independently signed
Ed25519 attestations: qualification and operator authorization. Each binds the
exact manifest, environment, account, risk fingerprint, permitted actions,
time window, and evidence. Their issuers and public keys must differ.
Authorization names the exact qualification receipt. Each dispatch reloads the
external trust/revocation source. A worker-owned trust file, writable parent,
unknown signer, wrong role, changed scope, revoked nonce, expired approval, or
missing proof fails closed. Trust must be provisioned by another OS principal;
no production approval issuer is included in ATS7.

Live evidence additionally needs at least 28 real elapsed days, sufficient
execution coverage, and no unreviewed anomalies. This is a necessary gate,
never authorization to submit live orders during this mission.

An approved Strategy is trusted executable code, not arbitrary research code
inside a Python security sandbox. The current operational sandbox is restricted
to the reviewed synthetic strategy and has no private credentials. Provisioning
a separately owned external execution service and qualified operator trust is
a remaining gate, not something a research worker can self-approve.

## Durable effect boundary

A deterministic 32-character execution identity derives from release identity,
causal decision timestamp, ordinal and action. The payload is bound separately:
a retry with a changed quantity cannot create a second economic order.
ReleaseJournal commits admission using SQLite rollback journaling and
synchronous EXTRA before calling native execution. The same identity reaches
the connector as the provider client-order key.

An acknowledged order is not recorded as a provider fill. Native local fills
are explicitly LOCAL_FILLED. Cancellation acknowledgment retains the pending
obligation until provider state establishes its terminal disposition. Transport
failure, task cancellation, and post-acknowledgment snapshot failure remain
UNKNOWN. Restart converts interrupted DISPATCHING decisions into UNKNOWN and
latches the halt. Unknown decisions cannot be automatically released by resume.

The connector no longer treats exception text containing words such as
“invalid” or “reject” as proof of a terminal rejection. Only typed pre-effect
refusals are eligible for that disposition. It refuses duplicate durable
client keys before retransmission and preserves known provider IDs after
post-acknowledgment failures.

## Risk, halt, and recovery

Native limits enforce explicit capital, order quantity/value, position
quantity/value, total exposure, position count, order rate, daily loss,
drawdown, price deviation, data age, and deduplication settings. The release
boundary rejects unbound instruments, invalid lot/tick increments, missing
market references, stale clocks/account evidence, and raw provider parameter
overrides.

Native and release halts are persistent. A service crash restarts into a halt;
it does not silently continue strategy callbacks. Resume requires a distinct
control, current valid authority where applicable, no unknown exposure, and
clean native reconciliation. Existing positions remain owned.

The halt gate suppresses strategy business callbacks through a delegate while
still invoking the native lifecycle dispatcher. Native phase counts, worker
timing, and shutdown validation remain authoritative; the release boundary
never fabricates or skips native lifecycle bookkeeping. Orderly systemd stop
waits for the native terminal receipt before the supervisor terminates.

Reduction is a separate action. It must use the verified native reduction
path, cannot exceed or cross the confirmed position, and passes both a stable
client identity and reduce-only semantics to the connector. Approval expiry
blocks opening risk without erasing reduction/cancellation obligations; any
external recovery action still needs its explicit signed recovery window.
A halt does not promise a fill, an exit price, or an available market.

Rollback restores exact bound source and dependencies while retaining the
newest native and release journals. Restoring an old journal beside newer
native decision references is refused. Changing the release requires a new
qualification; overwriting history or deleting uncertain positions is not a
rollback procedure.

## Evidence and operational scope

The acceptance command saves original bars, the immutable manifest, actual
native state/journal, the release decision journal, native terminal cash and
positions, and ATS6 synthetic admission comparisons. The outside judge runs
in another interpreter, uses Decimal arithmetic and the existing ATS3
projection, and must agree with native cash. Repriced fill evidence fails this
comparison. ATS6 comparison preserves intent quantity and direction through an
explicit fixture mapping; it does not assert provider fills or live permission.

Native VirtualPortfolio uses immediate simulated reference-price execution.
The zero commission/financing entries are explicit simulator assumptions, not
provider fee observations. No liquidity, queue, funding, slippage, or realistic
limit-fill claim follows from this local proof.

The public Bybit feed contains actual completed 1-minute observations, while
all fills remain local simulation. Minimum observation is 28 real days, at least
one completed cycle, at least 99% expected bar coverage, zero unknown or
unauthorized effects, and zero unreviewed loss breaches. Synthetic observation
cannot qualify an economically unapproved strategy.

The service is a fixed systemd user unit with lingering, bounded resources,
a credential-free environment, isolated process namespace, read-only
dependencies, and a writable private state directory. Metrics extend the
existing native projection and existing Prometheus/Grafana deployment.
Generic notification delivery is tested through the established Telegram
destination and Alertmanager. Project-status alert rules are staged pending
the explicit destination/payload approval required by automatic review.
