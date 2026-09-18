# TitanGym OS – Product Requirements

## Original problem statement
Build a production-ready full-stack Gym & Membership Management SaaS with admin/staff panel, member portal, lifecycle automation, plans, renewals, payments, notifications, photo storage interface, audit/reporting surfaces, secure authentication, tenant-ready records, and configurable WhatsApp/storage integrations.

## Architecture decisions
- Runtime stack (user-approved option A): **React (CRA) + FastAPI + MongoDB**. Environment-locked; a future migration to Next.js + PostgreSQL + Prisma remains an open architectural direction.
- Backend has been refactored into production-shaped modules so the business logic can be lifted onto any relational stack later:
  - `core.py` — config, Motor client, security primitives, IST time helpers, shared FastAPI deps, index setup.
  - `schemas.py` — validated Pydantic input models.
  - `services.py` — `AuditService`, `NotificationService`, `PaymentService`, `LifecycleService`.
  - `scheduler.py` — APScheduler (`AsyncIOScheduler`) with two cron jobs on **Asia/Kolkata**.
  - `routers.py` — HTTP endpoints under `/api/*`.
  - `seed.py` — idempotent demo data.
  - `server.py` — FastAPI bootstrap wiring the modules together.
- Notifications are idempotent via a SHA-256 `dedup_key = f"{member_id}|{type}|{scheduled_date}"` with a MongoDB unique index. Second-per-day scheduler runs produce zero duplicate messages.
- Membership month math uses `dateutil.relativedelta` (calendar-correct) instead of the previous 30-day approximation.
- Lifecycle boundaries evaluate `today_ist()` (`datetime.now(ZoneInfo("Asia/Kolkata")).date()`) — never server-local UTC.
- Provider abstractions for WhatsApp and object storage are always constructed; sending/upload are disabled while credentials are absent, and status is recorded truthfully (`QUEUED_PROVIDER_DISABLED`).

## User personas
- Gym admin/staff — daily operations, dashboards, member/plan/payment control, retention, audit trace.
- Gym member — mobile-first portal via phone + OTP; sees only their own membership, plan, days remaining, history, payments.

## Core requirements (static)
- Admin dashboard: total/active/expiring/grace/cancelled counts, revenue, expiring & grace lists.
- Member CRUD with duplicate-phone rejection, search & filters, CSV export, per-member detail (membership history, payments, notifications, audit).
- Membership plans (CRUD).
- Renewal workflow that never shrinks remaining days and always writes a `memberships` history row.
- Membership lifecycle: ACTIVE → EXPIRING_SOON → GRACE_PERIOD → CANCELLED → PERMANENTLY_DELETED with per-day idempotent notifications.
- Payments: list, create, per-member ledger, `/receipt` view.
- Notifications centre with retry (bounded attempts, `next_retry_at`), provider abstraction.
- Audit log for every important admin action + system-driven lifecycle events.
- Configurable settings (gym name/phone/address, timezone, reminder/grace/retention days) and integrations panel.
- Reports summary API (revenue this/last month, plan distribution, outstanding, new members).
- Secure admin auth: bcrypt + JWT httpOnly cookie + brute-force lockout (5 fails → 15 min).
- Secure member auth: phone + OTP (dev mode returns `123456`), JWT httpOnly `member_token` cookie, protected `/api/member/me`.
- APScheduler: daily lifecycle at 00:15 IST + notification retry every 15 minutes.

## Implemented (2026-02-18)
- Refactored monolithic `server.py` into 7 focused modules; total logic split cleanly into config/services/scheduler/routers.
- Added `AuditService`, `PaymentService`, `NotificationService`, `LifecycleService` with pure state classification + safe transactional persistence.
- Added APScheduler running two async jobs on Asia/Kolkata: `daily_lifecycle` (00:15) and `notification_retry` (every 15 min).
- Added notification `dedup_key` (unique index) — verified by second same-day job run returning zero counters.
- Added month-accurate expiry (`relativedelta`) and IST-anchored `today_ist()` for every lifecycle boundary check.
- Added new admin surfaces: **Payments** (list + receipt link), **Audit log** (trace of every action), notification **Retry** button, one-click **Run lifecycle** trigger.
- Added protected `/api/member/me`, member logout, CSV export (`/api/members/export/csv`), member detail modal with membership/payments/notifications/audit tabs, admin renewal + cancellation actions.
- Frontend now drives the member portal from real API data (no more hardcoded "Priya Roy" block) with proper OTP login flow.
- Added `/api/reports/summary` for month-over-month revenue, outstanding, plan distribution, new member count.
- Backend regression suite grew from 4 → 11 tests. All pass. Frontend end-to-end verified by testing agent (100% of exercised flows).

## Prioritized backlog
- **P1** — Enable real WhatsApp Cloud API delivery once Meta credentials arrive (`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_BUSINESS_ACCOUNT_ID`, `WHATSAPP_VERIFY_TOKEN`); wiring point is `NotificationService.attempt_delivery`.
- **P1** — Enable object storage for `photo_url` when S3/R2/Cloudinary credentials arrive; `STORAGE_ENABLED` is already wired.
- **P1** — Multi-gym tenant model: introduce `gymId` scoping across members/plans/payments/notifications/audit and enforce it on every server-side query.
- **P1** — Downloadable PDF receipts (currently returns JSON payload for the receipt).
- **P2** — Optional migration path to Next.js + PostgreSQL + Prisma when a Postgres endpoint is available.
- **P2** — Real SMS OTP provider (Twilio, MSG91, etc.) once credentials arrive; `OTP_DEV_MODE` toggle already respected.
- **P2** — Additional staff/role management UI (`SUPER_ADMIN`, `STAFF`).
- **P2** — Richer analytics (weekly cohorts, churn curve, revenue projection).

## Next tasks
1. Wire the WhatsApp Cloud provider inside `NotificationService.attempt_delivery` once credentials are supplied.
2. Wire object storage upload inside the member create/update flow when credentials are supplied.
3. Add `gymId` on records and derive it from the authenticated user's session on every query.
