"""Iteration 9 tests — Cash Transfer, Tags/Categories, Bot 'naya' confirm fix.

Scenarios (per iteration_9 review request):
- POST /api/transfers bank↔cash: balance changes, contra_txn_id, from/to shape.
- Invalid transfer bodies (same kinds, xyz) → 400.
- Delete one transfer txn → both sides gone, balances restored.
- Edit transfer amount via PATCH (mode='keep') → linked side updated.
- Account ledger direct entry as transfer via POST /api/transactions (mode='bank').
- Same-kind (Cash + mode=cash) → NO contra. mode='none' → no contra.
- Tag normalization on POST/PATCH (lowercase, dedupe, # strip) — propagates to contra.
- GET /api/tags returns used + suggested (unused with count 0).
- GET /api/summary/monthly?month=... returns categories[] with correct out/count and no double count.
- Bot: 'bank se 2000 cash nikala' → Transfer reply, cash+, bank−.
- Bot: '1000 cash bank me jama kiya' → Cash → Bank.
- Bot: 'last entry delete karo' → deletes pair.
- fallback_parse cases (transfer detection).
- Bot 'naya' confirm creates a NEW ledger, and 'haan' adds to matched.

Cleanup: any TGTEST_* ledgers created are soft-deleted; existing Cash/Bank
and other production ledgers are never modified.
"""
import os
import re
import sys
import time
import uuid
from datetime import datetime

import pytest
import requests

# make backend importable for the fallback_parse unit check
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://whatsapp-munim.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
PIN = "3366"

S = requests.Session()
_created_ledgers: list = []


# ---------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def auth():
    r = S.post(f"{API}/auth/login", json={"pin": PIN}, timeout=15)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def general_group_id(auth):
    r = S.get(f"{API}/groups", headers=auth, timeout=15)
    assert r.status_code == 200
    for g in r.json():
        if g["name"].lower() == "general":
            return g["id"]
    r2 = S.post(f"{API}/groups", json={"name": "General"}, headers=auth, timeout=15)
    return r2.json()["id"]


@pytest.fixture(scope="module")
def accounts_group_id(auth):
    r = S.get(f"{API}/groups", headers=auth, timeout=15)
    for g in r.json():
        if g["name"].lower() == "accounts":
            return g["id"]
    return None


@pytest.fixture(scope="module")
def cash_and_bank(auth):
    """Return (cash_id, bank_id) from GET /api/dashboard.accounts."""
    r = S.get(f"{API}/dashboard", headers=auth, timeout=15)
    assert r.status_code == 200
    accts = r.json()["accounts"]
    ids = {a["kind"]: a["ledger_id"] for a in accts}
    assert "cash" in ids and "bank" in ids, f"Cash/Bank ledgers missing: {accts}"
    return ids["cash"], ids["bank"]


def _bal(auth):
    r = S.get(f"{API}/dashboard", headers=auth, timeout=15)
    d = r.json()
    return d["cash_in_hand"], d["bank_balance"]


def _mk_party(auth, general_group_id, prefix="TGTEST"):
    name = f"{prefix}_{uuid.uuid4().hex[:6]}"
    r = S.post(f"{API}/ledgers", json={"name": name, "group_id": general_group_id}, headers=auth, timeout=15)
    assert r.status_code in (200, 201), r.text
    lid = r.json()["id"]
    _created_ledgers.append(lid)
    return lid, name


@pytest.fixture(scope="module", autouse=True)
def cleanup(auth):
    yield
    for lid in _created_ledgers:
        try:
            S.delete(f"{API}/ledgers/{lid}", headers=auth, timeout=10)
        except Exception:
            pass


# ================================================================ 1. Transfers
class TestTransfers:
    def test_transfer_bank_to_cash(self, auth, cash_and_bank):
        cash_id, bank_id = cash_and_bank
        c0, b0 = _bal(auth)
        r = S.post(f"{API}/transfers", json={"from_kind": "bank", "to_kind": "cash", "amount": 1500, "note": "atm TGTEST"},
                   headers=auth, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "txn" in j and "from" in j and "to" in j
        txn = j["txn"]
        assert txn["ledger_id"] == cash_id
        assert txn["direction"] == "debit"
        assert txn["contra_txn_id"]
        assert txn["contra_ledger_id"] == bank_id
        assert txn["amount"] == 1500.0
        assert j["from"]["kind"] == "bank" and j["to"]["kind"] == "cash"
        c1, b1 = _bal(auth)
        assert round(c1 - c0, 2) == 1500.0, (c0, c1)
        assert round(b1 - b0, 2) == -1500.0, (b0, b1)
        # stash id on class for chain
        TestTransfers.first_txn_id = txn["id"]

    def test_transfer_cash_to_bank(self, auth, cash_and_bank):
        c0, b0 = _bal(auth)
        r = S.post(f"{API}/transfers", json={"from_kind": "cash", "to_kind": "bank", "amount": 500, "note": "deposit TGTEST"},
                   headers=auth, timeout=15)
        assert r.status_code == 200, r.text
        c1, b1 = _bal(auth)
        assert round(c1 - c0, 2) == -500.0
        assert round(b1 - b0, 2) == 500.0
        TestTransfers.second_txn_id = r.json()["txn"]["id"]

    def test_transfer_invalid_same_kind(self, auth):
        r = S.post(f"{API}/transfers", json={"from_kind": "cash", "to_kind": "cash", "amount": 100}, headers=auth, timeout=15)
        assert r.status_code == 400

    def test_transfer_invalid_kind_xyz(self, auth):
        r = S.post(f"{API}/transfers", json={"from_kind": "xyz", "to_kind": "cash", "amount": 100}, headers=auth, timeout=15)
        assert r.status_code == 400

    def test_edit_transfer_amount_syncs_pair(self, auth):
        """PATCH the cash-to-bank transfer amount; the bank-side (linked) row should mirror it."""
        txn_id = TestTransfers.second_txn_id
        c0, b0 = _bal(auth)
        r = S.patch(f"{API}/transactions/{txn_id}", json={"amount": 800}, headers=auth, timeout=15)
        assert r.status_code == 200, r.text
        # cash goes further OUT by 300 (was 500 out → now 800 out) → -300; bank up by +300
        c1, b1 = _bal(auth)
        assert round(c1 - c0, 2) == -300.0, (c0, c1)
        assert round(b1 - b0, 2) == 300.0, (b0, b1)

    def test_delete_transfer_restores_balances(self, auth):
        """Delete the first (bank→cash 1500) transfer → both sides gone; balances restored."""
        txn_id = TestTransfers.first_txn_id
        c0, b0 = _bal(auth)
        r = S.delete(f"{API}/transactions/{txn_id}", headers=auth, timeout=15)
        assert r.status_code == 200, r.text
        c1, b1 = _bal(auth)
        # bank was −1500 (from transfer 1); after delete: bank +1500, cash −1500
        assert round(c1 - c0, 2) == -1500.0
        assert round(b1 - b0, 2) == 1500.0

    def test_delete_second_transfer_for_cleanup(self, auth):
        """Also delete the 2nd (edited) transfer to keep the DB clean."""
        r = S.delete(f"{API}/transactions/{TestTransfers.second_txn_id}", headers=auth, timeout=15)
        assert r.status_code == 200


# ================================================================ 2. Account ledger entry as transfer
class TestAccountEntryAsTransfer:
    def test_cash_debit_mode_bank_books_contra(self, auth, cash_and_bank):
        cash_id, bank_id = cash_and_bank
        c0, b0 = _bal(auth)
        r = S.post(f"{API}/transactions",
                   json={"ledger_id": cash_id, "amount": 700, "direction": "debit", "mode": "bank", "note": "TGTEST transfer"},
                   headers=auth, timeout=15)
        assert r.status_code == 200, r.text
        t = r.json()
        assert t["contra_ledger_id"] == bank_id
        assert t["contra_txn_id"]
        c1, b1 = _bal(auth)
        # cash gets debit = +700 (money in), bank gets credit = -700 (money out)
        assert round(c1 - c0, 2) == 700.0
        assert round(b1 - b0, 2) == -700.0
        # Verify contra direction via GET
        r2 = S.get(f"{API}/transactions", params={"ledger_id": bank_id, "limit": 5}, headers=auth, timeout=15)
        contra = next((x for x in r2.json() if x["id"] == t["contra_txn_id"]), None)
        assert contra is not None
        assert contra["direction"] == "credit"
        assert contra["amount"] == 700.0
        TestAccountEntryAsTransfer.txn_id_1 = t["id"]

    def test_cash_debit_mode_cash_no_contra(self, auth, cash_and_bank):
        """Same-kind mode on account ledger → mode should be dropped, NO contra booked."""
        cash_id, _ = cash_and_bank
        c0, b0 = _bal(auth)
        r = S.post(f"{API}/transactions",
                   json={"ledger_id": cash_id, "amount": 100, "direction": "debit", "mode": "cash", "note": "TGTEST self"},
                   headers=auth, timeout=15)
        assert r.status_code == 200, r.text
        t = r.json()
        assert not t.get("contra_txn_id"), f"Expected no contra, got {t}"
        c1, b1 = _bal(auth)
        assert round(c1 - c0, 2) == 100.0
        assert round(b1 - b0, 2) == 0.0
        TestAccountEntryAsTransfer.txn_id_2 = t["id"]

    def test_cash_credit_mode_none_no_contra(self, auth, cash_and_bank):
        cash_id, _ = cash_and_bank
        r = S.post(f"{API}/transactions",
                   json={"ledger_id": cash_id, "amount": 50, "direction": "credit", "mode": "none", "note": "TGTEST none"},
                   headers=auth, timeout=15)
        assert r.status_code == 200, r.text
        t = r.json()
        assert not t.get("contra_txn_id")
        TestAccountEntryAsTransfer.txn_id_3 = t["id"]

    def test_cleanup(self, auth):
        for tid in [getattr(TestAccountEntryAsTransfer, f"txn_id_{i}", None) for i in (1, 2, 3)]:
            if tid:
                S.delete(f"{API}/transactions/{tid}", headers=auth, timeout=10)


# ================================================================ 3. Bot transfer flow (AI slow ~20s)
class TestBotTransfer:
    def test_bot_bank_to_cash(self, auth):
        c0, b0 = _bal(auth)
        r = S.post(f"{API}/whatsapp/simulate", json={"text": "bank se 2000 cash nikala"}, headers=auth, timeout=90)
        assert r.status_code == 200, r.text
        reply = r.json().get("reply", "")
        assert reply.startswith("Transfer:"), reply
        assert "Bank" in reply and "Cash" in reply
        assert "→" in reply
        # per-account balance lines
        assert re.search(r"Cash:\s", reply), reply
        assert re.search(r"Bank:\s", reply), reply
        c1, b1 = _bal(auth)
        assert round(c1 - c0, 2) == 2000.0
        assert round(b1 - b0, 2) == -2000.0
        TestBotTransfer.first_reply = reply

    def test_bot_cash_to_bank(self, auth):
        c0, b0 = _bal(auth)
        r = S.post(f"{API}/whatsapp/simulate", json={"text": "1000 cash bank me jama kiya"}, headers=auth, timeout=90)
        assert r.status_code == 200, r.text
        reply = r.json().get("reply", "")
        assert reply.startswith("Transfer:"), reply
        assert "Cash" in reply and "Bank" in reply
        c1, b1 = _bal(auth)
        assert round(c1 - c0, 2) == -1000.0
        assert round(b1 - b0, 2) == 1000.0

    def test_bot_delete_last_transfer(self, auth):
        """'last entry delete karo' should undo the last (cash→bank 1000) transfer pair."""
        c0, b0 = _bal(auth)
        r = S.post(f"{API}/whatsapp/simulate", json={"text": "last entry delete karo"}, headers=auth, timeout=90)
        assert r.status_code == 200, r.text
        c1, b1 = _bal(auth)
        assert round(c1 - c0, 2) == 1000.0
        assert round(b1 - b0, 2) == -1000.0
        # also undo the bank→cash 2000 transfer to leave balances untouched
        r2 = S.post(f"{API}/whatsapp/simulate", json={"text": "last entry delete karo"}, headers=auth, timeout=90)
        assert r2.status_code == 200
        c2, b2 = _bal(auth)
        # After both deletes, cash/bank should be back to the module-start values
        # We compare against c0 (post first delete). c2 vs c1 should show cash −2000, bank +2000.
        assert round(c2 - c1, 2) == -2000.0
        assert round(b2 - b1, 2) == 2000.0


# ================================================================ 4. Fallback parser check (unit)
class TestFallbackParser:
    def test_fallback_bank_to_cash(self):
        from ai_parser import fallback_parse
        p = fallback_parse("bank se 5000 cash nikala", [])
        assert p["intent"] == "transfer"
        assert p["from_account"] == "bank"
        assert p["to_account"] == "cash"
        assert p["entries"][0]["amount"] == 5000.0

    def test_fallback_cash_to_bank(self):
        from ai_parser import fallback_parse
        p = fallback_parse("10000 bank me jama kiya", [])
        assert p["intent"] == "transfer"
        assert p["from_account"] == "cash"
        assert p["to_account"] == "bank"


# ================================================================ 5. Tags — normalize, propagate, GET
class TestTags:
    def test_create_txn_with_tags_normalizes_and_propagates(self, auth, general_group_id, cash_and_bank):
        cash_id, _ = cash_and_bank
        lid, name = _mk_party(auth, general_group_id, prefix="TGTEST_tag")
        r = S.post(f"{API}/transactions",
                   json={"ledger_id": lid, "amount": 300, "direction": "debit", "mode": "cash",
                         "tags": ["Petrol", "#staff", "petrol"], "note": "TGTEST tags"},
                   headers=auth, timeout=15)
        assert r.status_code == 200, r.text
        t = r.json()
        assert t["tags"] == ["petrol", "staff"], f"expected normalized dedup, got {t['tags']}"
        assert t["contra_ledger_id"] == cash_id
        # contra row in Cash should have the same normalized tags (use /transactions for id-based fetch)
        r2 = S.get(f"{API}/transactions", params={"ledger_id": cash_id, "limit": 50}, headers=auth, timeout=15)
        contra = next((x for x in r2.json() if x["id"] == t["contra_txn_id"]), None)
        assert contra is not None, f"contra id {t['contra_txn_id']} not found in latest Cash txns"
        assert contra["tags"] == ["petrol", "staff"], contra
        TestTags.txn_id = t["id"]
        TestTags.contra_id = t["contra_txn_id"]
        TestTags.party_id = lid
        TestTags.party_name = name

    def test_patch_tags_updates_contra(self, auth, cash_and_bank):
        cash_id, _ = cash_and_bank
        r = S.patch(f"{API}/transactions/{TestTags.txn_id}", json={"tags": ["bijli"]}, headers=auth, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["tags"] == ["bijli"]
        r2 = S.get(f"{API}/transactions", params={"ledger_id": cash_id, "limit": 50}, headers=auth, timeout=15)
        contra = next((x for x in r2.json() if x["id"] == TestTags.contra_id), None)
        assert contra is not None and contra["tags"] == ["bijli"], contra

    def test_get_tags_used_and_suggested(self, auth):
        r = S.get(f"{API}/tags", headers=auth, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert isinstance(j, list)
        by_tag = {row["tag"]: row["count"] for row in j}
        assert by_tag.get("bijli", 0) >= 1, f"'bijli' missing or count 0: {by_tag}"
        # suggested tags exist even if unused; at least one of petrol/staff/rent should be present with count>=0
        assert any(t in by_tag for t in ("petrol", "staff", "rent")), by_tag

    def test_statement_rows_include_tags_field(self, auth):
        st = S.get(f"{API}/ledgers/{TestTags.party_id}/statement", headers=auth, timeout=15).json()
        rows = st.get("rows") or []
        assert isinstance(rows, list) and rows, st
        assert "tags" in rows[0]


# ================================================================ 6. Monthly summary categories
class TestSummaryCategories:
    def test_summary_has_categories_with_bijli(self, auth):
        month = datetime.utcnow().strftime("%Y-%m")
        r = S.get(f"{API}/summary/monthly", params={"month": month}, headers=auth, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "categories" in j
        cats = {c["tag"]: c for c in j["categories"]}
        # from TestTags: 300 debit tagged 'bijli' should show as out
        assert "bijli" in cats, f"bijli missing from categories: {list(cats.keys())}"
        assert cats["bijli"]["out"] >= 300.0
        # count should equal exactly 1 (the party debit) — contra is skipped
        assert cats["bijli"]["count"] == 1, f"double-counted? bijli count={cats['bijli']['count']}"
        # (no tag) bucket exists (there are lots of untagged entries this month)
        assert "(no tag)" in cats

    def test_bot_tags_petrol(self, auth, general_group_id):
        """Bot: 'TGTEST_x ko diesel ke liye 400 diya' → reply contains #petrol and entry tagged."""
        lid, name = _mk_party(auth, general_group_id, prefix="TGTEST_bp")
        # use a fresh unique party name so AI/fuzzy finds it
        r = S.post(f"{API}/whatsapp/simulate", json={"text": f"{name} ko diesel ke liye 400 diya"}, headers=auth, timeout=90)
        assert r.status_code == 200, r.text
        reply = r.json().get("reply", "")
        # Either AI tagged with 'petrol' or the fallback keyword did. Both surface as '#petrol' in reply.
        assert "#petrol" in reply, f"reply missing #petrol: {reply}"
        # verify the txn actually got the tag
        st = S.get(f"{API}/ledgers/{lid}/statement", headers=auth, timeout=15).json()
        rows = st.get("rows") or []
        assert rows and "petrol" in (rows[0].get("tags") or []), rows[:1]


# ================================================================ 7. Bot confirm-match 'naya' fix
class TestBotConfirmMatch:
    def test_naya_creates_new_ledger(self, auth, general_group_id):
        # Seed a base ledger with a name that will fuzz-score in the confirm range (60..88) against typo
        suffix = uuid.uuid4().hex[:4]
        name = f"TGTEST_Karnitrix_{suffix}"
        r = S.post(f"{API}/ledgers", json={"name": name, "group_id": general_group_id}, headers=auth, timeout=15)
        assert r.status_code in (200, 201)
        base_id = r.json()["id"]
        _created_ledgers.append(base_id)
        typo = f"TGTEST_Xrgnifox_{suffix}"  # dissimilar prefix; scores in confirm range for Karnitrix
        r1 = S.post(f"{API}/whatsapp/simulate", json={"text": f"{typo} ko 100 diya"}, headers=auth, timeout=90)
        assert r1.status_code == 200
        q = r1.json().get("reply", "")
        if not ("Usme add" in q or "milta-julta" in q):
            pytest.skip(f"AI/fuzzy directly matched — could not reproduce confirm path. reply={q!r}")
        # 'naya' → must create NEW ledger and NOT complain about no pending
        r2 = S.post(f"{API}/whatsapp/simulate", json={"text": "naya"}, headers=auth, timeout=90)
        assert r2.status_code == 200
        reply = r2.json().get("reply", "")
        assert "Naya ledger bana" in reply, f"expected new-ledger creation, got: {reply}"
        assert "Abhi koi sawaal pending nahi hai" not in reply
        r3 = S.get(f"{API}/ledgers", headers=auth, timeout=15)
        for l in r3.json():
            if l["name"].lower() == typo.lower() and l["id"] != base_id:
                _created_ledgers.append(l["id"])
                break
        TestBotConfirmMatch.base_id = base_id
        TestBotConfirmMatch.base_name = name
        TestBotConfirmMatch.suffix = suffix

    def test_haan_adds_to_matched(self, auth, general_group_id):
        # Fresh isolated base to avoid AI/fuzzy picking up the 'naya'-created twin from prior test
        suffix = uuid.uuid4().hex[:4]
        name = f"TGTEST_Voltrigo_{suffix}"
        r = S.post(f"{API}/ledgers", json={"name": name, "group_id": general_group_id}, headers=auth, timeout=15)
        assert r.status_code in (200, 201)
        base_id = r.json()["id"]
        _created_ledgers.append(base_id)
        typo = f"TGTEST_Xrltriko_{suffix}"
        r1 = S.post(f"{API}/whatsapp/simulate", json={"text": f"{typo} ko 50 diya"}, headers=auth, timeout=90)
        assert r1.status_code == 200
        q = r1.json().get("reply", "")
        if not ("Usme add" in q or "milta-julta" in q):
            pytest.skip(f"Could not reproduce fuzzy confirm — reply={q!r}")
        r2 = S.post(f"{API}/whatsapp/simulate", json={"text": "haan"}, headers=auth, timeout=90)
        assert r2.status_code == 200
        reply = r2.json().get("reply", "")
        assert name in reply or "diya" in reply, reply
        # Verify the entry landed on the base ledger, not a new one
        r3 = S.get(f"{API}/ledgers/{base_id}/statement", headers=auth, timeout=15).json()
        rows = r3.get("rows") or []
        assert rows, "expected at least one entry on base ledger after 'haan'"
        assert rows[0]["amount"] == 50.0
