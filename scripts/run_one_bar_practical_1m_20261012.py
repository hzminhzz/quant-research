"""Execute the frozen practical one-minute native-engine replay."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "run_log/one_bar_practical_1m_20261012"
BASE = ROOT / "run_log/one_bar_dukascopy_2013_2026_20261011"
STORE = Path("/home/quant/dev/quant/ml4t-data/.data/store/index_minute_NQ")
sys.path.insert(0, str(ROOT / "scripts"))
import run_one_bar_dukascopy_phase567_20261011 as phase


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def files() -> list[Path]:
    return sorted(p for p in STORE.glob("year=*/month=*/data.parquet")
        if p.parent.parent.name < "year=2026" or
        (p.parent.parent.name == "year=2026" and int(p.parent.name.split("=")[1]) <= 7))


def frozen_spec() -> dict:
    manifest_path = BASE / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    return {
        "status": "frozen_before_execution", "classification": "EXPLORATORY retrospective; not approval",
        "source": "Dukascopy USATECH.IDX/USD BID 1-minute CFD proxy; not CME NQ",
        "data": {"root": str(STORE), "start_inclusive_utc": "2013-01-01", "end_inclusive_utc": "2026-07-14",
            "protected_after": "2026-07-14", "partition_count": len(manifest),
            "source_manifest": str(manifest_path.relative_to(ROOT)), "source_manifest_sha256": sha(manifest_path),
            "source_manifest_matches_frozen_baseline": sha(manifest_path) == json.loads((BASE / "frozen_spec.json").read_text())["data"]["source_manifest_sha256"]},
        "instrument_assumptions": {"multiplier_usd_per_point": 20, "tick_points": 0.25, "contracts": 1,
            "identity_limit": "NQ-equivalent sizing is illustrative, not source CFD specification."},
        "rules": {"lookback": "highest high / lowest low of 50 fully completed session-anchored 30m bars",
            "entry": "native buy STOP and sell STOP, cancel opposite after fill; max 2 entries per Chicago Globex date",
            "protective_stop": "$1000 nominal = 50 index points from entry", "exit": "market at next 30m boundary open; next actual source minute if boundary print is absent",
            "session": "Chicago 17:00 anchored 30m intervals; extended hours", "one contract": True,
            "ambiguous_ohlc": "Native engine ledger retained as modeled. Separate conservative bound replaces each affected trade/event with worst-case loss; no intraminute sequence inferred."},
        "trials": [
            {"id":"A","name":"native_zero_cost","commission_per_fill_usd":0,"slippage_points_per_fill":0},
            {"id":"B","name":"native_full_tick_cost","commission_per_fill_usd":2.5,"slippage_points_per_fill":0.25},
            {"id":"C","name":"native_additional_half_spread","commission_per_fill_usd":2.5,"slippage_points_per_fill":0.375,"note":"B plus 0.125 index points per fill; extra one tick round trip, proxy stress."},
            {"id":"D","name":"conservative_ambiguous_bound","source_trial":"B","method":"Replace ambiguous executions by -$1000 nominal plus B round-trip commission and slippage. Conservative diagnostic, not native replay."}],
        "skill_invariants": ["ml4t-run-backtest: Strategy/Engine/DataFeed; future-event fills; explicit costs",
            "ml4t-polars-patterns: sorted Polars source processing", "ml4t-calendar-ops: Chicago session dates and DST-aware UTC boundaries",
            "ml4t-build-bars: only 30 complete source minutes form a decision bar", "ml4t-lookahead-bias: levels released only after prior completed bar",
            "ml4t-validate-data: source row, duplicate, null, and OHLC audit", "ml4t-cost-model: isolate commission and adverse slippage"],
    }


def load_feed() -> tuple[pl.DataFrame, dict]:
    paths = files()
    frozen = json.loads((BASE / "frozen_spec.json").read_text())
    expected = json.loads((BASE / "source_manifest.json").read_text())
    if len(paths) != frozen["data"]["partitions"] or sha(BASE / "source_manifest.json") != frozen["data"]["source_manifest_sha256"]:
        raise ValueError("Source manifest identity mismatch")
    for path, record in zip(paths, expected, strict=True):
        if path.relative_to(STORE).as_posix() != record["path"] or sha(path) != record["sha256"]:
            raise ValueError(f"Source partition mismatch: {path}")
    raw = (pl.scan_parquet([str(p) for p in paths])
        .filter(pl.col("timestamp").dt.date().is_between(date(2013,1,1), date(2026,7,14)))
        .select("timestamp", "open", "high", "low", "close", "volume").sort("timestamp").collect()
        .with_columns(pl.col("timestamp").dt.replace_time_zone("UTC")))
    local = pl.col("timestamp").dt.convert_time_zone("America/Chicago")
    minute = local.dt.hour() * 60 + local.dt.minute()
    raw = raw.with_columns(local.alias("local"), pl.when(minute >= 1020).then(local.dt.date())
        .otherwise(local.dt.date().dt.offset_by("-1d")).alias("session_date"))
    dates = raw["session_date"].unique().sort().to_list()
    from zoneinfo import ZoneInfo
    from datetime import datetime as dt
    starts = pl.DataFrame({"session_date": dates, "session_start_utc": [dt(d.year,d.month,d.day,17,tzinfo=ZoneInfo("America/Chicago")).astimezone(timezone.utc) for d in dates]})
    source = raw.join(starts, on="session_date", how="left").with_columns(
        ((pl.col("timestamp")-pl.col("session_start_utc")).dt.total_minutes()//30).alias("bar_no"))
    bars = (source.group_by("session_date","bar_no").agg(pl.col("timestamp").min().alias("bar_start"),
        pl.col("high").max().alias("bar_high"),pl.col("low").min().alias("bar_low"),pl.len().alias("n"),
        pl.col("timestamp").n_unique().alias("unique_n")).filter((pl.col("n")==30)&(pl.col("unique_n")==30))
        .sort("bar_start").with_columns(pl.col("bar_high").rolling_max(50).alias("next_long_stop"),
        pl.col("bar_low").rolling_min(50).alias("next_short_stop"),
        ((pl.col("bar_high")-pl.col("bar_low"))/pl.col("bar_high")).alias("range_proxy"),
        (pl.col("bar_start")+pl.duration(minutes=30)).alias("available_at"))
        .filter(pl.col("next_long_stop").is_not_null()))
    # The prior minute's on_data call submits before the next source row opens at the release boundary.
    levels = bars.select((pl.col("available_at")-pl.duration(minutes=1)).alias("release_decision_at"),"next_long_stop","next_short_stop","range_proxy")
    feed = source.sort("timestamp").join_asof(levels.sort("release_decision_at"),left_on="timestamp",
        right_on="release_decision_at",strategy="backward").with_columns(
            pl.lit(phase.ASSET).alias("asset"),
            ((pl.col("next_long_stop")-pl.col("next_short_stop"))/pl.col("next_long_stop")).alias("range_proxy"))
    quality = {"source_rows": raw.height,"source_minutes_all_retained": feed.height,
        "complete_30m_bars": bars.height,"incomplete_bins": int(source.select(pl.struct("session_date","bar_no").n_unique()).item())-bars.height,
        "duplicate_timestamps": raw.height-raw["timestamp"].n_unique(),
        "null_ohlc": sum(raw[c].null_count() for c in ("open","high","low","close")),
        "invalid_ohlc": raw.filter((pl.col("high")<pl.col("low"))|(pl.col("close")>pl.col("high"))|(pl.col("close")<pl.col("low"))).height,
        "first_timestamp": str(raw["timestamp"].min()),"last_timestamp":str(raw["timestamp"].max()),
        "source_manifest_sha256":sha(BASE/"source_manifest.json"),"source_partitions":len(paths)}
    return feed, quality


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    spec=frozen_spec(); (OUT/"frozen_spec.json").write_text(json.dumps(spec,indent=2)+"\n")
    prior_ledger=OUT/"trial_ledger.json"
    prior_attempts=json.loads(prior_ledger.read_text()).get("attempts",[]) if prior_ledger.exists() else []
    ledger={"frozen_at_utc":datetime.now(timezone.utc).isoformat(),"attempts":prior_attempts,"status":"RUNNING"}
    (OUT/"trial_ledger.json").write_text(json.dumps(ledger,indent=2)+"\n")
    phase.OUT=OUT
    feed,quality=load_feed(); (OUT/"validation").mkdir(exist_ok=True)
    (OUT/"validation/source_quality.json").write_text(json.dumps(quality,indent=2)+"\n")
    trials=[("A","native_zero_cost",0,0),("B","native_full_tick_cost",2.5,.25),("C","native_additional_half_spread",2.5,.375)]
    summaries={}
    for code,name,commission,slippage in trials:
        print(f"ENGINE_START {name} {datetime.now(timezone.utc).isoformat()}",flush=True)
        try:
            phase.run_native(feed,name,commission,slippage)
            metrics=phase.audit_saved_trial(name,commission,slippage)
            summaries[name]=metrics
            ledger["attempts"].append({"id":code,"name":name,"status":"completed","metrics":metrics})
            print(f"ENGINE_DONE {name} pnl={metrics['sum_trade_pnl_usd']} trades={metrics['closed_trades']}",flush=True)
        except Exception as exc:
            ledger["attempts"].append({"id":code,"name":name,"status":"failed","error":repr(exc)})
            (OUT/"errors").mkdir(exist_ok=True); (OUT/f"errors/{name}.txt").write_text(repr(exc)+"\n")
            (OUT/"trial_ledger.json").write_text(json.dumps(ledger,indent=2,default=str)+"\n")
            raise
        (OUT/"trial_ledger.json").write_text(json.dumps(ledger,indent=2,default=str)+"\n")
    (OUT/"metrics").mkdir(exist_ok=True)
    (OUT/"ambiguity_report.json").write_text(json.dumps({name:{k:v for k,v in m.items() if "ambiguous" in k or "worst_case" in k or "simultaneous" in k} for name,m in summaries.items()},indent=2,default=str)+"\n")
    ledger["status"]="completed"; (OUT/"trial_ledger.json").write_text(json.dumps(ledger,indent=2,default=str)+"\n")
    (OUT/"final_report.json").write_text(json.dumps({"status":"COMPLETED_EXPLORATORY","quality":quality,"trials":summaries,
        "limitations":["Dukascopy BID CFD index proxy, not CME NQ","1m OHLC cannot sequence intraminute events","native broker has no atomic OCO; ambiguity stress is a diagnostic bound","no protected holdout"],"manager_reference_usd_per_trade":41},indent=2,default=str)+"\n")
    hashes={p.relative_to(ROOT).as_posix():sha(p) for p in OUT.rglob("*") if p.is_file() and p.name!="hashes.json"}
    (OUT/"hashes.json").write_text(json.dumps(hashes,indent=2)+"\n")
    print("RUN_COMPLETED",flush=True)

if __name__=="__main__": main()
