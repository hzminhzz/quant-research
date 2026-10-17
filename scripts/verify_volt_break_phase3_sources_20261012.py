"""Independent read-only file-identity audit for VOLT BREAK Phase 3."""
from pathlib import Path
import hashlib
import json
manifest=json.loads(Path("run_log/one_bar_dukascopy_2013_2026_20261011/source_manifest.json").read_text())
root=Path("/home/quant/dev/quant/ml4t-data/.data/store/index_minute_NQ")
eligible={f"year={y}" for y in range(2018,2026)}
items=[item for item in manifest if item["path"].split("/")[0] in eligible]
seen={item["path"] for item in items}
failed=[]
for item in items:
    p=root/item["path"]
    if not p.is_file():
        failed.append({"path":item["path"],"why":"missing"})
    else:
        sha=hashlib.sha256(p.read_bytes()).hexdigest()
        if sha != item["sha256"]:
            failed.append({"path":item["path"],"why":"mismatch"})
actual={str(p.relative_to(root)) for y in range(2018,2026)
        for p in (root/f"year={y}").glob("month=*/data.parquet")}
print(json.dumps({
"status":"PASS" if not failed and seen==actual else "FAIL",
"matched_files":len(items)-len(failed),
"manifest_files":len(items),"actual_files":len(actual),
"unmanifested":sorted(actual-seen)[:10],
"missing_from_store":sorted(seen-actual)[:10],
"failed":failed[:10]},indent=2))
