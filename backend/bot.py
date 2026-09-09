"""WhatsApp bot pipeline: message -> parse -> ledger action -> Hinglish reply."""
import logging
import os
import re
import secrets
from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional

from bson import ObjectId

from ai_parser import IST, NO_WORDS, YES_WORDS, ai_parse, parsed_date_or_none, today_ist
from db import db
from exports import build_export
from ledger_service import (
    add_alias,
    add_transaction,
    balance_text,
    create_ledger,
    delete_transaction,
    detect_mode,
    detect_tags,
    fmt_inr,
    fuzzy_match,
    get_ledger,
    get_or_create_group,
    list_ledgers,
    recalc_balance,
    statement,
    transfer,
    update_transaction,
)
from models import ExportFile, Group, Ledger, Pending, Settings, WaMessage, now_utc
from wa_provider import digits, same_number

logger = logging.getLogger(__name__)

MATCH_HIGH = 88
MATCH_LOW = 60


def resolve_mode(ai_mode: Optional[str], text: str, note: str) -> Optional[str]:
    """Payment mode for a party entry: AI's 'mode' (cash|bank|none) wins, else keyword detection (default cash)."""
    if ai_mode in ("cash", "bank"):
        return ai_mode
    if ai_mode == "none":
        return None
    return detect_mode(text, note)


async def get_settings() -> Settings:
    doc = await db.settings.find_one({"key": "main"})
    return Settings.from_mongo(doc)


def public_base_url(settings: Settings) -> str:
    return (settings.public_base_url or os.environ.get("PUBLIC_BASE_URL", "")).rstrip("/")


def ist_datetime_for(d: Optional[date]) -> datetime:
    now_ist = datetime.now(IST)
    if not d or d == now_ist.date():
        return now_ist.astimezone(timezone.utc)
    return datetime.combine(d, time(12, 0), tzinfo=IST).astimezone(timezone.utc)


def day_start(d: date) -> datetime:
    return datetime.combine(d, time(0, 0), tzinfo=IST).astimezone(timezone.utc)


def day_end(d: date) -> datetime:
    return datetime.combine(d, time(23, 59, 59), tzinfo=IST).astimezone(timezone.utc)


def nice_date(d: date) -> str:
    return d.strftime("%d %b %Y")


async def _groups() -> List[Group]:
    return [Group.from_mongo(g) async for g in db.groups.find({"deleted_at": None})]


async def _group_name(group_id: str) -> str:
    g = await db.groups.find_one({"_id": ObjectId(group_id)})
    return g["name"] if g else "General"


async def save_export(fmt: str, ledger: Ledger, d_from: Optional[date], d_to: Optional[date], settings: Settings) -> dict:
    stmt = await statement(ledger.id, day_start(d_from) if d_from else None, day_end(d_to) if d_to else None)
    subtitle = ""
    if d_from or d_to:
        subtitle = f"Period: {nice_date(d_from) if d_from else 'start'} to {nice_date(d_to) if d_to else 'today'}"
    filename, ctype, data = build_export(fmt, ledger.name, stmt, subtitle)
    token = secrets.token_urlsafe(32)
    ttl_hours = int(os.environ.get("EXPORT_LINK_TTL_HOURS", "24"))
    await db.export_files.insert_one(
        ExportFile(token=token, filename=filename, content_type=ctype, data=data, expires_at=now_utc() + timedelta(hours=ttl_hours)).to_mongo()
    )
    url = f"{public_base_url(settings)}/api/files/{token}"
    return {"url": url, "filename": filename, "format": fmt, "closing_balance": stmt["closing_balance"], "count": len(stmt["rows"]), "expires_in_hours": ttl_hours}


class Bot:
    def __init__(self, sender: str, source: str, wa_message_id: Optional[str], settings: Settings):
        self.sender = digits(sender)
        self.source = source
        self.wa_message_id = wa_message_id
        self.settings = settings
        self.files: List[dict] = []
        self.status = "processed"

    # ------------------------------------------------------------ helpers
    async def set_pending(self, kind: str, question: str, payload: dict) -> str:
        await db.pending.delete_many({"sender": self.sender})
        await db.pending.insert_one(Pending(sender=self.sender, kind=kind, question=question, payload=payload).to_mongo())
        self.status = "clarify"
        return question

    async def clear_pending(self):
        await db.pending.delete_many({"sender": self.sender})

    async def resolve_ledger(self, parsed: dict, party: Optional[str], ledgers: List[Ledger]):
        """Returns (kind, ledger, extra). kind in match|confirm|ambiguous|new."""
        if not party and not parsed.get("matched_ledger_id"):
            return "none", None, None
        by_id = {l.id: l for l in ledgers}
        ai_id = parsed.get("matched_ledger_id")
        conf = parsed.get("match_confidence") or "none"
        scored = await fuzzy_match(party or "", ledgers) if party else []
        if ai_id in by_id and conf == "high":
            return "match", by_id[ai_id], None
        if scored:
            best, score = scored[0]
            second = scored[1] if len(scored) > 1 else None
            if score >= MATCH_HIGH:
                if second and second[1] >= MATCH_HIGH and abs(second[1] - score) <= 4 and best.id != second[0].id:
                    return "ambiguous", None, [best, second[0]]
                return "match", best, None
            if score >= MATCH_LOW:
                return "confirm", best, score
        if ai_id in by_id and conf == "medium":
            return "confirm", by_id[ai_id], 70
        return "new", None, None

    # ------------------------------------------------------------ actions
    async def do_transfer(self, parsed: dict, text: str) -> str:
        """Own-account transfer: bank → cash (nikala/withdraw) or cash → bank (jama/deposit)."""
        entries = parsed.get("entries") or []
        amount = entries[0].get("amount") if entries else parsed.get("new_amount")
        if not amount or float(amount) <= 0:
            return "Amount samajh nahi aaya. Aise likho: 'bank se 50000 cash nikala'"
        frm = (parsed.get("from_account") or "").lower()
        to = (parsed.get("to_account") or "").lower()
        if frm not in ("cash", "bank") or to not in ("cash", "bank") or frm == to:
            low = text.lower()
            frm, to = ("cash", "bank") if any(w in low for w in ("jama", "deposit", "bank me", "bank mein", "dala", "daala")) else ("bank", "cash")
        d = parsed_date_or_none(parsed.get("entry_date"))
        note = (entries[0].get("note") if entries else "") or ("nikala" if frm == "bank" else "jama")
        _, from_l, to_l = await transfer(frm, to, float(amount), note, ist_datetime_for(d), "whatsapp" if self.source == "whatsapp" else "app",
                                         wa_message_id=self.wa_message_id, sender=self.sender)
        from_l, to_l = await get_ledger(from_l.id), await get_ledger(to_l.id)  # fresh balances
        when = f" [{nice_date(d)}]" if d and d != today_ist() else ""
        return (f"Transfer: {fmt_inr(float(amount))} {from_l.name} → {to_l.name}{when}.\n"
                f"{to_l.name}: {balance_text(to_l.current_balance, to_l.kind)}\n"
                f"{from_l.name}: {balance_text(from_l.current_balance, from_l.kind)}")

    async def do_entry(self, ledger: Ledger, parsed: dict, is_new: bool, group_name: str = "", text: str = "") -> str:
        d = parsed_date_or_none(parsed.get("entry_date"))
        entry_dt = ist_datetime_for(d)
        lines = []
        touched_accounts: dict = {}
        for e in parsed.get("entries") or []:
            mode = None if ledger.is_account else resolve_mode(parsed.get("mode"), text, e.get("note") or "")
            tags = e.get("tags") or parsed.get("tags") or detect_tags(text, e.get("note") or "")
            txn = await add_transaction(
                ledger.id, e["amount"], e["direction"], e.get("note") or "", entry_dt, "whatsapp" if self.source == "whatsapp" else "app",
                wa_message_id=self.wa_message_id, sender=self.sender, mode=mode, tags=tags,
            )
            if txn.contra_ledger_id:
                touched_accounts[txn.contra_ledger_id] = mode
            if ledger.is_account:
                verb = "jama (in)" if e["direction"] == "debit" else "nikla (out)"
            else:
                verb = "diya" if e["direction"] == "debit" else "mila"
            tag_s = (" #" + " #".join(txn.tags)) if txn.tags else ""
            lines.append(f"{fmt_inr(e['amount'])} {verb}" + (f" ({e['note']})" if e.get("note") else "") + tag_s)
        bal = await recalc_balance(ledger.id)
        head = f"Naya ledger bana: {ledger.name} ({group_name}). " if is_new else f"{ledger.name}: "
        when = f" [{nice_date(d)}]" if d and d != today_ist() else ""
        reply = f"{head}{', '.join(lines)}{when}. Balance: {balance_text(bal, ledger.kind)}"
        for acct_id, mode in touched_accounts.items():
            acct = await get_ledger(acct_id)
            if acct:
                reply += f"\n{acct.name}: {balance_text(acct.current_balance, acct.kind)}"
        return reply

    async def do_statement(self, ledger: Ledger, fmt: Optional[str], d_from: Optional[date], d_to: Optional[date]) -> str:
        period = ""
        if d_from or d_to:
            period = f" ({nice_date(d_from) if d_from else 'shuru'} se {nice_date(d_to) if d_to else 'aaj'} tak)"
        if fmt not in ("pdf", "excel", "csv"):
            return await self.set_pending(
                "choose_format",
                f"{ledger.name} ka ledger{period} kis format mein bhejun? PDF ya Excel?",
                {"ledger_id": ledger.id, "from": d_from.isoformat() if d_from else None, "to": d_to.isoformat() if d_to else None},
            )
        info = await save_export(fmt, ledger, d_from, d_to, self.settings)
        self.files.append(info)
        return f"{ledger.name} ka ledger{period} {fmt.upper()} mein bhej diya ({info['count']} entries). Balance: {balance_text(info['closing_balance'])}"

    async def do_balance(self, ledger: Ledger) -> str:
        bal = await recalc_balance(ledger.id)
        last = await db.transactions.find({"ledger_id": ledger.id, "deleted_at": None}).sort([("entry_date", -1), ("created_at", -1)]).limit(3).to_list(3)
        lines = [f"{ledger.name}: {balance_text(bal, ledger.kind)}"]
        for t in last:
            d = t["entry_date"].astimezone(IST).strftime("%d %b") if t["entry_date"].tzinfo else t["entry_date"].strftime("%d %b")
            verb = ("in" if t["direction"] == "debit" else "out") if ledger.is_account else ("diya" if t["direction"] == "debit" else "mila")
            lines.append(f"• {d}: {fmt_inr(t['amount'])} {verb}" + (f" ({t['note']})" if t.get("note") else ""))
        return "\n".join(lines)

    async def do_delete_last(self) -> str:
        t = await db.transactions.find_one({"deleted_at": None, "source": {"$in": ["whatsapp", "app"]}}, sort=[("created_at", -1)])
        if not t:
            return "Koi entry nahi mili delete karne ke liye."
        ledger = await get_ledger(t["ledger_id"])
        if t.get("contra_txn_id") and ledger and ledger.is_account:
            # the pair's account side was booked last — name the party side in the reply
            other = await db.transactions.find_one({"_id": ObjectId(t["contra_txn_id"]), "deleted_at": None})
            if other:
                t, ledger = other, await get_ledger(other["ledger_id"])
        await delete_transaction(str(t["_id"]))
        ledger = await get_ledger(t["ledger_id"])
        bal = ledger.current_balance if ledger else 0.0
        return f"Last entry delete ho gayi: {fmt_inr(t['amount'])} {'diya' if t['direction'] == 'debit' else 'mila'} ({ledger.name if ledger else '?'}). Balance: {balance_text(bal, ledger.kind if ledger else 'party')}"

    async def do_correct_last(self, new_amount: Optional[float]) -> str:
        if not new_amount or new_amount <= 0:
            return "Naya amount samajh nahi aaya. Aise likho: '500 nahi 700 tha'"
        t = await db.transactions.find_one({"deleted_at": None}, sort=[("created_at", -1)])
        if not t:
            return "Koi entry nahi mili correct karne ke liye."
        ledger = await get_ledger(t["ledger_id"])
        if t.get("contra_txn_id") and ledger and ledger.is_account:
            other = await db.transactions.find_one({"_id": ObjectId(t["contra_txn_id"]), "deleted_at": None})
            if other:
                t = other
        await update_transaction(str(t["_id"]), amount=float(new_amount))
        ledger = await get_ledger(t["ledger_id"])
        bal = ledger.current_balance if ledger else 0.0
        return f"Theek kiya: {fmt_inr(t['amount'])} → {fmt_inr(new_amount)} ({ledger.name if ledger else '?'}). Balance: {balance_text(bal, ledger.kind if ledger else 'party')}"

    # ------------------------------------------------------------ pending resolution
    async def resolve_pending(self, pending: dict, parsed: dict, text: str) -> Optional[str]:
        kind, payload = pending["kind"], pending["payload"]
        intent = parsed.get("intent")
        low = text.lower().strip()

        if kind == "choose_format":
            fmt = parsed.get("format") or (parsed.get("choice") or "").lower()
            if "pdf" in low:
                fmt = "pdf"
            elif "excel" in low or "xlsx" in low or "xls" in low:
                fmt = "excel"
            elif "csv" in low:
                fmt = "csv"
            if fmt in ("pdf", "excel", "csv"):
                await self.clear_pending()
                ledger = await get_ledger(payload["ledger_id"])
                if not ledger:
                    return "Ledger nahi mila."
                return await self.do_statement(ledger, fmt, parsed_date_or_none(payload.get("from")), parsed_date_or_none(payload.get("to")))
            if intent in ("yes", "no", "choose", "unknown"):
                return "PDF ya Excel — ek choose karo."
            await self.clear_pending()
            return None

        if kind == "confirm_match":
            ledger = await get_ledger(payload["ledger_id"])
            action = payload.get("action")
            words = re.findall(r"[a-z]+", low)
            says_yes = intent == "yes" or low in ("usme", "same", "wahi", "haan usme") or (words and all(w in YES_WORDS for w in words))
            says_no = intent == "no" or (words and all(w in NO_WORDS for w in words)) or (parsed.get("choice") or "").lower() in NO_WORDS
            if says_yes:
                await self.clear_pending()
                if not ledger:
                    return "Ledger nahi mila."
                if payload.get("query_name"):
                    await add_alias(ledger, payload["query_name"])
                if action == "entry":
                    return await self.do_entry(ledger, payload["parsed"], False, text=payload["parsed"].get("text", ""))
                if action == "statement":
                    return await self.do_statement(ledger, payload.get("format"), parsed_date_or_none(payload.get("from")), parsed_date_or_none(payload.get("to")))
                return await self.do_balance(ledger)
            if says_no:
                await self.clear_pending()
                if action == "entry":
                    group = await get_or_create_group(payload.get("group_name"))
                    new_ledger = await create_ledger(payload["query_name"], group.id)
                    return await self.do_entry(new_ledger, payload["parsed"], True, group.name, text=payload["parsed"].get("text", ""))
                return "Theek hai. Sahi ledger ka naam likh ke dobara bhejo."
            await self.clear_pending()
            return None

        if kind == "choose_ledger":
            options: List[str] = payload["options"]
            choice = (parsed.get("choice") or low).strip()
            picked = None
            if choice.isdigit() and 1 <= int(choice) <= len(options):
                picked = options[int(choice) - 1]
            else:
                ledgers = [l for l in [await get_ledger(i) for i in options] if l]
                scored = await fuzzy_match(choice, ledgers)
                if scored and scored[0][1] >= 70:
                    picked = scored[0][0].id
            if picked:
                await self.clear_pending()
                ledger = await get_ledger(picked)
                action = payload.get("action")
                if action == "entry":
                    return await self.do_entry(ledger, payload["parsed"], False, text=payload["parsed"].get("text", ""))
                if action == "statement":
                    return await self.do_statement(ledger, payload.get("format"), parsed_date_or_none(payload.get("from")), parsed_date_or_none(payload.get("to")))
                return await self.do_balance(ledger)
            if intent in ("yes", "no", "choose", "unknown"):
                return pending["question"]
            await self.clear_pending()
            return None
        await self.clear_pending()
        return None

    # ------------------------------------------------------------ main routing
    async def route(self, parsed: dict, text: str, ledgers: List[Ledger]) -> str:
        intent = parsed.get("intent") or "unknown"
        party = (parsed.get("party_name") or "").strip() or None

        if intent == "delete_last":
            return await self.do_delete_last()
        if intent == "correct_last":
            return await self.do_correct_last(parsed.get("new_amount"))
        if intent == "transfer":
            return await self.do_transfer(parsed, text)

        if intent in ("entry", "statement", "balance"):
            if intent == "entry" and not parsed.get("entries"):
                return "Amount samajh nahi aaya. Aise likho: 'Biki Mill - 5000'"
            kind, ledger, extra = await self.resolve_ledger(parsed, party, ledgers)
            d_from = parsed_date_or_none(parsed.get("from_date"))
            d_to = parsed_date_or_none(parsed.get("to_date"))
            fmt = (parsed.get("format") or None)
            base_payload = {"query_name": party, "group_name": parsed.get("group_name"),
                            "parsed": {"entries": parsed.get("entries") or [], "entry_date": parsed.get("entry_date"), "mode": parsed.get("mode"), "text": text},
                            "action": intent, "format": fmt, "from": d_from.isoformat() if d_from else None, "to": d_to.isoformat() if d_to else None}

            if kind == "none":
                return await self.set_pending("choose_ledger", "Kis party/ledger ke liye? Naam likho.", {**base_payload, "options": [l.id for l in ledgers][:50]}) if ledgers else \
                    "Kis party ke liye entry hai? Naam bhi likho, jaise: 'Biki Mill - 5000'"
            if kind == "ambiguous":
                opts = extra
                q = "Kaunsa ledger? " + " / ".join(f"{i + 1}. {l.name}" for i, l in enumerate(opts)) + " — number ya naam likho."
                return await self.set_pending("choose_ledger", q, {**base_payload, "options": [l.id for l in opts]})
            if kind == "confirm":
                gname = await _group_name(ledger.group_id)
                if intent == "entry":
                    q = f"'{party}' se milta-julta ledger already hai: {ledger.name} ({gname}). Usme add karu? (haan) ya naya ledger banau? (naya)"
                else:
                    q = f"Kya aapka matlab {ledger.name} ({gname}) hai? (haan/nahi)"
                return await self.set_pending("confirm_match", q, {**base_payload, "ledger_id": ledger.id})
            if kind == "new":
                if intent != "entry":
                    return f"'{party}' naam ka koi ledger nahi mila. Sahi naam likho."
                group = await get_or_create_group(parsed.get("group_name"))
                new_ledger = await create_ledger(party, group.id)
                return await self.do_entry(new_ledger, parsed, True, group.name, text=text)
            # match
            if party and ledger:
                await add_alias(ledger, party)
            if intent == "entry":
                return await self.do_entry(ledger, parsed, False, text=text)
            if intent == "statement":
                return await self.do_statement(ledger, fmt, d_from, d_to)
            return await self.do_balance(ledger)

        if intent in ("yes", "no", "choose"):
            return "Abhi koi sawaal pending nahi hai. Entry aise likho: 'Biki Mill - 5000'"
        return parsed.get("clarification") or "Samajh nahi aaya. Aise likho: 'Biki Mill - 5000' ya 'received 2000 - Biki Mill'."


async def handle_message(sender: str, text: str, wa_message_id: Optional[str] = None, source: str = "whatsapp") -> dict:
    settings = await get_settings()
    sender_d = digits(sender)
    if not same_number(sender_d, settings.owner_number):
        logger.info("Ignored non-whitelisted sender %s", sender_d)
        return {"reply": None, "files": [], "status": "ignored"}
    if wa_message_id and await db.wa_messages.find_one({"wa_message_id": wa_message_id}):
        return {"reply": None, "files": [], "status": "duplicate"}

    bot = Bot(sender_d, source, wa_message_id, settings)
    ledgers = await list_ledgers()
    groups = await _groups()
    pending = await db.pending.find_one({"sender": sender_d})
    reply: Optional[str] = None
    try:
        parsed = await ai_parse(text, ledgers, groups, pending_hint=pending["question"] if pending else None, api_key=settings.emergent_llm_key or None)
        if pending:
            reply = await bot.resolve_pending(pending, parsed, text)
        if reply is None:
            reply = await bot.route(parsed, text, ledgers)
    except Exception as e:  # noqa: BLE001
        logger.exception("bot error")
        bot.status = "error"
        reply = f"Kuch gadbad ho gayi ({type(e).__name__}). Thodi der baad try karo ya app se manual entry karo."

    await db.wa_messages.insert_one(
        WaMessage(wa_message_id=wa_message_id, sender=sender_d, text=text, reply=reply, status=bot.status, source=source, files=bot.files).to_mongo()
    )
    return {"reply": reply, "files": bot.files, "status": bot.status}
