"""Gemini 3 Flash based Hinglish message parser with regex fallback."""
import json
import logging
import os
import re
import uuid
from datetime import date, datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

from emergentintegrations.llm.chat import LlmChat, UserMessage

from emailer import send_alert
from models import Group, Ledger

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

CREDIT_WORDS = [
    "received", "receved", "recieved", "recved", "recv", "rcvd", "mila", "mile", "mili", "wapas", "aaya", "aya", "aaye",
    "return", "credit", "cr", "jama", "deposit", "paid me", "diya mujhe", "salary", "vasool", "wasool", "collected",
]
DELETE_WORDS = ["delete", "hata", "hatao", "remove", "cancel", "udao", "galat entry"]
STATEMENT_WORDS = ["ledger bhej", "statement", "ledger send", "ledger do", "hisab bhej", "khata bhej", "ledger chahiye", "report"]
BALANCE_WORDS = ["balance", "kitna", "baki", "baaki", "hisab kya", "kitne"]
YES_WORDS = ["haan", "ha", "han", "yes", "y", "ok", "okay", "sahi", "theek", "thik", "hn", "hmm", "usme", "same", "wahi"]
NO_WORDS = ["nahi", "na", "no", "n", "naya", "new", "nhi", "alag"]

SYSTEM_PROMPT = """You are "Munsiji", a Hinglish (Hindi+English, Roman script) bookkeeping assistant for a single business owner.
You convert WhatsApp messages into structured JSON for a personal ledger (Tally-style khata).

Conventions:
- "debit" = owner GAVE money / paid / lent / advance / expense paid (default when unclear). Increases "lena hai".
- "credit" = owner RECEIVED money back (received/recved/recv/mila/wapas/aaya/return/jama) OR owner OWES the party (e.g. staff salary due: "Mantu salary 8000" => credit 8000 to Mantu's ledger, because owner owes salary). "advance kaata" means the earlier advance (already a debit) is adjusted; do not create an extra entry for it, just mention in note.
- party_name: the person/firm the ledger is for. Clean it: remove amounts, keep brackets content e.g. "Biki [Mill]". Never include words like "account", "ledger", "ka", "ko", "se". Money accounts are also ledgers: "cash" / "Cash in hand" / "bank" / "SBI bank" — use party_name "Cash" or the bank name when the user is talking about the cash box / bank itself (e.g. "cash opening balance 500000", "bank me 20000 jama").
- mode: how the money physically moved for a PARTY entry — "cash" (default: paid/received in cash or unspecified), "bank" (UPI, GPay, PhonePe, Paytm, NEFT, IMPS, cheque, online, bank transfer, "account se"), or "none" when NO money moved now: opening balance / purana baki, goods or maal given on credit, bill/invoice raised, salary DUE (not paid), interest added. The system auto-books the counter entry in the Cash/Bank account, so be careful: "Mantu salary 8000" (owner owes) => mode "none"; "Mantu ko salary 8000 diya" (paid) => mode "cash".
- For entries directly on a Cash/Bank ledger: direction "debit" = money came INTO the account (deposit / opening balance / received), "credit" = money went OUT (withdrawal / expense). mode "none".
- group_name: only if the user explicitly names a group/account category (e.g. "Investment account", "Staff", "Expenses", "Personal"). Else null.
- matched_ledger_id: choose from EXISTING LEDGERS if the party clearly refers to one of them (ignore typos, case, brackets, spacing, e.g. "biki mill" == "Biki [Mill]"). Otherwise null. match_confidence: "high" if clearly same, "medium" if plausible but unsure, "none" if it is a new party.
- entry_date: resolve relative dates ("kal"=yesterday, "aaj"=today, "parso"=day before yesterday, "2 din pehle", "5 tarikh", "7 jan") using TODAY. Format YYYY-MM-DD. null if not mentioned.
- Intents:
  * "entry": record one or more amounts for a party. entries = [{amount, direction, note}]. Multiple amounts in one message => multiple entries.
  * "delete_last": user wants the last entry removed ("last entry delete karo").
  * "correct_last": user corrects the last amount ("500 nahi 700 tha" => new_amount 700).
  * "statement": user wants a ledger/statement/hisab sent ("cash account ka ledger bhej", "7 jan 2026 se aaj tak ka ledger bhej"). Fill party_name, from_date, to_date (YYYY-MM-DD or null), format ("pdf"|"excel"|"csv"|null if not specified).
  * "balance": user asks the balance of a party ("biki mill ka kitna balance hai").
  * "yes" / "no": short confirmations.
  * "choose": user picks an option (e.g. "pdf", "excel", "1", "2", "pehla"). Put the raw choice in "choice".
  * "unknown": cannot understand; write a short Hinglish clarification question in "clarification".
- If the message is genuinely ambiguous about WHICH party (e.g. only an amount, no name, and no pending context), use intent "unknown" with a clarification. Never guess a party.

Return ONLY a JSON object with keys:
intent, party_name, group_name, matched_ledger_id, match_confidence, entries, entry_date, mode, new_amount, from_date, to_date, format, choice, clarification.
No markdown, no explanation."""


def today_ist() -> date:
    return datetime.now(IST).date()


def _strip_fences(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    start, end = t.find("{"), t.rfind("}")
    return t[start : end + 1] if start != -1 and end != -1 else t


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


class Parsed(dict):
    """Loose container for parsed result."""

    @property
    def intent(self) -> str:
        return self.get("intent") or "unknown"


def _ledger_context(ledgers: List[Ledger], groups: List[Group]) -> str:
    gmap = {g.id: g.name for g in groups}
    lines = [f"- id={l.id} | name=\"{l.name}\" | group={gmap.get(l.group_id, '?')} | kind={l.kind} | aliases={l.aliases}" for l in ledgers]
    return "EXISTING LEDGERS (kind=cash/bank are money accounts, party = people/firms):\n" + ("\n".join(lines) if lines else "(none yet)") + "\n\nGROUPS: " + ", ".join(g.name for g in groups)


async def ai_parse(text: str, ledgers: List[Ledger], groups: List[Group], pending_hint: Optional[str] = None, api_key: Optional[str] = None) -> Parsed:
    api_key = api_key or os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        await send_alert("ai_failed", "AI parsing band hai — Emergent LLM key missing", ["Settings mein Emergent LLM key daalo.", f"Message: {text[:120]}", "Abhi simple regex parser use hua."])
        return fallback_parse(text, ledgers)
    today = today_ist()
    prompt = (
        f"TODAY: {today.isoformat()} ({today.strftime('%A')})\n\n"
        + _ledger_context(ledgers, groups)
        + (f"\n\nPENDING CONTEXT (the bot just asked this): {pending_hint}" if pending_hint else "")
        + f"\n\nMESSAGE: {text}"
    )
    try:
        chat = LlmChat(api_key=api_key, session_id=f"parse-{uuid.uuid4()}", system_message=SYSTEM_PROMPT).with_model(
            "gemini", "gemini-3-flash-preview"
        )
        raw = await chat.send_message(UserMessage(text=prompt))
        data = json.loads(_strip_fences(raw if isinstance(raw, str) else str(raw)))
        parsed = Parsed(data)
        parsed.setdefault("entries", [])
        parsed["entries"] = [
            {"amount": float(e.get("amount", 0)), "direction": e.get("direction") or "debit", "note": e.get("note") or ""}
            for e in (parsed.get("entries") or [])
            if e and float(e.get("amount") or 0) > 0
        ]
        parsed["_source"] = "ai"
        return parsed
    except Exception as e:  # noqa: BLE001
        logger.warning("AI parse failed, using fallback: %s", e)
        await send_alert("ai_failed", "AI parsing fail ho raha hai", [f"Error: {type(e).__name__}: {str(e)[:160]}", f"Message: {text[:120]}", "Emergent LLM key / balance check karo. Abhi simple regex parser use hua."])
        return fallback_parse(text, ledgers)


# ---------------------------------------------------------------- regex fallback
AMOUNT_RE = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(k|hazar|hazaar|lakh|l)?(?![\w])", re.I)


def _amounts(text: str) -> List[float]:
    out = []
    for m in AMOUNT_RE.finditer(text):
        num = float(m.group(1).replace(",", ""))
        unit = (m.group(2) or "").lower()
        if unit in ("k", "hazar", "hazaar"):
            num *= 1000
        elif unit in ("lakh", "l"):
            num *= 100000
        out.append(num)
    return out


def _relative_date(text: str) -> Optional[date]:
    t = text.lower()
    today = today_ist()
    if "parso" in t:
        return today - timedelta(days=2)
    if re.search(r"\bkal\b", t):
        return today - timedelta(days=1)
    if re.search(r"\baaj\b", t):
        return today
    m = re.search(r"(\d+)\s*din\s*pehle", t)
    if m:
        return today - timedelta(days=int(m.group(1)))
    return None


def fallback_parse(text: str, ledgers: List[Ledger]) -> Parsed:
    t = text.strip()
    low = t.lower()
    words = re.findall(r"[a-z]+", low)
    p = Parsed(intent="unknown", party_name=None, group_name=None, matched_ledger_id=None, match_confidence="none",
               entries=[], entry_date=None, new_amount=None, from_date=None, to_date=None, format=None, choice=None,
               clarification=None, _source="fallback")
    if low in ("pdf", "excel", "xlsx", "csv") or (len(words) == 1 and words[0] in ("pdf", "excel", "csv", "xlsx")):
        p.update(intent="choose", choice=low)
        return p
    if len(words) <= 2 and words and all(w in YES_WORDS for w in words):
        p["intent"] = "yes"
        return p
    if len(words) <= 2 and words and all(w in NO_WORDS for w in words):
        p["intent"] = "no"
        return p
    if re.fullmatch(r"\s*\d\s*", t):
        p.update(intent="choose", choice=t.strip())
        return p
    amounts = _amounts(t)
    if any(w in low for w in DELETE_WORDS) and "last" in low or ("last" in low and "delete" in low):
        p["intent"] = "delete_last"
        return p
    m = re.search(r"(\d[\d,]*)\s*nahi\s*(\d[\d,]*)", low)
    if m:
        p.update(intent="correct_last", new_amount=float(m.group(2).replace(",", "")))
        return p
    if any(w in low for w in STATEMENT_WORDS):
        p["intent"] = "statement"
        fmt = "pdf" if "pdf" in low else "excel" if ("excel" in low or "xlsx" in low) else "csv" if "csv" in low else None
        p["format"] = fmt
        name = re.sub(r"(ka|ki|ke)?\s*(ledger|statement|hisab|khata|report).*", "", low)
        name = re.sub(r"\b(pdf|excel|csv|me|mein|bhej|bhejo|do|send|se|leke|aaj|tak|\d{1,2}\s*\w*\s*\d{4})\b", " ", name)
        p["party_name"] = re.sub(r"\s+", " ", name).strip() or None
        return p
    if any(w in low for w in BALANCE_WORDS) and not amounts:
        p["intent"] = "balance"
        name = re.sub(r"\b(ka|ki|ke|kitna|balance|baki|baaki|hai|h|kya|hisab|bata|batao)\b", " ", low)
        p["party_name"] = re.sub(r"\s+", " ", name).strip() or None
        return p
    if amounts:
        direction = "credit" if any(re.search(rf"\b{re.escape(w)}\b", low) for w in CREDIT_WORDS) else "debit"
        rest = AMOUNT_RE.sub(" ", t)
        rest = re.sub(r"(?i)\b(rs|rupees|rupaye|inr)\b|₹", " ", rest)
        group = None
        gm = re.search(r"(?i),\s*([a-z ]+?)\s*(account|acc|group|me|mein)\s*$", rest)
        if gm:
            group = gm.group(1).strip()
            rest = rest[: gm.start()]
        for w in CREDIT_WORDS + ["diya", "diye", "de", "paid", "pay", "ko", "se", "kal", "aaj", "parso", "ka", "ki", "ke", "hai", "-", ","]:
            rest = re.sub(rf"(?i)(?<![\w]){re.escape(w)}(?![\w])", " ", rest)
        name = re.sub(r"[\-,:]+", " ", rest)
        name = re.sub(r"\s+", " ", name).strip()
        if not name:
            p.update(intent="unknown", clarification="Kis party/ledger ke liye entry karni hai? Naam bhi likho, jaise: '5000 - Biki Mill'")
            return p
        p.update(
            intent="entry",
            party_name=name,
            group_name=group,
            entries=[{"amount": a, "direction": direction, "note": ""} for a in amounts[:1]],
            entry_date=(_relative_date(t) or None) and _relative_date(t).isoformat(),
        )
        return p
    p["clarification"] = "Samajh nahi aaya. Aise likho: 'Biki Mill - 5000' ya 'received 2000 - Biki Mill'."
    return p


def parsed_date_or_none(value) -> Optional[date]:
    return _parse_date(value)
