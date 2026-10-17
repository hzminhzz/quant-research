# Methodology and packaging record

This work packages existing evidence. It does not run a new market-data experiment or change strategy rules.

| Skill | Local file | Reason selected | Invariant and verification |
| --- | --- | --- | --- |
| `ml4t-registry-system` | `.agents/skills/ml4t-registry-system/SKILL.md` | Preserve identities, source paths, run artifacts, and hashes. | The provenance manifest records SHA256 for each package file and the source path for each copied file. `verify_package.py` checks each recorded hash. |
| `ml4t-run-backtest` | `.agents/skills/ml4t-run-backtest/SKILL.md` | Review existing engine runs and their fill/cost evidence. | Keep original Strategy/Engine run artifacts and frozen specifications. Do not infer executable fills from a package snapshot. The copied run ledgers and audits retain their existing results and limits. |
| `ml4t-backtest-overfitting` | `.agents/skills/ml4t-backtest-overfitting/SKILL.md` | Preserve the retrospective trial history and avoid promoting a selected positive result. | Retain trial ledgers and failed/blocked status. No new Sharpe haircut or DSR is claimed because this packaging task did not reconstruct the full trial population. |
| `ml4t-strategy-workflow` | `.agents/skills/ml4t-strategy-workflow/SKILL.md` | Keep the hypothesis, execution limits, and research approval separate. | YAML and README classify the candidate as `EXPLORATORY` and `NOT_APPROVED`; live trading remains disabled. |
| `ml4t-production-readiness` | `.agents/skills/ml4t-production-readiness/SKILL.md` | Check the meaning of promotion status. | The package does not claim production readiness. The source is not a verified CME contract, and OCO, data, cost, and operational gates remain open. |

The package verifier parses all YAML files and checks the content hashes in `provenance/manifest.json`. The yearly refresh checks the annual ledger, requires both completed cost scenarios and their ledgers, and compares source hashes before and after each copy. It does not modify source run directories.
