"""All HTTP routers. Groups related endpoints under /api/*."""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import os
import secrets as _secrets
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse

from core import (
    STORAGE_ENABLED,
    WHATSAPP_ENABLED,
    aware_utc,
    clean,
    current_user,
    db,
    hash_identifier,
    issue_token,
    logger,
    now_utc,
    password_verify,
    today_ist,
)
from schemas import (
    LoginInput,
    MemberInput,
    MemberUpdateInput,
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
from storage import delete_object, presigned_url, upload_member_photo

api = APIRouter(prefix="/api")


def _attach_photo(member: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Inject a fresh presigned URL for the member's photo (if any)."""
    if not member:
        return member
    key = member.get("photo_key")
    if key:
        member["photo_url"] = presigned_url(key)
    return member

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
        samesite="none",
        secure=True,
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
    response.delete_cookie("access_token", samesite="none", secure=True)
    return {"success": True}


@api.get("/auth/me")
async def me(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    return clean(user)


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
        row = clean(_attach_photo(m))
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
    return [{**clean(_attach_photo(m)), "plan_name": plans.get(m.get("plan_id"), "Custom plan")} for m in members]


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
    return clean(_attach_photo(member))


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
        "member": clean(_attach_photo(member)),
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
        return clean(_attach_photo(member))
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
    return clean(_attach_photo(updated))


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


@api.delete("/plans/{plan_id}")
async def delete_plan(plan_id: str, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    plan = await db.plans.find_one({"id": plan_id}, {"_id": 0})
    if not plan:
        raise HTTPException(404, "Plan not found")
    in_use = await db.members.count_documents({"plan_id": plan_id, "status": {"$nin": ["CANCELLED", "PERMANENTLY_DELETED"]}})
    if in_use:
        # Soft-disable when members still use the plan so history stays intact.
        await db.plans.update_one({"id": plan_id}, {"$set": {"active": False}})
        await AuditService.record(
            action="PLAN_DISABLED",
            entity_type="PLAN",
            entity_id=plan_id,
            actor_id=user["id"],
            actor_role=user.get("role", "ADMIN"),
            metadata={"reason": "members_active", "count": in_use},
        )
        return {"success": True, "deleted": False, "disabled": True, "active_members": in_use}
    await db.plans.delete_one({"id": plan_id})
    await AuditService.record(
        action="PLAN_DELETED",
        entity_type="PLAN",
        entity_id=plan_id,
        actor_id=user["id"],
        actor_role=user.get("role", "ADMIN"),
    )
    return {"success": True, "deleted": True}


# =====================================================================
# Uploads (Cloudflare R2)
# =====================================================================
@api.post("/uploads/member-photo")
async def upload_photo(file: UploadFile = File(...), user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    if not STORAGE_ENABLED:
        raise HTTPException(503, "Photo storage is not configured")
    data = await file.read()
    try:
        key = upload_member_photo(data=data, filename=file.filename or "photo.jpg", content_type=file.content_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"success": True, "photo_key": key, "photo_url": presigned_url(key)}


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
# WhatsApp Cloud API webhook (Meta)
# =====================================================================

_STATUS_MAP = {
    "sent": "SENT",
    "delivered": "DELIVERED",
    "read": "READ",
    "failed": "FAILED",
}


def _verify_signature(raw_body: bytes, header: Optional[str], secret: str) -> bool:
    """Best-effort HMAC-SHA256 verification of the X-Hub-Signature-256 header."""
    if not secret or not header:
        return True  # Signature check skipped when app secret is not configured.
    if not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


@api.get("/webhooks/whatsapp", response_class=PlainTextResponse)
async def whatsapp_verify(request: Request) -> Response:
    """Meta subscription handshake. Echoes hub.challenge when the token matches."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge", "")
    expected = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
    if mode == "subscribe" and expected and token and hmac.compare_digest(token, expected):
        return PlainTextResponse(challenge, status_code=200)
    return PlainTextResponse("forbidden", status_code=403)


@api.post("/webhooks/whatsapp")
async def whatsapp_events(request: Request) -> Dict[str, Any]:
    """Receive Meta WhatsApp webhook events. Always returns 200 quickly.

    Access tokens are never logged or echoed back.
    """
    raw = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    app_secret = os.environ.get("WHATSAPP_APP_SECRET", "")
    valid_sig = _verify_signature(raw, signature, app_secret)

    try:
        payload = await request.json() if raw else {}
    except Exception:
        payload = {}

    event_record = {
        "id": "whe_" + _secrets.token_hex(6),
        "signature_valid": valid_sig,
        "payload": payload,
        "received_at": now_utc(),
    }
    try:
        await db.webhook_events.insert_one(event_record)
    except Exception:
        logger.exception("whatsapp.webhook_persist_failed")

    processed = {"statuses": 0, "messages": 0}
    if valid_sig and isinstance(payload, dict) and payload.get("object") == "whatsapp_business_account":
        for entry in payload.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                value = change.get("value") or {}
                for status in value.get("statuses", []) or []:
                    updated = await _apply_status_update(status)
                    if updated:
                        processed["statuses"] += 1
                for message in value.get("messages", []) or []:
                    await _record_inbound_message(message, value.get("metadata"))
                    processed["messages"] += 1

    logger.info("whatsapp.webhook received signature_valid=%s statuses=%s messages=%s",
                valid_sig, processed["statuses"], processed["messages"])
    return {"status": "received"}


async def _apply_status_update(status: Dict[str, Any]) -> bool:
    """Update the notification identified by provider_message_id."""
    message_id = status.get("id")
    kind = (status.get("status") or "").lower()
    mapped = _STATUS_MAP.get(kind)
    if not message_id or not mapped:
        return False
    updates: Dict[str, Any] = {"status": mapped, "updated_at": now_utc()}
    if mapped == "DELIVERED" or mapped == "READ":
        updates["sent_at"] = updates.get("sent_at") or now_utc()
    if mapped == "FAILED":
        errors = status.get("errors") or []
        updates["failed_at"] = now_utc()
        updates["error_message"] = (errors[0].get("title") if errors else "Provider reported failure")
    result = await db.notifications.update_one({"provider_message_id": message_id}, {"$set": updates})
    return bool(result.modified_count)


async def _record_inbound_message(message: Dict[str, Any], meta: Optional[Dict[str, Any]]) -> None:
    """Persist inbound WhatsApp messages for admin review. No token echoed."""
    try:
        await db.inbound_messages.insert_one({
            "id": "inm_" + _secrets.token_hex(6),
            "wa_message_id": message.get("id"),
            "from": message.get("from"),
            "type": message.get("type"),
            "text": (message.get("text") or {}).get("body"),
            "timestamp": message.get("timestamp"),
            "phone_number_id": (meta or {}).get("phone_number_id"),
            "received_at": now_utc(),
        })
    except Exception:
        logger.exception("whatsapp.inbound_persist_failed")


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
