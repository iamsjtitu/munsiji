import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from bson import ObjectId
from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError
from starlette.middleware.cors import CORSMiddleware

from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from ai_parser import IST  # noqa: E402
from auth import check_lockout, current_owner, hash_pin, make_token, record_fail, record_success, verify_pin  # noqa: E402
from bot import day_end, day_start, get_settings, handle_message, ist_datetime_for, public_base_url, save_export  # noqa: E402
from db import client, db  # noqa: E402
from ledger_service import (  # noqa: E402
    TAG_WORDS,
    account_balances,
    add_transaction,
    create_ledger,
    delete_transaction,
    ensure_default_groups,
    get_ledger,
    group_totals,
    list_ledgers,
    merge_ledgers,
    migrate_cashbook,
    normalize,
    recalc_balance,
    statement,
    transfer,
    update_transaction,
)
from models import ACCOUNT_KINDS, Group, Ledger, Settings, Transaction, WaMessage, now_utc  # noqa: E402
from wa_provider import ProviderNotConfigured, Wa9xProvider, digits, get_provider, is_owner, looks_like_lid, parse_incoming, same_number  # noqa: E402
import system  # noqa: E402
from emailer import send_alert  # noqa: E402
import asyncio  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Munsiji API")
api = APIRouter(prefix="/api")
protected = APIRouter(prefix="/api", dependencies=[Depends(current_owner)])


# ------------------------------------------------------------------ startup
@app.on_event("startup")
async def startup():
    await db.transactions.create_index([("ledger_id", 1), ("entry_date", 1)])
    await db.wa_messages.create_index("wa_message_id")
    await db.ledgers.create_index("group_id")
    await db.export_files.create_index("token", unique=True, sparse=True)
    await db.export_files.create_index("expires_at", expireAfterSeconds=0)
    await db.login_guard.create_index("key", unique=True)
    await db.wa_webhook_log.create_index("received_at", expireAfterSeconds=7 * 24 * 3600)
    await db.wa_seen.create_index("message_id", unique=True)
    await db.wa_seen.create_index("created_at", expireAfterSeconds=3 * 24 * 3600)
    if not await db.settings.find_one({"key": "main"}):
        s = Settings(owner_number=os.environ["OWNER_WHATSAPP"], pin_hash=hash_pin(os.environ["OWNER_PIN"]), owner_email=os.environ.get("OWNER_EMAIL", ""),
                     webhook_secret=secrets.token_urlsafe(24))
        await db.settings.insert_one(s.to_mongo())
    else:
        await db.settings.update_one(
            {"key": "main", "$or": [{"owner_email": {"$exists": False}}, {"owner_email": ""}]},
            {"$set": {"owner_email": os.environ.get("OWNER_EMAIL", "")}},
        )
        await db.settings.update_one(
            {"key": "main", "$or": [{"webhook_secret": {"$exists": False}}, {"webhook_secret": ""}]},
            {"$set": {"webhook_secret": secrets.token_urlsafe(24)}},
        )
    await ensure_default_groups()
    await migrate_cashbook()
    asyncio.create_task(update_failure_watcher())


async def update_failure_watcher():
    """Self-host only: email the owner once when a GitHub update fails."""
    while True:
        try:
            if system.supported():
                st = system.read_status()
                if st.get("state") == "failed" and st.get("updated_at"):
                    await send_alert("update_failed", "Server update fail hua", [st.get("message", ""), f"Time: {st['updated_at']}", "Settings > Server & Updates > Update log dekho, phir Retry karo."], force=True, ref=st["updated_at"])
        except Exception as e:  # noqa: BLE001
            logger.warning("update watcher: %s", e)
        await asyncio.sleep(60)


@app.on_event("shutdown")
async def shutdown():
    client.close()


def oid(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=404, detail="Not found")
    return ObjectId(value)


def parse_entry_date(value: Optional[str]) -> datetime:
    if not value:
        return now_utc()
    v = str(value)
    if len(v) == 10:
        return ist_datetime_for(date.fromisoformat(v))
    d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------ public
class LoginBody(BaseModel):
    pin: str = Field(pattern=r"^\d{4,8}$")


def client_ip(request: Request) -> str:
    # Cloudflare (if proxied) -> X-Forwarded-For (Caddy) -> socket
    cf = request.headers.get("cf-connecting-ip", "").strip()
    if cf:
        return cf[:64]
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown"))[:64]


@api.get("/health")
async def health():
    return {"ok": True}


@api.post("/auth/login")
async def login(body: LoginBody, request: Request):
    ip = client_ip(request)
    await check_lockout(ip)
    s = await get_settings()
    if not verify_pin(body.pin, s.pin_hash):
        if await record_fail(ip):
            await send_alert("pin_lockout", "Galat PIN — bahut baar try hua, login lock", [f"IP {ip} se baar-baar galat PIN daala gaya; login kuch der ke liye lock hai.", "Agar ye aap nahi the to Settings se PIN badal lo."])
        raise HTTPException(status_code=401, detail="Galat PIN")
    await record_success(ip)
    return {"access_token": make_token(), "token_type": "bearer"}


@api.get("/files/{token}")
async def get_file(token: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", token):
        raise HTTPException(status_code=404, detail="File not found")
    doc = await db.export_files.find_one({"token": token})
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")
    exp = doc.get("expires_at")
    if exp and (exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)) < now_utc():
        raise HTTPException(status_code=410, detail="Link expire ho gaya — app se dobara export karo")
    return Response(content=bytes(doc["data"]), media_type=doc["content_type"],
                    headers={"Content-Disposition": f'attachment; filename="{doc["filename"]}"', "Cache-Control": "private, no-store",
                             "X-Content-Type-Options": "nosniff"})


def _webhook_token(request: Request) -> str:
    return request.query_params.get("token") or request.headers.get("x-webhook-token") or ""


def wa_configured(s: Settings) -> bool:
    return bool(s.wa9x_api_key)


async def _require_webhook_token(request: Request) -> Settings:
    s = await get_settings()
    if not s.webhook_secret or not secrets.compare_digest(_webhook_token(request), s.webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook token")
    return s


async def _webhook_log(outcome: str, detail: str = "", payload=None, sender: str = "", text: str = "", event: str = "") -> ObjectId:
    """Every webhook hit (even rejected ones) is recorded so the owner can see from the app whether wa.9x reaches us."""
    raw = ""
    if payload is not None:
        try:
            raw = json.dumps(payload, ensure_ascii=False)[:1500]
        except (TypeError, ValueError):
            raw = str(payload)[:1500]
    doc = {"received_at": now_utc(), "outcome": outcome, "detail": detail[:300], "sender": sender, "text": (text or "")[:200], "event": event, "raw": raw}
    res = await db.wa_webhook_log.insert_one(doc)
    return res.inserted_id


def _verify_wa9x_signature(s: Settings, request: Request, body: bytes) -> bool:
    """Optional HMAC check (wa.9x → Settings → webhook signing secret). Skipped when no secret is saved."""
    if not s.wa9x_webhook_secret:
        return True
    sig = request.headers.get("x-wa9x-signature") or request.headers.get("x-wapihub-signature") or ""
    expected = "sha256=" + hmac.new(s.wa9x_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig.strip(), expected)


async def _process_incoming(settings: Settings, sender: str, text: str, message_id: Optional[str], log_id: ObjectId):
    """Runs after the 200 is returned (wa.9x waits max 10s) — AI parse + reply via provider."""
    outcome, detail = "error", ""
    try:
        result = await handle_message(sender, text, message_id, source="whatsapp")
        outcome = result["status"]
        if result["reply"]:
            provider = get_provider(settings)
            try:
                await provider.send_text(sender, result["reply"])
                for f in result["files"]:
                    await provider.send_document(sender, f["url"], f["filename"], caption=f["filename"])
            except (ProviderNotConfigured, Exception) as e:  # noqa: BLE001
                logger.error("send failed: %s", e)
                await db.wa_messages.update_many({"wa_message_id": message_id} if message_id else {"sender": sender, "text": text},
                                                 {"$set": {"status": "send_failed", "send_error": str(e)[:300]}})
                outcome, detail = "send_failed", str(e)[:300]
                await send_alert("wa_send_failed", "WhatsApp reply nahi gaya (wa.9x)", [f"Error: {str(e)[:160]}", f"Message: {text[:120]}", "Entry save ho gayi hai; sirf reply nahi gaya. Settings mein wa.9x config check karo ya app se kaam karo."])
    except Exception as e:  # noqa: BLE001
        logger.exception("webhook processing failed")
        detail = str(e)[:300]
    await db.wa_webhook_log.update_one({"_id": log_id}, {"$set": {"outcome": outcome, "detail": detail, "processed_at": now_utc()}})


@api.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request, background: BackgroundTasks):
    s = await get_settings()
    body = await request.body()
    try:
        payload = json.loads(body) if body else {}
    except ValueError:
        form = await request.form()
        payload = dict(form)
    event = str(payload.get("event") or "") if isinstance(payload, dict) else ""
    if not s.webhook_secret or not secrets.compare_digest(_webhook_token(request), s.webhook_secret):
        await _webhook_log("invalid_token", "Webhook URL ka ?token= galat/missing hai — Settings se poora URL copy karke wa.9x mein daalo", payload, event=event)
        raise HTTPException(status_code=401, detail="Invalid webhook token")
    if not _verify_wa9x_signature(s, request, body):
        await _webhook_log("bad_signature", "X-Wa9x-Signature match nahi hua — Settings mein webhook signing secret check karo", payload, event=event)
        raise HTTPException(status_code=401, detail="Invalid signature")
    msg, reason = parse_incoming(payload)
    if not msg:
        await _webhook_log("ignored", reason, payload, event=event)
        return {"status": "ignored", "reason": reason}
    sender_label = msg.sender + (f" / {msg.alt_sender}" if msg.alt_sender else "")
    if not is_owner(s, msg.sender, msg.alt_sender):
        # Pairing: owner sends the one-time code shown in the app → this sender id (LID) becomes an owner alias
        code_ok = s.pairing_code and s.pairing_expires_at and _aware(s.pairing_expires_at) > now_utc() and secrets.compare_digest(re.sub(r"\D", "", msg.text), s.pairing_code)
        if code_ok:
            new_ids = [x for x in (msg.sender, msg.alt_sender) if x and not same_number(x, s.owner_number)]
            await db.settings.update_one({"key": "main"}, {"$addToSet": {"owner_ids": {"$each": new_ids}}, "$set": {"pairing_code": "", "pairing_expires_at": None, "updated_at": now_utc()}})
            log_id = await _webhook_log("paired", f"Sender id {sender_label} ab owner ke saath linked hai", payload, sender=msg.sender, text=msg.text, event=event)
            background.add_task(_send_owner_text, s, "✅ Pairing ho gayi! Ab yahan se hisab likho — e.g. \"Biki mill ko 5000 diya\"", log_id)
            return {"status": "paired"}
        hint = " — ye WhatsApp LID lag rahi hai (phone number nahi): app → WhatsApp → Connection Check → Pairing code bhejo" if looks_like_lid(msg.sender) else ""
        await _webhook_log("not_owner", f"Sender {sender_label} whitelist ({s.owner_number}) se match nahi karta{hint}", payload, sender=msg.sender, text=msg.text, event=event)
        return {"status": "ignored", "reason": "not owner"}
    if msg.message_id:
        try:
            await db.wa_seen.insert_one({"message_id": msg.message_id, "created_at": now_utc()})
        except DuplicateKeyError:
            await _webhook_log("duplicate", "Same message_id dobara aaya (wa.9x retry) — skip", payload, sender=msg.sender, text=msg.text, event=event)
            return {"status": "duplicate"}
    log_id = await _webhook_log("accepted", "Processing…", payload, sender=msg.sender, text=msg.text, event=event)
    # canonical identity = owner phone (replies + pending clarifications always go to the real number, not a LID)
    background.add_task(_process_incoming, s, digits(s.owner_number), msg.text, msg.message_id, log_id)
    return {"status": "accepted"}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _send_owner_text(s: Settings, text: str, log_id: ObjectId):
    try:
        await get_provider(s).send_text(s.owner_number, text)
    except Exception as e:  # noqa: BLE001
        logger.error("pairing reply failed: %s", e)
        await db.wa_webhook_log.update_one({"_id": log_id}, {"$set": {"detail": f"Paired, par reply nahi gaya: {str(e)[:200]}"}})


@api.get("/whatsapp/webhook")
async def whatsapp_webhook_verify(request: Request):
    # some providers verify the URL with GET (echo challenge if present) — token still required
    await _require_webhook_token(request)
    challenge = request.query_params.get("hub.challenge") or request.query_params.get("challenge")
    return Response(content=challenge or "ok", media_type="text/plain")


# ------------------------------------------------------------------ auth/me
@protected.get("/auth/me")
async def me():
    return {"role": "owner"}


# ------------------------------------------------------------------ groups
class GroupBody(BaseModel):
    name: str


@protected.get("/groups")
async def get_groups():
    totals = await group_totals()
    out = []
    async for g in db.groups.find({"deleted_at": None}).sort("created_at", 1):
        grp = Group.from_mongo(g).api()
        grp.update(totals.get(grp["id"], {"ledger_count": 0, "balance": 0.0, "lena": 0.0, "dena": 0.0, "account_balance": None}))
        out.append(grp)
    return out


@protected.post("/groups")
async def create_group(body: GroupBody):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Naam zaroori hai")
    if await db.groups.find_one({"deleted_at": None, "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}):
        raise HTTPException(400, "Ye group already hai")
    g = Group(name=name)
    res = await db.groups.insert_one(g.to_mongo())
    g.id = str(res.inserted_id)
    return g.api()


@protected.patch("/groups/{group_id}")
async def rename_group(group_id: str, body: GroupBody):
    await db.groups.update_one({"_id": oid(group_id)}, {"$set": {"name": body.name.strip()}})
    doc = await db.groups.find_one({"_id": oid(group_id)})
    return Group.from_mongo(doc).api()


@protected.delete("/groups/{group_id}")
async def delete_group(group_id: str):
    if await db.ledgers.count_documents({"group_id": group_id, "deleted_at": None}):
        raise HTTPException(400, "Group mein ledgers hain, pehle unhe move karo")
    await db.groups.update_one({"_id": oid(group_id)}, {"$set": {"deleted_at": now_utc()}})
    return {"ok": True}


# ------------------------------------------------------------------ ledgers
class LedgerCreate(BaseModel):
    name: str
    group_id: str
    aliases: List[str] = []
    kind: Optional[str] = None  # party | cash | bank (default: guessed from name)


class LedgerPatch(BaseModel):
    name: Optional[str] = None
    group_id: Optional[str] = None
    aliases: Optional[List[str]] = None
    kind: Optional[str] = None


class MergeBody(BaseModel):
    target_ledger_id: str


@protected.get("/ledgers")
async def get_ledgers(group_id: Optional[str] = None):
    return [l.api() for l in await list_ledgers(group_id)]


@protected.post("/ledgers")
async def post_ledger(body: LedgerCreate):
    if not body.name.strip():
        raise HTTPException(400, "Naam zaroori hai")
    if not await db.groups.find_one({"_id": oid(body.group_id), "deleted_at": None}):
        raise HTTPException(404, "Group nahi mila")
    if body.kind not in (None, "party", "cash", "bank"):
        raise HTTPException(400, "kind party/cash/bank")
    l = await create_ledger(body.name, body.group_id, body.aliases, kind=body.kind)
    return l.api()


@protected.get("/ledgers/{ledger_id}")
async def get_one_ledger(ledger_id: str):
    l = await get_ledger(ledger_id)
    if not l:
        raise HTTPException(404, "Ledger nahi mila")
    out = l.api()
    g = await db.groups.find_one({"_id": ObjectId(l.group_id)})
    out["group_name"] = g["name"] if g else ""
    return out


@protected.patch("/ledgers/{ledger_id}")
async def patch_ledger(ledger_id: str, body: LedgerPatch):
    upd = {}
    if body.name is not None and body.name.strip():
        upd["name"] = body.name.strip()
        upd["normalized"] = normalize(body.name)
    if body.group_id is not None:
        if not await db.groups.find_one({"_id": oid(body.group_id), "deleted_at": None}):
            raise HTTPException(404, "Group nahi mila")
        upd["group_id"] = body.group_id
    if body.aliases is not None:
        upd["aliases"] = [a.strip() for a in body.aliases if a.strip()]
    if body.kind is not None:
        if body.kind not in ("party", "cash", "bank"):
            raise HTTPException(400, "kind party/cash/bank")
        upd["kind"] = body.kind
    if upd:
        await db.ledgers.update_one({"_id": oid(ledger_id)}, {"$set": upd})
    l = await get_ledger(ledger_id)
    if not l:
        raise HTTPException(404, "Ledger nahi mila")
    return l.api()


@protected.delete("/ledgers/{ledger_id}")
async def delete_ledger(ledger_id: str):
    await db.ledgers.update_one({"_id": oid(ledger_id)}, {"$set": {"deleted_at": now_utc()}})
    await db.transactions.update_many({"ledger_id": ledger_id, "deleted_at": None}, {"$set": {"deleted_at": now_utc()}})
    return {"ok": True}


@protected.post("/ledgers/{ledger_id}/merge")
async def post_merge(ledger_id: str, body: MergeBody):
    try:
        l = await merge_ledgers(ledger_id, body.target_ledger_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return l.api()


@protected.get("/ledgers/{ledger_id}/statement")
async def get_statement(ledger_id: str, month: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None):
    l = await get_ledger(ledger_id)
    if not l:
        raise HTTPException(404, "Ledger nahi mila")
    d_from = d_to = None
    if month:
        y, m = map(int, month.split("-"))
        d_from = day_start(date(y, m, 1))
        nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
        d_to = day_start(nxt)
    if date_from:
        d_from = day_start(date.fromisoformat(date_from))
    if date_to:
        d_to = day_end(date.fromisoformat(date_to))
    stmt = await statement(ledger_id, d_from, d_to)
    stmt["ledger"] = l.api()
    return stmt


class ExportBody(BaseModel):
    format: str = "pdf"  # pdf | excel | csv
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    send_whatsapp: bool = False


@protected.post("/ledgers/{ledger_id}/export")
async def post_export(ledger_id: str, body: ExportBody):
    l = await get_ledger(ledger_id)
    if not l:
        raise HTTPException(404, "Ledger nahi mila")
    if body.format not in ("pdf", "excel", "csv"):
        raise HTTPException(400, "format pdf/excel/csv hona chahiye")
    settings = await get_settings()
    info = await save_export(body.format, l, date.fromisoformat(body.date_from) if body.date_from else None,
                             date.fromisoformat(body.date_to) if body.date_to else None, settings)
    info["sent"] = False
    if body.send_whatsapp:
        try:
            provider = get_provider(settings)
            await provider.send_document(settings.owner_number, info["url"], info["filename"], caption=f"{l.name} ledger")
            info["sent"] = True
        except Exception as e:  # noqa: BLE001
            info["send_error"] = str(e)[:200]
    return info


# ------------------------------------------------------------------ transactions
class TxnCreate(BaseModel):
    ledger_id: str
    amount: float = Field(gt=0)
    direction: str
    note: str = ""
    entry_date: Optional[str] = None
    mode: Optional[str] = "cash"  # party entries: cash | bank | none (no money moved). Account ledgers: the OTHER account kind = transfer.
    tags: List[str] = []


class TransferCreate(BaseModel):
    from_kind: str  # cash | bank
    to_kind: str
    amount: float = Field(gt=0)
    note: str = ""
    entry_date: Optional[str] = None


class TxnPatch(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0)
    direction: Optional[str] = None
    note: Optional[str] = None
    entry_date: Optional[str] = None
    ledger_id: Optional[str] = None
    mode: Optional[str] = "keep"  # keep | cash | bank | none
    tags: Optional[List[str]] = None


@protected.get("/transactions")
async def get_transactions(ledger_id: Optional[str] = None, limit: int = 50):
    q: dict = {"deleted_at": None}
    if ledger_id:
        q["ledger_id"] = ledger_id
    docs = await db.transactions.find(q).sort([("entry_date", -1), ("created_at", -1)]).limit(limit).to_list(limit)
    return [Transaction.from_mongo(d).api() for d in docs]


@protected.post("/transactions")
async def post_transaction(body: TxnCreate):
    if body.direction not in ("debit", "credit"):
        raise HTTPException(400, "direction debit/credit")
    ledger = await get_ledger(body.ledger_id)
    if not ledger:
        raise HTTPException(404, "Ledger nahi mila")
    mode = None if body.mode in (None, "none") or (ledger.is_account and body.mode == ledger.kind) else body.mode
    if mode not in (None, "cash", "bank"):
        raise HTTPException(400, "mode cash/bank/none")
    t = await add_transaction(body.ledger_id, body.amount, body.direction, body.note.strip(), parse_entry_date(body.entry_date), "app", mode=mode, tags=body.tags)
    return t.api()


@protected.post("/transfers")
async def post_transfer(body: TransferCreate):
    """Move money between own accounts (bank→cash / cash→bank); books a linked pair of entries."""
    if body.from_kind not in ACCOUNT_KINDS or body.to_kind not in ACCOUNT_KINDS or body.from_kind == body.to_kind:
        raise HTTPException(400, "from_kind/to_kind cash|bank aur alag hone chahiye")
    txn, from_l, to_l = await transfer(body.from_kind, body.to_kind, body.amount, body.note.strip(), parse_entry_date(body.entry_date), "app")
    from_l, to_l = await get_ledger(from_l.id), await get_ledger(to_l.id)
    return {"txn": txn.api(), "from": from_l.api() if from_l else None, "to": to_l.api() if to_l else None}


@protected.patch("/transactions/{txn_id}")
async def patch_transaction(txn_id: str, body: TxnPatch):
    if body.ledger_id and not await get_ledger(body.ledger_id):
        raise HTTPException(404, "Ledger nahi mila")
    mode = body.mode if body.mode in ("keep", "cash", "bank") else None
    new = await update_transaction(txn_id, amount=body.amount, direction=body.direction, note=body.note,
                                   entry_date=parse_entry_date(body.entry_date) if body.entry_date else None, ledger_id=body.ledger_id, mode=mode, tags=body.tags)
    if not new:
        raise HTTPException(404, "Entry nahi mili")
    return Transaction.from_mongo(new).api()


@protected.delete("/transactions/{txn_id}")
async def delete_transaction_route(txn_id: str):
    if not await delete_transaction(txn_id):
        raise HTTPException(404, "Entry nahi mili")
    return {"ok": True}


@protected.get("/tags")
async def list_tags():
    """Suggested + used expense tags with usage counts (for quick chips in the entry form)."""
    rows = await db.transactions.aggregate([
        {"$match": {"deleted_at": None, "tags": {"$exists": True, "$ne": []}}},
        {"$unwind": "$tags"},
        {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 40},
    ]).to_list(40)
    used = [{"tag": r["_id"], "count": r["count"]} for r in rows]
    seen = {u["tag"] for u in used}
    return used + [{"tag": t, "count": 0} for t in TAG_WORDS if t not in seen]


# ------------------------------------------------------------------ dashboard & summary
@protected.get("/dashboard")
async def dashboard():
    lena = dena = 0.0
    count = 0
    async for l in db.ledgers.find({"deleted_at": None}):
        if l.get("kind", "party") in ACCOUNT_KINDS:
            continue
        count += 1
        b = l.get("current_balance", 0.0)
        if b > 0:
            lena += b
        else:
            dena += abs(b)
    accounts = await account_balances()
    recent_docs = await db.transactions.find({"deleted_at": None}).sort([("created_at", -1)]).limit(24).to_list(24)
    meta = {str(l["_id"]): l for l in await db.ledgers.find({}, {"name": 1, "kind": 1}).to_list(5000)}
    recent = []
    for d in recent_docs:
        lm = meta.get(d["ledger_id"], {})
        if d.get("contra_txn_id") and lm.get("kind", "party") in ACCOUNT_KINDS:
            continue  # auto-booked cash/bank side of a party entry — the party row already shows "via Cash"
        t = Transaction.from_mongo(d).api()
        t["ledger_name"] = lm.get("name", "?")
        t["ledger_kind"] = lm.get("kind", "party")
        if t.get("contra_ledger_id"):
            t["via"] = meta.get(t["contra_ledger_id"], {}).get("name")
        recent.append(t)
        if len(recent) >= 8:
            break
    return {"total_lena": round(lena, 2), "total_dena": round(dena, 2), "ledger_count": count, "recent": recent,
            "cash_in_hand": accounts["cash"], "bank_balance": accounts["bank"], "accounts": accounts["accounts"]}


@protected.get("/summary/monthly")
async def monthly_summary(month: str):
    y, m = map(int, month.split("-"))
    start = day_start(date(y, m, 1))
    end = day_start(date(y + (m == 12), 1 if m == 12 else m + 1, 1))
    pipeline = [
        {"$match": {"deleted_at": None, "entry_date": {"$gte": start, "$lt": end}}},
        {"$group": {"_id": "$ledger_id",
                    "debit": {"$sum": {"$cond": [{"$eq": ["$direction", "debit"]}, "$amount", 0]}},
                    "credit": {"$sum": {"$cond": [{"$eq": ["$direction", "credit"]}, "$amount", 0]}},
                    "count": {"$sum": 1}}},
    ]
    rows = await db.transactions.aggregate(pipeline).to_list(5000)
    ledgers = {str(l["_id"]): l for l in await db.ledgers.find({}).to_list(5000)}
    groups = {str(g["_id"]): g["name"] for g in await db.groups.find({}).to_list(500)}
    # expense categories (tags): where the money actually went this month — party entries + direct account entries,
    # skipping the auto-booked account side of a pair so nothing is counted twice
    cat: dict = {}
    async for t in db.transactions.find({"deleted_at": None, "entry_date": {"$gte": start, "$lt": end}}, {"ledger_id": 1, "amount": 1, "direction": 1, "tags": 1, "contra_txn_id": 1}):
        l = ledgers.get(t["ledger_id"])
        if not l:
            continue
        is_acct = l.get("kind", "party") in ACCOUNT_KINDS
        if is_acct and t.get("contra_txn_id"):
            continue
        money_out = (t["direction"] == "credit") if is_acct else (t["direction"] == "debit")
        for tag in (t.get("tags") or ["(no tag)"]):
            c = cat.setdefault(tag, {"tag": tag, "out": 0.0, "in": 0.0, "count": 0})
            c["out" if money_out else "in"] = round(c["out" if money_out else "in"] + t["amount"], 2)
            c["count"] += 1
    categories = sorted(cat.values(), key=lambda c: (c["tag"] == "(no tag)", -c["out"]))
    by_group: dict = {}
    ledger_rows = []
    account_rows = []
    for r in rows:
        l = ledgers.get(r["_id"])
        if not l:
            continue
        if l.get("kind", "party") in ACCOUNT_KINDS:
            # money accounts: debit = in, credit = out — shown separately, not mixed into party Dr/Cr totals
            account_rows.append({"ledger_id": r["_id"], "ledger_name": l["name"], "kind": l["kind"], "in": round(r["debit"], 2), "out": round(r["credit"], 2),
                                 "net": round(r["debit"] - r["credit"], 2), "count": r["count"], "current_balance": l.get("current_balance", 0.0)})
            continue
        gname = groups.get(l["group_id"], "General")
        g = by_group.setdefault(l["group_id"], {"group_id": l["group_id"], "group_name": gname, "debit": 0.0, "credit": 0.0, "count": 0})
        g["debit"] = round(g["debit"] + r["debit"], 2)
        g["credit"] = round(g["credit"] + r["credit"], 2)
        g["count"] += r["count"]
        ledger_rows.append({"ledger_id": r["_id"], "ledger_name": l["name"], "group_name": gname, "debit": round(r["debit"], 2),
                            "credit": round(r["credit"], 2), "net": round(r["debit"] - r["credit"], 2), "count": r["count"],
                            "current_balance": l.get("current_balance", 0.0)})
    ledger_rows.sort(key=lambda x: -(x["debit"] + x["credit"]))
    total_debit = round(sum(g["debit"] for g in by_group.values()), 2)
    total_credit = round(sum(g["credit"] for g in by_group.values()), 2)
    return {"month": month, "total_debit": total_debit, "total_credit": total_credit, "net": round(total_debit - total_credit, 2),
            "groups": sorted(by_group.values(), key=lambda g: -(g["debit"] + g["credit"])), "ledgers": ledger_rows, "accounts": account_rows,
            "categories": categories}


# ------------------------------------------------------------------ settings
class SettingsPatch(BaseModel):
    owner_number: Optional[str] = None
    owner_email: Optional[str] = None
    alerts_enabled: Optional[bool] = None
    emergent_llm_key: Optional[str] = None
    emergent_email_key: Optional[str] = None
    provider: Optional[str] = None
    wa9x_base_url: Optional[str] = None
    wa9x_api_key: Optional[str] = None
    wa9x_instance_id: Optional[str] = None
    wa9x_webhook_secret: Optional[str] = None
    public_base_url: Optional[str] = None


class PinChange(BaseModel):
    old_pin: str
    new_pin: str = Field(pattern=r"^\d{4,8}$")


SECRET_FIELDS = ("emergent_llm_key", "emergent_email_key", "wa9x_api_key", "wa9x_webhook_secret")


def webhook_url(s: Settings) -> str:
    return f"{public_base_url(s)}/api/whatsapp/webhook?token={s.webhook_secret}"


def settings_api(s: Settings) -> dict:
    d = s.api()
    d.pop("pin_hash", None)
    d.pop("webhook_secret", None)
    d.pop("pairing_code", None)
    d.pop("pairing_expires_at", None)
    for f in SECRET_FIELDS:
        val = d.pop(f, "") or ""
        d[f"has_{f}"] = bool(val)
        d[f"{f}_hint"] = f"••••{val[-4:]}" if val else ""
    d["ai_configured"] = bool(s.emergent_llm_key or os.environ.get("EMERGENT_LLM_KEY"))
    d["email_configured"] = bool((s.emergent_email_key or os.environ.get("EMERGENT_EMAIL_KEY")) and s.owner_email)
    d["webhook_url"] = webhook_url(s)
    d["configured"] = wa_configured(s)
    return d


@protected.get("/settings")
async def get_settings_route():
    return settings_api(await get_settings())


@protected.put("/settings")
async def put_settings(body: SettingsPatch):
    upd = {k: v.strip() if isinstance(v, str) else v for k, v in body.model_dump(exclude_none=True).items()}
    if "provider" in upd and upd["provider"] not in ("mock", "wa9x"):
        raise HTTPException(400, "provider mock/wa9x")
    if "owner_email" in upd and upd["owner_email"] and "@" not in upd["owner_email"]:
        raise HTTPException(400, "Sahi email daalo")
    for f in SECRET_FIELDS:  # empty = unchanged, "-" = clear
        if f in upd:
            if upd[f] == "":
                upd.pop(f)
            elif upd[f] == "-":
                upd[f] = ""
    upd["updated_at"] = now_utc()
    await db.settings.update_one({"key": "main"}, {"$set": upd})
    return settings_api(await get_settings())


@protected.post("/settings/test-email")
async def test_email():
    s = await get_settings()
    if not s.owner_email:
        raise HTTPException(400, "Owner email set karo")
    r = await send_alert("test", "Test alert — email chal rahi hai", ["Ye test email hai. Alerts is address pe aayenge:", s.owner_email], force=True)
    if not r.get("ok"):
        # 400 (not 5xx) so the real provider reason reaches the app through CDN edges
        raise HTTPException(400, f"Email nahi gaya: {r.get('error') or r.get('skipped')}")
    return r


@protected.get("/alerts")
async def list_alerts(limit: int = 20):
    docs = await db.alerts.find({}, {"_id": 0}).sort("sent_at", -1).limit(limit).to_list(limit)
    for d in docs:
        d["sent_at"] = d["sent_at"].isoformat() if hasattr(d["sent_at"], "isoformat") else d["sent_at"]
    return docs


@protected.put("/settings/pin")
async def change_pin(body: PinChange):
    s = await get_settings()
    if not verify_pin(body.old_pin, s.pin_hash):
        raise HTTPException(401, "Purana PIN galat hai")
    if body.new_pin in ("1234", "0000", "1111", "123456", "000000", "111111"):
        raise HTTPException(400, "Ye PIN bahut common hai — koi aur chuno")
    # all existing tokens are revoked (see auth.current_owner); the client re-logs in
    await db.settings.update_one({"key": "main"}, {"$set": {"pin_hash": hash_pin(body.new_pin), "pin_changed_at": now_utc(), "updated_at": now_utc()}})
    return {"ok": True, "relogin": True}


@protected.post("/settings/rotate-webhook-secret")
async def rotate_webhook_secret():
    await db.settings.update_one({"key": "main"}, {"$set": {"webhook_secret": secrets.token_urlsafe(24), "updated_at": now_utc()}})
    return settings_api(await get_settings())


# ------------------------------------------------------------------ whatsapp (app side)
class SimulateBody(BaseModel):
    text: str


@protected.post("/whatsapp/simulate")
async def simulate(body: SimulateBody):
    s = await get_settings()
    result = await handle_message(s.owner_number, body.text.strip(), None, source="simulate")
    return result


@protected.get("/whatsapp/messages")
async def wa_messages(limit: int = 50):
    docs = await db.wa_messages.find({}).sort("created_at", -1).limit(limit).to_list(limit)
    return [WaMessage.from_mongo(d).api() for d in docs][::-1]


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


@protected.get("/whatsapp/status")
async def wa_status():
    s = await get_settings()
    pending = await db.pending.find_one({})
    last = await db.wa_messages.find_one({"source": "whatsapp"}, sort=[("created_at", -1)])
    last_hook = await db.wa_webhook_log.find_one({}, sort=[("received_at", -1)])
    since = now_utc() - timedelta(hours=24)
    hits_24h = await db.wa_webhook_log.count_documents({"received_at": {"$gte": since}})
    return {"provider": s.provider, "configured": wa_configured(s), "owner_number": s.owner_number, "owner_ids": s.owner_ids or [],
            "pairing_code": s.pairing_code if s.pairing_code and s.pairing_expires_at and _aware(s.pairing_expires_at) > now_utc() else None,
            "pairing_expires_at": _iso(s.pairing_expires_at) if s.pairing_code else None,
            "webhook_url": webhook_url(s), "pending_question": pending["question"] if pending else None,
            "last_whatsapp_at": _iso(last["created_at"]) if last else None,
            "last_webhook_at": _iso(last_hook["received_at"]) if last_hook else None,
            "last_webhook_outcome": last_hook["outcome"] if last_hook else None,
            "webhook_hits_24h": hits_24h}


@protected.post("/whatsapp/pairing-code")
async def wa_pairing_code():
    """One-time 6-digit code (15 min). Owner sends it from WhatsApp to the bot → that sender id gets whitelisted (LID pairing)."""
    code = f"{secrets.randbelow(900000) + 100000}"
    exp = now_utc() + timedelta(minutes=15)
    await db.settings.update_one({"key": "main"}, {"$set": {"pairing_code": code, "pairing_expires_at": exp, "updated_at": now_utc()}})
    return {"code": code, "expires_at": exp.isoformat()}


@protected.delete("/whatsapp/owner-ids/{sender_id}")
async def wa_remove_owner_id(sender_id: str):
    await db.settings.update_one({"key": "main"}, {"$pull": {"owner_ids": sender_id}, "$set": {"updated_at": now_utc()}})
    return {"owner_ids": (await get_settings()).owner_ids}


@protected.get("/whatsapp/webhook-log")
async def wa_webhook_log(limit: int = 20):
    limit = max(1, min(limit, 100))
    docs = await db.wa_webhook_log.find({}).sort("received_at", -1).limit(limit).to_list(limit)
    out = []
    for d in docs:
        out.append({"id": str(d["_id"]), "received_at": _iso(d["received_at"]), "processed_at": _iso(d.get("processed_at")), "outcome": d["outcome"],
                    "detail": d.get("detail", ""), "sender": d.get("sender", ""), "text": d.get("text", ""), "event": d.get("event", ""), "raw": d.get("raw", "")})
    return out


@protected.post("/whatsapp/check-connection")
async def wa_check_connection():
    """Owner-triggered diagnostics: list wa.9x sessions + send a test WhatsApp to the owner number."""
    s = await get_settings()
    if s.provider != "wa9x":
        raise HTTPException(400, "Provider 'wa.9x live' select karo aur Save karo, phir test karo")
    if not wa_configured(s):
        raise HTTPException(400, "wa.9x API key set nahi hai — Settings → WhatsApp mein daalo")
    p = Wa9xProvider(s)
    out: dict = {"base_url": p.base, "sessions": [], "sessions_raw": "", "sessions_error": None, "sent": False, "send_error": None}
    try:
        sess, raw = await p.sessions()
        out["sessions_raw"] = raw
        out["sessions"] = [{"name": x.get("name"), "status": x.get("status"), "phone": x.get("phone") or x.get("number"), "id": x.get("id")} for x in sess if isinstance(x, dict)]
    except Exception as e:  # noqa: BLE001
        out["sessions_error"] = (str(e) or type(e).__name__)[:300]
    try:
        await p.send_text(s.owner_number, "✅ Munsiji connected! Ab yahan hisab likho — e.g. \"Biki mill ko 5000 diya\"")
        out["sent"] = True
    except Exception as e:  # noqa: BLE001
        out["send_error"] = (str(e) or type(e).__name__)[:300]
    return out


@protected.delete("/whatsapp/pending")
async def clear_pending():
    await db.pending.delete_many({})
    return {"ok": True}


# ------------------------------------------------------------------ system (self-host updates)
class AutoUpdateBody(BaseModel):
    enabled: bool


@protected.get("/system/version")
async def system_version(force: bool = False):
    return await system.version_info(force=force)


@protected.post("/system/update")
async def system_update():
    if not system.supported():
        raise HTTPException(400, "Update sirf self-hosted VPS install pe available hai")
    if system.is_busy():
        raise HTTPException(409, "Update already chal raha hai")
    return system.request_update()


@protected.put("/system/auto-update")
async def system_auto_update(body: AutoUpdateBody):
    if not system.supported():
        raise HTTPException(400, "Sirf self-hosted VPS install pe available hai")
    return {"auto_update": system.set_auto_update(body.enabled)}


app.include_router(api)
app.include_router(protected)
# Bearer tokens only (no cookies) -> no credentials needed for CORS
app.add_middleware(CORSMiddleware, allow_credentials=False, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    return response
