# Manual Web App Testing

## Local URLs
- Web app: `http://localhost:3000`
- API: `http://localhost:8000`

## Seeded Local Login
- Tenant slug: `acme-intelligence`
- Email: `owner@acme.example`
- Password: `correct horse battery staple`

## Setup
1. Start infrastructure:
   - `docker compose up -d postgres redis`
2. Apply DB migrations:
   - `./.venv/bin/python -m egp_db.migration_runner --database-url postgresql://egp:egp_dev@localhost:5432/egp --migrations-dir packages/db/src/migrations`
3. Seed a local tenant and owner user:
   - `./.venv/bin/python scripts/seed_manual_test_user.py`
4. Start API + web together from the web package:
   - `cd apps/web && DATABASE_URL=postgresql://egp:egp_dev@localhost:5432/egp EGP_PAYMENT_CALLBACK_SECRET=top-secret EGP_AUTH_REQUIRED=true EGP_JWT_SECRET=dev-jwt-secret EGP_SESSION_COOKIE_SECURE=false EGP_WEB_ALLOWED_ORIGINS=http://127.0.0.1:3002 EGP_WEB_BASE_URL=http://127.0.0.1:3002 npm run dev`
5. If you only need the frontend dev server:
   - `cd apps/web && NEXT_PUBLIC_EGP_API_BASE_URL=http://127.0.0.1:8000 npm run dev:web -- --hostname 127.0.0.1 --port 3002`

## Important Product Gaps
- The web app does not yet provide a full click-through crawler execution UI. Runs/tasks still need API or worker assistance; verify results in the web UI.

## Scenario 1: New User Setup And Plan Selection
1. Log in at `/login` with the seeded owner account.
2. Open `/admin`.
3. Create a new user.
4. Send invite for that user.
5. Open the invite link from the local email output/log and complete `/invite` password setup.
6. Log in as the new user and verify `/dashboard`, `/rules`, and `/billing` load.
7. Go to `/billing` and confirm the available plan labels:
   - `Free Trial`
   - `Monthly Membership`
   - `One-Time Search Pack`
8. Create a draft billing record for the chosen plan and verify the plan description and derived billing period end date.

Expected:
- Invite acceptance works.
- Login creates a session.
- Billing page shows the three implemented plans.

## Scenario 2: Billing Modes

### A. Monthly Subscription
1. Go to `/billing`.
2. Create a billing record with plan `Monthly Membership`.
3. Transition it through:
   - `draft`
   - `issued`
   - `awaiting_payment`
4. Click `สร้าง PromptPay QR`.
5. Verify QR, payment link, provider reference, and pending payment request status.
6. Complete settlement via callback helper/API.
7. Open `/rules` and verify:
   - active subscription
   - `monthly_membership`
   - keyword limit `5`
   - runs/exports/downloads/notifications enabled

### B. One-Time Shot
1. Create a billing record with plan `One-Time Search Pack`.
2. Move it to payment-ready state and generate PromptPay QR.
3. Settle payment.
4. Open `/rules` and verify:
   - active subscription
   - `one_time_search_pack`
   - keyword limit `1`

### C. Free Trial
1. Open `/billing` and click `เริ่ม Free Trial`.
2. Open `/rules` and verify:
   - `free_trial`
   - active subscription
   - keyword limit `1`
   - runs allowed
   - exports disabled
   - document downloads disabled
   - notifications disabled

## Scenario 3: Actual Crawling For 1, 3, 5 Keywords
Use `/rules` to verify the active keyword count and entitlement state, then trigger runs/tasks via API or worker.

### 1 Keyword
1. Ensure the tenant has one active keyword.
2. Create a run and a discover task for that keyword.
3. Execute the worker/discover flow.
4. Verify in web UI:
   - `/runs` shows the run and task
   - `/dashboard` metrics update
   - `/projects` shows discovered/updated data

### 3 Keywords
1. Ensure monthly membership is active.
2. Configure 3 active keywords.
3. Trigger discover tasks for the 3 keywords.
4. Verify `/rules` shows:
   - active keywords `3`
   - remaining slots `2`
5. Verify `/runs`, `/dashboard`, and `/projects` update.

### 5 Keywords
1. Ensure monthly membership is active.
2. Configure 5 active keywords.
3. Trigger discover tasks for all 5.
4. Verify `/rules` shows:
   - active keywords `5`
   - remaining slots `0`
5. Negative check: attempt a 6th keyword and verify entitlement rejection.

## Scenario 4: End Of Trial, One-Time Shot, Subscription

### End Of Free Trial
1. Move the trial subscription end date into the past.
2. Refresh `/rules`.
3. Verify subscription becomes inactive/expired and that runs/exports/downloads are blocked.

### End Of One-Time Shot
1. Activate `one_time_search_pack`.
2. Verify 1-keyword use while active.
3. Move its end date into the past.
4. Refresh `/rules` and verify entitlement is inactive.

### End Of Monthly Subscription
1. Activate `monthly_membership`.
2. Verify 5-keyword entitlement while active.
3. Move its end date into the past.
4. Refresh `/rules` and verify:
   - subscription expired/inactive
   - run creation blocked
   - export blocked
   - document download blocked

## Best Screens To Watch During Testing
- `/login`
- `/invite`
- `/dashboard`
- `/rules`
- `/billing`
- `/runs`
- `/projects`
- `/admin`

## Key Assertions Per Test Cycle
- plan label
- subscription status
- keyword limit
- active keyword count
- remaining slots
- runs allowed
- exports allowed
- document download allowed
- notifications allowed
