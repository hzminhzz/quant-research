"""Read existing monitoring and send only an explicitly generic notification test."""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta

import requests

from scripts.ats7_paper import USER_AGENT, save


async def check(output, *, send=False):
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    base = "http://127.0.0.1:19093"
    def counters():
        response = session.get(base + "/metrics", timeout=10)
        response.raise_for_status()
        rows = [r for r in response.text.splitlines() if 'integration="telegram"' in r]
        total = sum(float(r.rsplit(" ", 1)[1]) for r in rows if r.startswith("alertmanager_notifications_total{"))
        failed = sum(float(r.rsplit(" ", 1)[1]) for r in rows if r.startswith("alertmanager_notifications_failed_total{"))
        return {"total": total, "failed": failed}
    before = counters()
    evidence = {"before": before, "request": "NONE"}
    if send:
        now = datetime.now(UTC)
        payload = [{"labels": {"alertname": "NotificationDeliveryTest", "job": "notification-test", "severity": "info"},
                    "annotations": {"summary": "Notification delivery test."},
                    "startsAt": now.isoformat(), "endsAt": (now + timedelta(seconds=45)).isoformat()}]
        response = session.post(base + "/api/v2/alerts", json=payload, timeout=10)
        response.raise_for_status()
        evidence.update(request=payload, http_status=response.status_code)
        for _ in range(12):
            await asyncio.sleep(2)
            after = counters()
            if after["total"] > before["total"] or after["failed"] > before["failed"]:
                break
        evidence["after"] = after
        evidence["status"] = ("PASS" if after["total"] > before["total"] and after["failed"] == before["failed"] else "FAIL")
    evidence["checked_at"] = datetime.now(UTC).isoformat()
    evidence["scope"] = "existing Alertmanager to verified existing Telegram receiver; generic payload only"
    save(output, evidence)
    print(json.dumps(evidence, sort_keys=True))
    session.close()
    return 0 if evidence.get("status", "PASS") == "PASS" else 1


def main():
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--send-generic", action="store_true")
    args = parser.parse_args()
    return asyncio.run(check(args.output, send=args.send_generic))


if __name__ == "__main__":
    raise SystemExit(main())
