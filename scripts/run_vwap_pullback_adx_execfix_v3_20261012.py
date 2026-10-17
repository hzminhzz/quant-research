#!/usr/bin/env python3
"""Version 3 execution repair: use native ml4t.Engine with legal resting LIMIT fills.

This script never patches site-packages, never replaces the native fill loop, and
never overwrites version 2 evidence. Phase 4 dev data only; CME price proxy.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ml4t.backtest import Engine, OrderType
from ml4t.backtest.execution.fill_executor import FillExecutor
from ml4t.backtest.models import NoSlippage
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import run_vwap_pullback_adx_phase4_20261012 as prior
SID="vwap_pullback_adx_nq_20261012_proxy_v3_execfix"
OUT=ROOT/"run_log"/SID/"phase4_remediated"
PINNED_LIBRARY="0.1.7"


class LegalLimitFillExecutor(FillExecutor):
    """Keep the native engine's position, cash, fill, and OCO machinery.

    Fixed slippage is applied to market and STOP orders. A resting LIMIT
    order pays zero *adverse price slippage*: a SELL LIMIT cannot fill below
    its limit. No favorable fill improvement is assumed from candle OHLC.
    This is a conservative legal price-floor model, not a queue-fill model.
    """

    def execute(self, order, base_price: float) -> bool:
        if order.order_type != OrderType.LIMIT:
            return super().execute(order,base_price)
        previous_model=self.broker.slippage_model
        self.broker.slippage_model=NoSlippage()
        try:
            return super().execute(order,base_price)
        finally:
            self.broker.slippage_model=previous_model


class LegalLimitsEngine(Engine):
    """Engine subclass with order-aware native fill adapter and strict version pin."""

    def __init__(self,*args,**kwargs):
        import importlib.metadata as metadata
        version=metadata.version("ml4t-backtest")
        if version!=PINNED_LIBRARY:
            raise RuntimeError(f"Refuse unreviewed native library: {version}")
        super().__init__(*args,**kwargs)
        broker=self.broker
        old=broker._fill_executor
        replacement=LegalLimitFillExecutor(
            broker,
            account=old.account,
            market=old.market,
            orders=old.orders,
            risk=old.risk,
            journal=old.journal,
            record_pnl=old.record_pnl,
        )
        replacement.fill_engine=broker._fill_engine
        broker._fill_engine.executor=replacement
        broker._fill_executor=replacement


def sha(path: Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> None:
    if OUT.exists() and any(OUT.iterdir()):
        raise FileExistsError(f"No overwrite of existing trial evidence: {OUT}")
    # Fail closed if the schema-validated frozen session does not yet exist.
    frozen=ROOT/"run_log"/"research_sessions"/SID/"frozen_spec.json"
    if not frozen.exists():
        raise FileNotFoundError(f"Phase4 v3 session must be frozen before execution: {frozen}")
    feed=prior.prepare()
    prior.OUT=OUT
    prior.Engine=LegalLimitsEngine
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"provenance.json").write_text(json.dumps({
        "session_id":SID, "parent_session":prior.SID,
        "source_sha256":sha(prior.SOURCE),
        "frozen_spec_sha256":sha(frozen),
        "code_sha256":sha(Path(__file__)),
        "library":"ml4t-backtest 0.1.7",
        "library_adapter":"LegalLimitFillExecutor using native fill ledger and sibling cancellation",
        "changes_from_v2":"Only no adverse slippage for passive LIMIT; zero price improvement, same market/stop adverse slippage",
        "fee_per_side_usd":2.50,
        "base_adverse_market_stop_points":0.25,
        "stress_adverse_market_stop_points":0.50,
        "execution_assurance":"simulation OCO native parent_id, not broker atomic OCO live assurance",
        "CME_contract_level_qualified":False,
    },indent=2)+"\n")
    trials=[]
    for mode in ("B1","B2","B3"):
        for label,fee,slip in (("gross",0.0,0.0),("cost",2.50,.25),("stress",2.50,.5)):
            print("START",mode,label,flush=True)
            result=prior.run_mode(feed,mode,label,fee,slip)
            trials.append(result)
            print("DONE",mode,label,result["trades"],result["net_account_pnl_usd"],flush=True)
    (OUT/"all_trials.json").write_text(json.dumps(trials,indent=2,default=str)+"\n")
    print("REMEDIATED_COMPLETED",flush=True)


if __name__=="__main__":
    run()
