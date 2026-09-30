"""
tests/test_handover_validation.py
=================================
Covers the handover hardening of the auth / profile / messaging /
notifications / announcements / events / holidays / time-tracking / dashboard
modules:

  - Password policy (shared by every password-setting flow)
  - Mandatory first-login password change (API gate + endpoint)
  - Session hardening (refresh tokens as bearer, deactivated users)
  - Forgot-password OTP (no account enumeration, attempt limit)
  - Input validation schemas for each module

Run with:  pytest tests/test_handover_validation.py -v
"""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.password_policy import password_policy_errors
from app.core.security import hash_password, verify_password


def make_user(**overrides):
    user = MagicMock()
    user.id = 7
    user.email = "nimal@example.com"
    user.username = "nimal@example.com"
    user.first_name = "Nimal"
    user.last_name = "Perera"
    user.password_hash = hash_password("TempPass123")
    user.is_active = True
    user.is_deleted = False
    user.must_change_password = False
    user.refresh_token = None
    for k, v in overrides.items():
        setattr(user, k, v)
    return user


def db_returning(user):
    """A mock Session whose user lookup (query→options→filter→first) returns `user`."""
    db = MagicMock()
    db.query.return_value.options.return_value.filter.return_value.first.return_value = user
    return db


# ─────────────────────────────────────────────────────────────────────────────
# 1. Password policy
# ─────────────────────────────────────────────────────────────────────────────

class TestPasswordPolicy:
    def test_strong_password_passes(self):
        assert password_policy_errors("Blue#Harbor42") == []

    @pytest.mark.parametrize("pw, fragment", [
        ("Sh0rt!", "at least 8"),
        ("alllowercase1!", "uppercase"),
        ("ALLUPPERCASE1!", "lowercase"),
        ("NoDigitsHere!", "number"),
        ("NoSpecial123", "special"),
        (" Leading1!Space", "space"),
        ("", "required"),
    ])
    def test_each_rule_is_enforced(self, pw, fragment):
        errors = " ".join(password_policy_errors(pw)).lower()
        assert fragment in errors

    def test_rejects_passwords_over_bcrypt_limit(self):
        assert password_policy_errors("Aa1!" + "x" * 70)

    def test_rejects_common_password(self):
        assert password_policy_errors("Password@123")

    def test_rejects_name_or_email_in_password(self):
        assert password_policy_errors("Nimal#2026x", names=["Nimal"])
        assert password_policy_errors("xNIMAL#2026", email="nimal@example.com")


# ─────────────────────────────────────────────────────────────────────────────
# 2. API gate while a first-login change is pending (core/deps.py)
# ─────────────────────────────────────────────────────────────────────────────

def _call_get_current_user(user, path, token=None):
    from app.core.deps import get_current_user
    from app.core.jwt import create_access_token

    token = token or create_access_token({"sub": str(user.id)})
    request = SimpleNamespace(url=SimpleNamespace(path=path), query_params={})
    creds = SimpleNamespace(credentials=token)
    return get_current_user(request, creds, db_returning(user))


class TestFirstLoginGate:
    def test_pending_change_blocks_regular_endpoints(self):
        user = make_user(must_change_password=True)
        with pytest.raises(HTTPException) as exc:
            _call_get_current_user(user, "/leave/my-requests")
        assert exc.value.status_code == 403
        assert exc.value.detail == "PASSWORD_CHANGE_REQUIRED"

    @pytest.mark.parametrize("path", ["/auth/me", "/auth/first-login/password"])
    def test_pending_change_still_allows_whitelisted_paths(self, path):
        user = make_user(must_change_password=True)
        assert _call_get_current_user(user, path) is user

    def test_normal_user_is_not_gated(self):
        user = make_user()
        assert _call_get_current_user(user, "/leave/my-requests") is user


class TestSessionHardening:
    def test_refresh_token_is_not_accepted_as_bearer(self):
        from app.core.jwt import create_refresh_token
        user = make_user()
        with pytest.raises(HTTPException) as exc:
            _call_get_current_user(user, "/auth/me", token=create_refresh_token({"sub": "7"}))
        assert exc.value.status_code == 401

    def test_deactivated_user_is_rejected(self):
        with pytest.raises(HTTPException) as exc:
            _call_get_current_user(make_user(is_active=False), "/auth/me")
        assert exc.value.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# 3. First-login password change endpoint
# ─────────────────────────────────────────────────────────────────────────────

def _first_login(user, new, confirm=None):
    from app.auth.router import first_login_change_password
    from app.auth.schemas import FirstLoginPasswordChange

    response = MagicMock()
    data = FirstLoginPasswordChange(new_password=new, confirm_password=new if confirm is None else confirm)
    with patch("app.notifications.service.notify_user"):
        return first_login_change_password(data, response, MagicMock(), user), response


def test_tokens_issued_in_the_same_second_are_distinct():
    """Revocation compares stored vs presented refresh token — they must differ."""
    from app.core.jwt import create_access_token, create_refresh_token
    assert create_refresh_token({"sub": "1"}) != create_refresh_token({"sub": "1"})
    assert create_access_token({"sub": "1"}) != create_access_token({"sub": "1"})


class TestFirstLoginEndpoint:
    def test_success_clears_flag_rotates_session(self):
        user = make_user(must_change_password=True)
        result, response = _first_login(user, "Blue#Harbor42")
        assert user.must_change_password is False
        assert verify_password("Blue#Harbor42", user.password_hash)
        assert result["access_token"]
        assert user.refresh_token  # new token stored → other sessions revoked
        response.set_cookie.assert_called_once()

    def test_rejects_when_no_change_pending(self):
        with pytest.raises(HTTPException) as exc:
            _first_login(make_user(must_change_password=False), "Blue#Harbor42")
        assert exc.value.status_code == 400

    def test_rejects_mismatched_confirmation(self):
        with pytest.raises(HTTPException) as exc:
            _first_login(make_user(must_change_password=True), "Blue#Harbor42", "Blue#Harbor43")
        assert "match" in exc.value.detail

    def test_rejects_weak_password(self):
        with pytest.raises(HTTPException) as exc:
            _first_login(make_user(must_change_password=True), "weakpass")
        assert exc.value.status_code == 400

    def test_rejects_reusing_the_temporary_password(self):
        user = make_user(must_change_password=True, password_hash=hash_password("Temp#Pass123"))
        with pytest.raises(HTTPException) as exc:
            _first_login(user, "Temp#Pass123")
        assert "different" in exc.value.detail


class TestChangePassword:
    def test_weak_new_password_rejected(self):
        from app.auth.router import change_password
        from app.auth.schemas import UserPasswordUpdate
        user = make_user()
        with pytest.raises(HTTPException) as exc:
            change_password(UserPasswordUpdate(current_password="TempPass123", new_password="abc"),
                            MagicMock(), MagicMock(), user)
        assert exc.value.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# 4. Forgot-password OTP
# ─────────────────────────────────────────────────────────────────────────────

class TestOtpFlow:
    def test_unknown_email_gets_same_answer_as_known(self):
        from app.auth import router as auth_router
        from app.auth.schemas import SendOtpRequest
        with patch.object(auth_router, "enforce_rate_limit"), \
             patch.object(auth_router, "get_user_by_email", return_value=None), \
             patch.object(auth_router, "send_otp_email") as send:
            result = auth_router.send_otp(SendOtpRequest(email="nobody@example.com"), MagicMock(), MagicMock())
        assert "if an account exists" in result["message"].lower()
        send.assert_not_called()

    def test_otp_is_burned_after_max_attempts(self):
        from app.auth import router as auth_router
        from app.auth.schemas import VerifyOtpRequest
        record = SimpleNamespace(otp="123456", attempts=auth_router.OTP_MAX_ATTEMPTS - 1,
                                 expires_at=datetime.utcnow() + timedelta(minutes=5), verified=False)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = record
        with patch.object(auth_router, "enforce_rate_limit"), pytest.raises(HTTPException) as exc:
            auth_router.verify_otp(VerifyOtpRequest(email="a@b.co", otp="000000"), MagicMock(), db)
        assert "too many" in exc.value.detail.lower()
        db.delete.assert_called_once_with(record)

    def test_non_numeric_otp_rejected(self):
        from app.auth import router as auth_router
        from app.auth.schemas import VerifyOtpRequest
        with patch.object(auth_router, "enforce_rate_limit"), pytest.raises(HTTPException):
            auth_router.verify_otp(VerifyOtpRequest(email="a@b.co", otp="12ab56"), MagicMock(), MagicMock())


# ─────────────────────────────────────────────────────────────────────────────
# 5. Module input schemas
# ─────────────────────────────────────────────────────────────────────────────

class TestProfileSchema:
    def test_valid_profile(self):
        from app.auth.schemas import UserProfileUpdate
        p = UserProfileUpdate(first_name=" Anne-Marie ", last_name="O'Neil",
                              phone_number="+94 77 123 4567", date_of_birth="")
        assert p.first_name == "Anne-Marie"
        assert p.date_of_birth is None

    @pytest.mark.parametrize("field, value", [
        ("first_name", ""),
        ("first_name", "J0hn"),
        ("phone_number", "call me"),
        ("date_of_birth", "not-a-date"),
        ("date_of_birth", (date.today() + timedelta(days=1)).isoformat()),
        ("bank_account_no", "12AB34"),
        ("address", "x" * 501),
    ])
    def test_invalid_values_rejected(self, field, value):
        from app.auth.schemas import UserProfileUpdate
        with pytest.raises(ValidationError):
            UserProfileUpdate(**{field: value})

    def test_notification_preferences_must_be_boolean_channels(self):
        from app.auth.schemas import UserNotificationUpdate
        with pytest.raises(ValidationError):
            UserNotificationUpdate(notification_preferences={"leave": {"email": "sometimes"}})


class TestEventSchema:
    def test_aware_datetime_normalised_to_naive_utc(self):
        from app.events.schemas import EventCreate
        ev = EventCreate(title="AGM", event_date=datetime(2030, 1, 1, 14, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))))
        assert ev.event_date == datetime(2030, 1, 1, 8, 30)

    def test_naive_datetime_treated_as_local(self):
        from app.events.schemas import EventCreate
        assert EventCreate(title="AGM", event_date="2030-01-01T14:00:00").event_date == datetime(2030, 1, 1, 8, 30)

    def test_blank_title_rejected(self):
        from app.events.schemas import EventCreate
        with pytest.raises(ValidationError):
            EventCreate(title="   ", event_date="2030-01-01T10:00:00Z")

    def test_update_cannot_null_required_fields(self):
        from app.events.schemas import EventUpdate
        with pytest.raises(ValidationError):
            EventUpdate(title=None)
        with pytest.raises(ValidationError):
            EventUpdate(event_date=None)

    def test_response_marks_utc(self):
        from app.events.schemas import EventResponse
        r = EventResponse(id=1, title="x", event_date=datetime(2030, 1, 1, 8, 30), created_by=1)
        assert r.model_dump(mode="json")["event_date"] == "2030-01-01T08:30:00Z"


class TestHolidaySchema:
    def test_valid(self):
        from app.calendar_holidays.schemas import HolidayCreate
        assert HolidayCreate(name=" Vesak ", date="2026-05-01").name == "Vesak"

    @pytest.mark.parametrize("value", ["hello", "2026-02-30", "1999-12-31", ""])
    def test_invalid_dates_rejected(self, value):
        from app.calendar_holidays.schemas import HolidayCreate
        with pytest.raises(ValidationError):
            HolidayCreate(name="X", date=value)


class TestMessageAndAnnouncementSchemas:
    def test_blank_message_rejected(self):
        from app.messages.schemas import MessageCreate
        with pytest.raises(ValidationError):
            MessageCreate(target_group="All", subject="  ", content="hi")

    def test_group_name_length_limited(self):
        from app.messages.schemas import MessageGroupCreate
        with pytest.raises(ValidationError):
            MessageGroupCreate(name="g" * 101)

    def test_announcement_update_rejects_blank_but_allows_omitted(self):
        from app.announcements.schemas import AnnouncementUpdate
        assert AnnouncementUpdate(content="new").title is None
        with pytest.raises(ValidationError):
            AnnouncementUpdate(title=" ")


class TestNotificationAndDashboardSchemas:
    @pytest.mark.parametrize("link", ["https://evil.example/login", "//evil.example", "javascript:alert(1)"])
    def test_internal_notification_links_must_be_in_app(self, link):
        from app.notifications.schemas import NotificationCreate
        with pytest.raises(ValidationError):
            NotificationCreate(user_id=1, message="hi", link=link)

    def test_dashboard_widget_extra_keys_dropped_and_bounds_checked(self):
        from app.dashboard.schemas import DashboardLayoutUpdate
        layout = DashboardLayoutUpdate(widgets=[{"i": "calendar", "x": 0, "y": 0, "w": 4, "h": 3, "junk": "x" * 1000}])
        assert "junk" not in layout.widgets[0].model_dump()
        with pytest.raises(ValidationError):
            DashboardLayoutUpdate(widgets=[{"i": "calendar", "x": -1, "y": 0, "w": 4, "h": 3}])


class TestTimeTracking:
    def test_threshold_rejects_bool_and_strings(self):
        from app.time_tracking.schemas import OvertimeThresholdUpdate
        assert OvertimeThresholdUpdate(threshold_hours=8.5).threshold_hours == 8.5
        for bad in (True, "8", 0, 25):
            with pytest.raises(ValidationError):
                OvertimeThresholdUpdate(threshold_hours=bad)

    def test_week_follows_local_midnight(self):
        """Monday 01:00 local (Sunday 19:30 UTC) belongs to the NEW week."""
        from app.time_tracking import router as tt
        with patch.object(tt, "_local_today", return_value=date(2026, 9, 28)):  # a Monday
            monday_utc, sunday_utc = tt._week_bounds(0)
            assert tt._week_dates(0) == (date(2026, 9, 28), date(2026, 10, 4))
        session_start_utc = datetime(2026, 9, 27, 19, 30)  # = Mon 28 Sep 01:00 local
        assert monday_utc <= session_start_utc <= sunday_utc

    def test_period_offset_params_keep_their_own_names(self):
        """Regression: a shared Query() object renamed all-attendance's `offset` to `week`."""
        from app.main import app
        paths = app.openapi()["paths"]
        names = lambda p: [x["name"] for x in paths[p]["get"].get("parameters", [])]
        assert names("/time-tracking/all-attendance") == ["period", "offset"]
        assert names("/time-tracking/weekly-stats") == ["week"]
        assert names("/time-tracking/history") == ["week"]


# ─────────────────────────────────────────────────────────────────────────────
# 6. Temporary password expiry + "resend login details"
# ─────────────────────────────────────────────────────────────────────────────

class TestTemporaryPasswordExpiry:
    def _auth(self, user, password="TempPass123"):
        from app.auth.service import authenticate_user
        db = MagicMock()
        db.query.return_value.options.return_value.filter.return_value.first.return_value = user
        return authenticate_user(db, user.email, password)

    def test_expired_temporary_password_refused_after_correct_password(self):
        from app.auth.service import TemporaryPasswordExpired
        user = make_user(must_change_password=True, temp_password_expires_at=datetime.utcnow() - timedelta(minutes=1))
        with pytest.raises(TemporaryPasswordExpired):
            self._auth(user)
        assert user.refresh_token is None  # no session issued

    def test_wrong_password_still_generic_even_if_expired(self):
        user = make_user(must_change_password=True, temp_password_expires_at=datetime.utcnow() - timedelta(days=1))
        assert self._auth(user, "not-it") is None  # no hint that the account exists

    def test_unexpired_temporary_password_logs_in(self):
        user = make_user(must_change_password=True, temp_password_expires_at=datetime.utcnow() + timedelta(days=1))
        assert self._auth(user)["access_token"]

    def test_first_login_change_refused_once_expired(self):
        user = make_user(must_change_password=True, temp_password_expires_at=datetime.utcnow() - timedelta(seconds=1))
        with pytest.raises(HTTPException) as exc:
            _first_login(user, "Blue#Harbor42")
        assert exc.value.status_code == 403 and "expired" in exc.value.detail

    def test_successful_first_login_clears_expiry(self):
        user = make_user(must_change_password=True, temp_password_expires_at=datetime.utcnow() + timedelta(days=1))
        _first_login(user, "Blue#Harbor42")
        assert user.temp_password_expires_at is None


class TestResendLoginDetails:
    def _db_with(self, employee):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = employee
        return db

    def _employee(self, **user_overrides):
        user = make_user(**{"id": 21, "is_superadmin": False, "must_change_password": False, **user_overrides})
        return SimpleNamespace(id=5, first_name="Nimal", last_name="Perera", user=user), user

    def test_resend_issues_new_expiring_temp_password_and_revokes_sessions(self):
        from app.employees.service import resend_login_details
        emp, user = self._employee(refresh_token="old-session")
        old_hash = user.password_hash
        tasks = MagicMock()
        actor = make_user(id=1, is_superadmin=False)
        result = resend_login_details(self._db_with(emp), 5, actor, tasks)
        assert user.must_change_password is True
        assert user.password_hash != old_hash
        assert user.refresh_token is None
        assert user.temp_password_expires_at > datetime.utcnow() + timedelta(days=6)
        tasks.add_task.assert_called_once()
        sent_password = tasks.add_task.call_args.args[3]
        assert verify_password(sent_password, user.password_hash)
        assert "expire" in result["message"]

    def test_non_superadmin_cannot_reset_superadmin(self):
        from app.employees.service import resend_login_details
        emp, _ = self._employee(is_superadmin=True)
        with pytest.raises(HTTPException) as exc:
            resend_login_details(self._db_with(emp), 5, make_user(id=1, is_superadmin=False), MagicMock())
        assert exc.value.status_code == 403

    def test_cannot_resend_to_yourself_or_deactivated_or_missing(self):
        from app.employees.service import resend_login_details
        emp, user = self._employee()
        with pytest.raises(HTTPException):
            resend_login_details(self._db_with(emp), 5, user, MagicMock())
        emp2, _ = self._employee(is_active=False)
        with pytest.raises(HTTPException):
            resend_login_details(self._db_with(emp2), 5, make_user(id=1, is_superadmin=True), MagicMock())
        with pytest.raises(HTTPException) as exc:
            resend_login_details(self._db_with(None), 5, make_user(id=1, is_superadmin=True), MagicMock())
        assert exc.value.status_code == 404
