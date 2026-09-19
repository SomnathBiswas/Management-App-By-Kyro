"""Business services: audit log, notifications, payments, membership lifecycle.

Each service is stateless and pure with respect to its inputs; state is
persisted through the shared Motor database handle. Notifications are
idempotent through `dedup_key` unique index and lifecycle transitions are
safe to run multiple times per day.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pymongo.errors import DuplicateKeyError

from core import (
    add_months,
    aware_utc,
    db,
    iso,
    logger,
    now_utc,
    parse_date,
    today_ist,
    WHATSAPP_ENABLED,
)


# ---------- Constants ----------

NOTIFICATION_TYPES = [
    "WELCOME",
    "EXPIRY_REMINDER",
    "EXPIRY",
    "GRACE_FINAL",
    "CANCELLED",
    "DELETION",
]
MAX_NOTIFICATION_ATTEMPTS = 5
RETRY_BACKOFF_MINUTES = [5, 30, 120, 720, 1440]

STATUS_ACTIVE = "ACTIVE"
STATUS_EXPIRING = "EXPIRING_SOON"
STATUS_GRACE = "GRACE_PERIOD"
STATUS_CANCELLED = "CANCELLED"
STATUS_DELETED = "PERMANENTLY_DELETED"


# =====================================================================
# Audit service
# =====================================================================

class AuditService:
    @staticmethod
    async def record(
        *,
        action: str,
        entity_type: str,
        entity_id: str,
        actor_id: Optional[str] = None,
        actor_role: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        entry = {
            "id": "aud_" + secrets.token_hex(6),
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "metadata": metadata or {},
            "created_at": now_utc(),
        }
        try:
            await db.audit_logs.insert_one(entry)
        except Exception:  # pragma: no cover
            logger.exception("audit_log_insert_failed action=%s entity=%s", action, entity_type)

    @staticmethod
    async def list(limit: int = 200) -> List[Dict[str, Any]]:
        return await db.audit_logs.find({}, {"_id": 0}).sort("created_at", -1).to_list(limit)


# =====================================================================
# Notification service (idempotent, retry-safe)
# =====================================================================

class NotificationService:
    @staticmethod
    def make_dedup_key(member_id: str, notification_type: str, scheduled_for: date) -> str:
        raw = f"{member_id}|{notification_type}|{scheduled_for.isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    async def enqueue(
        *,
        member_id: str,
        notification_type: str,
        scheduled_for: Optional[date] = None,
        membership_id: Optional[str] = None,
        channel: str = "WHATSAPP",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Create a notification record. Returns the record if newly inserted, else None."""
        if notification_type not in NOTIFICATION_TYPES:
            raise ValueError(f"Unknown notification type {notification_type}")
        scheduled = scheduled_for or today_ist()
        dedup_key = NotificationService.make_dedup_key(member_id, notification_type, scheduled)
        record = {
            "id": "not_" + secrets.token_hex(6),
            "dedup_key": dedup_key,
            "member_id": member_id,
            "membership_id": membership_id,
            "type": notification_type,
            "channel": channel,
            "status": "QUEUED_PROVIDER_DISABLED" if not WHATSAPP_ENABLED else "QUEUED",
            "attempts": 0,
            "provider_message_id": None,
            "scheduled_for": scheduled.isoformat(),
            "next_retry_at": None,
            "sent_at": None,
            "failed_at": None,
            "error_message": None,
            "metadata": metadata or {},
            "created_at": now_utc(),
            "updated_at": now_utc(),
        }
        try:
            await db.notifications.insert_one(record)
            return record
        except DuplicateKeyError:
            return None

    @staticmethod
    async def attempt_delivery(notification: Dict[str, Any]) -> Dict[str, Any]:
        """Attempt to send. When the provider is disabled we mark it as QUEUED_PROVIDER_DISABLED.

        This function is the single place any real provider integration should be wired.
        """
        now = now_utc()
        attempts = int(notification.get("attempts", 0)) + 1
        update: Dict[str, Any] = {"attempts": attempts, "updated_at": now}
        if not WHATSAPP_ENABLED:
            update["status"] = "QUEUED_PROVIDER_DISABLED"
            update["error_message"] = "Provider disabled: WhatsApp credentials not configured"
            update["next_retry_at"] = None
        else:  # pragma: no cover - real provider not wired in this environment
            update["status"] = "SENT"
            update["sent_at"] = now
            update["provider_message_id"] = "sim_" + secrets.token_hex(6)
        await db.notifications.update_one({"id": notification["id"]}, {"$set": update})
        return {**notification, **update}

    @staticmethod
    async def retry(notification_id: str) -> Optional[Dict[str, Any]]:
        notification = await db.notifications.find_one({"id": notification_id}, {"_id": 0})
        if not notification:
            return None
        if notification.get("attempts", 0) >= MAX_NOTIFICATION_ATTEMPTS:
            await db.notifications.update_one(
                {"id": notification_id},
                {"$set": {"status": "FAILED_MAX_ATTEMPTS", "failed_at": now_utc(), "updated_at": now_utc()}},
            )
            return await db.notifications.find_one({"id": notification_id}, {"_id": 0})
        return await NotificationService.attempt_delivery(notification)

    @staticmethod
    async def process_retry_queue() -> int:
        """Retry notifications that are due. Returns count actually processed."""
        pending = await db.notifications.find(
            {"status": {"$in": ["FAILED", "PENDING_RETRY"]}, "attempts": {"$lt": MAX_NOTIFICATION_ATTEMPTS}},
            {"_id": 0},
        ).to_list(200)
        now = now_utc()
        processed = 0
        for note in pending:
            next_retry = note.get("next_retry_at")
            if next_retry:
                if aware_utc(next_retry) > now:
                    continue
            await NotificationService.attempt_delivery(note)
            processed += 1
        return processed


# =====================================================================
# Payment service
# =====================================================================

class PaymentService:
    @staticmethod
    async def record(
        *,
        member_id: str,
        amount: float,
        method: str,
        status: str,
        membership_id: Optional[str] = None,
        transaction_reference: Optional[str] = None,
        notes: str = "",
    ) -> Dict[str, Any]:
        payment = {
            "id": "pay_" + secrets.token_hex(6),
            "member_id": member_id,
            "membership_id": membership_id,
            "amount": float(amount),
            "method": method,
            "status": status,
            "transaction_reference": transaction_reference,
            "notes": notes,
            "created_at": now_utc(),
        }
        await db.payments.insert_one(payment)
        return payment

    @staticmethod
    async def list_for_member(member_id: str) -> List[Dict[str, Any]]:
        return await db.payments.find({"member_id": member_id}, {"_id": 0}).sort("created_at", -1).to_list(500)

    @staticmethod
    async def list_all(limit: int = 500) -> List[Dict[str, Any]]:
        return await db.payments.find({}, {"_id": 0}).sort("created_at", -1).to_list(limit)

    @staticmethod
    async def total_revenue() -> float:
        pipeline = [
            {"$match": {"status": "PAID"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ]
        result = await db.payments.aggregate(pipeline).to_list(1)
        return float(result[0]["total"]) if result else 0.0


# =====================================================================
# Membership lifecycle service
# =====================================================================

class LifecycleService:
    """Encapsulates the ACTIVE → EXPIRING → GRACE → CANCELLED → DELETED transitions.

    All transitions are idempotent per member per day.
    """

    @staticmethod
    def compute_expiry(start_date: date, duration_months: int) -> date:
        return add_months(start_date, duration_months)

    @staticmethod
    def compute_grace_end(expiry_date: date, grace_days: int) -> date:
        return expiry_date + timedelta(days=int(grace_days))

    @staticmethod
    def compute_status_for(member: Dict[str, Any], settings: Dict[str, Any], today: Optional[date] = None) -> str:
        """Pure classifier: returns the target status without persisting."""
        today = today or today_ist()
        expiry = parse_date(member.get("expiry_date"))
        grace_end = parse_date(member.get("grace_period_end"), expiry + timedelta(days=int(settings["grace_period_days"])))
        delete_after = parse_date(member.get("delete_after"), None) if member.get("delete_after") else None
        reminder = int(settings["expiry_reminder_days"])
        if member.get("status") == STATUS_DELETED:
            return STATUS_DELETED
        if delete_after and today >= delete_after:
            return STATUS_DELETED
        if today >= grace_end:
            return STATUS_CANCELLED
        if today >= expiry:
            return STATUS_GRACE
        if (expiry - today).days <= reminder:
            return STATUS_EXPIRING
        return STATUS_ACTIVE

    # ------------------------------------------------------------------
    # Persistence-level transitions
    # ------------------------------------------------------------------
    @staticmethod
    async def _get_settings() -> Dict[str, Any]:
        settings = await db.settings.find_one({"id": "settings_default"}, {"_id": 0})
        if not settings:
            settings = {"expiry_reminder_days": 7, "grace_period_days": 7, "retention_days": 60}
        return settings

    @staticmethod
    async def create_member_with_membership(
        *,
        payload: Dict[str, Any],
        plan: Dict[str, Any],
        actor_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        settings = await LifecycleService._get_settings()
        start = parse_date(payload["start_date"])
        expiry = LifecycleService.compute_expiry(start, int(plan["duration_months"]))
        grace_end = LifecycleService.compute_grace_end(expiry, int(settings["grace_period_days"]))
        member_id = "mem_" + secrets.token_hex(5)
        membership_id = "ms_" + secrets.token_hex(5)
        now = now_utc()
        member_doc = {
            "id": member_id,
            "full_name": payload["full_name"],
            "phone": payload["phone"],
            "address": payload.get("address", ""),
            "photo_key": payload.get("photo_key"),
            "photo_url": None,
            "plan_id": plan["id"],
            "start_date": start.isoformat(),
            "expiry_date": expiry.isoformat(),
            "grace_period_end": grace_end.isoformat(),
            "status": STATUS_ACTIVE,
            "payment_status": payload.get("payment_status", "PAID"),
            "payment_amount": float(payload.get("payment_amount", 0)),
            "payment_method": payload.get("payment_method", "UPI"),
            "notes": payload.get("notes", ""),
            "cancelled_at": None,
            "delete_after": None,
            "created_at": now,
            "updated_at": now,
        }
        membership_history = {
            "id": membership_id,
            "member_id": member_id,
            "plan_id": plan["id"],
            "plan_name": plan["name"],
            "start_date": start.isoformat(),
            "expiry_date": expiry.isoformat(),
            "amount": float(payload.get("payment_amount", plan.get("price", 0))),
            "type": "REGISTRATION",
            "created_at": now,
        }
        await db.members.insert_one(member_doc)
        await db.memberships.insert_one(membership_history)
        await PaymentService.record(
            member_id=member_id,
            membership_id=membership_id,
            amount=float(payload.get("payment_amount", 0)),
            method=payload.get("payment_method", "UPI"),
            status=payload.get("payment_status", "PAID"),
            notes="Initial registration",
        )
        await NotificationService.enqueue(
            member_id=member_id,
            membership_id=membership_id,
            notification_type="WELCOME",
        )
        await AuditService.record(
            action="MEMBER_CREATED",
            entity_type="MEMBER",
            entity_id=member_id,
            actor_id=actor_id,
            actor_role="ADMIN",
            metadata={"plan_id": plan["id"], "start_date": start.isoformat()},
        )
        return member_doc

    @staticmethod
    async def renew_membership(
        *,
        member: Dict[str, Any],
        plan: Dict[str, Any],
        payload: Dict[str, Any],
        actor_id: Optional[str] = None,
        actor_role: str = "ADMIN",
    ) -> Dict[str, Any]:
        settings = await LifecycleService._get_settings()
        current_expiry = parse_date(member.get("expiry_date"))
        today = today_ist()
        # Renewal before expiry: extend from current expiry to protect remaining days.
        # Renewal after expiry or during grace: start from the chosen start_date (default today).
        default_start = current_expiry if today < current_expiry else today
        raw_start = payload.get("start_date")
        start = parse_date(raw_start) if raw_start else default_start
        expiry = LifecycleService.compute_expiry(start, int(plan["duration_months"]))
        grace_end = LifecycleService.compute_grace_end(expiry, int(settings["grace_period_days"]))
        amount = float(payload.get("payment_amount", plan.get("price", 0)))
        now = now_utc()
        membership_id = "ms_" + secrets.token_hex(5)
        await db.members.update_one(
            {"id": member["id"]},
            {"$set": {
                "plan_id": plan["id"],
                "start_date": start.isoformat(),
                "expiry_date": expiry.isoformat(),
                "grace_period_end": grace_end.isoformat(),
                "status": STATUS_ACTIVE,
                "payment_status": payload.get("payment_status", "PAID"),
                "payment_amount": amount,
                "payment_method": payload.get("payment_method", "UPI"),
                "cancelled_at": None,
                "delete_after": None,
                "updated_at": now,
            }},
        )
        await db.memberships.insert_one({
            "id": membership_id,
            "member_id": member["id"],
            "plan_id": plan["id"],
            "plan_name": plan["name"],
            "start_date": start.isoformat(),
            "expiry_date": expiry.isoformat(),
            "amount": amount,
            "type": "RENEWAL" if actor_role == "ADMIN" else "MEMBER_RENEWAL_REQUEST",
            "created_at": now,
        })
        if payload.get("payment_amount") is not None:
            await PaymentService.record(
                member_id=member["id"],
                membership_id=membership_id,
                amount=amount,
                method=payload.get("payment_method", "UPI"),
                status=payload.get("payment_status", "PAID"),
                notes="Renewal payment",
            )
        await NotificationService.enqueue(
            member_id=member["id"],
            membership_id=membership_id,
            notification_type="WELCOME",
            scheduled_for=today,
            metadata={"reason": "renewal"},
        )
        await AuditService.record(
            action="MEMBERSHIP_RENEWED",
            entity_type="MEMBERSHIP",
            entity_id=membership_id,
            actor_id=actor_id,
            actor_role=actor_role,
            metadata={"member_id": member["id"], "plan_id": plan["id"]},
        )
        return {"expiry_date": expiry.isoformat(), "grace_period_end": grace_end.isoformat(), "membership_id": membership_id}

    # ------------------------------------------------------------------
    # Scheduled processors
    # ------------------------------------------------------------------
    @staticmethod
    async def process_expiring_and_expired() -> Dict[str, int]:
        settings = await LifecycleService._get_settings()
        today = today_ist()
        counters = {"reminded": 0, "grace_started": 0, "cancelled": 0, "deleted": 0}
        cursor = db.members.find({"status": {"$nin": [STATUS_CANCELLED, STATUS_DELETED]}}, {"_id": 0})
        async for member in cursor:
            expiry = parse_date(member.get("expiry_date"))
            grace_end = parse_date(member.get("grace_period_end"), expiry + timedelta(days=int(settings["grace_period_days"])))
            reminder = int(settings["expiry_reminder_days"])
            current_status = member.get("status")

            if today >= grace_end and current_status != STATUS_CANCELLED:
                cancelled = now_utc()
                delete_after_date = today + timedelta(days=int(settings["retention_days"]))
                await db.members.update_one(
                    {"id": member["id"]},
                    {"$set": {
                        "status": STATUS_CANCELLED,
                        "cancelled_at": cancelled,
                        "delete_after": delete_after_date.isoformat(),
                        "updated_at": cancelled,
                    }},
                )
                inserted = await NotificationService.enqueue(
                    member_id=member["id"],
                    notification_type="CANCELLED",
                    scheduled_for=today,
                )
                if inserted:
                    counters["cancelled"] += 1
                await AuditService.record(
                    action="MEMBERSHIP_CANCELLED",
                    entity_type="MEMBER",
                    entity_id=member["id"],
                    actor_role="SYSTEM",
                    metadata={"reason": "grace_period_ended"},
                )
            elif today >= expiry and current_status != STATUS_GRACE:
                await db.members.update_one(
                    {"id": member["id"]},
                    {"$set": {
                        "status": STATUS_GRACE,
                        "grace_period_end": grace_end.isoformat(),
                        "updated_at": now_utc(),
                    }},
                )
                inserted = await NotificationService.enqueue(
                    member_id=member["id"],
                    notification_type="EXPIRY",
                    scheduled_for=today,
                )
                if inserted:
                    counters["grace_started"] += 1
            elif current_status == STATUS_ACTIVE and 0 < (expiry - today).days <= reminder:
                await db.members.update_one(
                    {"id": member["id"]},
                    {"$set": {"status": STATUS_EXPIRING, "updated_at": now_utc()}},
                )
                inserted = await NotificationService.enqueue(
                    member_id=member["id"],
                    notification_type="EXPIRY_REMINDER",
                    scheduled_for=today,
                )
                if inserted:
                    counters["reminded"] += 1
            elif current_status == STATUS_EXPIRING and 0 < (expiry - today).days <= reminder:
                # already expiring, still record reminder once per day (idempotent)
                inserted = await NotificationService.enqueue(
                    member_id=member["id"],
                    notification_type="EXPIRY_REMINDER",
                    scheduled_for=today,
                )
                if inserted:
                    counters["reminded"] += 1
        deleted = await LifecycleService.process_deletions()
        counters["deleted"] = deleted
        return counters

    @staticmethod
    async def process_deletions() -> int:
        from storage import delete_object  # local import to avoid circular boot
        today = today_ist()
        count = 0
        cursor = db.members.find(
            {"status": STATUS_CANCELLED, "delete_after": {"$lte": today.isoformat()}},
            {"_id": 0},
        )
        async for member in cursor:
            member_id = member["id"]
            if member.get("photo_key"):
                delete_object(member["photo_key"])
            await db.members.update_one(
                {"id": member_id},
                {"$set": {
                    "status": STATUS_DELETED,
                    "full_name": "[erased]",
                    "phone": f"[erased-{member_id[-5:]}]",
                    "address": None,
                    "photo_url": None,
                    "photo_key": None,
                    "notes": None,
                    "payment_method": None,
                    "updated_at": now_utc(),
                }},
            )
            await NotificationService.enqueue(
                member_id=member_id,
                notification_type="DELETION",
                scheduled_for=today,
            )
            await AuditService.record(
                action="MEMBER_DELETED",
                entity_type="MEMBER",
                entity_id=member_id,
                actor_role="SYSTEM",
                metadata={"reason": "retention_period_expired"},
            )
            count += 1
        return count


__all__ = [
    "AuditService",
    "NotificationService",
    "PaymentService",
    "LifecycleService",
    "MAX_NOTIFICATION_ATTEMPTS",
    "NOTIFICATION_TYPES",
]
