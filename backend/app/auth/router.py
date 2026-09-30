import os
import re
import hmac
import secrets
import logging
import qrcode
import base64
from io import BytesIO
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Response, Request, UploadFile, File
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from app.database.database import get_db
from app.auth.schemas import (
    LoginRequest, TokenResponse, UserResponse,
    UserProfileUpdate, UserPasswordUpdate, UserNotificationUpdate,
    FirstLoginPasswordChange, SendOtpRequest, VerifyOtpRequest, ResetPasswordRequest,
    TwoFactorLoginRequest, TwoFactorCodeRequest, TwoFactorDisableRequest,
)
from app.core.security import SECRET_KEY, ALGORITHM, create_access_token, hash_password, verify_password
from app.core.deps import get_current_user, get_user_permissions
from app.core.password_policy import validate_password_or_raise
from app.auth.service import (
    authenticate_user, get_user_by_email,
    TemporaryPasswordExpired, TEMP_PASSWORD_EXPIRED_MESSAGE, temp_password_expired,
)
from app.auth.models import User, AuditLog, OTPRecord
from app.core.email import send_otp_email
from app.core.config import (
    COOKIE_SECURE, COOKIE_SAMESITE,
    LOGIN_RATE_LIMIT, LOGIN_RATE_WINDOW_SECONDS,
    OTP_RATE_LIMIT, OTP_RATE_WINDOW_SECONDS,
)
from app.core.rate_limit import enforce_rate_limit

router = APIRouter()
security = HTTPBearer()
logger = logging.getLogger(__name__)

# ── Environment Configuration ────────────────────────────────────────────────
OTP_EXPIRE_SECONDS = int(os.getenv("OTP_EXPIRE_SECONDS", "300"))

# ── Module-level constants ─────────────────────────────────────────────────────
OTP_LENGTH = 6              # Digits in a password-reset OTP / TOTP code
OTP_MAX_ATTEMPTS = 5        # Wrong guesses before a reset OTP is burned
CODE_RE = re.compile(r"^\d{6}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    from app.core.jwt import REFRESH_TOKEN_EXPIRE_DAYS
    response.set_cookie(
        key="refresh_token", value=refresh_token, httponly=True, secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE, max_age=60 * 60 * 24 * REFRESH_TOKEN_EXPIRE_DAYS, path="/"
    )


def _start_new_session(user: User, response: Response, db: Session) -> str:
    """
    Issue a fresh access + refresh pair for this browser and make it the ONLY
    valid refresh token for the user (one refresh token is stored per user), so
    every other browser is signed out at its next /refresh. Returns the access token.
    """
    from app.core.jwt import create_refresh_token
    refresh = create_refresh_token({"sub": str(user.id)})
    user.refresh_token = refresh
    db.commit()
    _set_refresh_cookie(response, refresh)
    return create_access_token({"sub": str(user.id)})


def _user_names(user: User) -> tuple:
    return (user.first_name, user.last_name, user.username if user.username != user.email else None)

# ---------------- LOGIN ----------------

@router.post("/login")
def login(data: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """
    Authenticate a user with email/username and password.
    If 2FA is enabled, returns a short-lived temp_token instead of a full session.
    On success, sets the refresh token as an HttpOnly cookie and returns the access token.
    Failed attempts are recorded in the audit log.
    """
    enforce_rate_limit(request, "login", LOGIN_RATE_LIMIT, LOGIN_RATE_WINDOW_SECONDS)

    client_ip = request.client.host if request.client else "Unknown"

    # A missing OR whitespace-only identifier is a bad request (400), not a failed
    # credential check (401) — checked before any lookup so the client gets a
    # clear required-field message.
    identifier = (data.email or data.username or "").strip()
    if not identifier:
        raise HTTPException(status_code=400, detail="Email or username required")

    try:
        token = authenticate_user(db, identifier, data.password)
    except TemporaryPasswordExpired:
        db.add(AuditLog(action="LOGIN_TEMP_PASSWORD_EXPIRED", ip_address=client_ip))
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=TEMP_PASSWORD_EXPIRED_MESSAGE)
    if not token:
        audit_log = AuditLog(action="LOGIN_FAILED", ip_address=client_ip)
        db.add(audit_log)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    user = token["user"]

    if user and user.two_factor_enabled:
        temp_token = create_access_token({"sub": str(user.id), "type": "2fa"})
        return {"require_2fa": True, "temp_token": temp_token}

    refresh_token = token["refresh_token"]

    from app.core.jwt import REFRESH_TOKEN_EXPIRE_DAYS
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=60 * 60 * 24 * REFRESH_TOKEN_EXPIRE_DAYS,
        path="/"
    )

    if user:
        audit_log = AuditLog(user_id=user.id, action="LOGIN_SUCCESS", ip_address=client_ip)
        db.add(audit_log)
        db.commit()

    return {
        "access_token": token["access_token"],
        "token_type": "bearer",
        # Tells the client to go straight to the first-login password screen;
        # the API enforces it regardless (core/deps.get_current_user).
        "must_change_password": bool(user.must_change_password),
    }


@router.post("/login/2fa")
def login_2fa(data: TwoFactorLoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """
    Complete the second step of two-factor authentication.
    Validates the TOTP code against the user's stored secret.
    On success, issues full access and refresh tokens, setting the cookie.
    """
    enforce_rate_limit(request, "login_2fa", LOGIN_RATE_LIMIT, LOGIN_RATE_WINDOW_SECONDS)

    temp_token = data.temp_token
    code = (data.code or "").strip()
    if not temp_token:
        raise HTTPException(401, "Invalid temporary token")
    if not CODE_RE.match(code):
        raise HTTPException(400, f"Enter the {OTP_LENGTH}-digit code from your authenticator app")

    try:
        payload = jwt.decode(temp_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "2fa":
            raise HTTPException(401, "Invalid token type")
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(401, "Invalid temporary token")

    user = db.query(User).filter(User.id == int(user_id)).first()
    import pyotp
    # Deactivated / soft-deleted accounts must not be able to complete step 2
    # even if they somehow hold a valid temp_token. Use the same generic 401 as
    # the primary login path so we don't disclose that the account is disabled.
    if not user or user.is_active is False or getattr(user, "is_deleted", False):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not user.totp_secret:
        raise HTTPException(400, "2FA not configured")

    if not pyotp.TOTP(user.totp_secret).verify(code):
        raise HTTPException(400, "Invalid 2FA code")

    # The refresh token MUST be persisted: /refresh rejects any cookie that
    # doesn't match users.refresh_token, so an unsaved one silently logged 2FA
    # users out as soon as their 15-minute access token expired.
    access_token = _start_new_session(user, response, db)

    client_ip = request.client.host if request.client else "Unknown"
    db.add(AuditLog(user_id=user.id, action="LOGIN_SUCCESS", ip_address=client_ip))
    db.commit()
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "must_change_password": bool(user.must_change_password),
    }


# ---------------- REFRESH TOKEN ----------------

@router.post("/refresh")
def refresh_token(request: Request, response: Response, db: Session = Depends(get_db)):
    """
    Issue a new access token using the HttpOnly refresh token cookie.
    Rotates the refresh token on every call (one-time-use) and persists
    the new value to the database to prevent token reuse.
    """
    refresh_token = request.cookies.get("refresh_token")

    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing")

    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if payload.get("type") != "refresh" or user_id is None:
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        user = db.query(User).filter(User.id == int(user_id)).first()

        # Deactivated accounts lose their session at the next refresh rather
        # than being able to renew it forever.
        if not user or user.is_active is False or user.refresh_token != refresh_token:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
            
        from app.core.jwt import create_refresh_token, REFRESH_TOKEN_EXPIRE_DAYS
        new_access = create_access_token({"sub": str(user_id)})
        new_refresh = create_refresh_token({"sub": str(user_id)})
        
        user.refresh_token = new_refresh
        db.commit()

        response.set_cookie(
            key="refresh_token", value=new_refresh, httponly=True, secure=COOKIE_SECURE,
            samesite=COOKIE_SAMESITE, max_age=60 * 60 * 24 * REFRESH_TOKEN_EXPIRE_DAYS, path="/"
        )
        return {"access_token": new_access, "token_type": "bearer"}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")


# ---------------- LOGOUT ----------------

@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """
    Log the user out by invalidating their refresh token in the database
    and clearing the HttpOnly cookie. Records a LOGOUT audit event.
    """
    refresh_token = request.cookies.get("refresh_token")
    client_ip = request.client.host if request.client else "Unknown"
    
    if refresh_token:
        try:
            payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = payload.get("sub")
            user = db.query(User).filter(User.id == int(user_id)).first()
            if user:
                user.refresh_token = None
                audit_log = AuditLog(user_id=user.id, action="LOGOUT", ip_address=client_ip)
                db.add(audit_log)
                db.commit()
        except JWTError:
            pass
            
    response.delete_cookie(key="refresh_token", path="/", httponly=True, secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE)
    return {"message": "Logged out successfully"}


# ---------------- SEND OTP ----------------

@router.post("/send-otp")
def send_otp(data: SendOtpRequest, request: Request, db: Session = Depends(get_db)):
    """
    Generate a 6-digit OTP for the given email and send it via email.
    Any existing OTP records for that email are deleted first to prevent reuse.
    The OTP expires after OTP_EXPIRE_SECONDS (default 300 s / 5 min).

    Always answers the same way whether or not the account exists, so this
    endpoint can't be used to discover which emails have accounts.
    """
    enforce_rate_limit(request, "send_otp", OTP_RATE_LIMIT, OTP_RATE_WINDOW_SECONDS)

    email = (data.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email required")
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address")

    generic = {"message": "If an account exists for this email, a verification code has been sent."}

    user = get_user_by_email(db, email)
    if not user or user.is_active is False:
        return generic

    # secrets, not random: the OTP is a credential and must be unpredictable.
    otp = f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"
    expires_at = datetime.utcnow() + timedelta(seconds=OTP_EXPIRE_SECONDS)

    # Save to DB (cleanup old ones for this email first)
    db.query(OTPRecord).filter(OTPRecord.email == email).delete()
    otp_record = OTPRecord(email=email, otp=otp, expires_at=expires_at)
    db.add(otp_record)
    db.commit()

    send_otp_email(email, otp)
    return generic


# ---------------- VERIFY OTP ----------------

@router.post("/verify-otp")
def verify_otp(data: VerifyOtpRequest, request: Request, db: Session = Depends(get_db)):
    """
    Verify the OTP submitted by the user against the stored record.
    Marks the record as verified so the reset-password endpoint can proceed.
    Returns 400 if the OTP is incorrect or has expired. After OTP_MAX_ATTEMPTS
    wrong guesses the code is burned and a new one must be requested.
    """
    enforce_rate_limit(request, "verify_otp", OTP_RATE_LIMIT, OTP_RATE_WINDOW_SECONDS)

    email = (data.email or "").strip().lower()
    otp = (data.otp or "").strip()
    if not email or not otp:
        raise HTTPException(status_code=400, detail="Email and OTP required")
    if not CODE_RE.match(otp):
        raise HTTPException(status_code=400, detail=f"The code must be {OTP_LENGTH} digits")

    record = db.query(OTPRecord).filter(OTPRecord.email == email).first()
    if not record:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    if datetime.utcnow() > record.expires_at:
        db.delete(record)
        db.commit()
        raise HTTPException(status_code=400, detail="OTP expired")

    if not hmac.compare_digest(record.otp, otp):
        record.attempts = (record.attempts or 0) + 1
        if record.attempts >= OTP_MAX_ATTEMPTS:
            db.delete(record)
            db.commit()
            raise HTTPException(status_code=400, detail="Too many incorrect attempts. Please request a new code.")
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid OTP")

    record.verified = True
    db.commit()
    return {"message": "OTP verified successfully"}


# ---------------- RESET PASSWORD ----------------

@router.post("/reset-password")
def reset_password(data: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """
    Reset the user's password after a successful OTP verification.
    Requires a verified (and non-expired) OTP record for the email.
    The OTP record is deleted after a successful password update.
    """
    enforce_rate_limit(request, "reset_password", OTP_RATE_LIMIT, OTP_RATE_WINDOW_SECONDS)

    email = (data.email or "").strip().lower()
    new_password = data.password
    if not email or not new_password:
        raise HTTPException(status_code=400, detail="Email and password required")

    record = db.query(OTPRecord).filter(OTPRecord.email == email, OTPRecord.verified == True).first()

    if not record:
        raise HTTPException(status_code=403, detail="OTP verification required")

    if datetime.utcnow() > record.expires_at:
        db.delete(record)
        db.commit()
        raise HTTPException(status_code=400, detail="OTP expired")

    user = get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    validate_password_or_raise(new_password, email=user.email, names=_user_names(user))
    if verify_password(new_password, user.password_hash):
        raise HTTPException(status_code=400, detail="New password must be different from your current password.")

    user.password_hash = hash_password(new_password)
    # Proving control of the mailbox is enough to also satisfy a pending
    # first-login change — the user has now chosen their own password.
    user.must_change_password = False
    user.temp_password_expires_at = None
    # Invalidate all other active sessions after a password reset: clearing the
    # stored refresh_token forces every other browser to re-authenticate on its
    # next /refresh (aligns with logout, which also nulls refresh_token).
    user.refresh_token = None
    db.delete(record) # Delete after use
    db.commit()
    return {"message": "Password updated successfully"}


# ---------------- CURRENT USER ----------------

@router.get("/me", response_model=UserResponse)
def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Return the authenticated user's full profile including resolved permissions.
    Sensitive fields (password_hash, refresh_token, totp_secret) are excluded.
    If the user has an associated employee record, those fields are merged in.
    """
    permissions = get_user_permissions(current_user, db)

    user_dict = {
        c.name: getattr(current_user, c.name, None)
        for c in current_user.__table__.columns
        if c.name not in ("hashed_password", "password_hash", "refresh_token", "totp_secret")
    }
    user_dict["permissions"] = permissions

    if current_user.employee:
        emp = current_user.employee
        user_dict.update({
            "designation": emp.designation,
            "joined_date": str(emp.joined_date) if emp.joined_date else None,
            "status": emp.status.value if emp.status else None,
            "gender": emp.gender,
            "marital_status": emp.marital_status,
            "nationality": emp.nationality,
            "emergency_contact_name": emp.emergency_contact_name,
            "emergency_contact_relation": emp.emergency_contact_relation,
            "bank_name": emp.bank_name,
            "bank_account_no": emp.bank_account_no,
            "bank_branch": emp.bank_branch,
            "skills": emp.skills,
            "qualifications": emp.qualifications,
            "designation_history": [
                {
                    "designation_name": h.designation_name,
                    "start_date": str(h.start_date) if h.start_date else None,
                    "end_date": str(h.end_date) if h.end_date else None,
                    "promotion_letter_sent": h.promotion_letter_sent
                }
                for h in sorted(emp.designation_history, key=lambda x: x.start_date or datetime.min.date(), reverse=True)
            ] if emp.designation_history else [],
        })

    return user_dict


# ---------------- SETTINGS & PROFILE ----------------

@router.put("/profile", response_model=UserResponse)
def update_profile(
    data: UserProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update the current user's own profile fields (name, phone, address, etc.).
    Empty-string date fields are coerced to None to avoid DB type errors.
    Changes are also synced to the linked Employee record if one exists.
    """
    user = current_user
    update_data = data.model_dump(exclude_unset=True)
    
    # Sanitize all possible date fields to prevent "invalid input syntax for type date: ''"
    date_fields = ["date_of_birth", "joined_date"]
    for field in date_fields:
        if field in update_data and update_data[field] in ("", "None", "null"):
            update_data[field] = None
            
    user_fields = ["first_name", "last_name", "phone_number", "address", "date_of_birth", "emergency_contact_number"]

    for key in user_fields:
        if key in update_data:
            setattr(user, key, update_data[key])

    if user.employee:
        emp_keys = ["gender", "marital_status", "nationality", "emergency_contact_name", "emergency_contact_relation", "bank_name", "bank_account_no", "bank_branch", "skills", "qualifications"]
        for key in emp_keys:
            if key in update_data:
                setattr(user.employee, key, update_data[key])
        
        # Sync User details to Employee model
        if "first_name" in update_data: user.employee.first_name = update_data["first_name"]
        if "last_name" in update_data: user.employee.last_name = update_data["last_name"]
        if "phone_number" in update_data: user.employee.phone = update_data["phone_number"]
        if "address" in update_data: user.employee.address = update_data["address"]
        if "date_of_birth" in update_data: user.employee.date_of_birth = update_data["date_of_birth"]
        if "emergency_contact_number" in update_data: user.employee.emergency_contact_phone = update_data["emergency_contact_number"]

    db.commit()
    db.refresh(user)
    return user


@router.post("/profile/image")
def upload_profile_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a new profile image for the current user.
    """
    from app.core.storage_service import storage as _storage, resolve_public_url
    from app.core.file_validation import validate_upload, IMAGE_TYPES

    # Validate by magic bytes and derive the extension from the DETECTED type.
    # This blocks non-images (.exe) and — critically — HTML/SVG carrying inline
    # JavaScript, which StaticFiles would otherwise serve as active content
    # (stored XSS). Never trust the client-supplied extension.
    content, _detected, detected_ext = validate_upload(
        file,
        IMAGE_TYPES,
        max_size_bytes=5 * 1024 * 1024,
        reject_message="Only JPEG, PNG, or WEBP images are allowed",
    )
    ext = detected_ext.lstrip(".")
    key = f"profiles/{current_user.id}.{ext}"

    _storage.upload(content, key)

    # Persist the storage KEY (not a fully-formed URL) so we can mint a fresh URL
    # on every read. S3 pre-signed URLs expire after 1h; storing the key avoids
    # baking a soon-to-be-dead URL into the DB.
    current_user.profile_image_url = key
    db.commit()
    db.refresh(current_user)
    return {"profile_image_url": resolve_public_url(current_user.profile_image_url)}


@router.post("/first-login/password")
def first_login_change_password(
    data: FirstLoginPasswordChange,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Replace the emailed temporary password on first login (mandatory).

    Only callable while must_change_password is set. The new password must meet
    the policy and differ from the temporary one. Every other session — e.g.
    someone else who also read the welcome email and logged in — is revoked,
    and this browser gets a fresh token pair.
    """
    if not current_user.must_change_password:
        raise HTTPException(status_code=400, detail="Your password has already been set. Use Security Settings to change it.")
    # A session opened before the deadline must not outlive it.
    if temp_password_expired(current_user):
        raise HTTPException(status_code=403, detail=TEMP_PASSWORD_EXPIRED_MESSAGE)
    if data.new_password != data.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match.")
    validate_password_or_raise(data.new_password, email=current_user.email, names=_user_names(current_user))
    if verify_password(data.new_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Your new password must be different from the temporary password.")

    current_user.password_hash = hash_password(data.new_password)
    current_user.must_change_password = False
    current_user.temp_password_expires_at = None
    access_token = _start_new_session(current_user, response, db)

    try:
        from app.notifications.service import notify_user
        notify_user(
            db, current_user.id,
            "Your password was set successfully. Welcome aboard!",
            category="security", type="success", link="/dashboard/settings/security",
            entity_type="user", entity_id=str(current_user.id),
        )
        db.commit()
    except Exception as e:
        logger.error(f"[Auth] Notification failed for first-login password change: {e}")
    return {"access_token": access_token, "token_type": "bearer", "message": "Password updated successfully"}


@router.put("/security/password")
def change_password(
    data: UserPasswordUpdate,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Change the authenticated user's password.
    Verifies the current password, enforces the password policy, and signs out
    every other session (this browser keeps working via a rotated refresh cookie).
    """
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect current password")
    validate_password_or_raise(data.new_password, email=current_user.email, names=_user_names(current_user))
    if data.new_password == data.current_password:
        raise HTTPException(status_code=400, detail="New password must be different from your current password.")

    current_user.password_hash = hash_password(data.new_password)
    _start_new_session(current_user, response, db)

    # ── Notify user ────────────────────────────────────────────────
    try:
        from app.notifications.service import notify_user
        notify_user(
            db, current_user.id,
            "Your password was changed successfully",
            category="security", type="success", link="/dashboard/settings/security",
            entity_type="user", entity_id=str(current_user.id),
        )
        db.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"[Auth] Notification failed for password change: {e}")
    return {"message": "Password updated successfully"}


@router.get("/security/2fa/setup")
def setup_two_factor(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate (or retrieve existing) TOTP secret for 2FA enrollment.
    Returns the secret key and a base64-encoded QR code PNG for the
    authenticator app to scan.
    """
    import pyotp

    # Once 2FA is on, the secret must never be handed out again — otherwise
    # anyone holding a session could clone the user's authenticator.
    if current_user.two_factor_enabled:
        raise HTTPException(status_code=400, detail="Two-factor authentication is already enabled")

    if not current_user.totp_secret:
        current_user.totp_secret = pyotp.random_base32()
        db.commit()

    uri = pyotp.totp.TOTP(current_user.totp_secret).provisioning_uri(name=current_user.email, issuer_name="HRMS")
    
    # Generate local QR code
    qr = qrcode.make(uri)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    return {
        "secret": current_user.totp_secret,
        "qr_code_url": f"data:image/png;base64,{qr_base64}"
    }


@router.post("/security/2fa/verify", response_model=UserResponse)
def verify_and_enable_two_factor(
    data: TwoFactorCodeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Confirm that the user's authenticator app is correctly configured
    by verifying a live TOTP code, then enable 2FA on the account.
    """
    code = (data.code or "").replace(" ", "")
    if not CODE_RE.match(code):
        raise HTTPException(status_code=400, detail=f"Enter the {OTP_LENGTH}-digit code from your authenticator app")
    import pyotp
    if not current_user.totp_secret or not pyotp.TOTP(current_user.totp_secret).verify(code):
        raise HTTPException(status_code=400, detail="Invalid verification code")

    current_user.two_factor_enabled = True
    db.commit()
    db.refresh(current_user)

    # ── Notify user ────────────────────────────────────────────────
    try:
        from app.notifications.service import notify_user
        notify_user(
            db, current_user.id,
            "Two-factor authentication was enabled",
            category="security", type="success", link="/dashboard/settings/security",
            entity_type="user", entity_id=str(current_user.id),
        )
        db.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"[Auth] Notification failed for 2FA enable: {e}")
    return current_user


@router.delete("/security/2fa", response_model=UserResponse)
def disable_two_factor(
    data: TwoFactorDisableRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Disable two-factor authentication for the current user.
    Requires the account password, so a hijacked or unattended session can't
    silently strip the second factor.
    Clears the stored TOTP secret so 2FA cannot be used until re-enrolled.
    """
    if not data.password or not verify_password(data.password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect password")
    current_user.two_factor_enabled = False
    current_user.totp_secret = None
    db.commit()
    db.refresh(current_user)

    # ── Notify user ────────────────────────────────────────────────
    try:
        from app.notifications.service import notify_user
        notify_user(
            db, current_user.id,
            "Two-factor authentication was disabled",
            category="security", type="warning", link="/dashboard/settings/security",
            entity_type="user", entity_id=str(current_user.id),
        )
        db.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"[Auth] Notification failed for 2FA disable: {e}")
    return current_user


@router.put("/notifications", response_model=UserResponse)
def update_notifications(
    data: UserNotificationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update the current user's notification preferences.
    Stored directly on the user record for use by the notification system.
    """
    current_user.notification_preferences = data.model_dump()["notification_preferences"]
    # None is a real choice here ("never auto-delete"), not a missing value.
    current_user.notification_retention_days = data.notification_retention_days

    db.commit()
    db.refresh(current_user)
    return current_user
