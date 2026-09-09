"""Regression tests for the backend after Cloudflare/CF-Connecting-IP changes.

Only touches /api/health and a single successful /api/auth/login (PIN 3366) — no
wrong-PIN attempts to avoid triggering the lockout policy.
"""
import os
import re
import requests
import pytest

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or "https://whatsapp-munim.preview.emergentagent.com"
).rstrip("/")

PIN = "3366"


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


class TestHealth:
    def test_health_ok(self, api):
        r = api.get(f"{BASE_URL}/api/health", timeout=15)
        assert r.status_code == 200
        assert r.json().get("ok") is True


TOKEN_KEYS = ("access_token", "token")


def _extract_token(body):
    for k in TOKEN_KEYS:
        if isinstance(body.get(k), str) and body[k]:
            return body[k]
    return None


class TestLoginCloudflareHeader:
    """Verify backend accepts logins with and without CF-Connecting-IP.

    Uses the internal loopback (localhost:8001) so that Cloudflare's edge does
    not strip/reject client-supplied CF-Connecting-IP (which it does on the
    public preview URL). The backend's client_ip() logic must prefer this
    header when present.
    """

    INTERNAL = "http://localhost:8001"

    def test_login_with_cf_connecting_ip_internal(self, api):
        r = api.post(
            f"{self.INTERNAL}/api/auth/login",
            json={"pin": PIN},
            headers={"CF-Connecting-IP": "1.2.3.4"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        tok = _extract_token(r.json())
        assert tok, r.json()
        assert re.match(r"^[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+$", tok)

    def test_login_without_cf_header_internal(self, api):
        r = api.post(
            f"{self.INTERNAL}/api/auth/login",
            json={"pin": PIN},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        assert _extract_token(r.json())

    def test_login_public_url_without_cf_header(self, api):
        """Sanity: public URL still logs in fine when we do NOT spoof CF header."""
        r = api.post(
            f"{BASE_URL}/api/auth/login",
            json={"pin": PIN},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        assert _extract_token(r.json())
