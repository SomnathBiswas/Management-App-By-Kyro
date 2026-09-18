from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import hashlib
import logging
import os
import secrets

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("titangym")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]
app = FastAPI(title="TitanGym OS API")
api = APIRouter(prefix="/api")
JWT_SECRET = os.environ.get("JWT_SECRET", "titangym-development-secret")
TZ_NAME = "Asia/Kolkata"


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, (datetime, date)) else str(value)


def aware_utc(value: Any) -> datetime:
    if not isinstance(value, datetime):
        return now()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def clean(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return doc
    result = dict(doc)
    result.pop("_id", None)
    for key, value in list(result.items()):
        if isinstance(value, (datetime, date)):
            result[key] = iso(value)
    return result


def password_hash(value: str) -> str:
    return bcrypt.hashpw(value.encode(), bcrypt.gensalt()).decode()


def token_for(user: Dict[str, Any]) -> str:
    return jwt.encode({"sub": user["id"], "role": user["role"], "exp": now() + timedelta(hours=12)}, JWT_SECRET, algorithm="HS256")


async def current_user(request: Request) -> Dict[str, Any]:
    token = request.cookies.get("access_token") or request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise HTTPException(401, "Authentication required")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0})
        if not user:
            raise HTTPException(401, "Session expired")
        return user
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Invalid session") from exc


class LoginInput(BaseModel):
    email: str
    password: str


class OtpInput(BaseModel):
    phone: str
    otp: str


class MemberInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    full_name: str = Field(min_length=2, max_length=80)
    phone: str = Field(min_length=8, max_length=20)
    address: str = ""
    plan_id: str
    start_date: str
    payment_amount: float = Field(ge=0)
    payment_status: str = "PAID"
    payment_method: str = "UPI"
    notes: str = ""
    photo_url: Optional[str] = None


class PlanInput(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    duration_months: int = Field(ge=1, le=36)
    price: float = Field(ge=0)
    description: str = ""
    active: bool = True


class SettingsInput(BaseModel):
    gym_name: str
    gym_phone: str
    gym_address: str
    timezone: str = TZ_NAME
    expiry_reminder_days: int = Field(ge=1, le=30)
    grace_period_days: int = Field(ge=1, le=30)
    retention_days: int = Field(ge=1, le=3650)


async def seed() -> None:
    await db.users.create_index("email", unique=True)
    await db.members.create_index([("phone", 1), ("status", 1), ("expiry_date", 1)])
    await db.notifications.create_index("id", unique=True)
    if not await db.users.find_one({"email": "admin@titangym.in"}):
        await db.users.insert_one({"id": "usr_admin", "email": "admin@titangym.in", "name": "Arjun Mehta", "role": "ADMIN", "password_hash": password_hash("Titan@123")})
    if not await db.settings.find_one({"id": "settings_default"}):
        await db.settings.insert_one({"id": "settings_default", "gym_name": "TitanGym Performance Club", "gym_phone": "+91 98765 43210", "gym_address": "Koramangala, Bengaluru", "timezone": TZ_NAME, "expiry_reminder_days": 7, "grace_period_days": 7, "retention_days": 60})
    if await db.plans.count_documents({}) == 0:
        await db.plans.insert_many([
            {"id": "plan_1", "name": "Forge Monthly", "duration_months": 1, "price": 1200, "description": "Flexible monthly access", "active": True},
            {"id": "plan_3", "name": "Momentum Quarter", "duration_months": 3, "price": 3000, "description": "Best for consistent progress", "active": True},
            {"id": "plan_6", "name": "Strength Half-Year", "duration_months": 6, "price": 5400, "description": "Serious training commitment", "active": True},
            {"id": "plan_12", "name": "Titan Annual", "duration_months": 12, "price": 9600, "description": "The complete performance year", "active": True},
        ])
    if await db.members.count_documents({}) == 0:
        seed_members = [
            ("mem_rahul", "Rahul Sharma", "+91 98201 44320", "plan_3", 18, "ACTIVE", "PAID"),
            ("mem_priya", "Priya Roy", "+91 98111 22031", "plan_1", -2, "GRACE_PERIOD", "PAID"),
            ("mem_amit", "Amit Das", "+91 99001 87222", "plan_6", 5, "EXPIRING_SOON", "PENDING"),
            ("mem_neha", "Neha Kapoor", "+91 98888 11223", "plan_12", -44, "CANCELLED", "PAID"),
        ]
        for member_id, name, phone, plan_id, offset, status, payment in seed_members:
            start = date.today() - timedelta(days=max(1, 30 - offset))
            expiry = date.today() + timedelta(days=offset)
            await db.members.insert_one({"id": member_id, "full_name": name, "phone": phone, "address": "Bengaluru", "plan_id": plan_id, "start_date": start.isoformat(), "expiry_date": expiry.isoformat(), "grace_period_end": (expiry + timedelta(days=7)).isoformat(), "status": status, "payment_status": payment, "payment_amount": 3000, "created_at": now(), "updated_at": now(), "notes": "Seed member"})


@app.on_event("startup")
async def startup() -> None:
    await seed()


@api.get("/")
async def root() -> Dict[str, str]:
    return {"message": "TitanGym OS is ready", "status": "online"}


@api.post("/auth/login")
async def login(payload: LoginInput, response: Response) -> Dict[str, Any]:
    user = await db.users.find_one({"email": payload.email.lower().strip()}, {"_id": 0})
    if not user or not bcrypt.checkpw(payload.password.encode(), user["password_hash"].encode()):
        raise HTTPException(401, "Email or password is incorrect")
    response.set_cookie("access_token", token_for(user), httponly=True, samesite="lax", max_age=43200)
    user.pop("password_hash", None)
    return {"success": True, "user": user}


@api.post("/auth/logout")
async def logout(response: Response) -> Dict[str, bool]:
    response.delete_cookie("access_token")
    return {"success": True}


@api.get("/auth/me")
async def me(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    user.pop("password_hash", None)
    return user


@api.post("/auth/member/request-otp")
async def request_otp(payload: Dict[str, str]) -> Dict[str, Any]:
    phone = payload.get("phone", "").strip()
    member = await db.members.find_one({"phone": phone}, {"_id": 0})
    if not member:
        raise HTTPException(404, "No member found for this phone number")
    await db.otp.update_one({"phone": phone}, {"$set": {"otp": "123456", "expires_at": now() + timedelta(minutes=5)}}, upsert=True)
    return {"success": True, "message": "OTP sent", "development_otp": "123456"}


@api.post("/auth/member/verify-otp")
async def verify_otp(payload: OtpInput, response: Response) -> Dict[str, Any]:
    record = await db.otp.find_one({"phone": payload.phone})
    expires_at = aware_utc(record.get("expires_at")) if record else now()
    if not record or record.get("otp") != payload.otp or expires_at < now():
        raise HTTPException(401, "Invalid or expired OTP")
    member = await db.members.find_one({"phone": payload.phone}, {"_id": 0})
    response.set_cookie("member_token", token_for({"id": member["id"], "role": "MEMBER"}), httponly=True, samesite="lax", max_age=43200)
    return {"success": True, "member": clean(member)}


@api.get("/dashboard")
async def dashboard(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    members = await db.members.find({}, {"_id": 0}).to_list(1000)
    counts = {status: sum(1 for m in members if m.get("status") == status) for status in ["ACTIVE", "EXPIRING_SOON", "EXPIRED", "GRACE_PERIOD", "CANCELLED"]}
    revenue = sum(float(m.get("payment_amount", 0)) for m in members if m.get("payment_status") == "PAID")
    return {"total_members": len(members), "active_members": counts["ACTIVE"], "expiring_soon": counts["EXPIRING_SOON"], "expired": counts["EXPIRED"], "grace_period": counts["GRACE_PERIOD"], "cancelled": counts["CANCELLED"], "new_today": sum(1 for m in members if str(m.get("created_at", ""))[:10] == str(date.today())), "revenue": revenue, "members": [clean(m) for m in members]}


@api.get("/members")
async def list_members(search: str = "", status: str = "ALL", user: Dict[str, Any] = Depends(current_user)) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {}
    if status != "ALL": query["status"] = status
    if search: query["$or"] = [{"full_name": {"$regex": search, "$options": "i"}}, {"phone": {"$regex": search, "$options": "i"}}]
    members = await db.members.find(query, {"_id": 0}).sort("expiry_date", 1).to_list(500)
    plans = {p["id"]: p["name"] for p in await db.plans.find({}, {"_id": 0}).to_list(100)}
    return [{**clean(m), "plan_name": plans.get(m.get("plan_id"), "Custom plan")} for m in members]


@api.post("/members")
async def create_member(payload: MemberInput, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    plan = await db.plans.find_one({"id": payload.plan_id}, {"_id": 0})
    if not plan: raise HTTPException(400, "Membership plan not found")
    start = date.fromisoformat(payload.start_date)
    expiry = start + timedelta(days=30 * int(plan["duration_months"]))
    member = {"id": "mem_" + secrets.token_hex(5), **payload.model_dump(), "start_date": start.isoformat(), "expiry_date": expiry.isoformat(), "grace_period_end": (expiry + timedelta(days=7)).isoformat(), "status": "ACTIVE", "created_at": now(), "updated_at": now()}
    await db.members.insert_one(member)
    await db.payments.insert_one({"id": "pay_" + secrets.token_hex(5), "member_id": member["id"], "amount": payload.payment_amount, "status": payload.payment_status, "method": payload.payment_method, "created_at": now()})
    await db.notifications.insert_one({"id": "not_" + secrets.token_hex(5), "member_id": member["id"], "type": "WELCOME", "channel": "WHATSAPP", "status": "QUEUED_PROVIDER_DISABLED", "created_at": now()})
    return clean(member)


@api.get("/members/{member_id}")
async def get_member(member_id: str, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    member = await db.members.find_one({"id": member_id}, {"_id": 0})
    if not member: raise HTTPException(404, "Member not found")
    plan = await db.plans.find_one({"id": member.get("plan_id")}, {"_id": 0})
    history = await db.memberships.find({"member_id": member_id}, {"_id": 0}).sort("created_at", -1).to_list(100)
    notifications = await db.notifications.find({"member_id": member_id}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return {"member": clean(member), "plan": clean(plan), "history": [clean(x) for x in history], "notifications": [clean(x) for x in notifications]}


@api.post("/members/{member_id}/renew")
async def renew_member(member_id: str, payload: Dict[str, Any], user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    member = await db.members.find_one({"id": member_id}, {"_id": 0})
    plan = await db.plans.find_one({"id": payload.get("plan_id")}, {"_id": 0})
    if not member or not plan: raise HTTPException(404, "Member or plan not found")
    start = date.fromisoformat(payload.get("start_date", str(date.today())))
    expiry = start + timedelta(days=30 * int(plan["duration_months"]))
    await db.members.update_one({"id": member_id}, {"$set": {"plan_id": plan["id"], "start_date": start.isoformat(), "expiry_date": expiry.isoformat(), "grace_period_end": (expiry + timedelta(days=7)).isoformat(), "status": "ACTIVE", "payment_status": payload.get("payment_status", "PAID"), "updated_at": now()}})
    await db.memberships.insert_one({"id": "hist_" + secrets.token_hex(5), "member_id": member_id, "plan_name": plan["name"], "start_date": start.isoformat(), "expiry_date": expiry.isoformat(), "amount": float(payload.get("amount", plan["price"])), "type": "RENEWAL", "created_at": now()})
    return {"success": True, "expiry_date": expiry.isoformat()}


@api.get("/plans")
async def list_plans(user: Dict[str, Any] = Depends(current_user)) -> List[Dict[str, Any]]:
    return [clean(p) for p in await db.plans.find({}, {"_id": 0}).sort("duration_months", 1).to_list(100)]


@api.post("/plans")
async def create_plan(payload: PlanInput, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    plan = {"id": "plan_" + secrets.token_hex(5), **payload.model_dump()}
    await db.plans.insert_one(plan)
    return clean(plan)


@api.get("/settings")
async def get_settings(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    return clean(await db.settings.find_one({"id": "settings_default"}, {"_id": 0})) or {}


@api.put("/settings")
async def update_settings(payload: SettingsInput, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    await db.settings.update_one({"id": "settings_default"}, {"$set": payload.model_dump()}, upsert=True)
    return payload.model_dump()


@api.get("/notifications")
async def notifications(user: Dict[str, Any] = Depends(current_user)) -> List[Dict[str, Any]]:
    return [clean(x) for x in await db.notifications.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)]


@api.post("/jobs/run")
async def run_jobs(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    settings = await db.settings.find_one({"id": "settings_default"}, {"_id": 0})
    changed = {"expiring": 0, "grace_started": 0, "cancelled": 0, "deleted": 0}
    today = date.today()
    for member in await db.members.find({}, {"_id": 0}).to_list(1000):
        expiry = date.fromisoformat(member["expiry_date"])
        if member["status"] == "ACTIVE" and 0 <= (expiry - today).days <= settings["expiry_reminder_days"]:
            await db.members.update_one({"id": member["id"]}, {"$set": {"status": "EXPIRING_SOON"}}); changed["expiring"] += 1
        elif member["status"] in ["ACTIVE", "EXPIRING_SOON"] and expiry < today:
            await db.members.update_one({"id": member["id"]}, {"$set": {"status": "GRACE_PERIOD", "grace_period_end": (expiry + timedelta(days=settings["grace_period_days"])).isoformat()}}); changed["grace_started"] += 1
        elif member["status"] == "GRACE_PERIOD" and date.fromisoformat(member["grace_period_end"]) < today:
            cancelled = now(); await db.members.update_one({"id": member["id"]}, {"$set": {"status": "CANCELLED", "cancelled_at": cancelled, "delete_after": (cancelled + timedelta(days=settings["retention_days"])).isoformat()}}); changed["cancelled"] += 1
    return {"success": True, "changed": changed, "provider": "WhatsApp disabled until credentials are configured"}


@api.get("/member/me")
async def member_me(request: Request) -> Dict[str, Any]:
    token = request.cookies.get("member_token")
    if not token: raise HTTPException(401, "Member login required")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError as exc: raise HTTPException(401, "Invalid session") from exc
    return await get_member(payload["sub"], {})


app.include_router(api)
configured_origins = [origin.strip() for origin in os.environ.get("CORS_ORIGINS", "").split(",") if origin.strip() and origin.strip() != "*"]
frontend_origin = os.environ.get("FRONTEND_URL")
if frontend_origin and frontend_origin not in configured_origins:
    configured_origins.append(frontend_origin)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=configured_origins, allow_methods=["*"], allow_headers=["*"])


@app.on_event("shutdown")
async def shutdown() -> None:
    client.close()