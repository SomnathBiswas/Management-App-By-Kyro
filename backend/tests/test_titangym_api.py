import io
import os
from datetime import date, timedelta

import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")


def _login():
    session = requests.Session()
    response = session.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@titangym.in", "password": "Titan@123"})
    assert response.status_code == 200, response.text
    assert response.cookies.get("access_token")
    return session


def _tiny_png() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001080200000090"
        "77538de0000000c4944415478da62f8ffff3f000005fe02fedccc59e70000"
        "0000049454e44ae426082"
    )


def test_admin_auth_and_dashboard():
    session = _login()
    me = session.get(f"{BASE_URL}/api/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == "ADMIN"
    dashboard = session.get(f"{BASE_URL}/api/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["total_members"] >= 4


def test_health_reports_provider_states():
    response = requests.get(f"{BASE_URL}/api/health")
    assert response.status_code == 200
    providers = response.json()["providers"]
    assert providers["storage"] == "enabled"
    assert providers["whatsapp"] in {"enabled", "disabled"}


def test_photo_upload_and_member_photo_url():
    session = _login()
    files = {"file": ("tiny.png", io.BytesIO(_tiny_png()), "image/png")}
    upload = session.post(f"{BASE_URL}/api/uploads/member-photo", files=files)
    assert upload.status_code == 200, upload.text
    body = upload.json()
    assert body["photo_key"].startswith("members/")
    assert body["photo_url"].startswith("https://")
    plan = session.post(f"{BASE_URL}/api/plans", json={"name": "Photo-Test Plan", "duration_months": 1, "price": 111, "description": "photo"}).json()
    phone = f"+91 900{plan['id'][-6:]}22"[:20]
    member = session.post(f"{BASE_URL}/api/members", json={
        "full_name": "Photo Member", "phone": phone, "address": "T", "plan_id": plan["id"],
        "start_date": date.today().isoformat(), "payment_amount": 111, "payment_status": "PAID",
        "payment_method": "UPI", "photo_key": body["photo_key"],
    })
    assert member.status_code == 200, member.text
    saved = session.get(f"{BASE_URL}/api/members/{member.json()['id']}").json()
    assert saved["member"]["photo_key"] == body["photo_key"]
    assert saved["member"]["photo_url"] and "X-Amz-Signature" in saved["member"]["photo_url"]


def test_member_and_plan_creation_persistence_with_payments_and_audit():
    session = _login()
    plan = session.post(f"{BASE_URL}/api/plans", json={"name": "TEST Plan API", "duration_months": 1, "price": 99, "description": "test"})
    assert plan.status_code == 200
    plan_id = plan.json()["id"]
    phone = f"+91 900{date.today().strftime('%m%d')}{plan_id[-4:]}"[:20]
    member = session.post(f"{BASE_URL}/api/members", json={
        "full_name": "TEST API Member", "phone": phone, "address": "Test", "plan_id": plan_id,
        "start_date": "2026-09-26", "payment_amount": 99, "payment_status": "PAID", "payment_method": "UPI",
    })
    assert member.status_code == 200, member.text
    member_id = member.json()["id"]
    detail = session.get(f"{BASE_URL}/api/members/{member_id}").json()
    assert detail["member"]["full_name"] == "TEST API Member"
    assert detail["history"] and detail["payments"]
    notifications = session.get(f"{BASE_URL}/api/notifications").json()
    assert any(n["member_id"] == member_id and n["type"] == "WELCOME" for n in notifications)
    audit = session.get(f"{BASE_URL}/api/audit").json()
    assert any(a["action"] == "MEMBER_CREATED" and a["entity_id"] == member_id for a in audit)


def test_plan_edit_and_delete_when_unused():
    session = _login()
    created = session.post(f"{BASE_URL}/api/plans", json={"name": "Ephemeral Plan", "duration_months": 2, "price": 250, "description": "temp"}).json()
    patched = session.patch(f"{BASE_URL}/api/plans/{created['id']}", json={"price": 275, "active": False})
    assert patched.status_code == 200
    assert patched.json()["price"] == 275
    assert patched.json()["active"] is False
    removed = session.delete(f"{BASE_URL}/api/plans/{created['id']}")
    assert removed.status_code == 200
    assert removed.json()["deleted"] is True


def test_plan_delete_soft_disables_when_in_use():
    session = _login()
    plan = session.post(f"{BASE_URL}/api/plans", json={"name": "In-Use Plan", "duration_months": 1, "price": 50, "description": "used"}).json()
    phone = f"+91 900{plan['id'][-6:]}33"[:20]
    session.post(f"{BASE_URL}/api/members", json={
        "full_name": "Occupier", "phone": phone, "address": "x", "plan_id": plan["id"],
        "start_date": date.today().isoformat(), "payment_amount": 50, "payment_status": "PAID", "payment_method": "UPI",
    })
    res = session.delete(f"{BASE_URL}/api/plans/{plan['id']}")
    assert res.status_code == 200
    body = res.json()
    assert body["deleted"] is False and body["disabled"] is True


def test_notification_dedup_key_is_idempotent_per_day():
    session = _login()
    _ = session.post(f"{BASE_URL}/api/jobs/run").json()
    after = session.post(f"{BASE_URL}/api/jobs/run").json()
    assert after["changed"]["expiring"] == 0
    assert after["changed"]["grace_started"] == 0
    assert after["changed"]["cancelled"] == 0


def test_renewal_extends_before_expiry_does_not_shrink():
    session = _login()
    plan = session.post(f"{BASE_URL}/api/plans", json={"name": "Renewal-Test Plan", "duration_months": 3, "price": 100, "description": "renewal"}).json()
    phone = f"+91 900{plan['id'][-6:]}44"[:20]
    member = session.post(f"{BASE_URL}/api/members", json={
        "full_name": "Renewal Member", "phone": phone, "address": "T", "plan_id": plan["id"],
        "start_date": date.today().isoformat(), "payment_amount": 100, "payment_status": "PAID", "payment_method": "UPI",
    }).json()
    detail = session.get(f"{BASE_URL}/api/members/{member['id']}").json()
    expiry_before = date.fromisoformat(detail["member"]["expiry_date"])
    renewal = session.post(f"{BASE_URL}/api/members/{member['id']}/renew", json={"plan_id": plan["id"], "payment_amount": 100})
    assert renewal.status_code == 200
    new_expiry = date.fromisoformat(renewal.json()["expiry_date"])
    assert new_expiry >= expiry_before + timedelta(days=80)


def test_settings_update_persists():
    session = _login()
    current = session.get(f"{BASE_URL}/api/settings").json()
    new_reminder = 5 if current["expiry_reminder_days"] != 5 else 6
    assert session.put(f"{BASE_URL}/api/settings", json={**current, "expiry_reminder_days": new_reminder}).status_code == 200
    assert session.get(f"{BASE_URL}/api/settings").json()["expiry_reminder_days"] == new_reminder


def test_reports_summary_returns_plan_distribution():
    session = _login()
    summary = session.get(f"{BASE_URL}/api/reports/summary").json()
    assert "plan_distribution" in summary
    assert "revenue_this_month" in summary
    assert "outstanding" in summary


def test_lifecycle_endpoint_is_idempotent_safe():
    session = _login()
    first = session.post(f"{BASE_URL}/api/jobs/run")
    second = session.post(f"{BASE_URL}/api/jobs/run")
    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["changed"] == {"expiring": 0, "grace_started": 0, "cancelled": 0, "deleted": 0}
