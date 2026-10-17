"""Create bounded, immutable Program 2 snapshots. Do not read sealed months."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import subprocess
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SID = "tokyo_fix_program2_cross_currency_20261011_v1"
OUT = ROOT / "run_log" / SID
DATA = ROOT / "data/processed" / SID
STORE = Path("/home/quant/dev/quant/ml4t-data/.data/store")
MAJORS = ["USDJPY", "EURUSD", "GBPUSD", "AUDUSD"]
CROSSES = ["EURJPY", "GBPJPY"]
BOUND = datetime(2026, 8, 31, 15, tzinfo=timezone.utc)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def safe_files(pair, year):
    """Partition selection excludes September 2026 and every later year."""
    if year not in range(2020, 2027):
        raise ValueError("Outside development")
    return sorted(p for m in range(1, 9 if year == 2026 else 13)
                  for p in (STORE / f"forex_minute_{pair}" / f"year={year}" / f"month={m}").rglob("data.parquet"))

def main():
    if DATA.exists() or OUT.exists():
        raise RuntimeError("Refuse existing version")
    DATA.mkdir(parents=True)
    OUT.mkdir(parents=True)
    prior = [p for base in [ROOT/"run_log/tokyo_alpha_map_program1_closure_v3",
                            ROOT/"run_log/tokyo_alpha_map_program1_native_exploratory_v2",
                            ROOT/"data/processed/tokyo_alpha_map_program1_v1"] for p in base.rglob("*") if p.is_file()]
    tracked = subprocess.check_output(["git", "ls-files", "-m"], cwd=ROOT, text=True).splitlines()
    preservation = {str(p.relative_to(ROOT)):sha(p) for p in prior + [ROOT/p for p in tracked]}
    (OUT/"preservation_before.json").write_text(json.dumps(preservation, indent=2))
    manifest = []
    for pair in MAJORS+CROSSES:
        for year in range(2020, 2027):
            files = safe_files(pair, year)
            if not files:
                continue
            lazy = pl.scan_parquet(files, hive_partitioning=False)
            schema = lazy.collect_schema()
            naive = schema["timestamp"].time_zone is None
            if naive:
                # Legacy writer uses UTC epoch decoding. This establishes the clock,
                # but does not establish comparability to LSE aggregated candles.
                lazy = lazy.with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
            df = (lazy.filter((pl.col("timestamp") >= datetime(2019,12,31,15,tzinfo=timezone.utc)) & (pl.col("timestamp") < BOUND))
                .with_columns(pl.col("timestamp").dt.convert_time_zone("Asia/Tokyo").alias("jst"))
                .with_columns(pl.col("jst").dt.date().alias("session"),
                    (pl.col("jst").dt.hour().cast(pl.Int32)*60+pl.col("jst").dt.minute()).alias("minute"))
                .filter(pl.col("minute").is_between(180,780))
                .select("timestamp","symbol","open","high","low","close","volume","session","minute")
                .sort("timestamp").collect())
            if df.is_empty():
                continue
            assert df["timestamp"].max() < BOUND
            assert df["symbol"].unique().to_list() == [pair]
            path = DATA/f"{pair}_{year}.parquet"
            df.write_parquet(path, compression="zstd")
            manifest.append({"pair":pair,"year":year,"path":str(path.relative_to(ROOT)),"sha256":sha(path),
                "rows":df.height,"first":str(df["timestamp"].min()),"last":str(df["timestamp"].max()),
                "source_files":[str(p) for p in files],"source_schema":str(schema),"naive_utc_localized":naive,
                "provider":"LSE" if pair in MAJORS else "Dukascopy BID legacy; inference ineligible",
                "raw_identity":"Bounded selected-row snapshot hash; raw August31 file is not hashed because it straddles sealed JST boundary"})
            print(pair,year,df.height,flush=True)
    (OUT/"source_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    calendar = ROOT/"run_log/tokyo_fix_alpha_map_program1_20261010/execution_v1/calendar_event_registry.parquet"
    (OUT/"calendar_manifest.json").write_text(json.dumps({"path":str(calendar.relative_to(ROOT)),"sha256":sha(calendar),"inheritance":"BOJ bank calendar; rollback is settlement-flow assumption"},indent=2))

if __name__ == "__main__":
    main()
