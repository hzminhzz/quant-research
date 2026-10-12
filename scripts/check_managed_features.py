"""Check the managed strategy namespace without linting legacy research code."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANAGED_ROOT = ROOT / "src" / "managed_strategies"
LEGACY_MODULES = {"src.features", "src.pipeline", "src.factory"}
INDICATOR_MODULES = {"talib", "TA-Lib", "pandas_ta"}


def _module_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _module_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _native_vwap(node: ast.AST) -> bool:
    function = _module_name(node.func) if isinstance(node, ast.Call) else None
    if function and function.endswith("EngineerNative"):
        return any(
            keyword.arg == "name"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value == "vwap"
            for keyword in node.keywords
        )
    if isinstance(node, ast.Dict):
        values = {
            key.value: value.value
            for key, value in zip(node.keys, node.values)
            if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)
        }
        if values.get("kind") == "engineer.native" and values.get("name") == "vwap":
            return True
    return any(_native_vwap(child) for child in ast.iter_child_nodes(node))


def check_source(source: str, path: str) -> list[dict[str, int | str]]:
    """Return stable policy findings for one managed strategy Python file."""
    if not path.replace("\\", "/").startswith("src/managed_strategies/"):
        return []
    tree = ast.parse(source, filename=path)
    findings: list[dict[str, int | str]] = []

    def report(node: ast.AST, code: str, message: str) -> None:
        findings.append(
            {"path": path, "line": getattr(node, "lineno", 1), "code": code, "message": message}
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                if module == "ml4t.engineer" or module.startswith("ml4t.engineer."):
                    report(node, "ENGINEER_BYPASS", "Import native Engineer features through the approved gateway")
                elif module in INDICATOR_MODULES or module.startswith("pandas_ta."):
                    report(node, "FORBIDDEN_INDICATOR_IMPORT", f"Indicator library import is not approved: {module}")
                elif module in LEGACY_MODULES or any(module.startswith(f"{legacy}.") for legacy in LEGACY_MODULES):
                    report(node, "LEGACY_INDICATOR_IMPORT", f"Legacy research module is unmanaged: {module}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("ml4t.engineer"):
                report(node, "ENGINEER_BYPASS", "Import native Engineer features through the approved gateway")
            elif module in INDICATOR_MODULES or module.startswith("pandas_ta"):
                report(node, "FORBIDDEN_INDICATOR_IMPORT", f"Indicator library import is not approved: {module}")
            elif module == "src" and any(alias.name in {"features", "pipeline", "factory"} for alias in node.names):
                report(node, "LEGACY_INDICATOR_IMPORT", "Legacy research module is unmanaged")
            elif module in LEGACY_MODULES:
                report(node, "LEGACY_INDICATOR_IMPORT", f"Legacy research module is unmanaged: {module}")
        elif isinstance(node, ast.Call) and _module_name(node.func) and _module_name(node.func).split(".")[-1] == "compute_features":
            report(node, "ENGINEER_BYPASS", "compute_features is allowed only inside the feature gateway")
        elif (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(word in node.name.lower().split("_") for word in ("adx", "rsi"))
            and (
                node.name.lower() in {"adx", "rsi"}
                or any(
                    word in node.name.lower().split("_")
                    for word in ("calc", "calculate", "compute", "custom", "indicator")
                )
            )
        ):
            report(node, "CUSTOM_INDICATOR_IMPLEMENTATION", "Custom ADX/RSI calculations are not allowed in managed strategies")

    if _native_vwap(tree):
        report(tree, "UNSUPPORTED_NATIVE_VWAP", "VWAP is an approved extension, not a native Engineer feature")
    return sorted(findings, key=lambda item: (str(item["path"]), int(item["line"]), str(item["code"])))


def main() -> int:
    findings = []
    files = sorted(MANAGED_ROOT.rglob("*.py"))
    for file_path in files:
        findings.extend(check_source(file_path.read_text(), file_path.relative_to(ROOT).as_posix()))
    print(
        json.dumps(
            {
                "scope": "src/managed_strategies/**/*.py",
                "checked_files": len(files),
                "findings": findings,
            },
            sort_keys=True,
        )
    )
    return int(bool(findings))


if __name__ == "__main__":
    sys.exit(main())
