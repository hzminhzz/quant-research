# ATS-7 Operational Incident Report — 2026-10-18

**Service:** `ats7-local-paper@observation-v1.service` (Systemd User Unit)  
**Incident Type:** Cgroup Memory Exhaustion (`oom-kill`), Process Termination (status 137), Service Restart Loop & Persistent Release Halt  
**Incident Time:** 2026-10-18 05:06:46 to 05:17:19 CEST (03:06:46 to 03:17:19 UTC)  
**Runbook Followed:** `docs/architecture/trading_system/ats7_runbook.md` (Section: Unexpected Process Termination & Incident Procedures)  
**Current State:** `HALTED` / `BLOCKED` (Unit stopped; kill switch latched; exposure preserved; zero blind restarts)

---

## 1. Executive Summary & Root Cause

1. **Host Memory Pressure**: Host swap space was 100% consumed (8,191 MB / 8,191 MB used) across the VPS during heavy parallel multi-process workloads (such as 4-worker Polars panel compilation).
2. **Cgroup OOM Kill**: The user unit `ats7-local-paper@observation-v1.service` is constrained by `MemoryMax=1G` in `/home/quant/.config/systemd/user/ats7-local-paper@.service`. When memory consumption spiked, the Linux kernel OOM killer struck the unit's processes, terminating the main Python worker with status `137` (`SIGKILL`).
3. **Repeated Restart Failure**: Systemd attempted automatic restarts (`Restart=on-failure`, `RestartSec=15`). The restarted process repeatedly detected that a service restart with existing history requires an explicit operator review:
   ```text
   python: Kill switch was previously activated: SERVICE_RESTART_REQUIRES_SEPARATE_REVIEW
   python: KILL SWITCH ACTIVATED: ATS7 persisted release halt
   python: KILL SWITCH ACTIVATED: SERVICE_RESTART_REQUIRES_SEPARATE_REVIEW
   ```
   At 05:17:19 CEST, the unit reached `StartLimitIntervalSec=300` / `StartLimitBurst=3` and failed with:
   `Start request repeated too quickly. Failed with result 'oom-kill'.`

---

## 2. Preservation of State, Journals & Simulated Exposure

In accordance with the runbook, all journals and state directories were preserved without tampering:

- **State Directory**: `/home/quant/.local/state/quant-research/ats7-local/observation-v1/state/ats7-local/`
  - `native-risk-journal.jsonl`: **2,548,272 bytes**, 4,898 journal events, journal head `12af699b5cfb60c2bf2b4b206bbf481a154556aa35ff7dfa34402c05f54eb715` (intact hash chain).
  - `native-risk.json`: State generation 3,056, clean schema version 1.
  - `release.sqlite`: **3,088,384 bytes**.
- **Simulated Exposure Preserved**:
  - Cash: `$99,918.47`
  - Position: `BTC/USDT:USDT` = `0.001` contracts (entry `$81,694.70`, mark `$81,912.90`)
  - Unrealized Equity: `$100,000.39`
  - Pending orders: `0`
  - Unknown orders: `0`
  - Reconciliation: `clean: true` (reconciliation observed epoch `1792293155.65`).

Zero exposure, journals, or order intents were deleted, modified, or cleared.

---

## 3. Observation Continuity & Accepted vs. Missing Coverage

The read-only observation assessor (`scripts.ats7_observation`) was executed against the preserved run root under the release environment:

| Gate | Requirement | Accepted / Observed Value | Gate Status |
| :--- | :--- | :--- | :---: |
| **Observation Start** | Frozen start epoch | `2026-10-17T06:38:25.888122Z` | **BOUND** |
| **Halt / Interruption Time** | First failure event | `2026-10-18T03:12:35.650537Z` | **HALTED** |
| **Accepted Elapsed Wall Time** | 2,419,200 s (28 days) | **77,782.79 s (~21.6 hours)** | **FAILED (3.2%)** |
| **Accepted Completed 1m Bars** | 40,320 bars | **1,229 completed bars** | **FAILED (3.0%)** |
| **Accepted Engine Cycles** | Bounded continuous cycles | **605 cycles** | — |
| **Bar Coverage Ratio** | $\ge 98.0\%$ | **94.83%** (1,229 / 1,296 expected) | **FAILED (< 98%)** |
| **Service Failures** | Zero unhandled failures | **3 failures** + 8 restart loops | **FAILED** |
| **Missing Coverage Window** | 0 missing minutes | Down since `2026-10-18T03:12:35Z` | **UNMET** |

### Decision on 28-Day Claim

**The original 28-day observation window is formally declared INTERRUPTED / BROKEN.**
Under the ATS-7 release boundary contract, an interrupted observation with repeated OOM kills and sub-98% bar coverage cannot be silently continued or treated as satisfying the continuous 28-day reliability gate. The 28-day clock **MUST BE RESET** after host memory remediation and service reconfiguration.

---

## 4. Runbook Remediation & Corrective Actions

1. **Keep Halt Active**: In accordance with `ats7_runbook.md`, the unit remains halted and stopped (`systemctl --user stop ats7-local-paper@observation-v1.service`). No blind resume or manual kill switch reset was performed.
2. **Memory Remediations Needed Before Next Run**:
   - Flush or expand VPS swap space (`swapoff -a && swapon -a`).
   - Increase `MemoryMax` on the synthetic paper service from `1G` to `2G` in `ats7-local-paper@.service`, or set `MemoryHigh=1.5G` to trigger memory throttling before kernel SIGKILL.
   - Adjust `StartLimitIntervalSec=600` / `RestartSec=30` to prevent rapid burst restart loops.
3. **Observation Reset Protocol**:
   - Requalify a clean `observation-v2` instance with a fresh start time and immutable policy.
   - Archive `observation-v1` forensic evidence (`health.json`, `native-risk-journal.jsonl`, `release.sqlite`) as historical proof.
