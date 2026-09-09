"""WhatsApp provider abstraction: MockProvider (logs to db) and Wa9xProvider (HTTP)."""
import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from db import db
from models import Settings, now_utc

logger = logging.getLogger(__name__)

# api_key -> "v1" | "v2": which wa.9x API flavour accepted this key (avoids a wasted 401 round-trip on every send)
_MODE_CACHE: dict[str, str] = {}


@dataclass
class IncomingMessage:
    sender: str
    text: str
    message_id: Optional[str]
    alt_sender: Optional[str] = None  # e.g. WhatsApp LID when a phone number is also present (or vice versa)


def digits(num: str) -> str:
    return re.sub(r"\D", "", num or "")


def same_number(a: str, b: str) -> bool:
    da, db_ = digits(a), digits(b)
    if not da or not db_:
        return False
    return da == db_ or da[-10:] == db_[-10:]


def looks_like_lid(sender: str) -> bool:
    """WhatsApp privacy IDs (xxx@lid) are 14–16 digit numbers, longer than any phone number (max 15 incl. country code, India = 12)."""
    d = digits(sender)
    return len(d) >= 14


def is_owner(settings: Settings, *ids: Optional[str]) -> bool:
    """Owner = whitelist phone number OR any paired sender id (LID) saved in settings.owner_ids."""
    extra = {digits(x) for x in (settings.owner_ids or [])}
    for i in ids:
        if not i:
            continue
        if same_number(i, settings.owner_number) or digits(i) in extra:
            return True
    return False


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

    @property
    def _mode(self) -> Optional[str]:
        return _MODE_CACHE.get(self.s.wa9x_api_key)

    def _remember(self, mode: str):
        _MODE_CACHE[self.s.wa9x_api_key] = mode

    def _client(self) -> httpx.AsyncClient:
        # IPv4 only (many VPS have half-working IPv6 → ConnectError/ReadError to Cloudflare-fronted wa.9x) + connect retries
        return httpx.AsyncClient(timeout=30, transport=httpx.AsyncHTTPTransport(local_address="0.0.0.0", retries=2))

    async def _request(self, method: str, url: str, **kw) -> httpx.Response:
        last: Optional[Exception] = None
        for attempt in range(3):
            try:
                async with self._client() as client:
                    return await client.request(method, url, **kw)
            except httpx.HTTPError as e:  # network / timeout / reset — retry a couple of times
                last = e
                logger.warning("wa.9x %s %s failed (%s: %s) attempt %d", method, url, type(e).__name__, e, attempt + 1)
                await asyncio.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"wa.9x tak request nahi gayi ({type(last).__name__}: {str(last) or 'timeout/network'}) — VPS se {self.base} reachable hai? (IPv6/MTU check)") from last

    @staticmethod
    def _json(r: httpx.Response) -> dict:
        try:
            d = r.json() if r.text else {}
        except ValueError:
            d = {"raw": r.text[:300]}
        return d if isinstance(d, dict) else {"data": d}

    # --- v1 (Modern JSON API): X-API-Key ---------------------------------------------------------
    async def _send_v1(self, to: str, text: str, media_url: str = "") -> httpx.Response:
        payload: dict = {"to": to, "text": text}
        if media_url:
            payload.update(media_url=media_url, caption=text)
        if self.s.wa9x_instance_id:
            payload["session_id"] = self.s.wa9x_instance_id
        return await self._request("POST", f"{self.base}/v1/messages", json=payload, headers={"X-API-Key": self.s.wa9x_api_key, "Accept": "application/json"})

    # --- v2 (360messenger-compatible): Authorization: Bearer, multipart form -----------------------
    async def _send_v2(self, to: str, text: str, media_url: str = "") -> httpx.Response:
        form = {"phonenumber": to, "text": text}
        if media_url:
            form["url"] = media_url
        return await self._request("POST", f"{self.base}/v2/sendMessage", data=form, headers={"Authorization": f"Bearer {self.s.wa9x_api_key}", "Accept": "application/json"})

    @staticmethod
    def _ok(r: httpx.Response, d: dict) -> bool:
        if not (200 <= r.status_code < 300) or d.get("error"):
            return False
        status = str(d.get("status") or "").lower()
        return d.get("success") is True or status in ("sent", "queued", "scheduled", "delivered", "")

    async def _send(self, to: str, text: str, media_url: str = "") -> dict:
        """Try v1 (X-API-Key). If the key is rejected (401), try v2 (Bearer) — wa.9x issues account keys and per-service keys."""
        self._check()
        order = ["v2", "v1"] if self._mode == "v2" else ["v1", "v2"]
        r = d = None
        for mode in order:
            r = await (self._send_v1 if mode == "v1" else self._send_v2)(to, text, media_url)
            d = self._json(r)
            if r.status_code in (401, 403):
                continue  # key not valid for this API flavour → try the other
            self._remember(mode)
            break
        ok = r is not None and r.status_code not in (401, 403) and self._ok(r, d or {})
        await db.wa_outbox.insert_one(
            {"to": to, "type": "document" if media_url else "text", "payload": {"to": to, "text": text, "media_url": media_url or None},
             "status": "sent" if ok else "failed", "http_status": r.status_code if r is not None else None, "response": (r.text[:500] if r is not None else ""), "created_at": now_utc()}
        )
        if not ok:
            if r is not None and r.status_code in (401, 403):
                raise RuntimeError("wa.9x ne API key reject ki (401, v1 aur v2 dono) — wa.9x dashboard → Settings → 'API key' (Copy) dobara paste karo; poori key wa9x_ se shuru hoti hai")
            detail = (d or {}).get("error") or (d or {}).get("detail") or (r.text[:200] if r is not None else "no response")
            raise RuntimeError(f"wa.9x {r.status_code if r is not None else ''}: {detail}")
        return d or {}

    async def send_text(self, to: str, text: str) -> dict:
        return await self._send(digits(to), text)

    async def send_document(self, to: str, url: str, filename: str, caption: str = "") -> dict:
        return await self._send(digits(to), caption or filename, media_url=url)

    async def sessions(self) -> tuple[list, str]:
        """Connection check: v1 GET /sessions (X-API-Key) → [{id,name,status,phone}]; if key is v2-only → GET /v2/account (Bearer)."""
        self._check()
        r = await self._request("GET", f"{self.base}/v1/sessions", headers={"X-API-Key": self.s.wa9x_api_key, "Accept": "application/json"})
        if r.status_code in (401, 403):
            r2 = await self._request("GET", f"{self.base}/v2/account", headers={"Authorization": f"Bearer {self.s.wa9x_api_key}", "Accept": "application/json"})
            if r2.status_code in (401, 403):
                raise RuntimeError("wa.9x ne API key reject ki (401, v1 aur v2 dono) — wa.9x dashboard → Settings → 'API key' Copy karke dobara paste karo")
            if r2.status_code >= 300:
                raise RuntimeError(f"wa.9x {r2.status_code}: {r2.text[:200]}")
            self._remember("v2")
            d = self._json(r2)
            res = d.get("result") if isinstance(d.get("result"), dict) else d
            return [{"id": "v2", "name": res.get("email") or "wa.9x account (v2 key)", "status": f"{res.get('sessions', '?')} session(s) linked", "phone": None}], r2.text[:400]
        if r.status_code >= 300:
            raise RuntimeError(f"wa.9x {r.status_code}: {r.text[:200]}")
        self._remember("v1")
        d = self._json(r)
        data = d.get("data") if "data" in d else (d.get("sessions") or d.get("result") or d.get("items") or [])
        if isinstance(data, dict):
            data = data.get("sessions") or data.get("items") or []
        return (data if isinstance(data, list) else []), r.text[:400]


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
    # Baileys ≥6.7 delivers privacy IDs (xxx@lid); the real phone may ride along in an alt field
    alt = _first(body, ["from_pn", "sender_pn", "senderPn", "participant_pn", "participantPn", "phone_number", "remoteJidAlt", "alt_jid", "senderPhone", "sender_phone"])
    if isinstance(body.get("key"), dict) and not alt:
        alt = _first(body["key"], ["senderPn", "participantPn", "remoteJidAlt"])
    if isinstance(alt, dict):
        alt = _first(alt, ["number", "id", "phone"])
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
    sender_d, alt_d = digits(str(sender)), digits(str(alt)) if alt and "@g.us" not in str(alt) else ""
    if alt_d and alt_d != sender_d and looks_like_lid(sender_d) and not looks_like_lid(alt_d):
        sender_d, alt_d = alt_d, sender_d  # prefer the real phone number as primary
    return IncomingMessage(sender=sender_d, text=text.strip(), message_id=str(mid) if mid else None, alt_sender=alt_d or None), "ok"
