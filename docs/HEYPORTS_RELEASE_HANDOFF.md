# HeyPorts — Release Handoff

This document consolidates the delivered feature summary, user flows,
implementation decisions, production configuration, and release notes for the
HeyPorts backend and frontend changes completed on `feat/scoped-changes`.

Last updated: 2026-07-28

## 1. Pull requests and delivered scope

| Application | Pull request | Delivered scope |
|---|---|---|
| Backend | [onemarinex/onemarinex-backend#10](https://github.com/onemarinex/onemarinex-backend/pull/10) | Registration OTP, authentication/email flows, SOS and contact email, bill upload and auto-extraction, Razorpay payments |
| Frontend | [onemarinex/heyports-frontend#11](https://github.com/onemarinex/heyports-frontend/pull/11) | OTP and forgot-password UI, SOS timeline, Terms and Privacy pages, bill upload, extracted-detail review, and payment UI |

### Delivered features

| Area | What was delivered |
|---|---|
| Registration | Crew registration is blocked until a six-digit email OTP is verified. |
| Authentication | Forgot-password and reset-password flows use a single-use email code. |
| SOS | Alerts are emailed to the ship address configured by the crew and to HeyPorts support. Admins can view the SOS event timeline. |
| Contact | Contact-us submissions email support and send an acknowledgement to the sender. |
| Legal | Full Terms of Service and Privacy Policy content is available in the frontend. |
| Bills | Crew can upload, list, and delete receipt images or PDFs. Production files are stored in DigitalOcean Spaces. |
| Bill extraction | Claude Haiku 4.5 extracts merchant, total, currency, and date for crew review before upload. |
| Payments | Bills can be paid through Razorpay, with server-side signature verification. |

## 2. Add environment variables in DigitalOcean

The production `.env` file is not deployed. Add configuration directly to the
appropriate DigitalOcean App Platform component.

### 2.1 Open the component settings

1. Sign in to the [DigitalOcean Control Panel](https://cloud.digitalocean.com/apps).
2. Open the HeyPorts App Platform app.
3. Select **Settings**.
4. Find the backend service/component and open its **Environment Variables**
   settings for editing.
5. Add each backend variable below as a runtime variable. Select **Encrypt** for
   passwords, keys, tokens, and other secrets.
6. Save the changes and allow App Platform to redeploy the backend.

Use component-level variables so backend secrets are not exposed to the
frontend component. DigitalOcean also supports app-level variables when a value
must be shared deliberately across components. See DigitalOcean's
[environment-variable guide](https://docs.digitalocean.com/products/app-platform/how-to/use-environment-variables/).

### 2.2 Backend variables

Replace every placeholder with the production value. Do not include the inline
comments when entering values in DigitalOcean.

```dotenv
# Core application
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@HOST:5432/onemarinex
SECRET_KEY=GENERATE_A_LONG_RANDOM_SECRET

# Email: registration OTP, password reset, SOS, and contact-us
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=no-reply@yourdomain.com
SMTP_PASSWORD=GOOGLE_APP_PASSWORD
SMTP_FROM=no-reply@yourdomain.com
SMTP_USE_TLS=true
SUPPORT_EMAIL=support@yourdomain.com

# DigitalOcean Spaces: bill receipts
SPACES_KEY=YOUR_SPACES_ACCESS_KEY
SPACES_SECRET=YOUR_SPACES_SECRET_KEY
SPACES_BUCKET=heyports-uploads
SPACES_REGION=blr1
SPACES_ENDPOINT=https://blr1.digitaloceanspaces.com

# Optional Spaces settings
SPACES_CDN_ENDPOINT=https://heyports-uploads.blr1.cdn.digitaloceanspaces.com
SPACES_PUBLIC=true
SPACES_PRESIGN_TTL=3600

# Razorpay
RAZORPAY_KEY_ID=rzp_live_xxx
RAZORPAY_KEY_SECRET=YOUR_RAZORPAY_KEY_SECRET
RAZORPAY_WEBHOOK_SECRET=YOUR_RAZORPAY_WEBHOOK_SECRET

# Claude bill extraction
ANTHROPIC_API_KEY=sk-ant-xxx
BILL_EXTRACTION_MODEL=claude-haiku-4-5
```

Configuration notes:

- `SMTP_PORT=587` uses STARTTLS. The current mail service does not implement
  implicit TLS on port 465.
- For Google Workspace, `SMTP_PASSWORD` should be an App Password and
  `SMTP_FROM` must match `SMTP_USER` or a verified alias.
- `SPACES_REGION` must match the Space's actual region. If it is not `blr1`,
  update the region in both `SPACES_REGION` and `SPACES_ENDPOINT`.
- `SPACES_ENDPOINT` is the region endpoint only. Do not add the bucket name or
  an object path.
- `SPACES_PUBLIC=true` uploads public-read objects. Use `false` for private
  receipts; the backend will return time-limited presigned URLs.
- `RAZORPAY_WEBHOOK_SECRET`, `SPACES_CDN_ENDPOINT`, and
  `BILL_EXTRACTION_MODEL` are optional.
- If the database is attached as a DigitalOcean managed database, a bindable
  database variable may be used instead of copying credentials. Confirm that
  the resulting URL uses a SQLAlchemy-compatible PostgreSQL driver.

Recommended encryption:

| Variable | Encrypt? |
|---|---|
| `DATABASE_URL`, `SECRET_KEY` | Yes |
| `SMTP_PASSWORD` | Yes |
| `SPACES_KEY`, `SPACES_SECRET` | Yes |
| `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` | Yes |
| `ANTHROPIC_API_KEY` | Yes |
| Hosts, ports, sender addresses, bucket, region, and public URLs | Optional |

### 2.3 Frontend variable

Edit the frontend/static-site component separately and add:

```dotenv
VITE_API_BASE_URL=https://api.yourdomain.com
```

This is a build-time Vite variable, so rebuild/redeploy the frontend after
changing it. It is public in the compiled browser bundle and must never contain
a secret.

### 2.4 Verify the deployment

After both components deploy:

1. Confirm both deployments are healthy in the **Runtime Logs**.
2. In the backend console, verify that the expected variable names exist.
   Avoid printing secret values into the console or logs.
3. Register a new crew account and confirm that the OTP email arrives.
4. Request a password reset and confirm the new password works, the old one is
   rejected, and the reset code cannot be reused.
5. Configure a test crew SOS email, trigger SOS, and confirm delivery to both
   the ship address and support.
6. Upload a receipt, open its returned URL, then delete it and confirm it is
   removed from Spaces.
7. Extract details from a receipt and confirm that the form is pre-filled.
8. Run a Razorpay test-mode payment before switching to live keys.

## 3. Feature flows and API contract

All backend endpoints below are under `/api/v1`.

### 3.1 Crew registration with email OTP

1. The crew member fills in the registration and profile details.
2. The frontend calls `POST /registration/send-otp` with `{email}`.
3. The backend stores a bcrypt hash of the six-digit code with a ten-minute
   expiry and emails the code.
4. The frontend may call `POST /registration/verify-otp` for non-consuming UI
   feedback.
5. The frontend calls `POST /registration/crew` with the registration payload
   and `otp`.
6. The backend consumes the code and creates the user, crew profile, and HPID.

| Step | Endpoint | Success | Important errors |
|---|---|---|---|
| Send code | `POST /registration/send-otp` | `200` | `409` email already registered |
| Pre-check code | `POST /registration/verify-otp` | `200 {verified: true}` | `400` invalid/expired; `429` too many attempts |
| Create account | `POST /registration/crew` | `201` with auth response | `400` invalid/expired; `409` email/mobile conflict; `422` invalid input |

Rules: six digits, bcrypt-hashed, ten-minute TTL, five-attempt limit,
single-use, and prior codes are invalidated when a new code is sent. OTP gating
currently applies to crew registration only.

### 3.2 Forgot and reset password

1. `POST /auth/forgot-password` with `{email}` always returns `200`, preventing
   account enumeration.
2. If the account exists, the backend emails a six-digit reset code with a
   15-minute TTL.
3. `POST /auth/reset-password` accepts `{email, code, new_password}`.

Reset codes are hashed, single-use, and replaced by each new request. The new
password must be at least eight characters.

### 3.3 SOS and contact email

- Crew first sets the ship address with `POST /crew/sos-config`.
- `POST /crew/trigger-sos` emails the crew-configured ship address and
  `SUPPORT_EMAIL`, including crew, vessel, port, and location context.
- Admins can review an event with `GET /sos/{id}/timeline`.
- `POST /contact` dispatches the support email and sender acknowledgement as a
  best-effort background task.

### 3.4 Bill upload, extraction, and payment

1. `POST /crew/expense-bills/extract` accepts a receipt image and returns
   `{merchant, amount, currency, bill_date, confidence, enabled}`. It does not
   persist anything.
2. Crew reviews or edits the extracted fields.
3. `POST /crew/expense-bills` stores an image or PDF of up to 10 MB and its
   confirmed metadata. Listing and deletion are crew-scoped.
4. `POST /crew/payments/order` creates a local payment and a Razorpay order.
5. The frontend completes checkout.
6. `POST /crew/payments/verify` validates the HMAC-SHA256 signature before
   marking the payment `paid`.

## 4. Implementation decisions and fallbacks

| Integration | Production behavior | Behavior when configuration is missing |
|---|---|---|
| SMTP | Sends OTP, reset, SOS, contact, and acknowledgement emails | Logs email only; OTP/reset cannot complete end-to-end |
| DigitalOcean Spaces | Stores durable receipt objects | Uses local `uploads/`; App Platform disk is ephemeral |
| Razorpay | Creates and verifies real orders | Uses mock orders and auto-verification |
| Anthropic | Extracts bill details with Claude Haiku 4.5 | Returns an empty result with `enabled: false` |

External integrations use a best-effort fallback so missing credentials do not
crash local development. These fallbacks are not production substitutes.

Additional decisions:

- Registration commits the account before attempting crew-manifest sync. A
  manifest failure is rolled back independently and does not turn a successful
  signup into a server error.
- Public Spaces objects return a direct/CDN URL. Private objects store a
  `spaces://` reference and are resolved to a presigned URL when read.
- Bill uploads validate the MIME type and 10 MB limit, use randomized keys, and
  clean up orphaned objects after failed database inserts.
- Bill extraction never saves the extracted values by itself. Crew must review
  and submit the normal upload form.
- Contact email uses a background task; email errors do not block the API
  response.
- SPF, DKIM, and DMARC should be configured for the sending domain to protect
  deliverability, especially for SOS and authentication emails.

## 5. Database and deployment notes

The project currently combines SQLAlchemy `create_all`, Alembic migrations,
ad-hoc scripts, and some code-level schema patches.

- A new table can be created by `create_all` when its model is imported through
  `app/db/base.py`.
- A new column on an existing table requires an Alembic migration because
  `create_all` does not alter existing tables.
- This release adds the `email_verifications`, `expense_bills`, and `payments`
  tables. Startup creates them if they are missing; existing tables and data
  are not dropped or altered by that operation.
- Alembic migrations for these tables are still recommended for consistent
  deployment history and rollback support.
- For frontend verification, use
  `tsc -p tsconfig.app.json --noEmit`; incremental `tsc -b` can reuse stale
  build information.

### Chat reply, edit, and delete schema decision (parked)

Decision status: **parked as of August 1, 2026**. Do not include the chat schema
change in a production deployment until the data-retention behavior and database
migration window have been approved.

The proposed Alembic revision `a8e1c2d3f4b5` changes only `chat_messages`. It
adds nullable `reply_to_id`, `edited_at`, and `deleted_at` columns, an index on
`reply_to_id`, and a self-referencing foreign key with `ON DELETE SET NULL`.
Existing rows remain valid and require no backfill, so the data-conversion risk
is low. Creating the index and validating the foreign key can temporarily block
writes on a large table, making the operational risk low-to-medium depending on
the production table size.

Important release constraints:

- Run the Alembic migration before deploying backend code that references the
  new columns. `Base.metadata.create_all()` does not alter an existing table.
- Take a managed-database backup or snapshot immediately before migration.
- If application rollback is required, roll back the backend code while leaving
  the additive nullable columns in place. Do not run the Alembic downgrade after
  users have used reply, edit, or delete because it discards that metadata.
- The proposed delete flow clears the original message text, and edit overwrites
  the previous text. Neither operation currently has recoverable history.
- Before approval, decide whether moderation, audit, legal, or customer-support
  requirements require an immutable message-revision/history table instead.

## 6. Verification completed

The following were verified on `feat/scoped-changes` on 2026-07-28:

- Backend imported successfully with 239 routes.
- Contact submission and SOS dispatch returned successfully.
- Admin SOS timeline endpoint was registered and access-controlled.
- Bill upload/list and mock payment order/verification completed successfully.
- Frontend TypeScript checking passed and the bill flow plus legal pages
  rendered.
- Real SMTP, DigitalOcean Spaces, and database tests passed.
- Registration OTP completed with a clean `201`.
- Password reset accepted the new password, rejected the old password, and
  rejected reuse of the code.
- Registration still returned `201` when manifest sync was intentionally made
  to fail.
- Real-receipt extraction returned merchant, total, currency, date, and a
  confidence value.

## 7. Release checklist and remaining work

### Required before production

- Merge and deploy the backend and frontend pull requests listed in section 1.
- Add and verify all required environment variables from section 2.
- Configure SPF, DKIM, and DMARC for the production sender domain.
- Use a production-shaped database and confirm the three new tables exist after
  backend startup.
- Rotate any Spaces key that may have been shared outside the intended secrets
  store.
- Run the post-deployment checks in section 2.4.

### Recommended follow-up

- Add explicit Alembic migrations for `email_verifications`, `expense_bills`,
  and `payments`.
- Extend registration OTP enforcement to agent and aggregator accounts.
- Add a dedicated payment-success confirmation screen.
- Verify the admin SOS timeline against production-shaped data.

## 8. Source documents

This handoff supersedes the need to share these two internal working notes
separately:

- `HEYPORTS_FLOWS.md`
- `HEYPORTS_TODOS_AND_DECISIONS.md`

Keep the source documents for detailed historical context; use this consolidated
handoff for review, deployment, and release coordination.
