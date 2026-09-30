# Handover Notes: Authentication, Validation & First-Login Hardening

These notes cover the final hardening work on the Authentication & Session,
Password Reset, Profile, Time Tracking & Attendance, Messaging, Notifications,
Announcements, Events, Holidays/Calendar and Dashboard modules.

---

## 1. Deploying these changes

### Database migrations (run before starting the new backend)

```bash
cd backend
alembic upgrade head
```

| Revision | Adds | Notes |
|---|---|---|
| `a7c3e9d1f2b4` | `users.must_change_password` (bool, NOT NULL, default `false`), `otp_records.attempts` (int, NOT NULL, default `0`) | Existing users are unaffected (`false`). |
| `b8d4f0e2a6c1` | `users.temp_password_expires_at` (timestamp, nullable) | `NULL` = no temporary password outstanding. |

Both are chained after the previous head `77e63f4240ef`, so `alembic heads`
shows a single head. Both were tested upgrade → downgrade → upgrade.

The backend **will fail at runtime** if the code is deployed without these
migrations: the new columns are read on every login.

### Environment variables (see `backend/.env.example`)

| Variable | Default | Set it when |
|---|---|---|
| `TRUST_PROXY_HEADERS` | `false` | **Set `true` when the API runs behind nginx, a load balancer or any reverse proxy.** The login/OTP rate limiter then uses the client IP from `X-Forwarded-For`. If it stays `false` behind a proxy, every user appears to come from the proxy's IP and a few failed logins lock out everyone. If it's `true` without a proxy, clients can fake their IP and bypass the limits. |
| `TEMP_PASSWORD_EXPIRE_DAYS` | `7` | Days an emailed temporary password stays valid. |
| `INTERNAL_API_KEY` | *(empty)* | Only if another service calls `POST /notifications/internal`. Empty means the endpoint is disabled (returns 503). Use a long random value. |
| `APP_TZ_OFFSET_MINUTES` | `330` | Organisation's UTC offset (Sri Lanka = UTC+5:30). Existing variable, now documented. |

Also confirm for production: `ENVIRONMENT=production`, `COOKIE_SECURE=true`.

---

## 2. First-login flow (new employees)

1. HR/Admin creates the employee. The system generates a random temporary
   password and emails it along with the login link.
2. The account is flagged `must_change_password = true`, and the temporary
   password expires after `TEMP_PASSWORD_EXPIRE_DAYS`.
3. The employee logs in with the temporary password and is sent to
   **`/change-password`**.
4. **Until they choose their own password, the API refuses everything else.**
   Only `GET /auth/me`, `POST /auth/logout` and `POST /auth/first-login/password`
   work; every other endpoint returns `403 {"detail": "PASSWORD_CHANGE_REQUIRED"}`.
   The frontend redirects on that response. Anyone else who can read the
   welcome email therefore can't use the account.
5. On a successful change, the new password must pass the policy and differ
   from the temporary one. **Every other session is revoked**, including anyone
   else who logged in with the emailed password.
6. If the temporary password expires first, login shows:
   *"Your temporary password has expired. Ask HR to resend your login details,
   or use Forgot Password to set a new password."*
   The expiry check runs only after a correct password, so it doesn't reveal
   which accounts exist.

### Resend login details (HR action)

On the employee view page (`/dashboard/EmployeeManagement/view?id=…`), users with
`employee:create` see **Resend login details**. It calls
`POST /employees/{id}/resend-login-details`, which:

- emails a new temporary password (expiring as above) and sets
  `must_change_password` again
- stops the old password working immediately and revokes all sessions
- is refused for your own account, deactivated accounts, and super admins
  (unless the caller is a super admin)
- is logged in `audit_logs` as `LOGIN_DETAILS_RESENT_BY:<admin user id>`

---

## 3. Password policy

Defined once in `backend/app/core/password_policy.py` and mirrored for live
feedback in `frontend/lib/passwordPolicy.ts`. **Keep the two in sync.**

- 8–72 characters (bcrypt only hashes the first 72 bytes)
- at least one uppercase letter, one lowercase letter, one number and one special character
- no leading or trailing spaces
- not a common password (small deny-list)
- must not contain the user's first name, last name or email username (3+ characters)
- must differ from the current or temporary password

It applies to first-login change, Security Settings → Change Password, and
Forgot Password → reset.

---

## 4. Other behaviour changes the team should know about

**Sessions**
- Changing a password (settings, first login or reset) signs out all other devices.
- Refresh tokens are rejected as bearer tokens, and deactivated accounts can no
  longer renew their session.
- Every JWT now has a unique `jti`. Previously two tokens issued in the same
  second were identical, so revocation could silently fail.
- 2FA logins now persist their session. Previously 2FA users were logged out
  after 15 minutes.

**Forgot password**
- It gives the same reply whether or not the email has an account.
- OTPs use a cryptographically secure generator and are burned after 5 wrong guesses.

**2FA**
- Disabling 2FA requires the account password: `DELETE /auth/security/2fa`
  with body `{"password": "…"}`.
- The TOTP secret can't be re-read once 2FA is enabled.

**Events**
- `event_date` is stored in UTC and returned with a `Z` suffix.
- Events can't be created in, or moved into, the past.
- Reminders use the local day and time.

**Validation (422 or 400 with a readable message)**
- **Profile:** name, phone, bank account and date-of-birth formats, plus field lengths.
- **Holidays:** real `YYYY-MM-DD` dates between 2000 and 2100, with duplicates rejected.
- **Messages:** subject and content can't be blank. Sending to a group with no recipients is refused.
- **Announcements:** title and content can't be blank.
- **Dashboard layout:** widget sizes and positions are checked.
- **Notification preferences:** only `{email: bool, inApp: bool}` per category.
- **Time tracking:** `week` and `offset` are limited to ±520, and `period` must be day, week or month.
- **Overtime threshold:** must be a number between 0 and 24.
- **Internal notifications:** links must be in-app paths.

**Time tracking**
- Weeks start at local Monday 00:00, not UTC.

**Welcome email**
- The link now goes to `/login`.
- The temporary password is no longer written to logs when `ENVIRONMENT=production`.

---

## 5. Known issues and follow-ups

1. **The old internal key `hrm-internal-2024` is public.** It was hard-coded
   and is still in git history. Treat it as compromised and **never reuse it**
   as `INTERNAL_API_KEY`. The code no longer has any default key.
2. **Events created from the dashboard widget before this release are stored
   5.5 hours off.** The old widget saved local time as if it were UTC, so those
   events now display 5:30 later than intended. Events created from the Events
   page were already correct. Fix: identify the affected rows (for example by
   creation date before this deployment, if the creator used the widget) and
   subtract 5:30 from `event_date`, or re-save them in the UI.
3. **Vacancy descriptions are rendered as raw HTML on the public job pages.**
   `frontend/app/jobs/[id]/page.tsx` uses `dangerouslySetInnerHTML` for
   `vacancy.description` and `vacancy.requirements`. Sanitise them (for example
   with DOMPurify) before rendering, or sanitise on save in the recruitment
   backend. This page is public, so it's a stored-XSS risk.
4. **A brand-new empty database can't be built with `alembic upgrade head`
   alone.** Migration `ba8ad705d455` drops a constraint that only exists on
   databases originally created with `create_all()`. Existing databases migrate
   fine. For a fresh install, fix that migration (for example
   `DROP CONSTRAINT IF EXISTS`), or build the schema and then
   `alembic stamp head`.
5. **Custom message groups were removed.** They never had members, so a
   message sent to one reached nobody. The `/messages/groups` endpoints and the
   compose-screen group controls are gone. Messages can target All, All
   Employees, HR or a department. The `message_groups` table and its
   migrations are left untouched (unused), and old messages keep their original
   `target_group` text. To restore the feature, revert the commit
   "refactor(messages): remove custom message groups".
6. **Access tokens stay valid for up to 15 minutes** after a password change or
   deactivation. Refresh tokens are revoked immediately. Add token versioning
   if instant cut-off is needed.
7. **The rate limiter is in-memory, per worker process.** With several workers
   or hosts, move it to a shared store such as Redis.
8. `backend/app/auth/dependencies.py` has an older, unused `get_current_user`
   **without** the new checks. Always import from `app.core.deps`, and consider
   deleting that file.

---

## 6. Tests

- `backend/tests/test_handover_validation.py` covers the password policy, the
  first-login gate and endpoint, session hardening, the OTP flow, temp-password
  expiry and resend, and each module's validation schemas.
- Run everything with `cd backend && pytest -q`. The remaining failures are
  pre-existing and outside these modules: `test_employees.py`,
  `test_recruitment.py` and `test_document_type_service.py`.
