import os
from datetime import date, timedelta

import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")


def _login():
    session = requests.Session()
    response = session.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@titangym.in", "password": "Titan@123"})
    assert response.status_code == 200, response.text
    assert response.cookies.get("access_token")
    assert response.json()["user"]["email"] == "admin@titangym.in"
    return session


# ---------- Admin auth & dashboard ----------

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
    assert providers["whatsapp"] in {"enabled", "disabled"}
    assert providers["otp"] == "dev-mode"


# ---------- Member OTP ----------

def test_member_otp_flow_and_portal_endpoint():
    session = requests.Session()
    requested = session.post(f"{BASE_URL}/api/auth/member/request-otp", json={"phone": "+91 98111 22031"})
    assert requested.status_code == 200
    assert requested.json()["development_otp"] == "123456"
    verified = session.post(f"{BASE_URL}/api/auth/member/verify-otp", json={"phone": "+91 98111 22031", "otp": "123456"})
    assert verified.status_code == 200
    assert verified.json()["member"]["full_name"] == "Priya Roy"
    assert session.cookies.get("member_token")
    portal = session.get(f"{BASE_URL}/api/member/me")
    assert portal.status_code == 200
    body = portal.json()
    assert body["member"]["phone"] == "+91 98111 22031"
    assert "days_remaining" in body
    assert "plan" in body


def test_member_portal_requires_auth():
    response = requests.get(f"{BASE_URL}/api/member/me")
    assert response.status_code == 401


# ---------- Member & plan CRUD, notification, payments ----------

def test_member_and_plan_creation_persistence_with_payments_and_audit():
    session = _login()
    plan_name = "TEST Plan API"
    plan = session.post(f"{BASE_URL}/api/plans", json={"name": plan_name, "duration_months": 1, "price": 99, "description": "test"})
    assert plan.status_code == 200
    plan_id = plan.json()["id"]

    phone = f"+91 900{date.today().strftime('%m%d')}{plan_id[-4:]}"[:20]
    member = session.post(f"{BASE_URL}/api/members", json={
        "full_name": "TEST API Member",
        "phone": phone,
        "address": "Test",
        "plan_id": plan_id,
        "start_date": "2026-09-26",
        "payment_amount": 99,
        "payment_status": "PAID",
        "payment_method": "UPI",
    })
    assert member.status_code == 200, member.text
    member_id = member.json()["id"]

    detail = session.get(f"{BASE_URL}/api/members/{member_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["member"]["full_name"] == "TEST API Member"
    assert body["history"], "membership history must include registration"
    assert body["payments"], "initial payment must be recorded"
    assert any(p["amount"] == 99 for p in body["payments"])

    notifications = session.get(f"{BASE_URL}/api/notifications").json()
    assert any(n["member_id"] == member_id and n["type"] == "WELCOME" for n in notifications)

    audit = session.get(f"{BASE_URL}/api/audit").json()
    assert any(a["action"] == "MEMBER_CREATED" and a["entity_id"] == member_id for a in audit)


def test_notification_dedup_key_is_idempotent_per_day():
    session = _login()
    before = session.post(f"{BASE_URL}/api/jobs/run").json()
    after = session.post(f"{BASE_URL}/api/jobs/run").json()
    # Second run same-day must not re-generate notifications
    assert after["changed"]["expiring"] == 0
    assert after["changed"]["grace_started"] == 0
    assert after["changed"]["cancelled"] == 0
    assert before["success"] and after["success"]


def test_renewal_extends_before_expiry_does_not_shrink():
    session = _login()
    plan = session.post(f"{BASE_URL}/api/plans", json={"name": "Renewal-Test Plan", "duration_months": 3, "price": 100, "description": "renewal test"}).json()
    phone = f"+91 900{plan['id'][-6:]}00"[:20]
    member = session.post(f"{BASE_URL}/api/members", json={
        "full_name": "Renewal Member", "phone": phone, "address": "T", "plan_id": plan["id"],
        "start_date": date.today().isoformat(),
        "payment_amount": 100, "payment_status": "PAID", "payment_method": "UPI",
    }).json()
    detail_before = session.get(f"{BASE_URL}/api/members/{member['id']}").json()
    expiry_before = date.fromisoformat(detail_before["member"]["expiry_date"])
    # Renew a 3-month plan early (default start_date = current expiry when today < expiry)
    renewal = session.post(f"{BASE_URL}/api/members/{member['id']}/renew", json={"plan_id": plan["id"], "payment_amount": 100})
    assert renewal.status_code == 200, renewal.text
    new_expiry = date.fromisoformat(renewal.json()["expiry_date"])
    assert new_expiry >= expiry_before + timedelta(days=80), f"early renewal must extend, got {new_expiry} vs base {expiry_before}"


def test_payments_receipt_and_totals():
    session = _login()
    payments = session.get(f"{BASE_URL}/api/payments").json()
    assert isinstance(payments, list)
    if payments:
        receipt = session.get(f"{BASE_URL}/api/payments/{payments[0]['id']}/receipt")
        assert receipt.status_code == 200
        assert receipt.json()["receipt"]["id"] == payments[0]["id"]


def test_settings_update_persists():
    session = _login()
    current = session.get(f"{BASE_URL}/api/settings").json()
    new_reminder = 5 if current["expiry_reminder_days"] != 5 else 6
    payload = {**current, "expiry_reminder_days": new_reminder}
    response = session.put(f"{BASE_URL}/api/settings", json=payload)
    assert response.status_code == 200
    reread = session.get(f"{BASE_URL}/api/settings").json()
    assert reread["expiry_reminder_days"] == new_reminder


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
    assert first.json()["success"] is True
    assert second.json()["changed"] == {"expiring": 0, "grace_started": 0, "cancelled": 0, "deleted": 0}
