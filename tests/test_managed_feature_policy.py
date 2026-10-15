from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.check_managed_features import check_source

ROOT = Path(__file__).resolve().parents[1]


def codes(source: str) -> set[str]:
    return {
        str(item["code"])
        for item in check_source(source, "src/managed_strategies/fixture.py")
    }


def test_custom_adx_calculation_is_rejected():
    assert codes("def custom_adx(high, low, close):\n    return close\n") == {
        "CUSTOM_INDICATOR_IMPLEMENTATION"
    }


def test_custom_rsi_calculation_is_rejected():
    assert codes("def calculate_rsi(close):\n    return close\n") == {
        "CUSTOM_INDICATOR_IMPLEMENTATION"
    }


def test_native_adx_strategy_name_is_not_mistaken_for_a_calculator():
    assert codes("def run_adx_strategy(features):\n    return features\n") == set()


def test_direct_talib_import_is_rejected():
    assert codes("import talib as ta\n") == {"FORBIDDEN_INDICATOR_IMPORT"}


def test_aliased_engineer_compute_bypass_is_rejected():
    assert codes("from ml4t.engineer import compute_features as compute\ncompute(data, ['adx'])\n") == {
        "ENGINEER_BYPASS"
    }


def test_aliased_engineer_module_bypass_is_rejected():
    assert codes("import ml4t.engineer as engineer\nengineer.compute_features(data, ['adx'])\n") == {
        "ENGINEER_BYPASS"
    }


def test_legacy_indicator_import_is_rejected():
    assert codes("from src import features as legacy\n") == {"LEGACY_INDICATOR_IMPORT"}


def test_unregistered_native_vwap_is_rejected():
    source = "contract = {'provider': {'kind': 'engineer.native', 'name': 'vwap'}}\n"
    constructor = "provider = EngineerNative(name='vwap', params={})\n"
    assert codes(source + constructor) == {"UNSUPPORTED_NATIVE_VWAP"}


def test_native_and_approved_extension_gateway_requests_pass():
    source = """
from src.research_control.feature_gateway import FeatureGateway
native = {'kind': 'engineer.native', 'name': 'adx', 'params': {'period': 14}}
extension = {'kind': 'extension.approved', 'extension_id': 'cash_open_vwap', 'version': '1.0.0'}
result = FeatureGateway().compute(data, contract)
"""
    assert check_source(source, "src/managed_strategies/fixture.py") == []


def test_cli_reports_json_and_limits_its_visible_scope_to_managed_modules():
    result = subprocess.run(
        [sys.executable, "scripts/check_managed_features.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload == {
        "scope": "src/managed_strategies/**/*.py",
        "checked_files": 1,
        "findings": [],
    }


def test_legacy_module_remains_outside_managed_scope():
    source = (ROOT / "src/features/legacy.py").read_text()
    assert check_source(source, "src/features/legacy.py") == []


def test_scoped_ruff_rule_rejects_indicator_import(tmp_path):
    fixture = tmp_path / "managed_feature.py"
    fixture.write_text("import talib\n")
    result = subprocess.run(
        [
            shutil.which("ruff") or "ruff",
            "check",
            "--config",
            str(ROOT / "scripts/ruff-managed.toml"),
            str(fixture),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "TID251" in result.stdout
