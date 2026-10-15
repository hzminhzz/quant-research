"""Issue #44 operator command tests: no credentials and synthetic native preflight only."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from connectors.bybit.client import BybitClient
from connectors.bybit.config import BybitConfig, Environment, Mode
from connectors.bybit.models import BybitSnapshotError

from scripts import bybit_demo_preflight as operator


def config(*, mode=Mode.READ_ONLY, credentials=True):
    return BybitConfig(
        environment=Environment.DEMO,
        mode=mode,
        api_key="synthetic-demo-key" if credentials else None,
        api_secret="synthetic-demo-secret" if credentials else None,
        expected_demo_uid="24680" if credentials else None,
    )


@pytest.mark.parametrize("bad", [config(credentials=False), config(mode=Mode.EXECUTION)])
def test_operator_rejects_unarmed_preflight_before_network(bad, tmp_path, monkeypatch):
    monkeypatch.setattr(
        operator, "BybitClient",
        lambda _: pytest.fail("operator attempted network before validation"),
    )
    path = tmp_path / "native-risk.json"
    with pytest.raises(BybitSnapshotError, match="operator_config"):
        asyncio.run(operator.inspect(bad, path))
    assert not path.exists()


def test_operator_only_calls_read_only_v5_and_redacts_identity(tmp_path, monkeypatch):
    exchange = MagicMock()
    exchange.hostname = "bybit.com"
    exchange.urls = {"api": {"private": "https://api-demo.{hostname}"}}
    exchange.isSandboxModeEnabled = False
    exchange.options = {"enableDemoTrading": True}
    exchange.load_markets = AsyncMock()
    exchange.close = AsyncMock()
    exchange.private_get_v5_user_query_api = AsyncMock(
        return_value={"retCode": 0, "result": {
            "userID": 24680, "apiKey": "synthetic-demo-key", "uta": 1, "readOnly": 1
        }}
    )
    exchange.private_get_v5_account_info = AsyncMock(
        return_value={"retCode": 0, "result": {"unifiedMarginStatus": 5}}
    )
    exchange.private_get_v5_account_wallet_balance = AsyncMock(
        return_value={"retCode": 0, "result": {"list": [{
            "accountType": "UNIFIED",
            "totalEquity": "10000.00", "totalAvailableBalance": "9500.00",
        }]}}
    )
    exchange.private_get_v5_position_list = AsyncMock(
        side_effect=lambda p: {"retCode": 0, "result": {
            "category": p["category"], "list": [], "nextPageCursor": "",
        }}
    )
    exchange.private_get_v5_order_realtime = AsyncMock(
        side_effect=lambda p: {"retCode": 0, "result": {
            "category": p["category"], "list": [], "nextPageCursor": "",
        }}
    )
    exchange.create_order = AsyncMock()
    exchange.cancel_order = AsyncMock()
    exchange.edit_order = AsyncMock()
    monkeypatch.setattr(
        operator, "BybitClient",
        lambda cfg: BybitClient(cfg, exchange=exchange),
    )
    result = asyncio.run(operator.inspect(config(), tmp_path / "native-risk.json"))
    assert result["status"] == "PASS"
    assert result["account"]["equity_usd"] == 10000.0
    assert result["account"]["available_usd"] == 9500.0
    assert result["positions"]["count"] == 0
    assert result["pending_orders"]["count"] == 0
    assert result["reconciliation"]["clean"] is True
    assert result["identity"]["authenticated_uid_matches_expected"] is True
    text = json.dumps(result)
    assert "24680" not in text
    assert "synthetic-demo-key" not in text
    assert "synthetic-demo-secret" not in text
    exchange.create_order.assert_not_awaited()
    exchange.cancel_order.assert_not_awaited()
    exchange.edit_order.assert_not_awaited()


@pytest.mark.parametrize("root", [operator.REPO_ROOT, operator.CONNECTOR_ROOT])
def test_private_state_and_evidence_rejected_inside_either_repo(root):
    assert operator._outside_repo(root / "issue44-private-evidence.json") is False


def test_operator_cli_missing_credentials_reports_blocked(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BYBIT_ENVIRONMENT", "demo")
    monkeypatch.setenv("BYBIT_MODE", "read_only")
    monkeypatch.setenv("BYBIT_DEMO_API_KEY", "")
    monkeypatch.setenv("BYBIT_DEMO_API_SECRET", "")
    monkeypatch.setenv("BYBIT_DEMO_EXPECTED_UID", "")
    evidence = tmp_path / "evidence.json"
    monkeypatch.setattr("sys.argv", [
        "bybit_demo_preflight", "--state-file", str(tmp_path / "state.json"),
        "--evidence-file", str(evidence),
    ])
    assert operator.main() == 2
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "BLOCKED"
    assert data["submitted_orders"] == 0
    assert json.loads(evidence.read_text()) == data
    assert evidence.stat().st_mode & 0o777 == 0o600
    assert not (tmp_path / "state.json").exists()
