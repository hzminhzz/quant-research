"""Portable resolution for sibling trading-connector repository."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path


def ensure_connectors() -> Path | None:
    try:
        mod = importlib.import_module("connectors")
        mod_file = getattr(mod, "__file__", None)
        if isinstance(mod_file, str):
            return Path(mod_file).resolve().parent.parent
        return None
    except ImportError:
        pass

    root = Path(__file__).resolve().parents[1]
    candidates = [
        root / "connectors",
        root / ".ci/trading-connector",
        root.parent / "trading-connector",
        root.parents[1] / "trading-connector",
        Path.home() / "dev/trading-connector",
        Path.home() / "dev/quant/trading-connector",
    ]
    devspace = Path.home() / ".devspace/worktrees"
    if devspace.is_dir():
        candidates.extend(sorted(devspace.glob("trading-connector*")))

    for p in candidates:
        if (p / "connectors").is_dir():
            sys.path.insert(0, str(p))
            try:
                _ = importlib.import_module("connectors")
                return p
            except ImportError:
                sys.path.pop(0)
    return None
