"""All HTTP routers. Groups related endpoints under /api/*."""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from core import (
    OTP_DEV_MODE,
    STORAGE_ENABLED,
    WHATSAPP_ENABLED,
    aware_utc,
    clean,
    current_member,
    current_user,
    db,
    hash_identifier,
    issue_token,
    now_utc,
    password_verify,
    today_ist,
)
from schemas import (
    LoginInput,
    MemberInput,
    MemberUpdateInput,
    OtpRequestInput,
    OtpVerifyInput,
    PaymentInput,
    PlanInput,
    PlanUpdateInput,
    RenewInput,
    SettingsInput,
)
from scheduler import trigger_lifecycle_now
from services import (
    AuditService,
    LifecycleService,
    NotificationService,
    PaymentService,
)

api = APIRouter(prefix="/api")

# =====================================================================
# Health
# =====================================================================
@api.get("/")
async def root() -> Dict[str, Any]:
    return {
        "message": "TitanGym OS is ready",
        "status": "online",
        "providers": {
            "whatsapp": "enabled" if WHATSAPP_ENABLED else "disabled",
            "storage": "enabled" if STORAGE_ENABLED else "disabled",
            "otp": "dev-mode" if OTP_DEV_MODE else "provider",
        },
    }


@api.get("/health")
async def health() -> Dict[str, Any]:
    return await root()


# =====================================================================
# Auth (admin/staff)
# =====================================================================
@api.post("/auth/login")
async def login(payload: LoginInput, response: Response) -> Dict[str, Any]:
    email = payload.email.lower().strip()
    identifier = hash_identifier(email)
    attempt = await db.login_attempts.find_one({"identifier": identifier}, {"_id": 0})
    if attempt and attempt.get("lock_until") and aware_utc(attempt.get("lock_until")) > now_utc():
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes")
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user or not password_verify(payload.password, user["password_hash"]):
        failures = int(attempt.get("failures", 0)) + 1 if attempt else 1
        update: Dict[str, Any] = {"failures": failures, "last_failed_at": now_utc()}
        if failures >= 5:
            update["lock_until"] = now_utc().replace(microsecond=0) + timedelta(minutes=15)
        await db.login_attempts.update_one({"identifier": identifier}, {"$set": update}, upsert=True)
        raise HTTPException(401, "Email or password is incorrect")
    await db.login_attempts.delete_one({"identifier": identifier})
    response.set_cookie(
        "access_token",
        issue_token(user["id"], user.get("role", "ADMIN")),
        httponly=True,
        samesite="lax",
        max_age=43200,
    )
    await AuditService.record(
        action="ADMIN_LOGIN",
        entity_type="USER",
        entity_id=user["id"],
        actor_id=user["id"],
        actor_role=user.get("role", "ADMIN"),
    )
    user.pop("password_hash", None)
    return {"success": True, "user": clean(user)}


@api.post("/auth/logout")
async def logout(response: Response) -> Dict[str, bool]:
    response.delete_cookie("access_token")
    return {"success": True}


@api.get("/auth/me")
async def me(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    return clean(user)


# =====================================================================
# Member OTP auth (phone + OTP)
# =====================================================================
@api.post("/auth/member/request-otp")
async def request_otp(payload: OtpRequestInput) -> Dict[str, Any]:
    phone = payload.phone.strip()
    member = await db.members.find_one({"phone": phone}, {"_id": 0})
    if not member:
        raise HTTPException(404, "No member found for this phone number")
    if member.get("status") == "PERMANENTLY_DELETED":
        raise HTTPException(410, "This membership record has been erased")
    otp_value = "123456" if OTP_DEV_MODE else "".join(__import__("secrets").choice("0123456789") for _ in range(6))
    await db.otp.update_one(
        {"phone": phone},
        {"$set": {
            "otp": otp_value,
            "expires_at": now_utc() + timedelta(minutes=5),
            "attempts": 0,
            "issued_at": now_utc(),
        }},
        upsert=True,
    )
    response: Dict[str, Any] = {"success": True, "message": "OTP sent"}
    if OTP_DEV_MODE:
        response["development_otp"] = otp_value
    return response


@api.post("/auth/member/verify-otp")
async def verify_otp(payload: OtpVerifyInput, response: Response) -> Dict[str, Any]:
    record = await db.otp.find_one({"phone": payload.phone})
    if not record:
        raise HTTPException(401, "Invalid or expired OTP")
    expires_at = aware_utc(record.get("expires_at"))
    attempts = int(record.get("attempts", 0))
    if attempts >= 5:
        raise HTTPException(429, "Too many OTP attempts. Request a new code")
    if record.get("otp") != payload.otp or expires_at < now_utc():
        await db.otp.update_one({"phone": payload.phone}, {"$inc": {"attempts": 1}})
        raise HTTPException(401, "Invalid or expired OTP")
    member = await db.members.find_one({"phone": payload.phone}, {"_id": 0})
    if not member:
        raise HTTPException(404, "Member record not found")
    await db.otp.delete_one({"phone": payload.phone})
    response.set_cookie(
        "member_token",
        issue_token(member["id"], "MEMBER"),
        httponly=True,
        samesite="lax",
        max_age=43200,
    )
    return {"success": True, "member": clean(member)}


@api.post("/auth/member/logout")
async def member_logout(response: Response) -> Dict[str, bool]:
    response.delete_cookie("member_token")
    return {"success": True}


# =====================================================================
# Dashboard
# =====================================================================
@api.get("/dashboard")
async def dashboard(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    members = await db.members.find({"status": {"$ne": "PERMANENTLY_DELETED"}}, {"_id": 0}).to_list(2000)
    counts = {status: sum(1 for m in members if m.get("status") == status)
              for status in ["ACTIVE", "EXPIRING_SOON", "EXPIRED", "GRACE_PERIOD", "CANCELLED"]}
    revenue = await PaymentService.total_revenue()
    today_str = today_ist().isoformat()
    plans = {p["id"]: p["name"] for p in await db.plans.find({}, {"_id": 0}).to_list(200)}
    enriched = []
    for m in members:
        row = clean(m)
        row["plan_name"] = plans.get(m.get("plan_id"), "Custom plan")
        enriched.append(row)
    return {
        "total_members": len(members),
        "active_members": counts["ACTIVE"],
        "expiring_soon": counts["EXPIRING_SOON"],
        "expired": counts["EXPIRED"],
        "grace_period": counts["GRACE_PERIOD"],
        "cancelled": counts["CANCELLED"],
        "new_today": sum(1 for m in members if str(m.get("created_at", ""))[:10] == today_str),
        "revenue": revenue,
        "members": enriched,
    }


# =====================================================================
# Members
# =====================================================================
@api.get("/members")
async def list_members(
    search: str = "",
    status: str = "ALL",
    plan_id: Optional[str] = None,
    payment_status: Optional[str] = None,
    limit: int = Query(500, ge=1, le=2000),
    user: Dict[str, Any] = Depends(current_user),
) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {"status": {"$ne": "PERMANENTLY_DELETED"}}
    if status != "ALL":
        query["status"] = status
    if plan_id:
        query["plan_id"] = plan_id
    if payment_status:
        query["payment_status"] = payment_status
    if search:
        query["$or"] = [
            {"full_name": {"$regex": search, "$options": "i"}},
            {"phone": {"$regex": search, "$options": "i"}},
        ]
    members = await db.members.find(query, {"_id": 0}).sort("expiry_date", 1).to_list(limit)
    plans = {p["id"]: p["name"] for p in await db.plans.find({}, {"_id": 0}).to_list(200)}
    return [{**clean(m), "plan_name": plans.get(m.get("plan_id"), "Custom plan")} for m in members]


@api.post("/members")
async def create_member(payload: MemberInput, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    plan = await db.plans.find_one({"id": payload.plan_id}, {"_id": 0})
    if not plan:
        raise HTTPException(400, "Membership plan not found")
    if not plan.get("active", True):
        raise HTTPException(400, "This plan is not currently active")
    duplicate = await db.members.find_one(
        {"phone": payload.phone, "status": {"$nin": ["PERMANENTLY_DELETED", "CANCELLED"]}},
        {"_id": 0},
    )
    if duplicate:
        raise HTTPException(409, "A member with this phone already exists")
    member = await LifecycleService.create_member_with_membership(
        payload=payload.model_dump(),
        plan=plan,
        actor_id=user["id"],
    )
    return clean(member)


@api.get("/members/{member_id}")
async def get_member(member_id: str, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    member = await db.members.find_one({"id": member_id}, {"_id": 0})
    if not member:
        raise HTTPException(404, "Member not found")
    plan = await db.plans.find_one({"id": member.get("plan_id")}, {"_id": 0})
    history = await db.memberships.find({"member_id": member_id}, {"_id": 0}).sort("created_at", -1).to_list(100)
    notifications = await db.notifications.find({"member_id": member_id}, {"_id": 0}).sort("created_at", -1).to_list(100)
    payments = await PaymentService.list_for_member(member_id)
    audit = await db.audit_logs.find({"entity_id": member_id}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return {
        "member": clean(member),
        "plan": clean(plan),
        "history": [clean(x) for x in history],
        "notifications": [clean(x) for x in notifications],
        "payments": [clean(x) for x in payments],
        "audit": [clean(x) for x in audit],
    }


@api.patch("/members/{member_id}")
async def update_member(member_id: str, payload: MemberUpdateInput, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    member = await db.members.find_one({"id": member_id}, {"_id": 0})
    if not member:
        raise HTTPException(404, "Member not found")
    changes = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not changes:
        return clean(member)
    changes["updated_at"] = now_utc()
    await db.members.update_one({"id": member_id}, {"$set": changes})
    await AuditService.record(
        action="MEMBER_UPDATED",
        entity_type="MEMBER",
        entity_id=member_id,
        actor_id=user["id"],
        actor_role=user.get("role", "ADMIN"),
        metadata={"fields": list(changes.keys())},
    )
    updated = await db.members.find_one({"id": member_id}, {"_id": 0})
    return clean(updated)


@api.post("/members/{member_id}/renew")
async def renew_member(member_id: str, payload: RenewInput, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    member = await db.members.find_one({"id": member_id}, {"_id": 0})
    plan = await db.plans.find_one({"id": payload.plan_id}, {"_id": 0})
    if not member or not plan:
        raise HTTPException(404, "Member or plan not found")
    result = await LifecycleService.renew_membership(
        member=member,
        plan=plan,
        payload=payload.model_dump(),
        actor_id=user["id"],
        actor_role="ADMIN",
    )
    return {"success": True, **result}


@api.post("/members/{member_id}/cancel")
async def cancel_member(member_id: str, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    member = await db.members.find_one({"id": member_id}, {"_id": 0})
    if not member:
        raise HTTPException(404, "Member not found")
    settings = await db.settings.find_one({"id": "settings_default"}, {"_id": 0}) or {"retention_days": 60}
    delete_after_date = today_ist() + timedelta(days=int(settings.get("retention_days", 60)))
    await db.members.update_one(
        {"id": member_id},
        {"$set": {
            "status": "CANCELLED",
            "cancelled_at": now_utc(),
            "delete_after": delete_after_date.isoformat(),
            "updated_at": now_utc(),
        }},
    )
    await NotificationService.enqueue(member_id=member_id, notification_type="CANCELLED")
    await AuditService.record(
        action="MEMBERSHIP_CANCELLED",
        entity_type="MEMBER",
        entity_id=member_id,
        actor_id=user["id"],
        actor_role=user.get("role", "ADMIN"),
        metadata={"reason": "admin_action"},
    )
    return {"success": True, "delete_after": delete_after_date.isoformat()}


@api.get("/members/export/csv")
async def export_members_csv(user: Dict[str, Any] = Depends(current_user)) -> StreamingResponse:
    members = await db.members.find({"status": {"$ne": "PERMANENTLY_DELETED"}}, {"_id": 0}).to_list(5000)
    plans = {p["id"]: p["name"] for p in await db.plans.find({}, {"_id": 0}).to_list(200)}
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Full name", "Phone", "Plan", "Start date", "Expiry date", "Status", "Payment status", "Amount"])
    for m in members:
        writer.writerow([
            m.get("full_name", ""),
            m.get("phone", ""),
            plans.get(m.get("plan_id"), ""),
            m.get("start_date", ""),
            m.get("expiry_date", ""),
            m.get("status", ""),
            m.get("payment_status", ""),
            m.get("payment_amount", 0),
        ])
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=titangym-members.csv"},
    )


# =====================================================================
# Plans
# =====================================================================
@api.get("/plans")
async def list_plans(user: Dict[str, Any] = Depends(current_user)) -> List[Dict[str, Any]]:
    return [clean(p) for p in await db.plans.find({}, {"_id": 0}).sort("duration_months", 1).to_list(200)]


@api.post("/plans")
async def create_plan(payload: PlanInput, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    import secrets
    plan = {"id": "plan_" + secrets.token_hex(5), **payload.model_dump()}
    await db.plans.insert_one(plan)
    await AuditService.record(
        action="PLAN_CREATED",
        entity_type="PLAN",
        entity_id=plan["id"],
        actor_id=user["id"],
        actor_role=user.get("role", "ADMIN"),
    )
    return clean(plan)


@api.patch("/plans/{plan_id}")
async def update_plan(plan_id: str, payload: PlanUpdateInput, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    plan = await db.plans.find_one({"id": plan_id}, {"_id": 0})
    if not plan:
        raise HTTPException(404, "Plan not found")
    changes = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if changes:
        await db.plans.update_one({"id": plan_id}, {"$set": changes})
        await AuditService.record(
            action="PLAN_UPDATED",
            entity_type="PLAN",
            entity_id=plan_id,
            actor_id=user["id"],
            actor_role=user.get("role", "ADMIN"),
            metadata={"fields": list(changes.keys())},
        )
    return clean(await db.plans.find_one({"id": plan_id}, {"_id": 0}))


# =====================================================================
# Settings
# =====================================================================
@api.get("/settings")
async def get_settings(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    return clean(await db.settings.find_one({"id": "settings_default"}, {"_id": 0})) or {}


@api.put("/settings")
async def update_settings(payload: SettingsInput, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    await db.settings.update_one({"id": "settings_default"}, {"$set": payload.model_dump()}, upsert=True)
    await AuditService.record(
        action="SETTINGS_UPDATED",
        entity_type="SETTINGS",
        entity_id="settings_default",
        actor_id=user["id"],
        actor_role=user.get("role", "ADMIN"),
    )
    return payload.model_dump()


# =====================================================================
# Notifications
# =====================================================================
@api.get("/notifications")
async def notifications(user: Dict[str, Any] = Depends(current_user)) -> List[Dict[str, Any]]:
    return [clean(x) for x in await db.notifications.find({}, {"_id": 0}).sort("created_at", -1).to_list(300)]


@api.post("/notifications/{notification_id}/retry")
async def retry_notification(notification_id: str, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    result = await NotificationService.retry(notification_id)
    if not result:
        raise HTTPException(404, "Notification not found")
    await AuditService.record(
        action="NOTIFICATION_RETRIED",
        entity_type="NOTIFICATION",
        entity_id=notification_id,
        actor_id=user["id"],
        actor_role=user.get("role", "ADMIN"),
    )
    return {"success": True, "notification": clean(result)}


# =====================================================================
# Payments
# =====================================================================
@api.get("/payments")
async def list_payments(user: Dict[str, Any] = Depends(current_user)) -> List[Dict[str, Any]]:
    return [clean(p) for p in await PaymentService.list_all(1000)]


@api.post("/payments")
async def create_payment(payload: PaymentInput, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    member = await db.members.find_one({"id": payload.member_id}, {"_id": 0})
    if not member:
        raise HTTPException(404, "Member not found")
    payment = await PaymentService.record(**payload.model_dump())
    await AuditService.record(
        action="PAYMENT_CREATED",
        entity_type="PAYMENT",
        entity_id=payment["id"],
        actor_id=user["id"],
        actor_role=user.get("role", "ADMIN"),
        metadata={"amount": payment["amount"], "member_id": payload.member_id},
    )
    return clean(payment)


@api.get("/payments/{payment_id}/receipt")
async def payment_receipt(payment_id: str, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    payment = await db.payments.find_one({"id": payment_id}, {"_id": 0})
    if not payment:
        raise HTTPException(404, "Payment not found")
    member = await db.members.find_one({"id": payment.get("member_id")}, {"_id": 0})
    settings = await db.settings.find_one({"id": "settings_default"}, {"_id": 0})
    return {
        "receipt": clean(payment),
        "member": clean(member),
        "gym": clean(settings),
        "issued_at": now_utc().isoformat(),
    }


# =====================================================================
# Audit
# =====================================================================
@api.get("/audit")
async def list_audit(limit: int = Query(200, ge=1, le=1000), user: Dict[str, Any] = Depends(current_user)) -> List[Dict[str, Any]]:
    return [clean(a) for a in await AuditService.list(limit)]


# =====================================================================
# Reports
# =====================================================================
@api.get("/reports/summary")
async def reports_summary(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    today = today_ist()
    start_of_month = today.replace(day=1)
    last_month_start = (start_of_month - timedelta(days=1)).replace(day=1)
    payments = await db.payments.find({}, {"_id": 0}).to_list(5000)
    def in_range(p: Dict[str, Any], start: date, end: date) -> bool:
        created = str(p.get("created_at", ""))[:10]
        try:
            created_d = date.fromisoformat(created)
        except ValueError:
            return False
        return start <= created_d <= end
    def total(items: List[Dict[str, Any]]) -> float:
        return round(sum(float(p.get("amount", 0)) for p in items if p.get("status") == "PAID"), 2)
    this_month = [p for p in payments if in_range(p, start_of_month, today)]
    last_month = [p for p in payments if in_range(p, last_month_start, start_of_month - timedelta(days=1))]
    members = await db.members.find({"status": {"$ne": "PERMANENTLY_DELETED"}}, {"_id": 0}).to_list(5000)
    plan_map: Dict[str, int] = {}
    for m in members:
        pid = m.get("plan_id", "custom")
        plan_map[pid] = plan_map.get(pid, 0) + 1
    plans = await db.plans.find({}, {"_id": 0}).to_list(200)
    plan_distribution = [{"plan_id": p["id"], "name": p["name"], "count": plan_map.get(p["id"], 0)} for p in plans]
    return {
        "revenue_this_month": total(this_month),
        "revenue_last_month": total(last_month),
        "outstanding": round(sum(float(m.get("payment_amount", 0)) for m in members if m.get("payment_status") == "PENDING"), 2),
        "plan_distribution": plan_distribution,
        "new_members_this_month": sum(1 for m in members if str(m.get("created_at", ""))[:10] >= start_of_month.isoformat()),
    }


# =====================================================================
# Jobs (admin trigger for lifecycle + retry)
# =====================================================================
@api.post("/jobs/run")
async def run_jobs(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    result = await trigger_lifecycle_now()
    await AuditService.record(
        action="LIFECYCLE_TRIGGERED",
        entity_type="SYSTEM",
        entity_id="lifecycle",
        actor_id=user["id"],
        actor_role=user.get("role", "ADMIN"),
        metadata=result,
    )
    return {
        "success": True,
        "changed": {
            "expiring": result["lifecycle"]["reminded"],
            "grace_started": result["lifecycle"]["grace_started"],
            "cancelled": result["lifecycle"]["cancelled"],
            "deleted": result["lifecycle"]["deleted"],
        },
        "retries_processed": result["retries_processed"],
        "provider": "WhatsApp disabled until credentials are configured" if not WHATSAPP_ENABLED else "WhatsApp enabled",
    }


# =====================================================================
# Member portal
# =====================================================================
@api.get("/member/me")
async def member_me(member: Dict[str, Any] = Depends(current_member)) -> Dict[str, Any]:
    plan = await db.plans.find_one({"id": member.get("plan_id")}, {"_id": 0})
    history = await db.memberships.find({"member_id": member["id"]}, {"_id": 0}).sort("created_at", -1).to_list(50)
    payments = await PaymentService.list_for_member(member["id"])
    settings = await db.settings.find_one({"id": "settings_default"}, {"_id": 0}) or {}
    today = today_ist()
    expiry = member.get("expiry_date")
    days_remaining = None
    if expiry:
        try:
            days_remaining = (date.fromisoformat(expiry) - today).days
        except ValueError:
            days_remaining = None
    return {
        "member": clean(member),
        "plan": clean(plan),
        "gym": {"name": settings.get("gym_name", "TitanGym"), "phone": settings.get("gym_phone"), "address": settings.get("gym_address")},
        "history": [clean(item) for item in history],
        "payments": [clean(p) for p in payments],
        "days_remaining": days_remaining,
    }
