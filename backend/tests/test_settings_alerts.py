"""Tests for the new Settings (Emergent Keys + Email Alerts) feature (iteration 3).

Covers:
- GET /api/settings masks secrets, exposes has_*/hint/ai_configured/email_configured
- PUT /api/settings write-only key semantics (empty = unchanged, '-' = clear)
- Owner email validation + test-email flow (delivered@resend.dev + undeliverable admin@munsiji.com)
- PIN lockout alert path (5 wrong PINs -> 401 then 6th -> 429, alert recorded)
- Regression: /api/whatsapp/simulate still works with the AI key from settings.
"""
import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://whatsapp-munim.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
PIN = "3366"
LLM_KEY = "sk-emergent-a8720A6Fc985b3986A"


@pytest.fixture(scope="module")
def auth():
    # Sleep to make sure any earlier lockout has expired before we start
    time.sleep(2)
    r = requests.post(f"{API}/auth/login", json={"pin": PIN}, timeout=15)
    if r.status_code == 429:
        # wait out the lock
        time.sleep(61)
        r = requests.post(f"{API}/auth/login", json={"pin": PIN}, timeout=15)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# --------------------------------------------------- Section A: PIN lockout FIRST
def test_a_pin_lockout_alert_recorded(auth):
    """5 wrong PINs -> 5th returns 401, 6th returns 429. Alert recorded."""
    # Reset counter first with a good login (already done in `auth` fixture)
    # Ensure owner_email is set so alert is not skipped
    requests.put(f"{API}/settings", json={"owner_email": "admin@munsiji.com", "alerts_enabled": True}, headers=auth, timeout=15)
    codes = []
    for _ in range(5):
        r = requests.post(f"{API}/auth/login", json={"pin": "9999"}, timeout=15)
        codes.append(r.status_code)
    # 6th should be locked
    r6 = requests.post(f"{API}/auth/login", json={"pin": "9999"}, timeout=15)
    assert codes == [401, 401, 401, 401, 401], f"first-5 codes: {codes}"
    assert r6.status_code == 429, f"6th: {r6.status_code} {r6.text}"

    # Alerts collection should have pin_lockout record
    alerts = requests.get(f"{API}/alerts", headers=auth, timeout=15).json()
    kinds = [a.get("kind") for a in alerts]
    assert "pin_lockout" in kinds, f"kinds seen: {kinds}"

    # Wait out the lockout so subsequent tests can login again
    time.sleep(62)


# --------------------------------------------------- Section B: settings GET masks secrets
def test_b_settings_masks_secrets(auth):
    r = requests.get(f"{API}/settings", headers=auth, timeout=15)
    assert r.status_code == 200
    d = r.json()
    for k in ("owner_email", "alerts_enabled", "has_emergent_llm_key", "emergent_llm_key_hint",
              "has_emergent_email_key", "emergent_email_key_hint", "ai_configured", "email_configured"):
        assert k in d, f"missing key {k} in settings response: {list(d.keys())}"
    assert "emergent_llm_key" not in d
    assert "emergent_email_key" not in d
    assert "pin_hash" not in d


# --------------------------------------------------- Section C: write-only key semantics
def test_c_put_llm_key_and_hint(auth):
    r = requests.put(f"{API}/settings", json={"emergent_llm_key": LLM_KEY}, headers=auth, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["has_emergent_llm_key"] is True
    assert d["emergent_llm_key_hint"].endswith("986A"), d["emergent_llm_key_hint"]


def test_d_put_empty_keeps_existing(auth):
    r = requests.put(f"{API}/settings", json={"emergent_llm_key": ""}, headers=auth, timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["has_emergent_llm_key"] is True  # unchanged
    assert d["emergent_llm_key_hint"].endswith("986A")


def test_e_put_dash_clears_email_key(auth):
    # First set an email key so we can clear it
    requests.put(f"{API}/settings", json={"emergent_email_key": "ek_TEST_dummykey_1234"}, headers=auth, timeout=15)
    r = requests.put(f"{API}/settings", json={"emergent_email_key": "-"}, headers=auth, timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["has_emergent_email_key"] is False
    assert d["emergent_email_key_hint"] == ""


def test_f_llm_key_still_set(auth):
    """Ensure LLM key still set to the target value at end for AI parser regression."""
    d = requests.get(f"{API}/settings", headers=auth, timeout=15).json()
    assert d["has_emergent_llm_key"] is True
    assert d["emergent_llm_key_hint"].endswith("986A")


# --------------------------------------------------- Section D: email validation & test-email
def test_g_bad_email_400(auth):
    r = requests.put(f"{API}/settings", json={"owner_email": "not-an-email"}, headers=auth, timeout=15)
    assert r.status_code == 400, r.text


def test_h_valid_email_and_test_send(auth):
    r = requests.put(f"{API}/settings", json={"owner_email": "delivered@resend.dev"}, headers=auth, timeout=15)
    assert r.status_code == 200
    r2 = requests.post(f"{API}/settings/test-email", headers=auth, timeout=45)
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body.get("ok") is True
    assert body.get("email_id"), f"missing email_id in {body}"

    # alerts list contains a 'test' kind
    alerts = requests.get(f"{API}/alerts", headers=auth, timeout=15).json()
    kinds = [a.get("kind") for a in alerts]
    assert "test" in kinds, f"kinds: {kinds}"


def test_i_undeliverable_email_502(auth):
    r = requests.put(f"{API}/settings", json={"owner_email": "admin@munsiji.com"}, headers=auth, timeout=15)
    assert r.status_code == 200
    r2 = requests.post(f"{API}/settings/test-email", headers=auth, timeout=45)
    # Backend returns 502 with 'Email nahi gaya: 422: Undeliverable recipient ...'.
    # Cloudflare edge intercepts *any* origin 5xx and replaces the body with a CF-branded
    # HTML error page, so we can only assert the status code from outside. The actual
    # 'Undeliverable' error string is verified via /api/alerts below.
    assert r2.status_code == 502, f"expected 502, got {r2.status_code}: {r2.text[:200]}"

    alerts = requests.get(f"{API}/alerts", headers=auth, timeout=15).json()
    # Latest 'test' alert should carry the 422/Undeliverable error and ok=False
    test_alerts = [a for a in alerts if a.get("kind") == "test"]
    assert test_alerts, f"no 'test' alert record found: {[a.get('kind') for a in alerts]}"
    latest = test_alerts[0]
    assert latest.get("ok") is False, f"expected ok=False for undeliverable, got: {latest}"
    err = (latest.get("error") or "").lower()
    assert "422" in err and "undeliverable" in err, f"unexpected error: {latest.get('error')}"


# --------------------------------------------------- Section E: AI regression
def test_j_ai_simulate_uses_settings_key(auth):
    text = f"Test Alert Party {uuid.uuid4().hex[:4]} - 1500"
    r = requests.post(f"{API}/whatsapp/simulate", json={"text": text}, headers=auth, timeout=45)
    assert r.status_code == 200, r.text
    reply = r.json().get("reply", "")
    assert reply, f"empty reply, body: {r.json()}"
    # Should mention balance 1500 in some form (running balance or new ledger)
    # AI parsed the input (either created ledger with 1500 balance, or found a similar match).
    # Either outcome proves the AI key from settings is being used.
    ok = ("1500" in reply.replace(",", "") or "1,500" in reply
          or "milta-julta" in reply or "similar" in reply.lower() or "Naya ledger" in reply)
    assert ok, f"reply: {reply}"


# --------------------------------------------------- Section F: leave final state consistent
def test_z_final_state(auth):
    """Ensure final state: owner_email=admin@munsiji.com, alerts_enabled=true, llm key set."""
    requests.put(f"{API}/settings", json={"owner_email": "admin@munsiji.com", "alerts_enabled": True}, headers=auth, timeout=15)
    d = requests.get(f"{API}/settings", headers=auth, timeout=15).json()
    assert d["owner_email"] == "admin@munsiji.com"
    assert d["alerts_enabled"] is True
    assert d["has_emergent_llm_key"] is True
