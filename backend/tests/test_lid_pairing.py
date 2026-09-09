"""Iteration 7 — WhatsApp LID (privacy id) pairing flow.

The wa.9x webhook may deliver the sender as a 14-16 digit WhatsApp LID
(e.g. "136962279219400") instead of the owner's phone number
(917205930002). This suite verifies:

  1) Pre-pairing:  LID sender → ignored (not owner) + webhook-log detail mentions LID
  2) Pairing code generation exposes a 6-digit code + is reflected in /status
  3) Wrong code from LID → ignored, owner_ids untouched
  4) Right code (embedded in text) from LID → paired, owner_ids saved, pairing_code cleared
  5) After pairing: LID msg is accepted; canonical stored sender is owner phone
  6) Reused code / random non-owner phone still ignored after pairing consumed
  7) DELETE /owner-ids/<id> unpairs LID; GET /settings hides pairing_code/expires
  8) Alt phone-number field (from_pn) recognised as owner even without owner_ids
  9) /whatsapp/check-connection with mock provider → 400

The provider stays `mock` at the end and owner_ids is emptied so downstream tests are unaffected.
"""
import os
import time
import uuid
from urllib.parse import urlparse, parse_qs

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://whatsapp-munim.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
PIN = "3366"
OWNER_PHONE = "917205930002"
LID = "136962279219400"

S = requests.Session()


# ---------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def auth():
    r = S.post(f"{API}/auth/login", json={"pin": PIN}, timeout=15)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def webhook_url(auth):
    r = S.get(f"{API}/settings", headers=auth, timeout=15)
    assert r.status_code == 200
    return r.json()["webhook_url"]


@pytest.fixture(scope="module", autouse=True)
def _cleanup(auth):
    """Ensure owner_ids is empty before AND after the whole module runs."""
    # Before: clear any leftover LID pairings and pairing code
    S.delete(f"{API}/whatsapp/owner-ids/{LID}", headers=auth, timeout=15)
    yield
    # After: cleanup
    r = S.get(f"{API}/whatsapp/status", headers=auth, timeout=15)
    for sid in (r.json().get("owner_ids") or []):
        S.delete(f"{API}/whatsapp/owner-ids/{sid}", headers=auth, timeout=15)


def _wh_payload(text, sender=LID, mid=None, **extra):
    p = {
        "event": "message.received",
        "session_id": str(uuid.uuid4()),
        "from": sender,
        "text": text,
        "type": "text",
        "message_id": mid or f"lid-{uuid.uuid4().hex[:10]}",
        "timestamp": int(time.time() * 1000),
        "has_media": False,
    }
    p.update(extra)
    return p


def _top_log(auth):
    r = S.get(f"{API}/whatsapp/webhook-log?limit=3", headers=auth, timeout=15)
    assert r.status_code == 200
    docs = r.json()
    assert docs, "webhook-log empty"
    return docs[0]


# ---------------------------------------------------- 1) LID pre-pairing
def test_1_lid_before_pairing_ignored(auth, webhook_url):
    r = S.post(webhook_url, json=_wh_payload("Hi"), timeout=10)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("status") == "ignored", j
    assert (j.get("reason") or "").lower().startswith("not"), j
    top = _top_log(auth)
    assert top["outcome"] == "not_owner", top
    assert "LID" in (top.get("detail") or ""), top


# ---------------------------------------------------- 2) generate pairing code
@pytest.fixture(scope="module")
def pairing_code(auth):
    r = S.post(f"{API}/whatsapp/pairing-code", headers=auth, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    code = j.get("code") or ""
    assert code.isdigit() and len(code) == 6, j
    assert j.get("expires_at"), j
    return code


def test_2_status_reflects_pairing_code(auth, pairing_code):
    r = S.get(f"{API}/whatsapp/status", headers=auth, timeout=15)
    assert r.status_code == 200
    j = r.json()
    for k in ("pairing_code", "pairing_expires_at", "owner_ids"):
        assert k in j, f"missing {k}: {j}"
    assert j["pairing_code"] == pairing_code
    assert j["owner_ids"] == []


# ---------------------------------------------------- 3) wrong code
def test_3_wrong_code_from_lid_ignored(auth, webhook_url, pairing_code):
    # ensure the "wrong" code differs from the real one
    wrong = "000000" if pairing_code != "000000" else "111111"
    r = S.post(webhook_url, json=_wh_payload(wrong), timeout=10)
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "ignored", r.json()
    st = S.get(f"{API}/whatsapp/status", headers=auth, timeout=15).json()
    assert st.get("owner_ids") == [], st


# ---------------------------------------------------- 4) right code from LID
def test_4_right_code_pairs_lid(auth, webhook_url, pairing_code):
    r = S.post(webhook_url, json=_wh_payload(f"Code: {pairing_code}"), timeout=10)
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "paired", r.json()
    st = S.get(f"{API}/whatsapp/status", headers=auth, timeout=15).json()
    assert LID in (st.get("owner_ids") or []), st
    assert st.get("pairing_code") in (None, ""), st
    top = _top_log(auth)
    assert top["outcome"] == "paired", top


# ---------------------------------------------------- 5) LID msg after pairing → canonical owner
def test_5_lid_msg_after_pairing_accepted_and_canonical(auth, webhook_url):
    mid = f"aft-{uuid.uuid4().hex[:10]}"
    r = S.post(webhook_url, json=_wh_payload("biki mill ka balance", mid=mid), timeout=10)
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "accepted", r.json()

    # Poll webhook-log for background outcome
    outcome = None
    for _ in range(15):
        time.sleep(1.5)
        docs = S.get(f"{API}/whatsapp/webhook-log?limit=20", headers=auth, timeout=15).json()
        m = next((d for d in docs if mid[-8:] in (d.get("raw") or "")), None)
        if m and m["outcome"] != "accepted":
            outcome = m["outcome"]
            break
    assert outcome in ("processed", "clarify", "error", "send_failed"), f"stuck: {outcome}"

    # newest wa_message should carry canonical owner phone (NOT the LID)
    msgs = S.get(f"{API}/whatsapp/messages?limit=5", headers=auth, timeout=15).json()
    assert msgs, "no wa messages persisted"
    latest = msgs[-1]  # endpoint returns oldest-first (reversed)
    assert latest.get("sender") == OWNER_PHONE, latest


# ---------------------------------------------------- 6) reused code / random phone still ignored
def test_6_reused_code_and_other_phone_ignored(auth, webhook_url, pairing_code):
    # a) same code re-sent from same LID → now ignored because owner_ids already has LID
    #    and pairing_code has been cleared; but LID is now owner, so it becomes accepted.
    #    The spec says: reusing pairing code after consumption → 'ignored' (code cleared).
    #    Simulate with a *different* not-owner LID to verify the code is gone.
    other_lid = "146962279219400"
    r = S.post(webhook_url, json=_wh_payload(f"Code: {pairing_code}", sender=other_lid), timeout=10)
    assert r.status_code == 200
    assert r.json().get("status") == "ignored", r.json()

    # b) Normal non-owner phone still ignored
    r2 = S.post(webhook_url, json=_wh_payload("hi", sender="919999999999"), timeout=10)
    assert r2.status_code == 200
    assert r2.json().get("status") == "ignored", r2.json()


# ---------------------------------------------------- 7) delete owner-id + settings shape
def test_7_delete_owner_id_and_settings_hides_pairing(auth, webhook_url):
    r = S.delete(f"{API}/whatsapp/owner-ids/{LID}", headers=auth, timeout=15)
    assert r.status_code == 200, r.text
    assert LID not in (r.json().get("owner_ids") or [])

    # LID once again 'ignored'
    r2 = S.post(webhook_url, json=_wh_payload("hello again"), timeout=10)
    assert r2.status_code == 200
    assert r2.json().get("status") == "ignored", r2.json()

    # GET /settings must NOT contain pairing_code / pairing_expires_at
    s = S.get(f"{API}/settings", headers=auth, timeout=15).json()
    assert "pairing_code" not in s, s
    assert "pairing_expires_at" not in s, s


# ---------------------------------------------------- 8) alt phone field recognised
def test_8_alt_phone_field_recognised(auth, webhook_url):
    # owner_ids empty at this point; sender is LID but from_pn is owner phone
    mid = f"altpn-{uuid.uuid4().hex[:10]}"
    payload = _wh_payload("hello", mid=mid, from_pn=OWNER_PHONE)
    r = S.post(webhook_url, json=payload, timeout=10)
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "accepted", r.json()


# ---------------------------------------------------- 9) check-connection with mock
def test_9_check_connection_mock_400(auth):
    S.put(f"{API}/settings", json={"provider": "mock"}, headers=auth, timeout=15)
    r = S.post(f"{API}/whatsapp/check-connection", headers=auth, timeout=15)
    assert r.status_code == 400, r.text
