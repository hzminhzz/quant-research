"""Independent ATS-6 numerical/state-machine oracle.

Reads only SQLite command evidence and final persisted projection. It imports no
router, ATS-2 validator, ATS-3 bridge, ATS-4 calculator, ATS-5 evaluator or fixtures.
Its independently coded rule check is deliberately restricted to the synthetic
flat static-floor account sources used by this acceptance program.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def digest(x):
    return hashlib.sha256(canonical(x)).hexdigest()


def dt(x):
    return datetime.fromisoformat(x)


def fresh(at, until, now, age):
    return dt(at) <= now < dt(until) and (now - dt(at)).total_seconds() <= age


def signature_valid(g, action, authority, now):
    try:
        key = next(x for x in authority["issuers"] if x["issuer_id"] == g["issuer_id"])
        if (not key["enabled"] or g["grant_id"] in authority["revoked_grant_ids"]
                or g["allowed_effect"] != "shadow_only" or g["trading"] or g["protected_data"]
                or g["scope"]["operation"] != "shadow_route"
                or not dt(g["issued_at"]) <= now < dt(g["expires_at"])
                or (dt(g["expires_at"]) - dt(g["issued_at"])).total_seconds() > authority["max_grant_seconds"]
                or g["scope_sha256"] != digest(g["scope"])
                or g["scope"]["action_sha256"] != digest(action)):
            return False
        payload = dict(g)
        signature = payload.pop("signature_b64")
        Ed25519PublicKey.from_public_bytes(base64.b64decode(key["public_key_b64"])).verify(
            base64.b64decode(signature), canonical(payload))
        return True
    except (KeyError, StopIteration, ValueError, TypeError, InvalidSignature):
        return False


def quote(raw, account):
    return {
        leg["leg_id"]: {
            "n": leg["quantity_lots"], "size": Decimal(leg["lot_size"]),
            "side": leg["side"], "instrument": leg["instrument"],
            "loss": (leg["stress_units_per_lot"] * account["stress_multiplier_bps"] + 9999) // 10000
                    + account["cost_units_per_lot"],
            "margin": leg["margin_units_per_lot"],
        } for leg in raw["legs"]
    }


def balances(accounts, routes):
    by_account = {key: Counter(reserved=0, recognized=0, margin=0, unknown=0) for key in accounts}
    families = defaultdict(Counter)
    for key, a in accounts.items():
        for o in a["opening_obligations"]:
            by_account[key]["reserved" if o["kind"] == "unknown" else "recognized"] += o["risk_units"]
            by_account[key]["unknown"] += o["risk_units"] if o["kind"] == "unknown" else 0
            by_account[key]["margin"] += o["margin_units"]
            families[key][o["family"]] += o["risk_units"]
    positions = defaultdict(Decimal)
    for r in routes.values():
        if r["account"] is None:
            continue
        a = by_account[r["account"]]
        pending, held, margin = r["extra_loss"], 0, r["extra_margin"]
        for key, leg in r["legs"].items():
            entries = sum(e["lots"] for e in r["fills"].values() if e["leg_id"] == key and e["role"] == "open")
            exits = sum(e["lots"] for eid, e in r["fills"].items() if eid in r["closed"] and e["leg_id"] == key)
            live = max(0, entries - exits)
            left = 0 if r["terminal"] else max(0, leg["n"] - entries)
            pending += left * leg["loss"]
            held += live * leg["loss"]
            margin += (left + live) * leg["margin"]
            poskey = r["account"] + "/" + leg["instrument"]
            positions[poskey] += live * leg["size"] * (1 if leg["side"] == "buy" else -1)
        a["reserved"] += pending
        a["recognized"] += held
        a["margin"] += margin
        if r["unknown"] or (r["sent"] and not r["ack"]):
            a["unknown"] += pending
        families[r["account"]][r["raw"]["family"]] += pending + held
    total = Counter(reserved=0, recognized=0, margin=0, unknown=0, used=0)
    combined_families = Counter()
    for key, a in by_account.items():
        a["used"] = a["reserved"] + a["recognized"]
        total.update(a)
        combined_families.update(families[key])
    return by_account, total, families, combined_families, dict(positions)


def account_allowed(a, raw, policy, now, used, global_used, family_used):
    # The harness uses flat synthetic static-floor account histories. Reject a
    # richer source rather than quietly treating this oracle as a second ATS-5.
    assert all(e["kind"] == "observation" for e in a["events"]), "ORACLE_REQUIRES_FLAT_SOURCE"
    b = a["binding"]
    terms = [x for x in b["assignments"] if dt(x["at"]) <= now]
    rule = next(r for r in a["rules"] if r["version_id"] == terms[-1]["version_id"])
    assert rule["max_loss_mode"] == "static", "ORACLE_REQUIRES_STATIC_FIXTURE"
    if (rule["daily_loss_fraction"] is None or rule["max_loss_fraction"] is None):
        return None
    headroom = int(Decimal(b["initial_capital"]) * min(
        Decimal(rule["daily_loss_fraction"]), Decimal(rule["max_loss_fraction"]))
        * policy["units_per_currency"])
    cap = min(a["risk_limit_units"], headroom)
    q = quote(raw, a)
    risk = sum(x["n"] * x["loss"] for x in q.values())
    margin = sum(x["n"] * x["margin"] for x in q.values())
    coverage = any(dt(c["start"]) <= now < dt(c["end"]) and c["events_complete"]
                   for c in b["coverage"])
    allowed = (
        fresh(a["at"], a["valid_until"], now, policy["max_source_age_seconds"])
        and a["marks_complete"] and a["margin_at"] is not None and a["margin_capacity_units"] is not None
        and fresh(a["margin_at"], a["valid_until"], now, policy["max_source_age_seconds"])
        and a["lifecycle"] == "active" and a["currency"] == policy["currency"]
        and coverage and b["agreement_verified"] and rule["source"]["evidence_type"] == "account_agreement"
        and not rule["unknown_rules"]
        and all(leg["instrument"] in a["permitted_instruments"]
                and leg["instrument"].split(":")[0] == a["venue"] for leg in raw["legs"])
        and used["used"] + risk <= cap and used["margin"] + margin <= a["margin_capacity_units"]
        and global_used["used"] + risk <= policy["shared_limit_units"]
        and family_used[raw["family"]] + risk <= policy["family_limit_units"]
    )
    return (q, risk, cap) if allowed else None


def audit(path):
    con = sqlite3.connect("file:" + str(Path(path).resolve()) + "?mode=ro", uri=True)
    con.execute("BEGIN")
    rows = con.execute("SELECT * FROM journal ORDER BY seq").fetchall()
    persisted_text, persisted_hash = con.execute("SELECT body,sha256 FROM projection WHERE id=1").fetchone()
    con.close()
    persisted = json.loads(persisted_text)
    assert digest(persisted) == persisted_hash, "PERSISTED_STATE_HASH"
    accounts, routes, trace = {}, {}, []
    policy = portfolio = authority = None
    epoch, previous, last_time = 0, "0" * 64, None
    publications, used_grants = set(), set()
    halted = False
    accepted, skipped, denied = 0, 0, 0
    for index, row in enumerate(rows, 1):
        seq, raw_command, raw_result, state_hash, previous_hash, record_hash = row
        command, result = json.loads(raw_command), json.loads(raw_result)
        record = {"seq": seq, "command": command, "result": result,
                  "state_sha256": state_hash, "previous_sha256": previous_hash}
        assert seq == index and previous_hash == previous and digest(record) == record_hash, "JOURNAL_CHAIN"
        previous = record_hash
        op, d, now = command["operation"], command["data"], dt(command["at"])
        if op == "initialize":
            policy, authority, last_time = d["policy"], d["authority"], now
        elif now < last_time:
            assert result["reason"] == "STALE_WRITER_CLOCK"
            denied += 1
        elif op == "claim":
            if d["expected_epoch"] == epoch:
                epoch += 1
                assert result["epoch"] == epoch
                last_time = now
            else:
                assert result["reason"] == "STALE_OWNER_EPOCH"
        elif d["epoch"] != epoch:
            assert result["reason"] == "STALE_OWNER_FENCE"
            denied += 1
        elif op in ("account", "portfolio", "policy", "authority"):
            if result["status"] == "DENIED":
                # Mutation rejection has no economic effect; check final current
                # sources against our retained authority below.
                denied += 1
            elif op == "account":
                a = d["snapshot"]
                assert a["revision"] == accounts.get(a["account_id"], {}).get("revision", 0) + 1
                if a["account_id"] in accounts:
                    old = accounts[a["account_id"]]
                    assert old["opening_obligations"] == a["opening_obligations"]
                    assert a["events"][:len(old["events"])] == old["events"]
                accounts[a["account_id"]] = a
                for r in routes.values():
                    if r["account"] == a["account_id"]:
                        q = quote(r["raw"], a)
                        for key, leg in r["legs"].items():
                            leg["loss"] = max(leg["loss"], q[key]["loss"])
            elif op == "portfolio":
                portfolio = d["snapshot"]
            elif op == "policy":
                policy = d["policy"]
            else:
                authority = d["policy"]
            last_time = now
        elif op == "admit":
            action, grant = d["action"], d["grant"]
            raw = action["intent"]
            ident = raw["intent_id"]
            if ident in routes:
                assert result["reason"] in ("EXISTING_DECISION", "INTENT_ID_CONFLICT")
            elif not signature_valid(grant, action, authority, now):
                assert result["status"] == "DENIED", "UNAUTHORIZED_ADMISSION"
                denied += 1
            elif (action["accounts"] != {key: digest(value) for key, value in accounts.items()}
                  or action["portfolio"] != digest(portfolio) or action["policy"] != digest(policy)
                  or action["authority"] != digest(authority)):
                assert result["status"] == "DENIED", "STALE_SOURCE_ADMISSION"
                denied += 1
            else:
                assert grant["grant_id"] not in used_grants
                ac, total, fam, family_total, _ = balances(accounts, routes)
                candidates = []
                general_ok = (
                    not halted and dt(raw["created_at"]) <= now < dt(raw["valid_until"])
                    and len({leg["instrument"].split(":")[0] for leg in raw["legs"]}) == 1
                    and portfolio is not None
                    and fresh(portfolio["at"], portfolio["valid_until"], now, policy["max_source_age_seconds"])
                    and raw["sleeve"] in portfolio["sleeves"]
                )
                for key, a in accounts.items():
                    answer = account_allowed(a, raw, policy, now, ac[key], total, family_total)
                    if answer and general_ok:
                        q, risk, cap = answer
                        if policy["allocation_policy"] == "cushion":
                            rank = (a["lifecycle_priority"], -Fraction(cap - ac[key]["used"] - risk, risk),
                                    Fraction(fam[key][raw["family"]] + risk, max(1, cap)), key)
                        elif policy["allocation_policy"] == "least_used":
                            rank = (ac[key]["used"], key)
                        else:
                            rank = (key,)
                        candidates.append((rank, key, q))
                chosen = min(candidates) if candidates else None
                expected_account = chosen[1] if chosen else None
                assert result["account_id"] == expected_account, "ELIGIBILITY_OR_RANKING_MISMATCH"
                assert result["status"] == ("ADMITTED" if chosen else "SKIPPED")
                routes[ident] = {
                    "raw": raw, "account": expected_account, "legs": chosen[2] if chosen else {},
                    "fills": {}, "closed": set(), "terminal": None, "seen": {}, "sequences": {},
                    "maxseq": 0, "maxat": now, "unknown": False, "ack": False, "sent": False,
                    "published_at": None, "ack_clock": None, "execution_clocks": {},
                    "conflicts": set(), "extra_loss": 0, "extra_margin": 0, "revision": 1,
                }
                used_grants.add(grant["grant_id"])
                accepted += bool(chosen)
                skipped += not bool(chosen)
                # This assertion uses original inputs and independent balances.
                _, after, _, _, _ = balances(accounts, routes)
                if chosen:
                    assert after["used"] <= policy["shared_limit_units"], "OVESPENT_SHARED_CUSHION"
            last_time = now
        elif op == "publish":
            r = routes[d["intent_id"]]
            if result["reason"] == "SHADOW_PUBLICATION_COMMITTED":
                assert not r["sent"] and r["account"] is not None
                r["sent"], r["revision"] = True, r["revision"] + 1
                r["published_at"] = now.isoformat()
                publications.add(d["intent_id"])
            elif result["reason"] == "EXISTING_SHADOW_PUBLICATION":
                assert r["sent"]
            else:
                assert result["status"] in ("DENIED", "DISPATCH_BLOCKED")
            last_time = now
        elif op == "confirm_publication":
            assert routes[d["intent_id"]]["sent"]
            last_time = now
        elif op == "observe":
            r = routes[d["intent_id"]]
            o = d["observation"]
            # The API normalizes datetime JSON. Independent hashing uses the
            # original scalar semantics (clock objects), not producer hashes.
            same = dict(o)
            same["at"] = dt(o["at"]).isoformat()
            event_digest = digest(same)
            if o["event_id"] in r["seen"]:
                assert r["seen"][o["event_id"]] == event_digest, "ORACLE_EVENT_CONFLICT_SCOPE"
                assert result["reason"] == "DUPLICATE_OBSERVATION"
            elif result["status"] == "DENIED":
                stale_control = (o["kind"] in ("ack", "unknown", "cancel", "reject")
                                 and (o["source_sequence"] < r["maxseq"] or dt(o["at"]) < r["maxat"]))
                assert d["expected_revision"] != r["revision"] or dt(o["at"]) > now or stale_control
                if stale_control:
                    assert result["reason"] == "STALE_EXECUTION_CONTROL_EVENT"
                denied += 1
            else:
                r["seen"][o["event_id"]] = event_digest
                seqkey = str(o["source_sequence"])
                if seqkey in r["sequences"]:
                    r["conflicts"].add("sequence:" + seqkey)
                    halted = r["unknown"] = True
                r["sequences"][seqkey] = event_digest
                before_seq, before_at = r["maxseq"], r["maxat"]
                r["maxseq"] = max(r["maxseq"], o["source_sequence"])
                r["maxat"] = max(r["maxat"], dt(o["at"]))
                for e in o["executions"]:
                    eid = e["execution_id"]
                    old = r["fills"].get(eid)
                    if old is not None:
                        if old != e and eid not in r["conflicts"]:
                            r["conflicts"].add(eid)
                            halted = r["unknown"] = True
                            if e["role"] == "open":
                                leg = r["legs"][e["leg_id"]]
                                r["extra_loss"] += e["lots"] * leg["loss"]
                                r["extra_margin"] += e["lots"] * leg["margin"]
                    else:
                        if r["terminal"] and e["role"] == "open":
                            r["terminal"] = None
                            r["conflicts"].add("late:" + eid)
                            halted = r["unknown"] = True
                        r["fills"][eid] = e
                        r["execution_clocks"][eid] = {"event_at": dt(o["at"]).isoformat(),
                                                       "observed_at": now.isoformat(),
                                                       "source_event_id": o["event_id"]}
                        if not r["sent"]:
                            r["conflicts"].add("unpublished")
                            halted = r["unknown"] = True
                for key, leg in r["legs"].items():
                    opening = sum(e["lots"] for e in r["fills"].values()
                                  if e["leg_id"] == key and e["role"] == "open")
                    closing = sum(e["lots"] for e in r["fills"].values()
                                  if e["leg_id"] == key and e["role"] == "close")
                    if opening > leg["n"] or closing > opening:
                        r["conflicts"].add("overfill:" + key)
                        halted = r["unknown"] = True
                if o["kind"] == "ack":
                    if not r["ack"]:
                        r["ack_clock"] = {"event_at": dt(o["at"]).isoformat(),
                                          "observed_at": now.isoformat(), "source_event_id": o["event_id"]}
                    r["ack"] = True
                    if not r["conflicts"]:
                        r["unknown"] = False
                elif o["kind"] == "unknown":
                    r["unknown"] = True
                elif o["kind"] == "reconcile":
                    complete = (
                        o["coverage_complete"] and {e["execution_id"]: e for e in o["executions"]} == r["fills"]
                        and o["source_sequence"] >= before_seq and dt(o["at"]) >= before_at
                        and not r["conflicts"]
                    )
                    openings = {key: sum(e["lots"] for e in r["fills"].values()
                                         if e["leg_id"] == key and e["role"] == "open")
                                for key in r["legs"]}
                    if o["terminal"] == "completed":
                        complete &= all(openings[key] == leg["n"] for key, leg in r["legs"].items())
                    if o["terminal"] == "rejected":
                        complete &= not any(openings.values())
                    if complete:
                        r["closed"] = {eid for eid, e in r["fills"].items() if e["role"] == "close"}
                        r["terminal"], r["unknown"] = o["terminal"], False
                    else:
                        r["unknown"] = True
                r["revision"] += 1
            last_time = now
        else:
            raise AssertionError("UNSUPPORTED_ORACLE_OPERATION:" + op)
        ac, total, _families, family_total, positions = balances(accounts, routes)
        trace.append({"journal_seq": seq, "operation": op, "at": command["at"], **dict(total),
                      "shared_limit": policy["shared_limit_units"],
                      "remaining": policy["shared_limit_units"] - total["used"],
                      "accounts": {k: dict(v) for k, v in ac.items()},
                      "family_risk": dict(family_total)})
    assert persisted["accounts"] == accounts, "ACCOUNT_SOURCE_PROJECTION_MISMATCH"
    assert persisted["policy"] == policy and persisted["authority"] == authority
    assert set(persisted["routes"]) == set(routes), "ROUTE_CENSUS_MISMATCH"
    assert len(persisted["sink"]) == len(publications), "DUPLICATE_SHADOW_PUBLICATION"
    for ident, r in routes.items():
        actual = persisted["routes"][ident]
        assert actual["account_id"] == r["account"], "ACCOUNT_SELECTION_PROJECTION"
        assert actual["executions"] == r["fills"], "EXECUTION_PROJECTION"
        assert actual["execution_clocks"] == r["execution_clocks"], "EXECUTION_CLOCK_PROJECTION"
        assert actual["published_at"] == r["published_at"], "PUBLICATION_CLOCK_PROJECTION"
        assert actual["ack_clock"] == r["ack_clock"], "ACK_CLOCK_PROJECTION"
        assert set(actual["closed_ids"]) == r["closed"], "POSITION_REDUCTION_PROJECTION"
        assert actual["terminal"] == r["terminal"], "TERMINAL_PROJECTION"
        assert actual["disputed_risk"] == r["extra_loss"], "DISPUTED_RISK_PROJECTION"
        for key, leg in r["legs"].items():
            assert actual["legs"][key]["unit_risk"] == leg["loss"], "STRESS_PRICE_PROJECTION"
    return {
        "status": "INDEPENDENT_RECONCILIATION_PASS", "database": str(path),
        "journal_records": len(rows), "accepted": accepted, "skipped": skipped, "denied": denied,
        "accounts": {k: dict(v) for k, v in ac.items()}, "shared": dict(total),
        "remaining_risk_units": policy["shared_limit_units"] - total["used"],
        "positions_lots_scaled": {k: str(v) for k, v in positions.items() if v},
        "peak_reserved_plus_recognized": max(x["used"] for x in trace),
        "peak_unknown": max(x["unknown"] for x in trace),
        "trace": trace, "scope": "SYNTHETIC_FLAT_STATIC_ACCOUNT_INPUTS",
        "conditional_modeled_cost_units": sum(
            e["lots"] * accounts[r["account"]]["cost_units_per_lot"]
            for r in routes.values() if r["account"] is not None
            for e in r["fills"].values() if e["role"] == "open"),
        "skip_reasons": dict(Counter(
            reason for ident, r in routes.items() if r["account"] is None
            for reason in persisted["routes"][ident]["reasons"])),
        "realized_profit": None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = audit(args.database)
    except Exception as exc:  # noqa: BLE001 - preserve failed outside-judge evidence.
        result = {"status": "INDEPENDENT_RECONCILIATION_FAIL",
                  "exception": type(exc).__name__, "message": str(exc)}
    with args.output.open("x") as f:
        json.dump(result, f, sort_keys=True, indent=2)
    print(result["status"])
    return 0 if result["status"] == "INDEPENDENT_RECONCILIATION_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
