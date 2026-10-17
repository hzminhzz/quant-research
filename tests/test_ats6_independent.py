"""Independent proof, strict boundary and shared stale-source regression probes."""
import json
import sqlite3
from datetime import timedelta

import pytest

from scripts.ats6_fixtures import (
    START,
    account,
    admitted,
    create_fixture,
    fill,
    intent,
    observe,
    publish,
    signed,
)
from scripts.ats6_outside_judge import audit, digest
from src.shadow_contracts import AccountSnapshot


def test_outside_judge_rejects_changed_fills_even_with_valid_projection_hash(tmp_path):
    r, key, epoch = create_fixture(tmp_path / "router.db")
    admitted(r, key, epoch, intent("one"))
    publish(r, "one", epoch)
    observe(r, "one", epoch, 1, "fill", executions=(fill("fill-1", 2),))
    report = audit(r.path)
    assert report["shared"]["reserved"] == 400
    assert report["shared"]["recognized"] == 200
    with sqlite3.connect(r.path) as con:
        state = json.loads(con.execute("SELECT body FROM projection").fetchone()[0])
        state["routes"]["one"]["executions"]["fill-1"]["lots"] = 3
        con.execute("UPDATE projection SET body=?,sha256=?", (json.dumps(state), digest(state)))
    with pytest.raises(AssertionError, match="EXECUTION_PROJECTION"):
        audit(r.path)


@pytest.mark.parametrize("touch,expected", [(False, "ADMITTED"), (True, "SKIPPED")])
def test_exact_account_floor_respects_ats5_touch_semantics(tmp_path, touch, expected):
    r, key, epoch = create_fixture(tmp_path / "router.db", caps=())
    s = account("shadow:a", cap=1000)
    b, rule = dict(s.binding), dict(s.rules[0])
    b["initial_capital"] = "100"
    rule["breach_on_touch"] = touch
    s = s.model_copy(update={"binding": b, "rules": (rule,)})
    assert r.update_account(s, epoch, now=START)["status"] == "UPDATED"
    a, g = signed(r, key, intent("boundary", 5))
    assert r.admit(a, g, epoch, now=START)["status"] == expected


def test_stale_active_account_cannot_lend_shared_cushion_to_fresh_account(tmp_path):
    r, key, epoch = create_fixture(tmp_path / "router.db")
    admitted(r, key, epoch, intent("held", 4))
    selected = r.snapshot()["routes"]["held"]["account_id"]
    s = AccountSnapshot.model_validate(r.snapshot()["accounts"][selected])
    s = s.model_copy(update={"revision": 2, "marks_complete": False})
    r.update_account(s, epoch, now=START + timedelta(seconds=1))
    a, g = signed(r, key, intent("new", 1))
    result = r.admit(a, g, epoch, now=START + timedelta(seconds=2))
    assert result["status"] == "SKIPPED"
    assert any(reason.startswith("ACTIVE_ACCOUNT_SOURCE_UNCERTAIN") for reason in result["reasons"])
    assert r.snapshot()["usage"]["shared"]["used"] == 400
