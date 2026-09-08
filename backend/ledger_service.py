"""Ledger domain logic: normalization, fuzzy matching, balances, statements, merge."""
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from bson import ObjectId
from rapidfuzz import fuzz

from db import db
from models import Group, Ledger, Transaction, now_utc

DEFAULT_GROUPS = ["Investment", "Staff", "Expenses", "Personal", "General"]
DEFAULT_GROUP = "General"


def normalize(name: str) -> str:
    s = (name or "").lower()
    s = re.sub(r"[\[\]\(\)\{\}]", " ", s)
    s = re.sub(r"[^a-z0-9\u0900-\u097F ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def fmt_inr(amount: float) -> str:
    amount = round(abs(amount), 2)
    whole = int(amount)
    frac = round(amount - whole, 2)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    if frac:
        s += f"{frac:.2f}"[1:]
    return "₹" + s


def balance_text(balance: float) -> str:
    if balance > 0.004:
        return f"{fmt_inr(balance)} lena hai"
    if balance < -0.004:
        return f"{fmt_inr(balance)} dena hai"
    return "₹0 (settled)"


# ---------------------------------------------------------------- groups
async def ensure_default_groups():
    count = await db.groups.count_documents({"deleted_at": None})
    if count == 0:
        for name in DEFAULT_GROUPS:
            await db.groups.insert_one(Group(name=name).to_mongo())


async def get_or_create_group(name: Optional[str]) -> Group:
    target = (name or DEFAULT_GROUP).strip()
    groups = [Group.from_mongo(g) async for g in db.groups.find({"deleted_at": None})]
    best, best_score = None, 0
    for g in groups:
        score = fuzz.ratio(normalize(g.name), normalize(target))
        if score > best_score:
            best, best_score = g, score
    if best and best_score >= 80:
        return best
    res = await db.groups.insert_one(Group(name=target.title()).to_mongo())
    doc = await db.groups.find_one({"_id": res.inserted_id})
    return Group.from_mongo(doc)


# ---------------------------------------------------------------- ledgers
async def list_ledgers(group_id: Optional[str] = None) -> List[Ledger]:
    q: dict = {"deleted_at": None}
    if group_id:
        q["group_id"] = group_id
    return [Ledger.from_mongo(d) async for d in db.ledgers.find(q).sort("name", 1)]


async def get_ledger(ledger_id: str) -> Optional[Ledger]:
    if not ObjectId.is_valid(ledger_id):
        return None
    doc = await db.ledgers.find_one({"_id": ObjectId(ledger_id), "deleted_at": None})
    return Ledger.from_mongo(doc) if doc else None


def score_ledger(ledger: Ledger, query: str) -> int:
    q = normalize(query)
    if not q:
        return 0
    candidates = [ledger.normalized] + [normalize(a) for a in ledger.aliases]
    best = 0
    for c in candidates:
        if not c:
            continue
        if c == q:
            return 100
        s = max(fuzz.ratio(c, q), fuzz.token_set_ratio(c, q) - 5, fuzz.partial_ratio(c, q) - 12)
        best = max(best, int(s))
    return best


async def fuzzy_match(query: str, ledgers: Optional[List[Ledger]] = None) -> List[Tuple[Ledger, int]]:
    """Return ledgers sorted by similarity score (desc)."""
    ledgers = ledgers if ledgers is not None else await list_ledgers()
    scored = [(l, score_ledger(l, query)) for l in ledgers]
    scored = [x for x in scored if x[1] >= 50]
    scored.sort(key=lambda x: -x[1])
    return scored


async def create_ledger(name: str, group_id: str, aliases: Optional[List[str]] = None) -> Ledger:
    name = re.sub(r"\s+", " ", name.strip())
    ledger = Ledger(name=name, normalized=normalize(name), group_id=group_id, aliases=aliases or [])
    res = await db.ledgers.insert_one(ledger.to_mongo())
    ledger.id = str(res.inserted_id)
    return ledger


async def add_alias(ledger: Ledger, alias: str):
    n = normalize(alias)
    if n and n != ledger.normalized and n not in [normalize(a) for a in ledger.aliases]:
        await db.ledgers.update_one({"_id": ObjectId(ledger.id)}, {"$addToSet": {"aliases": alias.strip()}})


# ---------------------------------------------------------------- balances
async def recalc_balance(ledger_id: str) -> float:
    pipeline = [
        {"$match": {"ledger_id": ledger_id, "deleted_at": None}},
        {
            "$group": {
                "_id": None,
                "debit": {"$sum": {"$cond": [{"$eq": ["$direction", "debit"]}, "$amount", 0]}},
                "credit": {"$sum": {"$cond": [{"$eq": ["$direction", "credit"]}, "$amount", 0]}},
            }
        },
    ]
    rows = await db.transactions.aggregate(pipeline).to_list(1)
    bal = round((rows[0]["debit"] - rows[0]["credit"]) if rows else 0.0, 2)
    await db.ledgers.update_one({"_id": ObjectId(ledger_id)}, {"$set": {"current_balance": bal}})
    return bal


async def add_transaction(
    ledger_id: str,
    amount: float,
    direction: str,
    note: str,
    entry_date: datetime,
    source: str,
    wa_message_id: Optional[str] = None,
    sender: Optional[str] = None,
) -> Transaction:
    txn = Transaction(
        ledger_id=ledger_id,
        amount=round(float(amount), 2),
        direction=direction,
        note=note or "",
        entry_date=entry_date,
        source=source,
        wa_message_id=wa_message_id,
        sender=sender,
    )
    res = await db.transactions.insert_one(txn.to_mongo())
    txn.id = str(res.inserted_id)
    await recalc_balance(ledger_id)
    return txn


async def statement(ledger_id: str, date_from: Optional[datetime] = None, date_to: Optional[datetime] = None) -> dict:
    """Tally-style statement with opening balance and running balance."""
    q: dict = {"ledger_id": ledger_id, "deleted_at": None}
    opening = 0.0
    if date_from:
        rows = await db.transactions.aggregate(
            [
                {"$match": {**q, "entry_date": {"$lt": date_from}}},
                {
                    "$group": {
                        "_id": None,
                        "d": {"$sum": {"$cond": [{"$eq": ["$direction", "debit"]}, "$amount", 0]}},
                        "c": {"$sum": {"$cond": [{"$eq": ["$direction", "credit"]}, "$amount", 0]}},
                    }
                },
            ]
        ).to_list(1)
        opening = round((rows[0]["d"] - rows[0]["c"]) if rows else 0.0, 2)
        q["entry_date"] = {"$gte": date_from}
    if date_to:
        q.setdefault("entry_date", {})["$lte"] = date_to
    cursor = db.transactions.find(q).sort([("entry_date", 1), ("created_at", 1)])
    running = opening
    total_debit = total_credit = 0.0
    rows_out = []
    async for d in cursor:
        t = Transaction.from_mongo(d)
        if t.direction == "debit":
            running += t.amount
            total_debit += t.amount
        else:
            running -= t.amount
            total_credit += t.amount
        row = t.api()
        row["running_balance"] = round(running, 2)
        rows_out.append(row)
    return {
        "opening_balance": opening,
        "closing_balance": round(running, 2),
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "rows": rows_out,
    }


async def merge_ledgers(source_id: str, target_id: str) -> Ledger:
    source = await get_ledger(source_id)
    target = await get_ledger(target_id)
    if not source or not target or source_id == target_id:
        raise ValueError("Invalid ledgers for merge")
    await db.transactions.update_many({"ledger_id": source_id}, {"$set": {"ledger_id": target_id, "updated_at": now_utc()}})
    aliases = list({*target.aliases, source.name, *source.aliases})
    await db.ledgers.update_one({"_id": ObjectId(target_id)}, {"$set": {"aliases": aliases}})
    await db.ledgers.update_one({"_id": ObjectId(source_id)}, {"$set": {"deleted_at": now_utc(), "current_balance": 0}})
    await recalc_balance(target_id)
    return await get_ledger(target_id)


async def group_totals() -> dict:
    """Return {group_id: {ledger_count, balance, lena, dena}} for live ledgers."""
    out: dict = {}
    async for d in db.ledgers.find({"deleted_at": None}):
        g = out.setdefault(d["group_id"], {"ledger_count": 0, "balance": 0.0, "lena": 0.0, "dena": 0.0})
        bal = d.get("current_balance", 0.0)
        g["ledger_count"] += 1
        g["balance"] = round(g["balance"] + bal, 2)
        if bal > 0:
            g["lena"] = round(g["lena"] + bal, 2)
        else:
            g["dena"] = round(g["dena"] + abs(bal), 2)
    return out


def to_utc(d: datetime) -> datetime:
    if d.tzinfo is None:
        return d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)
