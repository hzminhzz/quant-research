"""Bounded process-death, ownership, resume and manual-halt drill for local paper."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from scripts.ats7_paper import ROOT, save


async def drill(run, output):
    unit = "ats7-local-paper@" + run.name + ".service"
    if not run.name.startswith("drill-"):
        raise ValueError("only a dedicated synthetic drill instance is allowed")
    output.mkdir(parents=True, exist_ok=False)
    def health():
        return json.loads((run / "health.json").read_text())
    async def until(predicate, timeout=160):
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            try:
                value = health()
            except FileNotFoundError:
                # systemd start returns before native connect writes first health.
                await asyncio.sleep(2)
                continue
            age = (datetime.now(UTC) - datetime.fromisoformat(value["observed_at"])).total_seconds()
            if age < 15 and predicate(value):
                return value
            await asyncio.sleep(2)
        raise TimeoutError("drill observation condition not met")
    def control(action, reason):
        save(run / "control.json", {"action": action, "reason": reason,
             "id": datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f"),
             "requested_at": datetime.now(UTC).isoformat()})
    before = await until(lambda h: h["account"]["positions"].get("BTC/USDT:USDT", {}).get("quantity") == 0.001)
    save(output / "before-crash.json", before)
    crash_at = datetime.now(UTC)
    await asyncio.to_thread(subprocess.run, ["systemctl", "--user", "kill", "--signal=SIGKILL", unit], check=True)
    restarted = await until(lambda h: datetime.fromisoformat(h["observed_at"]) > crash_at and h["status"] == "HALTED")
    assert restarted["account"]["positions"]["BTC/USDT:USDT"]["quantity"] == 0.001
    assert restarted["account"]["cash"] == before["account"]["cash"]
    assert restarted["metrics"]["unknown_orders"] == 0
    save(output / "restart-halted-exposure-preserved.json", restarted)
    control("resume", "ATS7 local process-death drill: native position and cash independently matched")
    await until(lambda h: h["status"] == "PAPER_RUNNING")
    closed = await until(lambda h: not h["account"]["positions"])
    save(output / "resumed-native-cycle-closed.json", closed)
    control("halt", "ATS7 manual-halt drill")
    halted = await until(lambda h: h["status"] == "HALTED")
    initial_bars = halted["metrics"]["observed_bars"]
    final = await until(lambda h: h["metrics"]["observed_bars"] >= initial_bars + 2)
    assert not final["account"]["positions"] and final["status"] == "HALTED"
    assert final["metrics"]["completed_cycles"] == closed["metrics"]["completed_cycles"]
    save(output / "manual-halt-two-bars-no-new-risk.json", final)
    await asyncio.to_thread(subprocess.run, ["systemctl", "--user", "stop", unit], check=True)
    stopped = json.loads((run / "stopped.json").read_text())
    terminal = await asyncio.to_thread(subprocess.run,
        ["systemctl", "--user", "show", unit, "-p", "Result", "--value"],
        check=True, capture_output=True, text=True)
    save(output / "terminal-service.json", {"native_stopped": stopped, "systemd_result": terminal.stdout.strip()})
    assert stopped["returncode"] == 0 and terminal.stdout.strip() == "success"
    save(output / "result.json", {"status": "PASS", "scope": "dedicated synthetic native local paper",
         "process_death": "SIGKILL", "restart": "HALTED", "preexisting_simulated_exposure_preserved": True,
         "resume": "separate reviewed local control", "manual_halt": "two completed public bars without new risk",
         "external_orders": 0, "finished_at": datetime.now(UTC).isoformat()})
    print(json.dumps({"status": "PASS", "evidence": str(output)}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--detach", action="store_true")
    args = parser.parse_args()
    if args.detach:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.with_suffix(".log").open("x") as out:
            process = subprocess.Popen([sys.executable, "-m", "scripts.ats7_service_drill",
                 "--run-root", str(args.run_root), "--output", str(args.output)], cwd=ROOT,
                 env={k: v for k, v in os.environ.items() if not k.startswith(("BYBIT_", "TELEGRAM_", "AWS_", "OPENAI_"))},
                 start_new_session=True, stdout=out, stderr=subprocess.STDOUT)
        print(json.dumps({"pid": process.pid, "log": str(args.output.with_suffix(".log"))}))
        return 0
    try:
        asyncio.run(drill(args.run_root, args.output))
    except Exception as exc:
        if args.output.is_dir() and not (args.output / "result.json").exists():
            save(args.output / "result.json", {"status": "FAIL", "reason": type(exc).__name__})
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
