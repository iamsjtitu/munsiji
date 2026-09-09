"""Munsiji.app backend API tests.

Covers auth, groups, ledgers, transactions, statement/export, dashboard/summary,
settings, whatsapp simulate/webhook. AI-powered simulate calls may take up to 15s.
"""
import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://whatsapp-munim.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
PIN = "3366"
OWNER = "917205930002"

SESSION = requests.Session()


# ---------------------------------------------------- fixtures & helpers
@pytest.fixture(scope="session")
def token():
    r = SESSION.post(f"{API}/auth/login", json={"pin": PIN}, timeout=15)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text}"
    tok = r.json().get("access_token")
    assert tok
    return tok


@pytest.fixture(scope="session")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def groups(auth):
    r = SESSION.get(f"{API}/groups", headers=auth, timeout=15)
    assert r.status_code == 200
    return r.json()


# ---------------------------------------------------- health & auth
def test_health():
    r = SESSION.get(f"{API}/health", timeout=10)
    assert r.status_code == 200 and r.json().get("ok") is True


def test_login_success():
    r = SESSION.post(f"{API}/auth/login", json={"pin": PIN}, timeout=15)
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_login_wrong_pin():
    r = SESSION.post(f"{API}/auth/login", json={"pin": "9999"}, timeout=15)
    assert r.status_code == 401


def test_protected_without_token():
    r = SESSION.get(f"{API}/groups", timeout=15)
    assert r.status_code in (401, 403)


def test_auth_me(auth):
    r = SESSION.get(f"{API}/auth/me", headers=auth, timeout=15)
    assert r.status_code == 200
    assert r.json().get("role") == "owner"


# ---------------------------------------------------- groups
def test_default_groups_present(groups):
    names = {g["name"].lower() for g in groups}
    # Expect 5 default groups: Investment, Staff, Expenses, Sales, Purchases (or similar)
    assert len(groups) >= 5, f"Expected >= 5 default groups, got {len(groups)}: {names}"


def test_group_create_rename_delete(auth):
    name = f"TEST_grp_{uuid.uuid4().hex[:6]}"
    r = SESSION.post(f"{API}/groups", json={"name": name}, headers=auth, timeout=15)
    assert r.status_code == 200, r.text
    gid = r.json()["id"]

    r2 = SESSION.patch(f"{API}/groups/{gid}", json={"name": name + "_r"}, headers=auth, timeout=15)
    assert r2.status_code == 200 and r2.json()["name"].endswith("_r")

    r3 = SESSION.delete(f"{API}/groups/{gid}", headers=auth, timeout=15)
    assert r3.status_code == 200


# ---------------------------------------------------- ledgers
@pytest.fixture(scope="session")
def test_group(auth):
    name = f"TEST_grp_{uuid.uuid4().hex[:6]}"
    r = SESSION.post(f"{API}/groups", json={"name": name}, headers=auth, timeout=15)
    assert r.status_code == 200
    gid = r.json()["id"]
    yield gid
    # cleanup: delete ledgers then group
    r2 = SESSION.get(f"{API}/ledgers?group_id={gid}", headers=auth, timeout=15)
    if r2.ok:
        for l in r2.json():
            SESSION.delete(f"{API}/ledgers/{l['id']}", headers=auth, timeout=15)
    SESSION.delete(f"{API}/groups/{gid}", headers=auth, timeout=15)


def test_create_and_list_ledger(auth, test_group):
    payload = {"name": f"TEST_ledger_{uuid.uuid4().hex[:6]}", "group_id": test_group, "aliases": ["tst"]}
    r = SESSION.post(f"{API}/ledgers", json=payload, headers=auth, timeout=15)
    assert r.status_code == 200, r.text
    lid = r.json()["id"]

    r2 = SESSION.get(f"{API}/ledgers?group_id={test_group}", headers=auth, timeout=15)
    assert r2.status_code == 200
    assert any(l["id"] == lid for l in r2.json())


def test_ledger_patch_rename(auth, test_group):
    r = SESSION.post(f"{API}/ledgers", json={"name": f"TEST_l_{uuid.uuid4().hex[:6]}", "group_id": test_group}, headers=auth)
    lid = r.json()["id"]
    new_name = f"TEST_renamed_{uuid.uuid4().hex[:6]}"
    r2 = SESSION.patch(f"{API}/ledgers/{lid}", json={"name": new_name}, headers=auth, timeout=15)
    assert r2.status_code == 200 and r2.json()["name"] == new_name


# ---------------------------------------------------- transactions & statement
def test_txn_crud_and_balance(auth, test_group):
    r = SESSION.post(f"{API}/ledgers", json={"name": f"TEST_txn_{uuid.uuid4().hex[:6]}", "group_id": test_group}, headers=auth)
    lid = r.json()["id"]

    # create debit 1000
    r1 = SESSION.post(f"{API}/transactions", json={"ledger_id": lid, "amount": 1000, "direction": "debit", "note": "TEST d"}, headers=auth, timeout=15)
    assert r1.status_code == 200, r1.text
    tid = r1.json()["id"]

    # verify statement
    st = SESSION.get(f"{API}/ledgers/{lid}/statement", headers=auth, timeout=15).json()
    assert st["closing_balance"] == 1000, st

    # patch amount → 1500
    r2 = SESSION.patch(f"{API}/transactions/{tid}", json={"amount": 1500}, headers=auth, timeout=15)
    assert r2.status_code == 200
    st2 = SESSION.get(f"{API}/ledgers/{lid}/statement", headers=auth, timeout=15).json()
    assert st2["closing_balance"] == 1500

    # add credit 400 → net 1100
    SESSION.post(f"{API}/transactions", json={"ledger_id": lid, "amount": 400, "direction": "credit"}, headers=auth, timeout=15)
    st3 = SESSION.get(f"{API}/ledgers/{lid}/statement", headers=auth, timeout=15).json()
    assert st3["closing_balance"] == 1100, st3

    # delete first txn → balance -400
    SESSION.delete(f"{API}/transactions/{tid}", headers=auth, timeout=15)
    st4 = SESSION.get(f"{API}/ledgers/{lid}/statement", headers=auth, timeout=15).json()
    assert st4["closing_balance"] == -400, st4


def test_statement_has_running_balance(auth, test_group):
    r = SESSION.post(f"{API}/ledgers", json={"name": f"TEST_stmt_{uuid.uuid4().hex[:6]}", "group_id": test_group}, headers=auth)
    lid = r.json()["id"]
    SESSION.post(f"{API}/transactions", json={"ledger_id": lid, "amount": 500, "direction": "debit"}, headers=auth)
    SESSION.post(f"{API}/transactions", json={"ledger_id": lid, "amount": 200, "direction": "credit"}, headers=auth)
    st = SESSION.get(f"{API}/ledgers/{lid}/statement", headers=auth, timeout=15).json()
    assert "rows" in st and len(st["rows"]) >= 2
    for row in st["rows"]:
        assert "running_balance" in row
    assert "opening_balance" in st and "closing_balance" in st


# ---------------------------------------------------- ledger merge
def test_ledger_merge(auth, test_group):
    r1 = SESSION.post(f"{API}/ledgers", json={"name": f"TEST_src_{uuid.uuid4().hex[:6]}", "group_id": test_group}, headers=auth).json()
    r2 = SESSION.post(f"{API}/ledgers", json={"name": f"TEST_dst_{uuid.uuid4().hex[:6]}", "group_id": test_group}, headers=auth).json()
    SESSION.post(f"{API}/transactions", json={"ledger_id": r1["id"], "amount": 300, "direction": "debit"}, headers=auth)
    m = SESSION.post(f"{API}/ledgers/{r1['id']}/merge", json={"target_ledger_id": r2["id"]}, headers=auth, timeout=15)
    assert m.status_code == 200, m.text
    # Target should now have the merged balance
    st = SESSION.get(f"{API}/ledgers/{r2['id']}/statement", headers=auth, timeout=15).json()
    assert st["closing_balance"] == 300


# ---------------------------------------------------- export & file
@pytest.mark.parametrize("fmt", ["pdf", "excel", "csv"])
def test_export_and_file_serve(auth, test_group, fmt):
    r = SESSION.post(f"{API}/ledgers", json={"name": f"TEST_exp_{fmt}_{uuid.uuid4().hex[:6]}", "group_id": test_group}, headers=auth).json()
    SESSION.post(f"{API}/transactions", json={"ledger_id": r["id"], "amount": 100, "direction": "debit"}, headers=auth)
    ex = SESSION.post(f"{API}/ledgers/{r['id']}/export", json={"format": fmt, "send_whatsapp": True}, headers=auth, timeout=30)
    assert ex.status_code == 200, ex.text
    info = ex.json()
    assert info.get("url") and info.get("filename")
    assert info.get("sent") is True  # mock provider sends

    # File is served publicly
    fr = SESSION.get(info["url"], timeout=15)
    assert fr.status_code == 200
    assert len(fr.content) > 0


# ---------------------------------------------------- dashboard & summary
def test_dashboard(auth):
    r = SESSION.get(f"{API}/dashboard", headers=auth, timeout=15)
    assert r.status_code == 200
    d = r.json()
    for k in ("total_lena", "total_dena", "ledger_count", "recent"):
        assert k in d


def test_monthly_summary(auth):
    from datetime import datetime
    month = datetime.now().strftime("%Y-%m")
    r = SESSION.get(f"{API}/summary/monthly?month={month}", headers=auth, timeout=15)
    assert r.status_code == 200
    for k in ("month", "total_debit", "total_credit", "groups", "ledgers"):
        assert k in r.json()


# ---------------------------------------------------- settings
def test_get_and_put_settings(auth):
    r = SESSION.get(f"{API}/settings", headers=auth, timeout=15)
    assert r.status_code == 200
    orig = r.json()
    assert "owner_number" in orig and "provider" in orig and "webhook_url" in orig

    # No-op PUT (keep provider)
    r2 = SESSION.put(f"{API}/settings", json={"provider": orig["provider"]}, headers=auth, timeout=15)
    assert r2.status_code == 200


def test_change_pin_same_value(auth):
    # Change PIN to same 3366 — should be accepted. NOTE: this revokes all existing JWTs
    # (backend uses pin_changed_at). We re-login and update the shared auth dict so downstream
    # tests keep working when this file is run standalone.
    r = SESSION.put(f"{API}/settings/pin", json={"old_pin": PIN, "new_pin": PIN}, headers=auth, timeout=15)
    assert r.status_code == 200
    # refresh token in-place
    time.sleep(1.1)  # ensure new iat > pin_changed_at
    r2 = SESSION.post(f"{API}/auth/login", json={"pin": PIN}, timeout=15)
    assert r2.status_code == 200
    auth["Authorization"] = f"Bearer {r2.json()['access_token']}"


# ---------------------------------------------------- whatsapp simulate (AI, slow)
@pytest.fixture(scope="session")
def unique_party():
    return f"TESTPARTY_{uuid.uuid4().hex[:6]}"


def _sim(auth, text):
    return SESSION.post(f"{API}/whatsapp/simulate", json={"text": text}, headers=auth, timeout=45)


def test_simulate_flow_ai(auth, unique_party):
    # 1. new ledger creation
    r = _sim(auth, f"{unique_party} - 12000, Expenses account")
    assert r.status_code == 200, r.text
    body = r.json()
    reply = body.get("reply", "")
    assert "Naya ledger" in reply or "naya ledger" in reply.lower(), f"reply: {reply}"

    # 2. fuzzy match: add 3000 → balance 15000
    time.sleep(1)
    r2 = _sim(auth, f"3000 - {unique_party.lower()}")
    assert r2.status_code == 200
    assert "15000" in r2.json().get("reply", "").replace(",", "") or "15,000" in r2.json().get("reply", "")

    # 3. received 5000 → balance 10000
    time.sleep(1)
    r3 = _sim(auth, f"received 5000 - {unique_party}")
    assert r3.status_code == 200
    reply3 = r3.json().get("reply", "").replace(",", "")
    assert "10000" in reply3, f"reply3: {reply3}"

    # 4. ledger bhej → clarify (PDF/Excel)
    time.sleep(1)
    r4 = _sim(auth, f"{unique_party} ka ledger bhej")
    assert r4.status_code == 200
    b4 = r4.json()
    reply4 = b4.get("reply", "").lower()
    assert ("pdf" in reply4 and "excel" in reply4) or b4.get("status") == "clarify", f"reply4: {reply4}"

    # 5. answer 'pdf'
    time.sleep(1)
    r5 = _sim(auth, "pdf")
    assert r5.status_code == 200
    b5 = r5.json()
    assert "PDF" in b5.get("reply", "") or "pdf" in b5.get("reply", "").lower()
    assert isinstance(b5.get("files"), list) and len(b5["files"]) >= 1
    assert b5["files"][0].get("url")


def test_simulate_last_entry_delete(auth, unique_party):
    # Add one more debit then delete last
    time.sleep(1)
    _sim(auth, f"200 - {unique_party}")
    time.sleep(1)
    r = _sim(auth, "last entry delete karo")
    assert r.status_code == 200
    # any reply text acceptable but should not error
    assert r.json().get("reply")


# ---------------------------------------------------- webhook (secret token) & dedupe/whitelist
def _webhook_url(auth):
    r = SESSION.get(f"{API}/settings", headers=auth, timeout=15)
    assert r.status_code == 200
    return r.json()["webhook_url"]


def test_webhook_requires_token():
    payload = {"from": OWNER, "text": "hello", "id": f"nt-{uuid.uuid4().hex[:6]}"}
    assert SESSION.post(f"{API}/whatsapp/webhook", json=payload, timeout=30).status_code == 401
    assert SESSION.post(f"{API}/whatsapp/webhook?token=wrong", json=payload, timeout=30).status_code == 401


def test_webhook_process_and_dedupe(auth):
    url = _webhook_url(auth)
    mid = f"testmsg-{uuid.uuid4().hex[:8]}"
    payload = {"from": OWNER, "text": "hello munim", "id": mid}
    r1 = SESSION.post(url, json=payload, timeout=45)
    assert r1.status_code == 200
    assert r1.json().get("status") is not None

    # send same id again → duplicate
    r2 = SESSION.post(url, json=payload, timeout=30)
    assert r2.status_code == 200
    assert r2.json().get("status") == "duplicate", r2.json()


def test_webhook_non_whitelisted_ignored(auth):
    url = _webhook_url(auth)
    payload = {"from": "919999999999", "text": "hi", "id": f"nw-{uuid.uuid4().hex[:6]}"}
    r = SESSION.post(url, json=payload, timeout=30)
    assert r.status_code == 200
    assert r.json().get("status") == "ignored", r.json()


# ---------------------------------------------------- wa messages & status
def test_wa_messages_and_status(auth):
    r = SESSION.get(f"{API}/whatsapp/messages", headers=auth, timeout=15)
    assert r.status_code == 200 and isinstance(r.json(), list)
    r2 = SESSION.get(f"{API}/whatsapp/status", headers=auth, timeout=15)
    assert r2.status_code == 200
    for k in ("provider", "configured", "owner_number", "webhook_url"):
        assert k in r2.json()
