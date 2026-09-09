"""Tests for deploy/gen-caddyfile.sh across TLS modes and structural expectations.

Requires /tmp/caddy (v2 binary) available for `caddy validate` on generated files.
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path("/app")
SCRIPT_SRC = REPO_ROOT / "deploy" / "gen-caddyfile.sh"
CADDY_BIN = "/tmp/caddy"


def _stage(env_content: str, extra_files=None):
    """Copy script into a tmp APP_DIR/deploy layout with an .env, return APP_DIR."""
    app_dir = Path(tempfile.mkdtemp(prefix="munsiji_"))
    (app_dir / "deploy").mkdir()
    shutil.copy2(SCRIPT_SRC, app_dir / "deploy" / "gen-caddyfile.sh")
    (app_dir / "deploy" / "gen-caddyfile.sh").chmod(0o755)
    (app_dir / ".env").write_text(env_content)
    if extra_files:
        for rel, content in extra_files.items():
            p = app_dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                p.write_bytes(content)
            else:
                p.write_text(content)
    return app_dir


def _run(app_dir: Path):
    r = subprocess.run(
        ["bash", "deploy/gen-caddyfile.sh"],
        cwd=str(app_dir),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"gen-caddyfile.sh failed: {r.stderr}\n{r.stdout}"
    caddyfile = (app_dir / "data" / "Caddyfile").read_text()
    return caddyfile, r.stdout


def _validate(caddyfile_path: Path):
    r = subprocess.run(
        [CADDY_BIN, "validate", "--config", str(caddyfile_path), "--adapter", "caddyfile"],
        capture_output=True,
        text=True,
    )
    combined = (r.stdout or "") + (r.stderr or "")
    assert "Valid configuration" in combined, f"validate failed: {combined}"
    return combined


COMMON_HEADERS = [
    "X-Content-Type-Options nosniff",
    "X-Frame-Options DENY",
    "Referrer-Policy strict-origin-when-cross-origin",
    "Permissions-Policy",
    "-Server",
]
COMMON_ROUTES = [
    "handle /api/* {",
    "reverse_proxy backend:8001",
    "handle {",
    "reverse_proxy web:80",
]


def _assert_common(cf: str):
    for h in COMMON_HEADERS:
        assert h in cf, f"missing header: {h}\n---\n{cf}"
    for r in COMMON_ROUTES:
        assert r in cf, f"missing route line: {r}\n---\n{cf}"


# ------------------ gen-caddyfile.sh cases ------------------

class TestGenCaddyfile:
    def test_case1_empty_domain_plain_http(self):
        d = _stage("DOMAIN=\nACME_EMAIL=\nTLS_MODE=\n")
        cf, _ = _run(d)
        assert cf.startswith(":80 {"), f"expected ':80 {{' start, got: {cf[:40]!r}"
        assert "tls " not in cf
        assert "Strict-Transport-Security" not in cf
        _assert_common(cf)
        _validate(d / "data" / "Caddyfile")

    def test_case2_domain_auto_letsencrypt(self):
        d = _stage("DOMAIN=munsiji.app\nACME_EMAIL=admin@munsiji.com\n")
        cf, _ = _run(d)
        assert "{\n  email admin@munsiji.com\n}" in cf, cf
        assert "munsiji.app {" in cf
        # No explicit `tls` directive in auto mode
        for bad in ("tls internal", "tls /certs"):
            assert bad not in cf
        assert "Strict-Transport-Security" in cf
        _assert_common(cf)
        _validate(d / "data" / "Caddyfile")

    def test_case3_domain_tls_internal(self):
        d = _stage(
            "DOMAIN=munsiji.app\nACME_EMAIL=admin@munsiji.com\nTLS_MODE=internal\n"
        )
        cf, _ = _run(d)
        assert "tls internal" in cf
        # email block only emitted when TLS_MODE=auto
        assert "email admin@munsiji.com" not in cf
        assert "munsiji.app {" in cf
        assert "Strict-Transport-Security" in cf
        _assert_common(cf)
        _validate(d / "data" / "Caddyfile")

    def test_case4_origin_cert_autodetect(self):
        # generate a self-signed cert/key inline
        d = _stage("DOMAIN=munsiji.app\nACME_EMAIL=admin@munsiji.com\n")
        certs = d / "data" / "certs"
        certs.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(certs / "origin.key"),
                "-out", str(certs / "origin.pem"),
                "-days", "1", "-subj", "/CN=munsiji.app",
            ],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stderr
        cf, out = _run(d)
        assert "tls /certs/origin.pem /certs/origin.key" in cf
        assert "tls=origin" in out
        # For local validation, rewrite container paths to real host paths (use g flag)
        local = cf.replace("/certs/origin.pem", str(certs / "origin.pem"))
        local = local.replace("/certs/origin.key", str(certs / "origin.key"))
        tmpfile = d / "data" / "Caddyfile.local"
        tmpfile.write_text(local)
        _validate(tmpfile)
        _assert_common(cf)


# ------------------ install.sh + docker-compose regressions ------------------

class TestInstallScriptAndCompose:
    def test_install_sh_syntax(self):
        r = subprocess.run(["bash", "-n", str(REPO_ROOT / "deploy" / "install.sh")],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    def test_install_sh_invokes_gen_caddyfile(self):
        content = (REPO_ROOT / "deploy" / "install.sh").read_text()
        assert "deploy/gen-caddyfile.sh" in content

    def test_compose_mounts_certs_readonly(self):
        content = (REPO_ROOT / "deploy" / "docker-compose.yml").read_text()
        assert "../data/certs:/certs:ro" in content

    def test_readme_has_cloudflare_options(self):
        content = (REPO_ROOT / "deploy" / "README.md").read_text()
        # Section header
        assert "Cloudflare" in content
        # Option A/B/C descriptors present
        assert "DNS only" in content
        assert "TLS_MODE=internal" in content
        assert "Origin" in content and "origin.pem" in content and "origin.key" in content
        assert "Full (strict)" in content
