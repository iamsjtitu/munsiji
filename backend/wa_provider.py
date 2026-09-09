"""WhatsApp provider abstraction: MockProvider (logs to db) and Wa9xProvider (HTTP)."""
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from db import db
from models import Settings, now_utc

logger = logging.getLogger(__name__)


@dataclass
class IncomingMessage:
    sender: str
    text: str
    message_id: Optional[str]


def digits(num: str) -> str:
    return re.sub(r"\D", "", num or "")


def same_number(a: str, b: str) -> bool:
    da, db_ = digits(a), digits(b)
    if not da or not db_:
        return False
    return da == db_ or da[-10:] == db_[-10:]


class ProviderNotConfigured(Exception):
    pass


class WhatsAppProvider:
    name = "base"

    async def send_text(self, to: str, text: str) -> dict:
        raise NotImplementedError

    async def send_document(self, to: str, url: str, filename: str, caption: str = "") -> dict:
        raise NotImplementedError


class MockProvider(WhatsAppProvider):
    """Stores outgoing messages in `wa_outbox` so the flow is testable without wa.9x."""

    name = "mock"

    async def send_text(self, to: str, text: str) -> dict:
        await db.wa_outbox.insert_one({"to": to, "type": "text", "text": text, "status": "mock_sent", "created_at": now_utc()})
        return {"status": "mock_sent"}

    async def send_document(self, to: str, url: str, filename: str, caption: str = "") -> dict:
        await db.wa_outbox.insert_one(
            {"to": to, "type": "document", "url": url, "filename": filename, "caption": caption, "status": "mock_sent", "created_at": now_utc()}
        )
        return {"status": "mock_sent"}


WA9X_DEFAULT_BASE = "https://wa.9x.design/api"


def normalize_base_url(url: str) -> str:
    """Accept https://wa.9x.design, .../api, .../api/v1/messages → always https://host/api."""
    u = (url or "").strip().rstrip("/")
    if not u:
        return ""
    if not re.match(r"^https?://", u):
        u = "https://" + u
    u = re.sub(r"/api(/v[12](/.*)?)?$", "/api", u)
    if not u.endswith("/api"):
        u += "/api"
    return u


class Wa9xProvider(WhatsAppProvider):
    """wa.9x.design — Modern API v1 (JSON): POST /api/v1/messages with X-API-Key header.

    Request: {"to": "919876543210", "text": "...", "media_url"?: str, "caption"?: str, "session_id"?: str}
    Response: {"status": "sent", "message_id": "...", "to": "...", "error": null}
    """

    name = "wa9x"

    def __init__(self, settings: Settings):
        self.s = settings
        self.base = normalize_base_url(settings.wa9x_base_url) or WA9X_DEFAULT_BASE

    def _check(self):
        if not self.s.wa9x_api_key:
            raise ProviderNotConfigured("wa.9x API key set nahi hai (Settings → WhatsApp)")

    def _headers(self) -> dict:
        return {
            "X-API-Key": self.s.wa9x_api_key,
            "Authorization": f"Bearer {self.s.wa9x_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _send(self, payload: dict) -> dict:
        self._check()
        if self.s.wa9x_instance_id:
            payload["session_id"] = self.s.wa9x_instance_id
        url = f"{self.base}/v1/messages"
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.post(url, json=payload, headers=self._headers())
        try:
            data = r.json() if r.text else {}
        except ValueError:
            data = {"raw": r.text[:300]}
        status = str(data.get("status") or "").lower() if isinstance(data, dict) else ""
        err = data.get("error") if isinstance(data, dict) else None
        ok = 200 <= r.status_code < 300 and not err and (status in ("sent", "queued", "scheduled", "delivered", "") or data.get("success") is True)
        await db.wa_outbox.insert_one(
            {"to": payload.get("to"), "type": "document" if payload.get("media_url") else "text", "payload": {k: v for k, v in payload.items()},
             "status": "sent" if ok else "failed", "http_status": r.status_code, "response": r.text[:500], "created_at": now_utc()}
        )
        if not ok:
            detail = err or (data.get("detail") if isinstance(data, dict) else None) or r.text[:200]
            raise RuntimeError(f"wa.9x {r.status_code}: {detail}")
        return data

    async def send_text(self, to: str, text: str) -> dict:
        return await self._send({"to": digits(to), "text": text})

    async def send_document(self, to: str, url: str, filename: str, caption: str = "") -> dict:
        return await self._send({"to": digits(to), "media_url": url, "caption": caption or filename, "text": caption or filename})

    async def sessions(self) -> list:
        """GET /api/v1/sessions → [{id, name, status, phone}] — used by the in-app connection check."""
        self._check()
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(f"{self.base}/v1/sessions", headers=self._headers())
        if r.status_code in (401, 403):
            raise RuntimeError("wa.9x ne API key reject ki (401) — Settings mein sahi X-API-Key daalo (wa9x_... se shuru)")
        if r.status_code >= 300:
            raise RuntimeError(f"wa.9x {r.status_code}: {r.text[:200]}")
        data = r.json()
        if isinstance(data, dict):
            data = data.get("sessions") or data.get("result") or data.get("data") or []
        return data if isinstance(data, list) else []


def get_provider(settings: Settings) -> WhatsAppProvider:
    if settings.provider == "wa9x":
        return Wa9xProvider(settings)
    return MockProvider()


# ---------------------------------------------------------------- incoming normalisation
def _first(d: dict, keys, default=None):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] not in (None, ""):
            return d[k]
    return default


def parse_incoming(payload: Any) -> tuple[Optional[IncomingMessage], str]:
    """Normalise webhook shapes (wa.9x.design `message.received`, Baileys-like, generic) → (IncomingMessage | None, reason)."""
    if not isinstance(payload, dict):
        return None, "body JSON object nahi hai"
    event = payload.get("event")
    if isinstance(event, str) and event and "message" not in event.lower():
        # e.g. wa.9x "Test" button / status events — reached us fine, just nothing to process
        return None, f"event '{event}' (message nahi)"
    body = payload
    for wrapper in ("data", "message_data", "payload", "event"):
        if isinstance(body.get(wrapper), dict) and not _first(body, ["text", "message", "body"]):
            body = body[wrapper]
    if isinstance(body.get("messages"), list) and body["messages"]:
        body = body["messages"][0]
    if body.get("fromMe") is True or body.get("from_me") is True or (isinstance(body.get("key"), dict) and body["key"].get("fromMe")):
        return None, "khud ka bheja message (fromMe)"
    sender = _first(body, ["from", "sender", "number", "phone", "remoteJid", "chatId", "chat_id", "waId", "wa_id", "author"])
    if isinstance(body.get("key"), dict) and not sender:
        sender = body["key"].get("remoteJid")
    if isinstance(sender, dict):
        sender = _first(sender, ["number", "id", "phone"])
    text = _first(body, ["text", "message", "body", "content", "caption", "msg"])
    if isinstance(text, dict):
        text = _first(text, ["body", "text", "conversation", "message"])
        if isinstance(text, dict):
            text = _first(text, ["text", "body"])
    if isinstance(text, dict) and "extendedTextMessage" in text:
        text = text["extendedTextMessage"].get("text")
    mid = _first(body, ["id", "message_id", "messageId", "msg_id", "wa_message_id"])
    if isinstance(body.get("key"), dict) and not mid:
        mid = body["key"].get("id")
    if not sender:
        return None, "sender number nahi mila"
    if "@g.us" in str(sender):  # ignore groups
        return None, "group message"
    if not isinstance(text, str) or not text.strip():
        return None, "text nahi hai (media/sticker?)" if body.get("has_media") or body.get("type") not in (None, "text", "chat") else "text khaali hai"
    return IncomingMessage(sender=digits(str(sender)), text=text.strip(), message_id=str(mid) if mid else None), "ok"
