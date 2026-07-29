# HeyPorts — Shipped Features & Design Decisions

Covers the features delivered this cycle across the two repos:

- **Backend** — `onemarinex-backend` (FastAPI + SQLAlchemy + Postgres)
- **Frontend** — `heyports-frontend` (Vite + React 19 + TS)

Both live on branch **`feat/scoped-changes`** in each repo (branched from the
team's latest `main`). Last updated: 2026-07-28.

See **§6 Next steps** for what remains before/after production.

---

## 1. Delivered features

| # | Area | Feature | Key files |
|---|------|---------|-----------|
| 1 | Registration & Login | Forgot password in login | BE `routes_auth.py` (`/auth/forgot-password`, `/reset-password`), `services/email.py`; FE `UnifiedLogin.tsx` |
| 2 | Registration & Login | Validate email id | FE `UnifiedLogin.tsx` (regex) + BE Pydantic `EmailStr` |
| 3 | SOS | Alert goes to the ship mail id set by crew | BE `routes_crew.trigger_sos` → `services/email.send_sos_alert()` (crew `sos_email` + support) |
| 4 | SOS | Admin button to see the SOS timeline of events | BE `routes_sos.py` `GET /sos/{id}/timeline`; FE `SuperAdmin/SosRequests.tsx` |
| 5 | Services | Contact-us page mail flow | BE `routes_contact.py` (background email to support + acknowledgement) |
| 6 | Profile | Full Privacy Policy & Terms text | FE `legal/legalContent.ts` + `legal/LegalDocument.tsx`, `Terms.tsx`, `PrivacyPolicy.tsx` |
| 7 | Payments | Bill upload & pay-online flow | BE `routes_expenses.py`, `models/expense_bill.py`, `services/storage.py` (Spaces), `routes_payments.py`, `models/payment.py`, `services/payments.py` (Razorpay); FE `Expenses/`, `services/payments.ts` |
| 8 | Registration | Email OTP verification at signup ("block") | BE `models/email_verification.py`, `registration.py` (`/send-otp`, `/verify-otp`, `otp` on `/crew`), `services/email.send_email_verification_code`; FE `CrewRegistrationStep2.tsx` |
| 9 | Payments | Bill auto-extract (Claude Haiku 4.5 vision) | BE `services/bill_extraction.py`, `routes_expenses.py` (`POST /crew/expense-bills/extract`); FE `Expenses/expenses.ts` (`extractBill`) + "Extract details" in `ExpensesFlow.tsx` |

All verified end-to-end (see §5).

---

## 2. Environment variables (production)

Set on DigitalOcean App Platform. Everything degrades to a safe dev fallback
when unset (see §3.1).

```bash
# Database
DATABASE_URL=postgresql+psycopg2://USER:PASS@HOST:5432/onemarinex
SECRET_KEY=...

# Email — SMTP (SOS alerts, contact-us, password reset)
SMTP_HOST=smtp.gmail.com          # Google Workspace
SMTP_PORT=587                     # STARTTLS only (465/SSL not supported)
SMTP_USER=no-reply@yourdomain.com
SMTP_PASSWORD=<16-char app password>
SMTP_FROM=no-reply@yourdomain.com # MUST equal SMTP_USER or a verified alias
SUPPORT_EMAIL=support@yourdomain.com

# Object storage — DigitalOcean Spaces (bill receipts)
SPACES_KEY=...
SPACES_SECRET=...
SPACES_BUCKET=heyports-uploads
SPACES_REGION=blr1
# SPACES_ENDPOINT / SPACES_CDN_ENDPOINT / SPACES_PUBLIC / SPACES_PRESIGN_TTL optional

# Payments — Razorpay
RAZORPAY_KEY_ID=rzp_live_xxx
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...        # optional

# Bill extraction — Claude vision (planned; see §3.7)
ANTHROPIC_API_KEY=sk-ant-...       # unset → debug/mock extraction (empty fields)

# Frontend (.env.local)
VITE_API_BASE_URL=https://api.yourdomain.com
```

Local dev values live in `onemarinex-backend/.env` (loaded by
`core/config.py` via `python-dotenv`). Secrets there are placeholders —
paste real values in and never commit them. In production these are set on the
DigitalOcean App Platform env, not in `.env`.

Reference: `onemarinex-backend/.env.spaces.example`.

---

## 3. Design decisions

### 3.1 "Works without credentials" fallback pattern
Every external integration detects whether it's configured and, if not, runs a
**debug/mock path** that logs instead of calling the real service. The app stays
runnable/testable locally without cloud accounts, and a missing/broken external
service never 500s a request.
- `services/email.py` → logs the message when SMTP unset.
- `services/storage.py` → local disk when Spaces unset.
- `services/payments.py` → mock order + auto-verify when Razorpay unset.

### 3.2 Email — SMTP (`services/email.py`) — items 1, 3, 5
- Plain `smtplib` + STARTTLS on 587. **465/implicit-SSL not supported.**
- Google Workspace: use an **App Password** (needs 2FA); `SMTP_FROM` must match
  the authenticated user or a verified alias or Gmail rewrites it.
- Sends are best-effort (never raise); contact-us dispatches via `BackgroundTasks`.
- **Deliverability:** configure SPF/DKIM/DMARC or SOS/reset mail risks spam — a
  real safety issue for SOS.
- Password reset uses a hashed 6-digit code, 15-min TTL, single-use; the
  forgot-password endpoint always returns 200 (no email enumeration).

### 3.3 File storage — DigitalOcean Spaces (`services/storage.py`) — item 7
- Spaces (S3-compatible via `boto3`) is the prod store so bill receipts survive
  deploys/restarts and are shared across instances. **App Platform's container
  disk is ephemeral** — local-disk uploads are dev-only.
- `receipt_url` stores a raw reference resolved at read time: public bucket →
  direct/CDN URL; private → `spaces://<key>` presigned per read; dev →
  `/uploads/<key>`.

### 3.4 Bill upload (`routes_expenses.py`, `models/expense_bill.py`) — item 7
- Crew-scoped: list filters by `crew_id`, delete checks ownership.
- Validated: content-type allowlist (image/PDF), 10 MB cap, randomized keys,
  orphan cleanup on failed insert.
- Bill fields (merchant/amount/date) are entered manually; the receipt is stored
  as an attachment (no OCR).

### 3.5 Payments — Razorpay (`services/payments.py`, `routes_payments.py`) — item 7
- Flow: `POST /crew/payments/order` (Razorpay order + local `Payment` row) →
  frontend checkout → `POST /crew/payments/verify` (HMAC-SHA256 signature check →
  mark `paid`).
- **Mock mode** (no creds): order id `order_mock_…`, `key_id` returns `""`;
  frontend `services/payments.ts` sees the empty key and confirms directly,
  skipping the hosted checkout — fully testable offline.
- Entry point: a **"Pay Online"** button on a bill's detail sheet. Amounts are
  rupees in the API, paise for Razorpay.

### 3.6 Legal content (`legal/`) — item 6
- Source PDFs parsed into structured blocks (`h2/h3/p/li`) using line
  y-coordinates for paragraph breaks (the PDFs have no blank-line separators) →
  `legalContent.ts`, rendered by a shared `LegalDocument` (scroll-to-top on open).
  Regenerate the data file if the source PDFs change.

### 3.7 Bill extraction — Claude vision (shipped)
An **"Extract details"** button on the bill-upload screen reads the receipt
image and pre-fills merchant / amount / date, which the crew confirms.

**Provider decision: Claude Haiku 4.5 (`claude-haiku-4-5`).** Comparison (per
receipt ≈ 1.5K image tok in + ~300 JSON tok out):

| Option | Per-receipt cost | Notes |
|--------|------------------|-------|
| **Claude Haiku 4.5** ✅ | ~$0.003 | Cheapest; any JSON schema via structured outputs; same SDK/stack |
| OpenAI GPT-4o | ~$0.006–0.008 | New provider; ~2× cost; no upside here |
| Google Document AI (Expense Parser) | ~$0.10/page | Purpose-built OCR w/ confidence scores, but ~30× cost + full GCP setup |

Chosen for lowest cost, native structured-JSON output mapping straight onto
`ExpenseBill` (merchant/amount/bill_date), and reuse of the §3.1 fallback
pattern. Shape: `POST /crew/expense-bills/extract` (multipart image, crew-gated)
→ `services/bill_extraction.py` (Anthropic SDK `messages.parse` with a Pydantic
schema; `ANTHROPIC_API_KEY` unset → empty result, never raises) → returns
`{merchant, amount, currency, bill_date, confidence, enabled}` → FE "Extract
details" pre-fills the form → crew edits/confirms → normal `uploadBill`.
Model `claude-haiku-4-5` (override via `BILL_EXTRACTION_MODEL`). **Verified**
2026-07-28: real receipt → merchant/amount(total)/currency/date, confidence 0.95.

### 3.8 Email OTP verification at registration ("block") — new
New-account signup now requires a verified emailed code before the user row is
created (crew registration).

- **Pre-registration, keyed by email** (no user exists yet), so the account is
  only created once the code checks out. This needs **only a new table**
  (`email_verifications`) — auto-created by `create_all` — and deliberately
  **avoids a `users`-column migration** (§4 gotcha).
- Endpoints: `POST /registration/send-otp` (409 if email already registered),
  `POST /registration/verify-otp` (non-consuming pre-check for UI feedback),
  and `POST /registration/crew` now **requires** `otp` — authoritative,
  single-use check (`_consume_valid_otp`) before account creation.
- Code: 6-digit, bcrypt-hashed, 10-min TTL, 5-attempt cap. Email built by
  `email.send_email_verification_code` (reuses §3.2 SMTP + fallback).
- FE `CrewRegistrationStep2.tsx`: two-phase submit — "Send Verification Code"
  → 6-digit field + Resend → "Complete Registration" (sends the code).
- **Registration resilience fix:** the account row commits *before*
  `sync_crew_manifest_helper`; that sync now `db.rollback()`s on failure so a
  manifest hiccup can't 500 an already-created account (previously it did).

---

## 4. The schema-management gotcha (read before touching models)

The project mixes `create_all` on startup, ad-hoc `scripts/`, Alembic (with
branch/merge points), and code-level `ALTER TABLE` patches in `main.py`.

- **New table** → free: add the model + import it in `app/db/base.py`
  (`create_all` builds it). `expense_bills` and `payments` rely on this.
- **New column on an existing table** → **requires an Alembic migration**, or prod
  500s with `UndefinedColumn` (create_all never alters existing tables).
- **Reading old rows** → don't trust shapes; legacy rows may predate the current
  model. The codebase's pattern is defensive parsing, not data migration.
- **Verification:** use `tsc -p tsconfig.app.json --noEmit` (clean) — `tsc -b`
  (incremental) can give a **false pass** from stale build info.

---

## 5. Verification & production caveats

**Verified on `feat/scoped-changes`:** BE imports clean (239 routes);
`/auth/forgot-password` 200; contact 200; `trigger_sos` 200 + SOS email dispatched
to the ship address; `/sos/{id}/timeline` present (admin-gated); bill upload 201 /
list 200; payment order + verify (mock) → `paid`; FE `tsc` clean; `/trip-expenses`
renders the Bill Upload flow; Terms/Privacy render full text.

**Caveats:**
1. **Email is config-gated** — items 1/3/5 only actually send once `SMTP_*` is set
   (Google Workspace app password). They log until then.
2. **Uploads need Spaces in prod** — without `SPACES_*`, receipts land on the
   ephemeral container disk and vanish on redeploy.
3. **New tables** (`expense_bills`, `payments`) auto-create via `create_all`;
   consider Alembic migrations for parity/rollback hygiene.
4. **Branches not pushed** — `feat/scoped-changes` is local in both repos; verify
   against a prod-shaped (migrated) DB before release.
5. **Local DB was behind the models** — reconciled 6 missing columns during E2E
   (`vessel_crew.passport_number/shore_pass_eligible/shore_pass_valid_upto`,
   `vessels.flag/agency_name`, `agent_profiles.auth_document_url`). Prod is
   migrated; this was a local-dev gap surfaced by crew registration.

**E2E verified (real SMTP + Spaces + DB, 2026-07-28):** Spaces upload→public
fetch→delete PASS; SMTP auth + send PASS; registration OTP send/verify → clean
`201`; login PASS; forgot-password → reset → login-with-new / old-rejected /
code-single-use all PASS; registration survives an induced manifest-sync failure
(`201`, not `500`).

---

## 6. Next steps

### 6.1 Before production (deploy blockers / must-do)
1. **Set backend env vars on DigitalOcean App Platform** (Settings → backend
   component → Environment Variables; mark secrets **Encrypt**). `.env` is
   git-ignored and does NOT deploy. Needed: `SMTP_HOST/PORT/USER/PASSWORD/FROM/
   USE_TLS`, `SUPPORT_EMAIL`, `SPACES_KEY/SECRET/BUCKET/REGION`
   (`SPACES_ENDPOINT=https://sgp1.digitaloceanspaces.com` — region host only,
   no bucket), and later `RAZORPAY_*` / `ANTHROPIC_API_KEY`. Frontend component
   gets `VITE_API_BASE_URL`.
2. **Deploy triggers table creation.** On startup `create_all` creates the new
   tables (`email_verifications`, `expense_bills`, `payments`) if missing;
   existing tables/data are untouched (no ALTER/DROP). No new columns on
   existing tables in this branch, so the §4 gotcha does not apply here.
3. **Email deliverability** — add SPF / DKIM / DMARC DNS for the sending domain
   (`hello@heyports.com`). Without it, SOS / OTP / reset mail risks spam — a
   safety issue for SOS.
4. **Push the branches** — `feat/scoped-changes` is local in both repos; push +
   open PRs against the team `main`.
5. **Rotate the DO Spaces key** if the value used in local `.env` was shared
   anywhere (it appeared in a chat transcript during setup).

### 6.2 Recommended (parity / hardening)
6. **Alembic migrations for the new tables** (`email_verifications`,
   `expense_bills`, `payments`) so prod has migration parity instead of relying
   on `create_all`. (Optional — `create_all` already builds them.)
7. **Extend OTP to agent & aggregator registration** — currently crew-only
   (`/registration/crew`). Same `_consume_valid_otp` gate + `otp` field.
8. **Restart the local `uvicorn`** (or redeploy) to serve the new `/send-otp`
   routes for a browser/UI click-through of the OTP flow.

### 6.3 Build next (feature work)
9. **Bill extraction — Claude Haiku 4.5 vision** (§3.7, task open). Add
   `services/bill_extraction.py` + `POST /crew/expense-bills/extract` +
   "Extract details" on the upload screen. `ANTHROPIC_API_KEY` unset → mock.
10. **Payments finish-up (Razorpay, parked)** — go-live needs real
    `RAZORPAY_*` creds and a "Payment Successful" confirmation screen; verify
    the admin SOS timeline against a prod-shaped DB.

### 6.4 Test-account state (local dev)
- `swetan369@gmail.com` / `NewPass@2026` (role `crew`) — created + password
  reset during the 2026-07-28 E2E.
