from pathlib import Path

import pandas as pd

CACHE_ROOT = Path.home() / ".qtools_cache"


def cache_path(namespace: str, key: str) -> Path:
    return CACHE_ROOT / namespace / f"{key}.parquet"


def read_parquet(namespace: str, key: str) -> pd.DataFrame | None:
    p = cache_path(namespace, key)
    if p.exists():
        return pd.read_parquet(p)
    return None


def write_parquet(namespace: str, key: str, df: pd.DataFrame) -> None:
    p = cache_path(namespace, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)


def clear_cache(namespace: str | None = None) -> int:
    """Remove cached files. Returns number of files deleted."""
    root = CACHE_ROOT / namespace if namespace else CACHE_ROOT
    if not root.exists():
        return 0
    count = 0
    for f in root.rglob("*.parquet"):
        f.unlink()
        count += 1
    return count
