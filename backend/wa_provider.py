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


class Wa9xProvider(WhatsAppProvider):
    name = "wa9x"

    def __init__(self, settings: Settings):
        self.s = settings

    def _check(self):
        if not self.s.wa9x_base_url or not self.s.wa9x_api_key:
            raise ProviderNotConfigured("wa.9x base URL / API key set nahi hai")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.s.wa9x_api_key}",
            "apikey": self.s.wa9x_api_key,
            "Content-Type": "application/json",
        }

    async def _post(self, path: str, payload: dict) -> dict:
        self._check()
        url = self.s.wa9x_base_url.rstrip("/") + "/" + path.lstrip("/")
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(url, json=payload, headers=self._headers())
            ok = 200 <= r.status_code < 300
            await db.wa_outbox.insert_one(
                {"to": payload.get("number"), "type": payload.get("type", "text"), "payload": payload, "status": "sent" if ok else "failed",
                 "http_status": r.status_code, "response": r.text[:500], "created_at": now_utc()}
            )
            if not ok:
                raise RuntimeError(f"wa.9x error {r.status_code}: {r.text[:200]}")
            try:
                return r.json()
            except ValueError:
                return {"raw": r.text}

    async def send_text(self, to: str, text: str) -> dict:
        payload = {"number": digits(to), "message": text, "type": "text"}
        if self.s.wa9x_instance_id:
            payload["instance_id"] = self.s.wa9x_instance_id
        return await self._post(self.s.wa9x_send_path, payload)

    async def send_document(self, to: str, url: str, filename: str, caption: str = "") -> dict:
        payload = {"number": digits(to), "media_url": url, "url": url, "filename": filename, "caption": caption, "type": "document", "message": caption}
        if self.s.wa9x_instance_id:
            payload["instance_id"] = self.s.wa9x_instance_id
        return await self._post(self.s.wa9x_send_doc_path, payload)


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


def parse_incoming(payload: Any) -> Optional[IncomingMessage]:
    """Normalise many webhook shapes (wa.9x / Baileys-like / generic) into IncomingMessage."""
    if not isinstance(payload, dict):
        return None
    body = payload
    for wrapper in ("data", "message_data", "payload", "event"):
        if isinstance(body.get(wrapper), dict) and not _first(body, ["text", "message", "body"]):
            body = body[wrapper]
    if isinstance(body.get("messages"), list) and body["messages"]:
        body = body["messages"][0]
    if body.get("fromMe") is True or body.get("from_me") is True or (isinstance(body.get("key"), dict) and body["key"].get("fromMe")):
        return None
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
    if not sender or not isinstance(text, str) or not text.strip():
        return None
    if "@g.us" in str(sender):  # ignore groups
        return None
    return IncomingMessage(sender=digits(str(sender)), text=text.strip(), message_id=str(mid) if mid else None)
