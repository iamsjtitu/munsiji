"""Emergent-managed Resend email: alert emails to the owner (throttled, templated, guard-railed)."""
import ipaddress
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from html import escape
from html.parser import HTMLParser
from typing import List, Optional
from urllib.parse import urlparse

import httpx

from db import db

logger = logging.getLogger(__name__)

# Emergent managed email proxy. Constant on purpose (survives deployment).
EMAIL_BASE_URL = "https://integrations.emergentagent.com"
EMAIL_FROM_NAME = os.environ["EMAIL_FROM_NAME"]  # this app's own brand
EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO")
ALERT_THROTTLE = timedelta(minutes=30)

# ---------------------------------------------------------------- guardrail gate (G2 + G3)
_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = ("reply with your password", "reply with the code", "send your password", "cvv",
             "send us your password", "enter your password below", "confirm your card number",
             "your full card number", "seed phrase", "recovery phrase", "verify your card",
             "social security number", "confirm your bank details")
_HOSTISH = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)


def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)


def _same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)


class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.urls, self.anchors = set(), [], []
        self._href, self._text = None, []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href, self._text = None, []


def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan()
    scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email (G2)")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks the recipient for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Email links/assets must be absolute https: {url!r} (G3)")
        host = urlparse(low).hostname or ""
        if not _host_ok(host) or urlparse(low).username is not None:
            raise ValueError(f"Shortened, numeric-host or credential-bearing URL: {url!r} (G3)")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH.finditer(text):
            if not _same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor text {m.group(1)!r} ≠ real link host {real!r} (G3)")


class EmailNotConfigured(Exception):
    pass


# ---------------------------------------------------------------- sending
async def send_email(*, to: str, subject: str, html: str, api_key: str, reply_to: Optional[str] = None) -> Optional[str]:
    _assert_safe_email(subject, html)
    if not api_key:
        raise EmailNotConfigured("Emergent email key set nahi hai")
    payload = {"to": [to], "subject": subject, "html": html, "from_name": EMAIL_FROM_NAME}
    if reply_to or EMAIL_REPLY_TO:
        payload["contact_email"] = reply_to or EMAIL_REPLY_TO
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{EMAIL_BASE_URL}/api/v1/email/send", headers={"X-Email-Key": api_key}, json=payload)
    resp.raise_for_status()
    return resp.json().get("id")


def alert_html(title: str, lines: List[str], app_url: str = "") -> str:
    items = "".join(f'<tr><td style="padding:4px 0;font-size:14px;color:#27272A">{escape(l)}</td></tr>' for l in lines)
    link = ""
    if app_url.startswith("https://"):
        link = (f'<p style="margin:16px 0 0"><a href="{escape(app_url)}" style="color:#047857;font-weight:bold">'
                f"{escape(EMAIL_FROM_NAME)} app kholo</a></p>")
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-family:Arial,sans-serif;background:#FAFAFA">'
        '<tr><td style="padding:24px">'
        '<table role="presentation" width="100%" style="max-width:560px;margin:0 auto;background:#FFFFFF;border:1px solid #E4E4E7;border-radius:12px">'
        f'<tr><td style="padding:20px 24px;border-bottom:1px solid #E4E4E7"><strong style="font-size:16px;color:#047857">{escape(EMAIL_FROM_NAME)}</strong>'
        f'<div style="font-size:18px;font-weight:bold;color:#18181B;margin-top:6px">{escape(title)}</div></td></tr>'
        f'<tr><td style="padding:16px 24px"><table role="presentation" cellpadding="0" cellspacing="0">{items}</table>{link}</td></tr>'
        f'<tr><td style="padding:12px 24px;font-size:12px;color:#71717A;border-top:1px solid #E4E4E7">'
        f"Ye alert {escape(EMAIL_FROM_NAME)} app ne bheja hai. Hum kabhi PIN ya password email pe nahi maangte.</td></tr>"
        "</table></td></tr></table>"
    )


async def send_alert(kind: str, title: str, lines: List[str], *, force: bool = False, ref: Optional[str] = None) -> dict:
    """Send an owner alert (recipient/template server-side). Throttled per kind unless force. Never raises."""
    s = await db.settings.find_one({"key": "main"})
    if not s:
        return {"ok": False, "skipped": "no settings"}
    to = (s.get("owner_email") or "").strip()
    if not to or (not s.get("alerts_enabled", True) and not force):
        return {"ok": False, "skipped": "alerts off / no email"}
    api_key = s.get("emergent_email_key") or os.environ.get("EMERGENT_EMAIL_KEY", "")
    now = datetime.now(timezone.utc)
    if ref and await db.alerts.find_one({"kind": kind, "ref": ref}):
        return {"ok": False, "skipped": "already sent"}
    if not force:
        last = await db.alerts.find_one({"kind": kind, "ok": True}, sort=[("sent_at", -1)])
        if last:
            last_at = last["sent_at"] if last["sent_at"].tzinfo else last["sent_at"].replace(tzinfo=timezone.utc)
            if now - last_at < ALERT_THROTTLE:
                return {"ok": False, "skipped": "throttled"}
    app_url = (s.get("public_base_url") or os.environ.get("PUBLIC_BASE_URL", "")).rstrip("/")
    subject = f"[{EMAIL_FROM_NAME}] {title}"
    record = {"kind": kind, "subject": subject, "to": to, "sent_at": now, "ok": False, "ref": ref}
    try:
        record["email_id"] = await send_email(to=to, subject=subject, html=alert_html(title, lines, app_url), api_key=api_key)
        record["ok"] = True
    except httpx.HTTPStatusError as e:
        record["error"] = f"{e.response.status_code}: {e.response.text[:200]}"
        logger.error("alert email failed: %s", record["error"])
    except Exception as e:  # noqa: BLE001
        record["error"] = str(e)[:200]
        logger.error("alert email error: %s", e)
    await db.alerts.insert_one(record)
    record.pop("_id", None)
    record["sent_at"] = now.isoformat()
    return record
