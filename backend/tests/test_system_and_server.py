"""Backend tests for the new self-host system endpoints + smoke regressions."""
import os

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://whatsapp-munim.preview.emergentagent.com").rstrip("/")
PIN = "3366"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"pin": PIN}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ------------------ Auth required (401 without token) ------------------
class TestSystemAuthRequired:
    def test_version_401_without_token(self):
        r = requests.get(f"{BASE_URL}/api/system/version", timeout=15)
        assert r.status_code == 401, r.text

    def test_update_401_without_token(self):
        r = requests.post(f"{BASE_URL}/api/system/update", timeout=15)
        assert r.status_code == 401, r.text

    def test_auto_update_401_without_token(self):
        r = requests.put(f"{BASE_URL}/api/system/auto-update", json={"enabled": True}, timeout=15)
        assert r.status_code == 401, r.text


# ------------------ Unsupported mode behavior ------------------
class TestSystemUnsupportedMode:
    def test_version_returns_supported_false(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/system/version", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("supported") is False, data

    def test_update_returns_400(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/system/update", headers=auth_headers, timeout=15)
        assert r.status_code == 400, r.text
        assert "self-hosted" in r.json().get("detail", "").lower() or "vps" in r.json().get("detail", "").lower()

    def test_auto_update_enabled_true_returns_400(self, auth_headers):
        r = requests.put(
            f"{BASE_URL}/api/system/auto-update",
            headers=auth_headers,
            json={"enabled": True},
            timeout=15,
        )
        assert r.status_code == 400, r.text


# ------------------ Regression smoke (existing flows) ------------------
class TestRegressionSmoke:
    def test_login_pin_3366(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"pin": PIN}, timeout=15)
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_groups_list(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/groups", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_dashboard(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/dashboard", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        d = r.json()
        for k in ("total_lena", "total_dena", "ledger_count", "recent"):
            assert k in d
