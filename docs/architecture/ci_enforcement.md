# M5-B: mandatory research compliance checks

**Verified 2026-10-13, GitHub remote:** `hzminhzz/quant-research` default branch `main`.

## Enforcement contract

GitHub branch protection requires a pull request and the following named jobs (strict base-branch freshness enabled):

- `Managed feature policy`
- `Fast tests`
- `Full tests`

Enforcement also applies to administrators. At time of verification, the GitHub branch-protection REST response reported `enforce_admins.enabled=true`, `required_status_checks.strict=true`, `required_pull_request_reviews.required_approving_review_count=0` and the three exact status-check names above.

## Negative regression: prohibited custom ADX

A disposable probe branch introduced `src/managed_strategies/ci_negative_probe.py` with an unauthorized `compute_adx` function. The CI workflow rejected the input. GitHub Actions run [38340578671](https://github.com/hzminhzz/quant-research/actions/runs/38340578671) reported `Managed feature policy=FAILURE` (and additional failing test jobs), and PR [#15](https://github.com/hzminhzz/quant-research/pull/15) reported `mergeStateStatus=BLOCKED`. PR #15 was closed unmerged and the disposable remote branch deleted. No policy violation was introduced into `main`.

## Positive regression: compliant changes

This documentation-only PR is the positive branch-protection probe. Verify the exact three required jobs complete with success on this PR and that GitHub permits merging without bypassing protection. Record its merged SHA and closure of issue #7 in GitHub evidence. Do not equate a locally passing suite, or an unrelated GitGuardian check, with remote compliance enforcement.

## Repeatable verification

```bash
gh api repos/hzminhzz/quant-research/branches/main/protection --jq '{contexts:.required_status_checks.contexts,strict:.required_status_checks.strict,admins:.enforce_admins.enabled,approvals:.required_pull_request_reviews.required_approving_review_count}'
gh pr checks <PR-number>
gh pr view <PR-number> --json mergeStateStatus,mergeable
```

If remote rules vanish or credentials cannot inspect them, report `CI_NOT_ENFORCED` and block guarded research promotions.
