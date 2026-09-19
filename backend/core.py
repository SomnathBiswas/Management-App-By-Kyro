"""Configuration, database client, security primitives and shared dependencies."""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import bcrypt
import jwt
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from fastapi import HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("titangym")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ.get("JWT_SECRET", "titangym-development-secret")
GYM_TZ_NAME = os.environ.get("GYM_TIMEZONE", "Asia/Kolkata")
GYM_TZ = ZoneInfo(GYM_TZ_NAME)

WHATSAPP_ENABLED = bool(os.environ.get("WHATSAPP_ACCESS_TOKEN") and os.environ.get("WHATSAPP_PHONE_NUMBER_ID"))
STORAGE_ENABLED = bool(os.environ.get("S3_ACCESS_KEY_ID") and os.environ.get("S3_BUCKET_NAME") and os.environ.get("S3_ENDPOINT"))
OTP_DEV_MODE = os.environ.get("OTP_DEV_MODE", "1") == "1"

client: AsyncIOMotorClient = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]


# ---------- Time helpers (Asia/Kolkata aware) ----------

def now_utc() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


def today_ist() -> date:
    """Today's civil date in the gym timezone (default Asia/Kolkata)."""
    return datetime.now(GYM_TZ).date()


def aware_utc(value: Any) -> datetime:
    """Coerce a value to a UTC-aware datetime. Falls back to now() if not a datetime."""
    if not isinstance(value, datetime):
        return now_utc()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def add_months(start: date, months: int) -> date:
    """Calendar-correct month addition (30 Jan + 1 month → 28/29 Feb)."""
    return start + relativedelta(months=int(months))


def iso(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def parse_date(value: Any, fallback: Optional[date] = None) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            pass
    return fallback or today_ist()


# ---------- Document normalization ----------

def clean(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Remove Mongo _id, ISO-serialize datetimes/dates in a defensive copy."""
    if not doc:
        return doc
    result = dict(doc)
    result.pop("_id", None)
    for key, value in list(result.items()):
        if isinstance(value, (datetime, date)):
            result[key] = iso(value)
    return result


# ---------- Security primitives ----------

def password_hash(value: str) -> str:
    return bcrypt.hashpw(value.encode(), bcrypt.gensalt()).decode()


def password_verify(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


def hash_identifier(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


def issue_token(subject: str, role: str, hours: int = 12) -> str:
    payload = {"sub": subject, "role": role, "exp": now_utc() + timedelta(hours=hours)}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> Dict[str, Any]:
    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])


# ---------- FastAPI dependencies ----------

async def current_user(request: Request) -> Dict[str, Any]:
    token = request.cookies.get("access_token")
    if not token:
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            token = header[7:]
    if not token:
        raise HTTPException(401, "Authentication required")
    try:
        payload = decode_token(token)
        if payload.get("role") not in {"ADMIN", "SUPER_ADMIN", "STAFF"}:
            raise HTTPException(403, "Staff access required")
        user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0})
    except jwt.PyJWTError as exc:  # pragma: no cover - handled by test
        raise HTTPException(401, "Invalid session") from exc
    if not user:
        raise HTTPException(401, "Session expired")
    user.pop("password_hash", None)
    return user


async def ensure_indexes() -> None:
    """Create indexes needed for correctness and query performance."""
    await db.users.create_index("email", unique=True)
    await db.users.create_index("id", unique=True)
    await db.members.create_index("id", unique=True)
    await db.members.create_index([("phone", 1)])
    await db.members.create_index([("status", 1), ("expiry_date", 1)])
    await db.members.create_index([("delete_after", 1)])
    await db.plans.create_index("id", unique=True)
    await db.settings.create_index("id", unique=True)
    await db.notifications.create_index("id", unique=True)
    await db.notifications.create_index("dedup_key", unique=True, sparse=True)
    await db.notifications.create_index([("status", 1), ("next_retry_at", 1)])
    await db.notifications.create_index([("member_id", 1), ("created_at", -1)])
    await db.payments.create_index("id", unique=True)
    await db.payments.create_index([("member_id", 1), ("created_at", -1)])
    await db.memberships.create_index("id", unique=True)
    await db.memberships.create_index([("member_id", 1), ("created_at", -1)])
    await db.audit_logs.create_index([("created_at", -1)])
    await db.audit_logs.create_index([("entity_type", 1), ("entity_id", 1)])
    await db.webhook_events.create_index([("received_at", -1)])
    await db.inbound_messages.create_index([("received_at", -1)])
    await db.inbound_messages.create_index("wa_message_id", unique=True, sparse=True)


__all__ = [
    "db",
    "client",
    "logger",
    "GYM_TZ",
    "GYM_TZ_NAME",
    "WHATSAPP_ENABLED",
    "STORAGE_ENABLED",
    "OTP_DEV_MODE",
    "now_utc",
    "today_ist",
    "aware_utc",
    "add_months",
    "iso",
    "parse_date",
    "clean",
    "password_hash",
    "password_verify",
    "hash_identifier",
    "issue_token",
    "decode_token",
    "current_user",
    "ensure_indexes",
]
