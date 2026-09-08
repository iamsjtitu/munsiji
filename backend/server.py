import logging
import os
from datetime import date, datetime, timezone
from typing import List, Optional

from bson import ObjectId
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from ai_parser import IST  # noqa: E402
from auth import check_lockout, current_owner, hash_pin, make_token, record_fail, record_success, verify_pin  # noqa: E402
from bot import day_end, day_start, get_settings, handle_message, ist_datetime_for, public_base_url, save_export  # noqa: E402
from db import client, db  # noqa: E402
from ledger_service import (  # noqa: E402
    create_ledger,
    ensure_default_groups,
    get_ledger,
    group_totals,
    list_ledgers,
    merge_ledgers,
    normalize,
    recalc_balance,
    statement,
)
from models import Group, Ledger, Settings, Transaction, WaMessage, now_utc  # noqa: E402
from wa_provider import ProviderNotConfigured, get_provider, parse_incoming  # noqa: E402

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
    if not await db.settings.find_one({"key": "main"}):
        s = Settings(owner_number=os.environ["OWNER_WHATSAPP"], pin_hash=hash_pin(os.environ["OWNER_PIN"]))
        await db.settings.insert_one(s.to_mongo())
    await ensure_default_groups()


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
    pin: str = Field(pattern=r"^\d{4,6}$")


@api.get("/health")
async def health():
    return {"ok": True}


@api.post("/auth/login")
async def login(body: LoginBody):
    check_lockout()
    s = await get_settings()
    if not verify_pin(body.pin, s.pin_hash):
        record_fail()
        raise HTTPException(status_code=401, detail="Galat PIN")
    record_success()
    return {"access_token": make_token(), "token_type": "bearer"}


@api.get("/files/{file_id}")
async def get_file(file_id: str):
    doc = await db.export_files.find_one({"_id": oid(file_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")
    return Response(content=bytes(doc["data"]), media_type=doc["content_type"],
                    headers={"Content-Disposition": f'attachment; filename="{doc["filename"]}"'})


@api.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        form = await request.form()
        payload = dict(form)
    msg = parse_incoming(payload)
    if not msg:
        return {"status": "ignored", "reason": "no text message"}
    result = await handle_message(msg.sender, msg.text, msg.message_id, source="whatsapp")
    if result["reply"]:
        settings = await get_settings()
        provider = get_provider(settings)
        try:
            await provider.send_text(msg.sender, result["reply"])
            for f in result["files"]:
                await provider.send_document(msg.sender, f["url"], f["filename"], caption=f["filename"])
        except (ProviderNotConfigured, Exception) as e:  # noqa: BLE001
            logger.error("send failed: %s", e)
            await db.wa_messages.update_many({"wa_message_id": msg.message_id} if msg.message_id else {"sender": msg.sender, "text": msg.text},
                                             {"$set": {"status": "send_failed", "send_error": str(e)[:300]}})
            result["status"] = "send_failed"
    return {"status": result["status"]}


@api.get("/whatsapp/webhook")
async def whatsapp_webhook_verify(request: Request):
    # some providers verify the URL with GET (echo challenge if present)
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
        grp.update(totals.get(grp["id"], {"ledger_count": 0, "balance": 0.0, "lena": 0.0, "dena": 0.0}))
        out.append(grp)
    return out


@protected.post("/groups")
async def create_group(body: GroupBody):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Naam zaroori hai")
    if await db.groups.find_one({"deleted_at": None, "name": {"$regex": f"^{name}$", "$options": "i"}}):
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


class LedgerPatch(BaseModel):
    name: Optional[str] = None
    group_id: Optional[str] = None
    aliases: Optional[List[str]] = None


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
    l = await create_ledger(body.name, body.group_id, body.aliases)
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


class TxnPatch(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0)
    direction: Optional[str] = None
    note: Optional[str] = None
    entry_date: Optional[str] = None
    ledger_id: Optional[str] = None


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
    if not await get_ledger(body.ledger_id):
        raise HTTPException(404, "Ledger nahi mila")
    t = Transaction(ledger_id=body.ledger_id, amount=round(body.amount, 2), direction=body.direction, note=body.note.strip(),
                    entry_date=parse_entry_date(body.entry_date), source="app")
    res = await db.transactions.insert_one(t.to_mongo())
    t.id = str(res.inserted_id)
    await recalc_balance(body.ledger_id)
    return t.api()


@protected.patch("/transactions/{txn_id}")
async def patch_transaction(txn_id: str, body: TxnPatch):
    doc = await db.transactions.find_one({"_id": oid(txn_id), "deleted_at": None})
    if not doc:
        raise HTTPException(404, "Entry nahi mili")
    upd: dict = {"updated_at": now_utc()}
    if body.amount is not None:
        upd["amount"] = round(body.amount, 2)
    if body.direction in ("debit", "credit"):
        upd["direction"] = body.direction
    if body.note is not None:
        upd["note"] = body.note.strip()
    if body.entry_date:
        upd["entry_date"] = parse_entry_date(body.entry_date)
    if body.ledger_id and body.ledger_id != doc["ledger_id"]:
        if not await get_ledger(body.ledger_id):
            raise HTTPException(404, "Ledger nahi mila")
        upd["ledger_id"] = body.ledger_id
    await db.transactions.update_one({"_id": doc["_id"]}, {"$set": upd})
    await recalc_balance(doc["ledger_id"])
    if upd.get("ledger_id"):
        await recalc_balance(upd["ledger_id"])
    new = await db.transactions.find_one({"_id": doc["_id"]})
    return Transaction.from_mongo(new).api()


@protected.delete("/transactions/{txn_id}")
async def delete_transaction(txn_id: str):
    doc = await db.transactions.find_one({"_id": oid(txn_id), "deleted_at": None})
    if not doc:
        raise HTTPException(404, "Entry nahi mili")
    await db.transactions.update_one({"_id": doc["_id"]}, {"$set": {"deleted_at": now_utc()}})
    await recalc_balance(doc["ledger_id"])
    return {"ok": True}


# ------------------------------------------------------------------ dashboard & summary
@protected.get("/dashboard")
async def dashboard():
    lena = dena = 0.0
    count = 0
    async for l in db.ledgers.find({"deleted_at": None}):
        count += 1
        b = l.get("current_balance", 0.0)
        if b > 0:
            lena += b
        else:
            dena += abs(b)
    recent_docs = await db.transactions.find({"deleted_at": None}).sort([("created_at", -1)]).limit(8).to_list(8)
    names = {str(l["_id"]): l["name"] for l in await db.ledgers.find({}, {"name": 1}).to_list(5000)}
    recent = []
    for d in recent_docs:
        t = Transaction.from_mongo(d).api()
        t["ledger_name"] = names.get(t["ledger_id"], "?")
        recent.append(t)
    return {"total_lena": round(lena, 2), "total_dena": round(dena, 2), "ledger_count": count, "recent": recent}


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
    by_group: dict = {}
    ledger_rows = []
    for r in rows:
        l = ledgers.get(r["_id"])
        if not l:
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
            "groups": sorted(by_group.values(), key=lambda g: -(g["debit"] + g["credit"])), "ledgers": ledger_rows}


# ------------------------------------------------------------------ settings
class SettingsPatch(BaseModel):
    owner_number: Optional[str] = None
    provider: Optional[str] = None
    wa9x_base_url: Optional[str] = None
    wa9x_api_key: Optional[str] = None
    wa9x_instance_id: Optional[str] = None
    wa9x_send_path: Optional[str] = None
    wa9x_send_doc_path: Optional[str] = None
    public_base_url: Optional[str] = None


class PinChange(BaseModel):
    old_pin: str
    new_pin: str = Field(pattern=r"^\d{4,6}$")


def settings_api(s: Settings) -> dict:
    d = s.api()
    d.pop("pin_hash", None)
    d["webhook_url"] = f"{public_base_url(s)}/api/whatsapp/webhook"
    d["configured"] = bool(s.wa9x_base_url and s.wa9x_api_key)
    return d


@protected.get("/settings")
async def get_settings_route():
    return settings_api(await get_settings())


@protected.put("/settings")
async def put_settings(body: SettingsPatch):
    upd = {k: v.strip() if isinstance(v, str) else v for k, v in body.model_dump(exclude_none=True).items()}
    if "provider" in upd and upd["provider"] not in ("mock", "wa9x"):
        raise HTTPException(400, "provider mock/wa9x")
    upd["updated_at"] = now_utc()
    await db.settings.update_one({"key": "main"}, {"$set": upd})
    return settings_api(await get_settings())


@protected.put("/settings/pin")
async def change_pin(body: PinChange):
    s = await get_settings()
    if not verify_pin(body.old_pin, s.pin_hash):
        raise HTTPException(401, "Purana PIN galat hai")
    await db.settings.update_one({"key": "main"}, {"$set": {"pin_hash": hash_pin(body.new_pin), "updated_at": now_utc()}})
    return {"ok": True}


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


@protected.get("/whatsapp/status")
async def wa_status():
    s = await get_settings()
    pending = await db.pending.find_one({})
    last = await db.wa_messages.find_one({"source": "whatsapp"}, sort=[("created_at", -1)])
    return {"provider": s.provider, "configured": bool(s.wa9x_base_url and s.wa9x_api_key), "owner_number": s.owner_number,
            "webhook_url": f"{public_base_url(s)}/api/whatsapp/webhook", "pending_question": pending["question"] if pending else None,
            "last_whatsapp_at": last["created_at"].isoformat() if last else None}


@protected.delete("/whatsapp/pending")
async def clear_pending():
    await db.pending.delete_many({})
    return {"ok": True}


app.include_router(api)
app.include_router(protected)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
