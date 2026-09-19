"""Idempotent seed for demo data. Only inserts documents that do not yet exist."""
from __future__ import annotations

from datetime import timedelta

from core import GYM_TZ_NAME, db, now_utc, password_hash, today_ist


async def seed() -> None:
    admin = await db.users.find_one({"email": "admin@titangym.in"})
    if not admin:
        await db.users.insert_one({
            "id": "usr_admin",
            "email": "admin@titangym.in",
            "name": "Arjun Mehta",
            "role": "ADMIN",
            "password_hash": password_hash("Titan@123"),
            "created_at": now_utc(),
        })
    if not await db.settings.find_one({"id": "settings_default"}):
        await db.settings.insert_one({
            "id": "settings_default",
            "gym_name": "TitanGym Performance Club",
            "gym_phone": "+91 98765 43210",
            "gym_address": "Koramangala, Bengaluru",
            "timezone": GYM_TZ_NAME,
            "expiry_reminder_days": 7,
            "grace_period_days": 7,
            "retention_days": 60,
        })
    if await db.plans.count_documents({}) == 0:
        await db.plans.insert_many([
            {"id": "plan_1", "name": "Forge Monthly", "duration_months": 1, "price": 1200, "description": "Flexible monthly access", "active": True},
            {"id": "plan_3", "name": "Momentum Quarter", "duration_months": 3, "price": 3000, "description": "Best for consistent progress", "active": True},
            {"id": "plan_6", "name": "Strength Half-Year", "duration_months": 6, "price": 5400, "description": "Serious training commitment", "active": True},
            {"id": "plan_12", "name": "Titan Annual", "duration_months": 12, "price": 9600, "description": "The complete performance year", "active": True},
        ])
    if await db.members.count_documents({}) == 0:
        seed_members = [
            ("mem_rahul", "Rahul Sharma", "+91 98201 44320", "plan_3", 18, "ACTIVE", "PAID", 3000, "UPI"),
            ("mem_priya", "Priya Roy", "+91 98111 22031", "plan_1", -2, "GRACE_PERIOD", "PAID", 1200, "UPI"),
            ("mem_amit", "Amit Das", "+91 99001 87222", "plan_6", 5, "EXPIRING_SOON", "PENDING", 5400, "Cash"),
            ("mem_neha", "Neha Kapoor", "+91 98888 11223", "plan_12", -44, "CANCELLED", "PAID", 9600, "Card"),
        ]
        today = today_ist()
        for member_id, name, phone, plan_id, offset, status, payment, amount, method in seed_members:
            start = today - timedelta(days=max(1, 30 - offset))
            expiry = today + timedelta(days=offset)
            grace_end = expiry + timedelta(days=7)
            cancelled_at = now_utc() - timedelta(days=44) if status == "CANCELLED" else None
            delete_after = (today + timedelta(days=16)).isoformat() if status == "CANCELLED" else None
            await db.members.insert_one({
                "id": member_id,
                "full_name": name,
                "phone": phone,
                "address": "Bengaluru",
                "photo_url": None,
                "photo_key": None,
                "plan_id": plan_id,
                "start_date": start.isoformat(),
                "expiry_date": expiry.isoformat(),
                "grace_period_end": grace_end.isoformat(),
                "status": status,
                "payment_status": payment,
                "payment_amount": amount,
                "payment_method": method,
                "cancelled_at": cancelled_at,
                "delete_after": delete_after,
                "notes": "Seed member",
                "created_at": now_utc(),
                "updated_at": now_utc(),
            })
            await db.payments.insert_one({
                "id": f"pay_seed_{member_id[-4:]}",
                "member_id": member_id,
                "membership_id": None,
                "amount": amount,
                "method": method,
                "status": payment,
                "transaction_reference": None,
                "notes": "Seed registration",
                "created_at": now_utc(),
            })
