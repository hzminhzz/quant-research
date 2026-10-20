"""Non-executing qualification and triage pass across all 112 inbox theses."""
from __future__ import annotations

import sys
from pathlib import Path

# Direct ``python scripts/...`` execution must not depend on the caller's
# PYTHONPATH. Bootstrap this checkout before importing src, matching the
# convention used by the other repository CLIs.
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.research_control.research_inbox_queue import InboxQueue


def generate_triage_audit() -> str:
    queue = InboxQueue(REPO / "research_inbox", REPO / "run_log")
    report = queue.report()
    cases = report["cases"]

    out = [
        "# ATS Research Inbox Full Corpus Triage Audit — 2026-10-18\n",
        "**Scope:** Non-executing structural qualification and scientific readiness triage pass across all 112 existing research inbox theses.\n",
        "## 1. Executive Summary & Actionable Frontier\n",
        f"- **Total Inbox Theses Inspected:** {len(cases)}",
        f"- **Admitted & Triaged:** {report['counts']['admitted']} / {len(cases)}",
        "- **Structurally Blocked Handoffs:** 1 (`crypto_ml_fieberg_ctrend_price_volume_factor_2025_v1` — URL anchor mismatch between brief and thesis)",
        "- **Unsupported Protocol Blockers:** 8 (All single-instrument event strategies; general single-instrument stop breakout execution is not a qualified ATS-4 factory protocol)",
        "- **Descriptive Blockers (Specification / Data):** 103 (Descriptive research briefs without executable CandidateSpec or with unresolved data/parameter dependencies)",
        "- **Actionable Frontier:** Cross-sectional theses with source-hash-bound local adaptations and qualified development data vaults (`crypto_xs_funding_velocity_dislocation_basket_v1`, `crypto_xs_90d_high_anchoring_basket_v1`).\n",
        "## 2. Protocol & Status Census\n",
        "| Scientific Protocol | Triage Status | Count | Description / Frontier Decision |",
        "| :--- | :--- | :---: | :--- |",
        "| `single_instrument_event` | `BLOCKED_PROTOCOL` | 8 | General single-instrument stop breakout execution is not qualified in native Engine; requires intrabar quote depth and gap adapter before Stage 3. |",
        "| `nested_unqualified` (Cross-Sectional) | `BLOCKED_SPEC` | 62 | Descriptive academic/practitioner thesis; lacks executable entry/exit/allocation rules or declares contradictory parameters. |",
        "| `nested_unqualified` (Cross-Sectional) | `BLOCKED_DATA` | 13 | Descriptive thesis; declared market data (e.g. orderbook depth, funding velocity, altcoin universe) not yet compiled into canonical development vault. |",
        "| `flat_unqualified` (Cross-Sectional) | `BLOCKED_SPEC` | 28 | Flat descriptive handoff; unverified executable specification; requires source-bound adaptation before freezing. |",
        "| `unknown` | `BLOCKED_HANDOFF` | 1 | DOI URL mismatch between `thesis.yaml` and `brief.md`; fails closed on provenance verification. |\n",
        "## 3. Comprehensive Source-by-Source Triage Matrix\n",
        "| # | Candidate ID | Format | Protocol | Status | Justified Next Action |",
        "| :---: | :--- | :--- | :--- | :--- | :--- |",
    ]

    for idx, c in enumerate(sorted(cases, key=lambda x: x["candidate_id"]), 1):
        cid = c["candidate_id"]
        fmt = c.get("source_format", "unknown")
        proto = c.get("protocol", "unknown")
        status = c.get("status", "UNKNOWN")

        if status == "BLOCKED_PROTOCOL":
            action = "Qualify intrabar CFD stop adapter on ML4T Engine before Stage 3"
        elif status == "BLOCKED_HANDOFF":
            action = "Reconcile brief DOI URL anchor with thesis source reference"
        elif status == "BLOCKED_DATA":
            action = "Compile missing market data family into canonical development vault"
        elif cid == "crypto_xs_funding_velocity_dislocation_basket_v1":
            action = "Execute through inbox via bound adaptation `ats_crypto_xs_funding_velocity_local_adaptation_20261018.yaml`"
        elif cid == "crypto_xs_90d_high_anchoring_basket_v1":
            action = "Execute through inbox via bound adaptation `ats_crypto_xs_90d_high_anchoring_local_adaptation_20261018.yaml`"
        else:
            action = "Formulate source-bound `local_adaptation` CandidateSpec with explicit economic mechanism"

        out.append(f"| {idx} | `{cid}` | `{fmt}` | `{proto}` | `{status}` | {action} |")

    content = "\n".join(out) + "\n"
    target = REPO / "docs/audit/ats_inbox_full_corpus_triage_20261018.md"
    target.write_text(content, encoding="utf-8")
    print(f"Generated full corpus triage audit at: {target}")
    return content


if __name__ == "__main__":
    generate_triage_audit()
