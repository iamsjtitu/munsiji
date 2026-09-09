"""Ledger domain logic: normalization, fuzzy matching, balances, statements, merge."""
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from bson import ObjectId
from rapidfuzz import fuzz

from db import db
from models import ACCOUNT_KINDS, Group, Ledger, Transaction, now_utc

DEFAULT_GROUPS = ["Investment", "Staff", "Expenses", "Personal", "General"]
DEFAULT_GROUP = "General"
ACCOUNTS_GROUP = "Accounts"  # home of Cash / Bank ledgers

CASH_NAMES = {"cash", "cash in hand", "cash account", "nakad", "nagad", "rokad", "rokda", "cash book", "cashbook", "haath", "petty cash"}
BANK_WORDS = ("bank", "sbi", "hdfc", "icici", "axis", "pnb", "kotak", "bob", "canara", "union bank", "current account", "saving", "upi", "paytm", "gpay", "phonepe")
BANK_MODE_WORDS = ("bank", "upi", "gpay", "google pay", "phonepe", "phone pe", "paytm", "neft", "imps", "rtgs", "cheque", "check", "chq", "online", "transfer", "net banking", "netbanking", "account se", "a/c", "acc se", "bhim")
NO_MONEY_WORDS = ("opening balance", "opening bal", "op bal", "maal", "goods", "samaan", "saman", "bill", "invoice", "bori", "bag", "quintal", "kg", "ton", "bhada", "credit sale", "udhaar maal")

# expense categories: canonical tag -> trigger words (Hinglish + English)
TAG_WORDS = {
    "petrol": ("petrol", "diesel", "fuel", "cng", "tel"),
    "staff": ("salary", "staff", "wages", "mazdoori", "majdoori", "labour", "labor", "tankha", "advance salary"),
    "bijli": ("bijli", "electricity", "electric", "light bill", "current bill", "power bill"),
    "rent": ("rent", "kiraya", "bhada", "bhaada"),
    "maal": ("maal", "goods", "purchase", "kharid", "stock", "samaan", "saman", "bori", "quintal"),
    "transport": ("transport", "truck", "tempo", "gaadi bhada", "freight", "loading", "unloading", "courier"),
    "khana": ("khana", "food", "chai", "nashta", "lunch", "dinner", "hotel", "tiffin"),
    "repair": ("repair", "maintenance", "servicing", "mistri", "mechanic", "spare"),
    "tax": ("tax", "gst", "tds", "challan", "fine"),
    "byaj": ("interest", "byaj", "vyaj", "emi"),
    "mobile": ("mobile", "recharge", "internet", "wifi", "phone bill"),
    "personal": ("personal", "ghar", "home", "family", "shaadi", "gift", "medical", "doctor", "dawai", "school", "fees"),
}


def normalize_tags(tags) -> List[str]:
    out: List[str] = []
    for t in tags or []:
        s = re.sub(r"[^a-z0-9\u0900-\u097F ]+", " ", str(t).lower().strip().lstrip("#"))
        s = re.sub(r"\s+", " ", s).strip()
        if s and s not in out:
            out.append(s[:24])
    return out[:5]


def detect_tags(text: str, note: str = "") -> List[str]:
    """Keyword fallback for expense categories when the AI didn't tag the entry."""
    low = f" {text} {note} ".lower()
    found = [tag for tag, words in TAG_WORDS.items() if any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", low) for w in words)]
    return found[:3]


def normalize(name: str) -> str:
    s = (name or "").lower()
    s = re.sub(r"[\[\]\(\)\{\}]", " ", s)
    s = re.sub(r"[^a-z0-9\u0900-\u097F ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def guess_kind(name: str) -> str:
    """Ledger name → party | cash | bank (so 'Cash' / 'SBI Bank' created from WhatsApp become money accounts automatically)."""
    n = normalize(name)
    if not n:
        return "party"
    if n in CASH_NAMES or n.startswith("cash "):
        return "cash"
    if any(w in n.split() or w in n for w in BANK_WORDS):
        return "bank"
    return "party"


def detect_mode(text: str, note: str = "") -> Optional[str]:
    """How the money moved for a PARTY entry: 'cash' (default) | 'bank' | None (no money moved: opening balance, goods on credit)."""
    low = f"{text} {note}".lower()
    if any(w in low for w in NO_MONEY_WORDS):
        return None
    if any(w in low for w in BANK_MODE_WORDS):
        return "bank"
    return "cash"


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


def balance_text(balance: float, kind: str = "party") -> str:
    if kind in ACCOUNT_KINDS:
        label = "cash in hand" if kind == "cash" else "bank balance"
        if balance < -0.004:
            return f"{fmt_inr(balance)} minus ({label})"
        return f"{fmt_inr(balance)} {label}"
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


async def create_ledger(name: str, group_id: str, aliases: Optional[List[str]] = None, kind: Optional[str] = None) -> Ledger:
    name = re.sub(r"\s+", " ", name.strip())
    kind = kind or guess_kind(name)
    if kind in ACCOUNT_KINDS:
        group_id = (await get_or_create_group(ACCOUNTS_GROUP)).id
    ledger = Ledger(name=name, normalized=normalize(name), group_id=group_id, aliases=aliases or [], kind=kind)
    res = await db.ledgers.insert_one(ledger.to_mongo())
    ledger.id = str(res.inserted_id)
    return ledger


async def get_account_ledger(kind: str) -> Ledger:
    """Primary Cash / Bank account ledger (oldest one of that kind), created on demand in the Accounts group."""
    doc = await db.ledgers.find_one({"kind": kind, "deleted_at": None}, sort=[("created_at", 1)])
    if doc:
        return Ledger.from_mongo(doc)
    group = await get_or_create_group(ACCOUNTS_GROUP)
    return await create_ledger("Cash" if kind == "cash" else "Bank", group.id, kind=kind)


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


def _opposite(direction: str) -> str:
    return "credit" if direction == "debit" else "debit"


async def add_transaction(
    ledger_id: str,
    amount: float,
    direction: str,
    note: str,
    entry_date: datetime,
    source: str,
    wa_message_id: Optional[str] = None,
    sender: Optional[str] = None,
    mode: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> Transaction:
    """Record an entry. mode 'cash'/'bank' also books the contra entry in that money account:
    - PARTY ledger: party debit = money went out → account credit; party credit = money came in → account debit.
    - ACCOUNT ledger (Cash/Bank) with mode = the OTHER account kind → transfer between own accounts."""
    txn = Transaction(
        ledger_id=ledger_id,
        amount=round(float(amount), 2),
        direction=direction,
        note=note or "",
        tags=normalize_tags(tags),
        entry_date=entry_date,
        source=source,
        wa_message_id=wa_message_id,
        sender=sender,
    )
    res = await db.transactions.insert_one(txn.to_mongo())
    txn.id = str(res.inserted_id)
    await recalc_balance(ledger_id)
    if mode in ACCOUNT_KINDS:
        ledger = await get_ledger(ledger_id)
        if ledger and (not ledger.is_account or ledger.kind != mode):
            await _book_contra(txn, ledger, mode)
    return txn


async def transfer(from_kind: str, to_kind: str, amount: float, note: str, entry_date: datetime, source: str,
                   wa_message_id: Optional[str] = None, sender: Optional[str] = None) -> tuple[Transaction, Ledger, Ledger]:
    """Move money between own accounts (bank→cash withdrawal, cash→bank deposit). Returns (in-side txn, from_ledger, to_ledger)."""
    to_ledger = await get_account_ledger(to_kind)
    txn = await add_transaction(to_ledger.id, amount, "debit", note, entry_date, source, wa_message_id=wa_message_id, sender=sender, mode=from_kind)
    from_ledger = await get_account_ledger(from_kind)
    return txn, from_ledger, to_ledger


async def _book_contra(txn: Transaction, party: Ledger, mode: str) -> Transaction:
    acct = await get_account_ledger(mode)
    contra = Transaction(
        ledger_id=acct.id,
        amount=txn.amount,
        direction=_opposite(txn.direction),
        note=f"{party.name}" + (f" — {txn.note}" if txn.note else ""),
        tags=txn.tags,
        entry_date=txn.entry_date,
        source=txn.source,
        wa_message_id=txn.wa_message_id,
        sender=txn.sender,
        contra_txn_id=txn.id,
        contra_ledger_id=party.id,
    )
    res = await db.transactions.insert_one(contra.to_mongo())
    contra.id = str(res.inserted_id)
    await db.transactions.update_one({"_id": ObjectId(txn.id)}, {"$set": {"contra_txn_id": contra.id, "contra_ledger_id": acct.id}})
    txn.contra_txn_id, txn.contra_ledger_id = contra.id, acct.id
    await recalc_balance(acct.id)
    return contra


async def update_transaction(txn_id: str, amount: Optional[float] = None, direction: Optional[str] = None, note: Optional[str] = None,
                             entry_date: Optional[datetime] = None, ledger_id: Optional[str] = None, mode: Optional[str] = "keep",
                             tags: Optional[List[str]] = None) -> Optional[dict]:
    """Edit an entry and keep its contra (cash/bank side) in sync. mode: 'keep' | 'cash' | 'bank' | None (remove contra)."""
    doc = await db.transactions.find_one({"_id": ObjectId(txn_id), "deleted_at": None})
    if not doc:
        return None
    upd: dict = {"updated_at": now_utc()}
    if amount is not None:
        upd["amount"] = round(float(amount), 2)
    if direction in ("debit", "credit"):
        upd["direction"] = direction
    if note is not None:
        upd["note"] = note.strip()
    if tags is not None:
        upd["tags"] = normalize_tags(tags)
    if entry_date is not None:
        upd["entry_date"] = entry_date
    if ledger_id and ledger_id != doc["ledger_id"]:
        upd["ledger_id"] = ledger_id
    await db.transactions.update_one({"_id": doc["_id"]}, {"$set": upd})
    await recalc_balance(doc["ledger_id"])
    if upd.get("ledger_id"):
        await recalc_balance(upd["ledger_id"])
    new = await db.transactions.find_one({"_id": doc["_id"]})
    txn = Transaction.from_mongo(new)
    ledger = await get_ledger(txn.ledger_id)
    contra_doc = await db.transactions.find_one({"_id": ObjectId(txn.contra_txn_id), "deleted_at": None}) if txn.contra_txn_id and ObjectId.is_valid(txn.contra_txn_id) else None
    contra_acct = await get_ledger(contra_doc["ledger_id"]) if contra_doc else None
    if ledger and ledger.is_account and (mode == ledger.kind or (contra_doc and mode == "keep")):
        mode = "keep"  # editing a money-account row: only sync the other side
    same_account = contra_acct is not None and mode in ACCOUNT_KINDS and contra_acct.kind == mode
    if contra_doc and (mode == "keep" or same_account):
        c_upd = {"amount": txn.amount, "direction": _opposite(txn.direction), "entry_date": txn.entry_date, "tags": txn.tags, "updated_at": now_utc()}
        if ledger and not ledger.is_account:
            c_upd["note"] = ledger.name + (f" — {txn.note}" if txn.note else "")
        await db.transactions.update_one({"_id": contra_doc["_id"]}, {"$set": c_upd})
        await recalc_balance(contra_doc["ledger_id"])
    elif mode in ACCOUNT_KINDS and ledger and (not ledger.is_account or ledger.kind != mode):
        if contra_doc:
            await _remove_contra(txn, contra_doc)
        await _book_contra(txn, ledger, mode)
    elif mode is None and contra_doc:
        await _remove_contra(txn, contra_doc)
    return await db.transactions.find_one({"_id": doc["_id"]})


async def _remove_contra(txn: Transaction, contra_doc: dict):
    await db.transactions.update_one({"_id": contra_doc["_id"]}, {"$set": {"deleted_at": now_utc()}})
    await db.transactions.update_one({"_id": ObjectId(txn.id)}, {"$set": {"contra_txn_id": None, "contra_ledger_id": None}})
    await recalc_balance(contra_doc["ledger_id"])


async def delete_transaction(txn_id: str) -> Optional[dict]:
    """Soft-delete an entry together with its contra entry."""
    doc = await db.transactions.find_one({"_id": ObjectId(txn_id), "deleted_at": None})
    if not doc:
        return None
    ids = [doc["_id"]]
    ledger_ids = {doc["ledger_id"]}
    if doc.get("contra_txn_id") and ObjectId.is_valid(doc["contra_txn_id"]):
        c = await db.transactions.find_one({"_id": ObjectId(doc["contra_txn_id"]), "deleted_at": None})
        if c:
            ids.append(c["_id"])
            ledger_ids.add(c["ledger_id"])
    await db.transactions.update_many({"_id": {"$in": ids}}, {"$set": {"deleted_at": now_utc()}})
    for lid in ledger_ids:
        await recalc_balance(lid)
    return doc


async def migrate_cashbook():
    """One-time: tag existing Cash/Bank-named ledgers as accounts (move to Accounts group) and book cash contra for old party entries."""
    if await db.meta.find_one({"key": "cashbook_v1"}):
        return
    async for d in db.ledgers.find({"deleted_at": None, "kind": {"$exists": False}}):
        kind = guess_kind(d["name"])
        upd = {"kind": kind}
        if kind in ACCOUNT_KINDS:
            upd["group_id"] = (await get_or_create_group(ACCOUNTS_GROUP)).id
        await db.ledgers.update_one({"_id": d["_id"]}, {"$set": upd})
    ledgers = {str(l["_id"]): Ledger.from_mongo(l) for l in await db.ledgers.find({"deleted_at": None}).to_list(5000)}
    async for t in db.transactions.find({"deleted_at": None, "contra_txn_id": None}):
        party = ledgers.get(t["ledger_id"])
        if not party or party.is_account:
            continue
        mode = detect_mode("", t.get("note", ""))
        if mode:
            await _book_contra(Transaction.from_mongo(t), party, mode)
    await db.meta.insert_one({"key": "cashbook_v1", "at": now_utc()})


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
    names: dict = {}
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
        if t.contra_ledger_id:
            if t.contra_ledger_id not in names:
                cl = await db.ledgers.find_one({"_id": ObjectId(t.contra_ledger_id)}, {"name": 1})
                names[t.contra_ledger_id] = cl["name"] if cl else None
            row["via"] = names[t.contra_ledger_id]
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
    """Return {group_id: {ledger_count, balance, lena, dena, account_balance}} for live ledgers.
    lena/dena/balance cover PARTY ledgers only; account_balance sums cash/bank ledgers (None if the group has none)."""
    out: dict = {}
    async for d in db.ledgers.find({"deleted_at": None}):
        g = out.setdefault(d["group_id"], {"ledger_count": 0, "balance": 0.0, "lena": 0.0, "dena": 0.0, "account_balance": None})
        bal = d.get("current_balance", 0.0)
        g["ledger_count"] += 1
        if d.get("kind", "party") in ACCOUNT_KINDS:
            g["account_balance"] = round((g["account_balance"] or 0.0) + bal, 2)
            continue
        g["balance"] = round(g["balance"] + bal, 2)
        if bal > 0:
            g["lena"] = round(g["lena"] + bal, 2)
        else:
            g["dena"] = round(g["dena"] + abs(bal), 2)
    return out


async def account_balances() -> dict:
    """{'cash': float, 'bank': float, 'accounts': [{ledger_id, name, kind, balance}]} over live cash/bank ledgers."""
    out = {"cash": 0.0, "bank": 0.0, "accounts": []}
    async for d in db.ledgers.find({"deleted_at": None, "kind": {"$in": list(ACCOUNT_KINDS)}}).sort("created_at", 1):
        bal = round(d.get("current_balance", 0.0), 2)
        out[d["kind"]] = round(out[d["kind"]] + bal, 2)
        out["accounts"].append({"ledger_id": str(d["_id"]), "name": d["name"], "kind": d["kind"], "balance": bal})
    return out


def to_utc(d: datetime) -> datetime:
    if d.tzinfo is None:
        return d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)
