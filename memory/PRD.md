# TitanGym OS Product Requirements

## Original problem statement
Build a production-ready full-stack Gym & Membership Management SaaS with an admin/staff panel, member portal, lifecycle automation, plans, renewals, payments, notifications, photo storage interface, audit/reporting surfaces, secure authentication, tenant-ready records, and configurable WhatsApp/storage integrations.

## Architecture decisions
- The workspace runtime remains React + FastAPI + MongoDB so the application is immediately runnable in the provided environment.
- Business-owned records use stable string IDs and configurable lifecycle settings; MongoDB responses explicitly remove `_id`.
- Admin sessions use httpOnly JWT cookies. Member access uses phone + OTP abstraction.
- WhatsApp and object storage are provider abstractions with records/UI states ready for credentials; sending and storage are disabled until configured.
- Asia/Kolkata is the default operating timezone and lifecycle transitions are idempotent at the service boundary.

## User personas
- Gym admin/staff: needs fast daily visibility, member operations, plans, revenue, settings, and lifecycle actions.
- Gym member: needs a simple mobile portal showing status, expiry, payments, and history.

## Core requirements (static)
- Admin dashboard metrics and charts
- Member search/filter/list and registration
- Plans, payments, renewal history, notifications
- Active/expiring/grace/cancelled lifecycle controls
- Member OTP portal
- Reports, settings, provider readiness, and privacy-oriented cleanup job endpoint
- Responsive accessible interface with user-facing test IDs

## Implemented (2026-09-18)
- Replaced starter splash with TitanGym OS admin workspace and mobile member portal.
- Added real FastAPI/Mongo APIs for auth, seeded plans/members, dashboard, member CRUD, renewals, plans, settings, notifications, and lifecycle processing.
- Added admin email/password auth, member phone/OTP flow, secure cookies, seeded demo data, notification records, provider-disabled states, and test credentials.
- Added responsive dark performance-oriented UI with dashboard charts, member table, filters, add-member workflow, plan builder, reports, settings, and member history view.
- Verified Python compilation, frontend production build, API login/dashboard, and live preview navigation.

## Prioritized backlog
- P0: Add real PostgreSQL/Prisma deployment adapter if the runtime provides a PostgreSQL service.
- P0: Configure Meta WhatsApp Cloud API and object storage credentials to enable external delivery/uploads.
- P1: Add true OTP delivery provider and rate limiting with resend cooldown.
- P1: Add downloadable receipts, CSV export endpoint, and audit log persistence.
- P2: Add staff role management, multi-gym tenant administration, and richer historical analytics.

## Next tasks
1. Run the full browser/API test suite and fix any blocking regressions.
2. Add credentials for WhatsApp and storage when available, without changing membership logic.
3. Complete receipts, CSV export, and audit log screens.