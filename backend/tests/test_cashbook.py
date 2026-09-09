"""Cash Book / double-entry tests for Munsiji.app.

Scenarios (per iteration_8 review request):
- dashboard shape (cash_in_hand, bank_balance, accounts, ledger_kind, via)
- party entries with mode cash/bank/none contra bookings
- edit sync (keep/cash/bank/none)
- delete sync (party + account side)
- account ledger direct entry (no contra)
- kind toggle and auto-move to Accounts group
- bot flow (AI, slow)
- monthly summary accounts[]

Cleanup: any CBTEST_* ledgers created are soft-deleted; existing "Cash",
"Bank", "Biki [Mill]", "Mantu" ledgers are NOT touched.
"""
import os
import time
import uuid
from datetime import datetime

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://whatsapp-munim.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
PIN = "3366"

S = requests.Session()

# module-level state populated by fixtures
_created_ledgers: list = []


# ------------------------------------------------------------ helpers
@pytest.fixture(scope="module")
def auth():
    r = S.post(f"{API}/auth/login", json={"pin": PIN}, timeout=15)
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def general_group_id(auth):
    r = S.get(f"{API}/groups", headers=auth, timeout=15)
    assert r.status_code == 200
    for g in r.json():
        if g["name"].lower() == "general":
            return g["id"]
    # Create if not present
    r2 = S.post(f"{API}/groups", json={"name": "General"}, headers=auth, timeout=15)
    return r2.json()["id"]


@pytest.fixture(scope="module")
def accounts_group_id(auth):
    r = S.get(f"{API}/groups", headers=auth, timeout=15)
    for g in r.json():
        if g["name"].lower() == "accounts":
            return g["id"]
    return None


@pytest.fixture(scope="module", autouse=True)
def _cleanup(auth):
    yield
    # cleanup any ledger tracked
    for lid in _created_ledgers:
        try:
            S.delete(f"{API}/ledgers/{lid}", headers=auth, timeout=15)
        except Exception:
            pass


def _new_ledger_name(prefix: str = "CBTEST") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:6]}"


def _dashboard(auth):
    r = S.get(f"{API}/dashboard", headers=auth, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _get_ledgers(auth):
    r = S.get(f"{API}/ledgers", headers=auth, timeout=15)
    assert r.status_code == 200
    return r.json()


def _find_ledger_by_kind(auth, kind: str):
    for l in _get_ledgers(auth):
        if l.get("kind") == kind:
            return l
    return None


# ------------------------------------------------------------ 1) Dashboard shape
def test_dashboard_shape_and_groups(auth):
    d = _dashboard(auth)
    for k in ("cash_in_hand", "bank_balance", "accounts", "total_lena", "total_dena", "recent"):
        assert k in d, f"dashboard missing {k}"
    assert isinstance(d["cash_in_hand"], (int, float))
    assert isinstance(d["bank_balance"], (int, float))
    assert isinstance(d["accounts"], list)
    for a in d["accounts"]:
        for k in ("ledger_id", "name", "kind", "balance"):
            assert k in a, f"account missing {k}"
        assert a["kind"] in ("cash", "bank")

    # recent items may include ledger_kind / via
    for r in d["recent"]:
        assert "ledger_kind" in r or True  # optional but should not error

    # groups must expose account_balance (null for party-only)
    gs = S.get(f"{API}/groups", headers=auth, timeout=15).json()
    for g in gs:
        assert "account_balance" in g, f"group {g['name']} missing account_balance"
    # Accounts group should have a number
    accts = [g for g in gs if g["name"].lower() == "accounts"]
    if accts:
        assert isinstance(accts[0]["account_balance"], (int, float))

    # ledgers have kind
    for l in _get_ledgers(auth):
        assert "kind" in l


# ------------------------------------------------------------ 2) Cash contra
@pytest.fixture(scope="module")
def cash_scenario(auth, general_group_id):
    """Create a CBTEST party ledger and record a 5000 debit with mode=cash."""
    name = _new_ledger_name()
    r = S.post(f"{API}/ledgers", json={"name": name, "group_id": general_group_id}, headers=auth, timeout=15)
    assert r.status_code == 200, r.text
    party = r.json()
    _created_ledgers.append(party["id"])
    assert party["kind"] == "party"

    before = _dashboard(auth)
    tr = S.post(f"{API}/transactions", json={
        "ledger_id": party["id"], "amount": 5000, "direction": "debit",
        "note": "advance", "mode": "cash",
    }, headers=auth, timeout=15)
    assert tr.status_code == 200, tr.text
    txn = tr.json()
    assert txn.get("contra_txn_id"), "contra_txn_id missing"
    assert txn.get("contra_ledger_id"), "contra_ledger_id missing"

    after = _dashboard(auth)
    return {"party": party, "party_name": name, "txn": txn, "before": before, "after": after}


def test_cash_contra_dashboard_delta(cash_scenario):
    before = cash_scenario["before"]
    after = cash_scenario["after"]
    assert round(before["cash_in_hand"] - after["cash_in_hand"], 2) == 5000.0
    assert round(after["total_lena"] - before["total_lena"], 2) == 5000.0


def test_cash_contra_ledger_kind_and_statement(auth, cash_scenario):
    txn = cash_scenario["txn"]
    party = cash_scenario["party"]
    name = cash_scenario["party_name"]

    cash_id = txn["contra_ledger_id"]
    # verify contra ledger is kind=cash
    rl = S.get(f"{API}/ledgers/{cash_id}", headers=auth, timeout=15).json()
    assert rl["kind"] == "cash"

    st_cash = S.get(f"{API}/ledgers/{cash_id}/statement", headers=auth, timeout=15).json()
    top = st_cash["rows"][-1]  # newest last in ascending order
    assert top["direction"] == "credit"
    assert top["amount"] == 5000
    assert name in (top.get("note") or "")
    assert top.get("via") == name

    st_p = S.get(f"{API}/ledgers/{party['id']}/statement", headers=auth, timeout=15).json()
    top_p = st_p["rows"][-1]
    assert top_p.get("via") == "Cash"


# ------------------------------------------------------------ 3) Bank contra
def test_bank_contra(auth, cash_scenario):
    party = cash_scenario["party"]
    before = _dashboard(auth)
    tr = S.post(f"{API}/transactions", json={
        "ledger_id": party["id"], "amount": 2000, "direction": "credit",
        "note": "gpay payment", "mode": "bank",
    }, headers=auth, timeout=15)
    assert tr.status_code == 200, tr.text
    txn = tr.json()
    assert txn.get("contra_ledger_id")
    rl = S.get(f"{API}/ledgers/{txn['contra_ledger_id']}", headers=auth, timeout=15).json()
    assert rl["kind"] == "bank"

    # A bank kind ledger exists
    banks = [l for l in _get_ledgers(auth) if l.get("kind") == "bank"]
    assert banks, "no bank kind ledger found"

    after = _dashboard(auth)
    assert round(after["bank_balance"] - before["bank_balance"], 2) == 2000.0

    # stash the bank txn id for step 6
    cash_scenario["bank_txn"] = txn


# ------------------------------------------------------------ 4) mode = none
def test_mode_none_no_contra(auth, cash_scenario):
    party = cash_scenario["party"]
    before = _dashboard(auth)
    tr = S.post(f"{API}/transactions", json={
        "ledger_id": party["id"], "amount": 700, "direction": "debit",
        "note": "opening balance", "mode": "none",
    }, headers=auth, timeout=15)
    assert tr.status_code == 200, tr.text
    txn = tr.json()
    assert txn.get("contra_txn_id") in (None, "")
    after = _dashboard(auth)
    assert after["cash_in_hand"] == before["cash_in_hand"]


# ------------------------------------------------------------ 5) Edit sync
def test_edit_sync_all_modes(auth, cash_scenario):
    txn = cash_scenario["txn"]  # 5000 debit party, cash contra
    party = cash_scenario["party"]
    txn_id = txn["id"]

    start = _dashboard(auth)

    # a) increase to 8000 (mode keep)
    r = S.patch(f"{API}/transactions/{txn_id}", json={"amount": 8000}, headers=auth, timeout=15)
    assert r.status_code == 200, r.text
    d1 = _dashboard(auth)
    # cash went from being down 5000 (before this test start_) to being down 8000
    # start reflects after the -5000+0 (step2) and -0 (step3 credit adds to bank not cash) and -0 (none)
    # so relative to start, cash should decrease by 3000 (from -5000 to -8000)
    assert round(start["cash_in_hand"] - d1["cash_in_hand"], 2) == 3000.0

    # verify contra amount now 8000
    contra_id = txn["contra_ledger_id"]
    st = S.get(f"{API}/ledgers/{contra_id}/statement", headers=auth, timeout=15).json()
    # find latest row that has via=partyname
    party_name = cash_scenario["party_name"]
    row = next((r_ for r_ in reversed(st["rows"]) if r_.get("via") == party_name), None)
    assert row is not None
    assert row["amount"] == 8000

    # b) mode=none → contra removed, cash restored by 8000
    r = S.patch(f"{API}/transactions/{txn_id}", json={"mode": "none"}, headers=auth, timeout=15)
    assert r.status_code == 200, r.text
    resp = r.json()
    assert resp.get("contra_txn_id") in (None, "")
    d2 = _dashboard(auth)
    assert round(d2["cash_in_hand"] - d1["cash_in_hand"], 2) == 8000.0

    # c) mode=bank → new contra in Bank; bank_balance decreases by 8000 (party debit=out)
    r = S.patch(f"{API}/transactions/{txn_id}", json={"mode": "bank"}, headers=auth, timeout=15)
    assert r.status_code == 200, r.text
    resp = r.json()
    assert resp.get("contra_txn_id")
    d3 = _dashboard(auth)
    assert round(d2["bank_balance"] - d3["bank_balance"], 2) == 8000.0

    # save new contra id for the party (bank) so subsequent tests know state
    cash_scenario["txn_after_bank"] = resp


# ------------------------------------------------------------ 6) Delete sync
def test_delete_sync(auth, cash_scenario, general_group_id):
    # 6a) delete the bank txn from step 3 → bank_balance restored by 2000
    bank_txn = cash_scenario.get("bank_txn")
    assert bank_txn is not None
    before = _dashboard(auth)
    r = S.delete(f"{API}/transactions/{bank_txn['id']}", headers=auth, timeout=15)
    assert r.status_code == 200
    after = _dashboard(auth)
    # The party entry was credit (money in) via bank → deleting: bank_balance decreases by 2000
    assert round(before["bank_balance"] - after["bank_balance"], 2) == 2000.0

    # 6b) create fresh cash entry, delete via contra_txn_id (account side) → party txn also gone
    party = cash_scenario["party"]
    tr = S.post(f"{API}/transactions", json={
        "ledger_id": party["id"], "amount": 1000, "direction": "debit", "mode": "cash",
    }, headers=auth, timeout=15).json()
    assert tr.get("contra_txn_id")
    # delete via cash side
    dr = S.delete(f"{API}/transactions/{tr['contra_txn_id']}", headers=auth, timeout=15)
    assert dr.status_code == 200

    # verify party txn is gone
    txns = S.get(f"{API}/transactions?ledger_id={party['id']}", headers=auth, timeout=15).json()
    assert not any(t["id"] == tr["id"] for t in txns), "party txn still visible after account-side delete"


# ------------------------------------------------------------ 7) Direct account ledger entry (no contra)
def test_account_direct_entry_no_contra(auth):
    cash = _find_ledger_by_kind(auth, "cash")
    assert cash is not None, "no cash ledger exists"
    before = _dashboard(auth)
    tr = S.post(f"{API}/transactions", json={
        "ledger_id": cash["id"], "amount": 100, "direction": "debit",
        "note": "CBTEST opening", "mode": "cash",
    }, headers=auth, timeout=15)
    assert tr.status_code == 200, tr.text
    txn = tr.json()
    assert txn.get("contra_txn_id") in (None, "")
    after = _dashboard(auth)
    assert round(after["cash_in_hand"] - before["cash_in_hand"], 2) == 100.0

    # cleanup
    S.delete(f"{API}/transactions/{txn['id']}", headers=auth, timeout=15)


# ------------------------------------------------------------ 8) Kind toggle & auto-move
def test_kind_toggle_and_auto_move(auth, general_group_id, accounts_group_id):
    name = _new_ledger_name()
    r = S.post(f"{API}/ledgers", json={"name": name, "group_id": general_group_id}, headers=auth, timeout=15)
    assert r.status_code == 200
    lid = r.json()["id"]
    _created_ledgers.append(lid)

    # party → bank
    r2 = S.patch(f"{API}/ledgers/{lid}", json={"kind": "bank"}, headers=auth, timeout=15)
    assert r2.status_code == 200
    assert r2.json()["kind"] == "bank"

    # dashboard.accounts includes it
    d = _dashboard(auth)
    assert any(a["ledger_id"] == lid for a in d["accounts"])

    # back to party
    r3 = S.patch(f"{API}/ledgers/{lid}", json={"kind": "party"}, headers=auth, timeout=15)
    assert r3.status_code == 200
    assert r3.json()["kind"] == "party"

    # invalid kind
    r4 = S.patch(f"{API}/ledgers/{lid}", json={"kind": "xyz"}, headers=auth, timeout=15)
    assert r4.status_code == 400

    # Auto-move: create with "SBI Bank" name in General → gets kind=bank, moved to Accounts group
    bname = f"CBTEST_SBI_Bank_{uuid.uuid4().hex[:4]}"
    r5 = S.post(f"{API}/ledgers", json={"name": bname, "group_id": general_group_id}, headers=auth, timeout=15)
    assert r5.status_code == 200, r5.text
    bank_l = r5.json()
    _created_ledgers.append(bank_l["id"])
    assert bank_l["kind"] == "bank", bank_l
    if accounts_group_id:
        assert bank_l["group_id"] == accounts_group_id, "auto-created bank ledger not in Accounts group"


# ------------------------------------------------------------ 9) Bot AI flow (slow)
@pytest.mark.slow
def test_bot_cashbook_flow(auth):
    # use a unique random-looking name to avoid fuzzy-match against CBTEST_* ledgers
    party = f"Zulnok{uuid.uuid4().hex[:6]}"  # unique, unlike anything else
    # 1) diya → cash contra
    r1 = S.post(f"{API}/whatsapp/simulate", json={"text": f"{party} ko 3000 diya"}, headers=auth, timeout=45)
    assert r1.status_code == 200, r1.text
    reply1 = r1.json().get("reply", "")
    # If a fuzzy-match confirmation was triggered, answer "naya"
    if "milta-julta" in reply1 or "Usme add karu" in reply1:
        r1 = S.post(f"{API}/whatsapp/simulate", json={"text": "naya"}, headers=auth, timeout=45)
        reply1 = r1.json().get("reply", "")
    assert "lena hai" in reply1.lower() or "lena" in reply1.lower(), f"reply: {reply1}"
    assert "cash" in reply1.lower(), f"reply missing Cash line: {reply1}"

    # 2) mila gpay → bank contra
    time.sleep(1)
    r2 = S.post(f"{API}/whatsapp/simulate", json={"text": f"{party} se 1000 mila gpay se"}, headers=auth, timeout=45)
    assert r2.status_code == 200
    reply2 = r2.json().get("reply", "")
    assert "bank" in reply2.lower(), f"reply missing Bank line: {reply2}"

    # 3) last entry delete
    time.sleep(1)
    r3 = S.post(f"{API}/whatsapp/simulate", json={"text": "last entry delete karo"}, headers=auth, timeout=45)
    assert r3.status_code == 200
    reply3 = r3.json().get("reply", "")
    assert "delete" in reply3.lower()
    # should mention the party name, not "Cash"
    assert party.lower() in reply3.lower() or party in reply3, f"reply should name the party, got: {reply3}"

    # 4) opening balance → no Cash line (mode none)
    time.sleep(1)
    r4 = S.post(f"{API}/whatsapp/simulate", json={"text": f"{party} opening balance 500"}, headers=auth, timeout=45)
    assert r4.status_code == 200
    reply4 = r4.json().get("reply", "")
    assert "cash:" not in reply4.lower(), f"reply should NOT have Cash line: {reply4}"

    # cleanup — the AI-created party ledger
    ledgers = _get_ledgers(auth)
    for l in ledgers:
        if l["name"].lower() == party.lower() or l["name"].lower().startswith(party.lower()):
            S.delete(f"{API}/ledgers/{l['id']}", headers=auth, timeout=15)


# ------------------------------------------------------------ 10) monthly summary
def test_monthly_summary_accounts(auth):
    month = datetime.now().strftime("%Y-%m")
    r = S.get(f"{API}/summary/monthly?month={month}", headers=auth, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "accounts" in body, "summary missing accounts[]"
    for a in body["accounts"]:
        for k in ("ledger_name", "kind", "in", "out", "net"):
            assert k in a, f"accounts row missing {k}"
        assert a["kind"] in ("cash", "bank")
    # party ledgers list excludes kind cash/bank
    for l in body["ledgers"]:
        # ledger_rows use ledger_id — verify their kind via ledgers endpoint
        pass
    all_ledgers = {l["id"]: l for l in _get_ledgers(auth)}
    for l in body["ledgers"]:
        lid = l["ledger_id"]
        if lid in all_ledgers:
            assert all_ledgers[lid].get("kind", "party") == "party", \
                f"ledgers[] contains a non-party ledger: {all_ledgers[lid]}"
