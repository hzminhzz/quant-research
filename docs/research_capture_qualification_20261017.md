# ATS source capture qualification — 2026-10-17

## Result

The seven published `research_inbox` handoffs were captured as descriptive
records: **7/7 `THESIS_CAPTURED`, 0/7 executable**. The strict executable
thesis-ingest baseline accepted **0/7**; all seven returned a nonzero result
because their descriptive handoff shape does not satisfy the executable thesis
contract. Capture intentionally does not relax that parser.

No backtests or protected data were accessed. This qualifies intake mechanics
only; it does not establish data availability, thesis quality, strategy
validity, or readiness for execution.

## Captured source identities

| Candidate | Source SHA-256 |
|---|---|
| `audusd_policy_carry_cfd_v1` | `398c209408574462462e272139793d01b0c184126bc51b1b38fae33003cbe295` |
| `dax_monthend_liquidity_rebound_cfd_20261015_v1` | `c250110ee7116ba3505ad2b8bfe52e71598e7b2089ffbc23f23b0090fda485c1` |
| `fomc_overnight_uncertainty_premium_us500_cfd_20261015_v1` | `ace6f8c9c5ccd9a70d0134b62a17b06e60c858e7d34fb56d321ba8e61160733d` |
| `gbpusd_weekend_gap_reversal_cfd_20261015_v1` | `f69814bfc6fd6395b5d5693e9d1e05374bc56c1739d7185e0d49f13d3df8069a` |
| `hanna_spy_bear_gap_fade_us500_cfd_20261017_1600_v1` | `e031c0b4d299f15fc0633dbbd7d9a235e17132db80fdf6d2808e456832b15166` |
| `oil_to_cad_daily_delayed_adjustment_20261015_v1` | `e4342c64d56f5930746fd3fe3001ae1001511cc53793ecf5d2494c2f708d34bc` |
| `us500_european_open_uncertainty_resolution_cfd_v1` | `ae90903b9a3ad89ad96d2e073c51fa42047c8845e637166129986b615bd1357c` |

## Checks

- Independent post-review capture, strict handoff, inbox queue and legacy
  thesis conversion tests: **70 passed, 1 deselected** (the environment-blocked
  Bubblewrap CLI test), including a synthetic 62-folder archive batch.
- Eight synthetic-only dual-mode regression modules: **50 passed**, including
  pipeline, execution ordering, isolation and market materialization checks.
- Adversarial coverage: nested placeholders, modified reports, independently
  pinned report hashes, modified sources and archives, immutable repeated
  captures, unexpected subdirectories, symlinked output ancestors, duplicate
  YAML keys and ZIP paths, traversal, archive symlinks, compression bombs,
  invalid UTF-8, per-file and archive-wide size/count caps, unsupported
  compression, unsafe YAML tags, and incomplete pairs.
- Ruff: scoped to capture implementation, CLI and tests; PASS.
- An independent read-only reviewer identified symlinked output ancestors,
  ignored extra directories, self-asserted report checksums, and overly strong
  structural `RESEARCH_READY` classification. All four were addressed before
  final qualification. Reports always remain `THESIS_CAPTURED`; an external
  SHA-256 can authenticate a report separately from its self-contained
  corruption checksum. This does not provide owner-proof filesystem isolation.
- Seven `quant.py ingest` attempts failed closed; none emitted an executable
  candidate. Their exact diagnostics are input-contract blockers, not thesis
  falsification.
- One development-only CLI regression cannot complete in this container:
  Bubblewrap cannot create a user namespace and returns
  `ISOLATION_UNAVAILABLE`. The test remains failing here; isolation was not
  disabled to force a pass.
- The original `ats_theses_all_62_cycles.zip` was not available in this
  worktree. The archive command was exercised on a synthetic 62-folder ZIP;
  its output contained 62 distinct `THESIS_CAPTURED` reports. This does not
  qualify the inaccessible archive's actual contents.

The preserved byte copies and generated capture reports used for this run were
written under `/tmp/ats-captures` and are intentionally not committed as bulk
artifacts. Re-run the documented batch command to regenerate and verify them.
