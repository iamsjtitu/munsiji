"""Munsiji.app security hardening tests (iteration 4).

Covers:
- Webhook auth (query token / header token / rotate)
- Export tokens (long random, expiry via ObjectId-style rejection)
- Login lockout (persistent, per IP+global, 60s window)
- PIN change → token revocation + common-PIN reject
- Settings masking (no wa9x_api_key, has_*/_hint)
- Security headers + CORS (allow_credentials false)
- Regex escaping in group create
- PIN validation regex (4-8 digits)

NOTE: run ISOLATED — the lockout test sleeps 62s.
Final state restored to PIN=3366.
"""
import os
import re
import time
import uuid

import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://whatsapp-munim.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"
PIN = "3366"
OWNER = "917205930002"

S = requests.Session()


def _login(pin=PIN):
    r = S.post(f"{API}/auth/login", json={"pin": pin}, timeout=15)
    return r


def _auth_headers():
    r = _login()
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------------------------------------------------- 1. Settings masking + get webhook_url
def test_settings_masks_secrets():
    h = _auth_headers()
    r = S.get(f"{API}/settings", headers=h, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert "wa9x_api_key" not in data, f"raw wa9x_api_key exposed: {list(data.keys())}"
    assert "webhook_secret" not in data, "raw webhook_secret exposed"
    assert "has_wa9x_api_key" in data
    assert "wa9x_api_key_hint" in data
    assert "webhook_url" in data and "token=" in data["webhook_url"], data.get("webhook_url")


def test_settings_wa9x_key_write_only():
    h = _auth_headers()
    # set a value
    r = S.put(f"{API}/settings", json={"wa9x_api_key": "testkey1234"}, headers=h, timeout=15)
    assert r.status_code == 200, r.text
    g = S.get(f"{API}/settings", headers=h).json()
    assert g["has_wa9x_api_key"] is True
    assert g["wa9x_api_key_hint"].endswith("1234")
    # empty string keeps existing
    S.put(f"{API}/settings", json={"wa9x_api_key": ""}, headers=h)
    g2 = S.get(f"{API}/settings", headers=h).json()
    assert g2["has_wa9x_api_key"] is True
    # dash clears
    S.put(f"{API}/settings", json={"wa9x_api_key": "-"}, headers=h)
    g3 = S.get(f"{API}/settings", headers=h).json()
    assert g3["has_wa9x_api_key"] is False


# ---------------------------------------------------- 2. Webhook auth
def test_webhook_requires_token():
    payload = {"from": OWNER, "text": "hi", "id": f"sec-a-{uuid.uuid4().hex[:6]}"}

    # no token
    r = S.post(f"{API}/whatsapp/webhook", json=payload, timeout=15)
    assert r.status_code == 401, f"no-token expected 401 got {r.status_code}: {r.text}"

    # wrong token
    r2 = S.post(f"{API}/whatsapp/webhook?token=WRONG", json=payload, timeout=15)
    assert r2.status_code == 401

    # correct token from settings
    h = _auth_headers()
    wu = S.get(f"{API}/settings", headers=h).json()["webhook_url"]
    m = re.search(r"[?&]token=([^&]+)", wu)
    assert m, f"token missing in webhook_url: {wu}"
    tok = m.group(1)

    r3 = S.post(f"{API}/whatsapp/webhook?token={tok}",
                json={"from": OWNER, "text": "hi", "id": f"sec-b-{uuid.uuid4().hex[:6]}"},
                timeout=45)
    assert r3.status_code == 200, r3.text
    status = r3.json().get("status")
    assert status is not None

    # header variant
    r4 = S.post(f"{API}/whatsapp/webhook",
                headers={"X-Webhook-Token": tok},
                json={"from": OWNER, "text": "hi", "id": f"sec-c-{uuid.uuid4().hex[:6]}"},
                timeout=45)
    assert r4.status_code == 200, r4.text

    # GET verify (challenge)
    r5 = S.get(f"{API}/whatsapp/webhook?token={tok}&challenge=abc123", timeout=15)
    assert r5.status_code == 200
    assert r5.text.strip('"') == "abc123", r5.text

    # GET without token → 401
    r6 = S.get(f"{API}/whatsapp/webhook?challenge=abc123", timeout=15)
    assert r6.status_code == 401


def test_webhook_rotate():
    h = _auth_headers()
    old_url = S.get(f"{API}/settings", headers=h).json()["webhook_url"]
    old_tok = re.search(r"token=([^&]+)", old_url).group(1)

    rr = S.post(f"{API}/settings/rotate-webhook-secret", headers=h, timeout=15)
    assert rr.status_code == 200
    new_url = S.get(f"{API}/settings", headers=h).json()["webhook_url"]
    new_tok = re.search(r"token=([^&]+)", new_url).group(1)
    assert new_tok != old_tok

    # old token should now 401
    r = S.post(f"{API}/whatsapp/webhook?token={old_tok}",
               json={"from": OWNER, "text": "hi", "id": f"rot-old-{uuid.uuid4().hex[:6]}"},
               timeout=15)
    assert r.status_code == 401

    # new token 200
    r2 = S.post(f"{API}/whatsapp/webhook?token={new_tok}",
                json={"from": OWNER, "text": "hi", "id": f"rot-new-{uuid.uuid4().hex[:6]}"},
                timeout=45)
    assert r2.status_code == 200


# ---------------------------------------------------- 3. Export tokens
def test_export_file_random_token():
    h = _auth_headers()
    groups = S.get(f"{API}/groups", headers=h).json()
    gid = groups[0]["id"]
    # create a ledger with 1 txn
    lr = S.post(f"{API}/ledgers",
                json={"name": f"TEST_sec_exp_{uuid.uuid4().hex[:6]}", "group_id": gid},
                headers=h).json()
    lid = lr["id"]
    S.post(f"{API}/transactions",
           json={"ledger_id": lid, "amount": 100, "direction": "debit"},
           headers=h)

    ex = S.post(f"{API}/ledgers/{lid}/export", json={"format": "pdf"}, headers=h, timeout=30)
    assert ex.status_code == 200, ex.text
    url = ex.json()["url"]
    m = re.search(r"/api/files/([A-Za-z0-9_-]+)", url)
    assert m, url
    token = m.group(1)
    assert len(token) >= 40, f"file token too short: {token}"

    # public GET (no auth)
    fr = requests.get(BASE + url if url.startswith("/") else url, timeout=15)
    assert fr.status_code == 200, fr.status_code
    ct = fr.headers.get("content-type", "")
    assert "pdf" in ct.lower()
    cc = fr.headers.get("cache-control", "").lower()
    assert "no-store" in cc, cc

    # ObjectId-style path → 404
    r404 = requests.get(f"{API}/files/6aa05a3d3240a1020ec1e8ba", timeout=15)
    assert r404.status_code == 404
    r404b = requests.get(f"{API}/files/short", timeout=15)
    assert r404b.status_code == 404

    # cleanup
    S.delete(f"{API}/ledgers/{lid}", headers=h)


# ---------------------------------------------------- 4. Security headers + CORS
def test_security_headers():
    r = S.get(f"{API}/health", timeout=10)
    hdrs = {k.lower(): v.lower() for k, v in r.headers.items()}
    assert hdrs.get("x-content-type-options") == "nosniff", hdrs
    assert hdrs.get("referrer-policy") == "no-referrer", hdrs


def test_cors_no_credentials():
    r = S.options(f"{API}/health",
                  headers={
                      "Origin": "https://evil.example",
                      "Access-Control-Request-Method": "GET",
                  }, timeout=10)
    hdrs = {k.lower(): v for k, v in r.headers.items()}
    aco = hdrs.get("access-control-allow-origin", "")
    assert aco in ("*", "https://evil.example"), aco
    # allow-credentials must NOT be true
    assert hdrs.get("access-control-allow-credentials", "").lower() != "true"


# ---------------------------------------------------- 5. Regex escape (group create)
def test_group_create_special_chars_escaped():
    h = _auth_headers()
    name = "TEST_Sec.Test(Group)"
    r = S.post(f"{API}/groups", json={"name": name}, headers=h, timeout=15)
    assert r.status_code == 200, r.text
    gid = r.json()["id"]
    r2 = S.delete(f"{API}/groups/{gid}", headers=h)
    assert r2.status_code == 200


# ---------------------------------------------------- 6. PIN validation regex
def test_pin_validation_regex():
    # too short
    r = S.post(f"{API}/auth/login", json={"pin": "12"}, timeout=15)
    assert r.status_code in (400, 422), r.status_code
    # 8 digits (valid format but wrong) → 401
    r2 = S.post(f"{API}/auth/login", json={"pin": "12345678"}, timeout=15)
    assert r2.status_code == 401, r2.status_code


# ---------------------------------------------------- 7. WhatsApp simulate regression
def test_simulate_regression_after_security_fixes():
    h = _auth_headers()
    r = S.post(f"{API}/whatsapp/simulate", json={"text": "biki mill ka balance"},
               headers=h, timeout=45)
    assert r.status_code == 200
    assert r.json().get("reply")


# ---------------------------------------------------- 8. Lockout + PIN change (LAST — takes 65s)
@pytest.mark.order("last")
def test_lockout_and_pin_change_and_revoke():
    """Isolated: 5 wrong PINs → lock, wait 61s, then PIN change revocation flow."""
    # get a token first (before lockout)
    tokA = S.post(f"{API}/auth/login", json={"pin": PIN}, timeout=15).json()["access_token"]

    # 5 wrong pins → 401 x5
    for i in range(5):
        r = S.post(f"{API}/auth/login", json={"pin": "9999"}, timeout=15)
        assert r.status_code == 401, f"attempt {i}: {r.status_code}"

    # 6th → 429 with 'baad'
    r6 = S.post(f"{API}/auth/login", json={"pin": "9999"}, timeout=15)
    assert r6.status_code == 429, f"expected 429 got {r6.status_code}: {r6.text}"
    assert "baad" in r6.text.lower(), r6.text

    # wait 62s for the lock to clear
    print("waiting 62s for lockout to clear...")
    time.sleep(62)

    # counter reset — login succeeds
    r_ok = S.post(f"{API}/auth/login", json={"pin": PIN}, timeout=15)
    assert r_ok.status_code == 200, r_ok.text
    # then verify one wrong then correct still works (reset)
    S.post(f"{API}/auth/login", json={"pin": "0001"}, timeout=15)
    r_ok2 = S.post(f"{API}/auth/login", json={"pin": PIN}, timeout=15)
    assert r_ok2.status_code == 200

    # --- PIN change & token revocation ---
    hA = {"Authorization": f"Bearer {tokA}"}
    # tokA should still be valid pre-change
    pre = S.get(f"{API}/groups", headers=hA, timeout=10)
    assert pre.status_code == 200

    # common PIN rejected
    bad = S.put(f"{API}/settings/pin",
                json={"old_pin": PIN, "new_pin": "1234"},
                headers=hA, timeout=10)
    assert bad.status_code == 400, f"expected 400 for common pin got {bad.status_code}: {bad.text}"

    # good change
    ok = S.put(f"{API}/settings/pin",
               json={"old_pin": PIN, "new_pin": "336699"},
               headers=hA, timeout=10)
    assert ok.status_code == 200, ok.text
    assert ok.json().get("relogin") is True

    # old token now invalid
    after = S.get(f"{API}/groups", headers=hA, timeout=10)
    assert after.status_code == 401, f"expected 401 for revoked jwt got {after.status_code}"

    # old pin fails now
    r_old = S.post(f"{API}/auth/login", json={"pin": PIN}, timeout=15)
    assert r_old.status_code == 401

    # new pin works
    r_new = S.post(f"{API}/auth/login", json={"pin": "336699"}, timeout=15)
    assert r_new.status_code == 200
    tokB = r_new.json()["access_token"]
    hB = {"Authorization": f"Bearer {tokB}"}
    assert S.get(f"{API}/groups", headers=hB, timeout=10).status_code == 200

    # --- RESTORE PIN (mandatory) ---
    restore = S.put(f"{API}/settings/pin",
                    json={"old_pin": "336699", "new_pin": PIN},
                    headers=hB, timeout=10)
    assert restore.status_code == 200, restore.text
    r_final = S.post(f"{API}/auth/login", json={"pin": PIN}, timeout=15)
    assert r_final.status_code == 200, f"FINAL LOGIN FAILED: {r_final.text}"
