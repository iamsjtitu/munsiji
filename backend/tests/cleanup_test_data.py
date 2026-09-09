"""Soft-delete TEST* ledgers/groups created by automated test runs and recalc money accounts (preview DB hygiene)."""
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from db import db  # noqa: E402
from ledger_service import recalc_balance  # noqa: E402


async def main():
    now = datetime.now(timezone.utc)
    ids = [str(l["_id"]) async for l in db.ledgers.find({"deleted_at": None, "name": {"$regex": "^(TEST|CBTEST)"}})]
    r = await db.ledgers.update_many({"deleted_at": None, "name": {"$regex": "^(TEST|CBTEST)"}}, {"$set": {"deleted_at": now}})
    r2 = await db.transactions.update_many({"ledger_id": {"$in": ids}, "deleted_at": None}, {"$set": {"deleted_at": now}})
    r3 = await db.groups.update_many({"deleted_at": None, "name": {"$regex": "^(TEST|CBTEST)"}}, {"$set": {"deleted_at": now}})
    print("ledgers", r.modified_count, "txns", r2.modified_count, "groups", r3.modified_count)
    async for a in db.ledgers.find({"deleted_at": None}):
        bal = await recalc_balance(str(a["_id"]))
        if a.get("kind") in ("cash", "bank"):
            print(a["name"], bal)


if __name__ == "__main__":
    asyncio.run(main())
