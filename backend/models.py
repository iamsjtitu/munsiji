from datetime import datetime, timezone
from typing import Annotated, Any, List, Literal, Optional

from bson import ObjectId
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _coerce_oid(v: Any) -> Any:
    return str(v) if isinstance(v, ObjectId) else v


PyObjectId = Annotated[str, BeforeValidator(_coerce_oid)]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class BaseDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: Optional[PyObjectId] = Field(default=None, alias="_id")

    def to_mongo(self) -> dict:
        d = self.model_dump(by_alias=True, exclude_none=True)
        d.pop("_id", None)
        return d

    @classmethod
    def from_mongo(cls, doc: dict):
        return cls.model_validate(doc)

    def api(self) -> dict:
        return self.model_dump(mode="json")


class Group(BaseDocument):
    name: str
    created_at: datetime = Field(default_factory=now_utc)
    deleted_at: Optional[datetime] = None


LedgerKind = Literal["party", "cash", "bank"]
ACCOUNT_KINDS = ("cash", "bank")


class Ledger(BaseDocument):
    name: str
    normalized: str
    group_id: PyObjectId
    aliases: List[str] = []
    kind: LedgerKind = "party"  # cash/bank = money accounts (cash book); party = people/firms (lena/dena)
    current_balance: float = 0.0
    created_at: datetime = Field(default_factory=now_utc)
    deleted_at: Optional[datetime] = None

    @property
    def is_account(self) -> bool:
        return self.kind in ACCOUNT_KINDS


Direction = Literal["debit", "credit"]


class Transaction(BaseDocument):
    ledger_id: PyObjectId
    amount: float
    direction: Direction
    note: str = ""
    tags: List[str] = []  # expense categories e.g. ["petrol"], lowercase
    entry_date: datetime
    source: str = "app"  # whatsapp | app
    wa_message_id: Optional[str] = None
    sender: Optional[str] = None
    contra_txn_id: Optional[str] = None  # double entry: the linked cash/bank (or party) transaction
    contra_ledger_id: Optional[str] = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


class WaMessage(BaseDocument):
    wa_message_id: Optional[str] = None
    sender: str
    text: str
    reply: Optional[str] = None
    status: str = "processed"  # processed | ignored | duplicate | clarify | error
    source: str = "whatsapp"  # whatsapp | simulate
    files: List[dict] = []
    created_at: datetime = Field(default_factory=now_utc)


class Settings(BaseDocument):
    key: str = "main"
    owner_number: str
    pin_hash: str
    pin_changed_at: Optional[datetime] = None
    webhook_secret: str = ""
    owner_email: str = ""
    alerts_enabled: bool = True
    emergent_llm_key: str = ""
    emergent_email_key: str = ""
    provider: str = "mock"  # mock | wa9x
    wa9x_base_url: str = ""
    wa9x_api_key: str = ""
    wa9x_instance_id: str = ""  # optional wa.9x session_id (only if several numbers linked)
    wa9x_webhook_secret: str = ""  # optional: wa.9x "webhook signing secret" → verifies X-Wa9x-Signature
    owner_ids: List[str] = []  # paired sender ids (WhatsApp LIDs) that also count as the owner
    pairing_code: str = ""  # one-time code the owner sends from WhatsApp to link a LID
    pairing_expires_at: Optional[datetime] = None
    public_base_url: str = ""
    updated_at: datetime = Field(default_factory=now_utc)


class Pending(BaseDocument):
    sender: str
    kind: str  # confirm_match | choose_format | choose_ledger
    question: str
    payload: dict
    created_at: datetime = Field(default_factory=now_utc)


class ExportFile(BaseDocument):
    token: str
    filename: str
    content_type: str
    data: bytes
    created_at: datetime = Field(default_factory=now_utc)
    expires_at: datetime
