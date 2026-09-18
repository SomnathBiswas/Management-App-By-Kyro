import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")


def login_session():
    session = requests.Session()
    response = session.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@titangym.in", "password": "Titan@123"})
    assert response.status_code == 200, response.text
    assert response.cookies.get("access_token")
    assert response.json()["user"]["email"] == "admin@titangym.in"
    return session


def test_admin_auth_and_dashboard():
    session = login_session()
    me = session.get(f"{BASE_URL}/api/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == "ADMIN"
    dashboard = session.get(f"{BASE_URL}/api/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["total_members"] >= 4


def test_member_otp_flow():
    session = requests.Session()
    requested = session.post(f"{BASE_URL}/api/auth/member/request-otp", json={"phone": "+91 98111 22031"})
    assert requested.status_code == 200
    assert requested.json()["development_otp"] == "123456"
    verified = session.post(f"{BASE_URL}/api/auth/member/verify-otp", json={"phone": "+91 98111 22031", "otp": "123456"})
    assert verified.status_code == 200
    assert verified.json()["member"]["full_name"] == "Priya Roy"
    assert session.cookies.get("member_token")


def test_member_and_plan_creation_persistence():
    session = login_session()
    plan_name = "TEST Plan API"
    plan = session.post(f"{BASE_URL}/api/plans", json={"name": plan_name, "duration_months": 1, "price": 99, "description": "test"})
    assert plan.status_code == 200
    plan_id = plan.json()["id"]
    member = session.post(f"{BASE_URL}/api/members", json={"full_name": "TEST API Member", "phone": "+91 90000 11111", "address": "Test", "plan_id": plan_id, "start_date": "2026-09-26", "payment_amount": 99, "payment_status": "PAID", "payment_method": "UPI"})
    assert member.status_code == 200
    member_id = member.json()["id"]
    fetched = session.get(f"{BASE_URL}/api/members/{member_id}")
    assert fetched.status_code == 200
    assert fetched.json()["member"]["full_name"] == "TEST API Member"
    notifications = session.get(f"{BASE_URL}/api/notifications")
    assert any(n["member_id"] == member_id and n["status"] == "QUEUED_PROVIDER_DISABLED" for n in notifications.json())


def test_lifecycle_endpoint_is_idempotent_safe():
    session = login_session()
    first = session.post(f"{BASE_URL}/api/jobs/run")
    second = session.post(f"{BASE_URL}/api/jobs/run")
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["provider"].startswith("WhatsApp disabled")
    assert second.json()["changed"] == {"expiring": 0, "grace_started": 0, "cancelled": 0, "deleted": 0}