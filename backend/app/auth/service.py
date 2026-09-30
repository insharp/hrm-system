"""
auth/service.py — Authentication logic only.
Role/Permission management has moved to roles/service.py.
"""
from typing import Optional, List
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.auth.models import User
from app.core.security import verify_password
from app.core.jwt import create_access_token, create_refresh_token

class TemporaryPasswordExpired(Exception):
    """Correct temporary password, but past its expiry — no session is issued."""


TEMP_PASSWORD_EXPIRED_MESSAGE = (
    "Your temporary password has expired. Ask HR to resend your login details, "
    "or use Forgot Password to set a new password."
)


def temp_password_expired(user: User) -> bool:
    expires = getattr(user, "temp_password_expires_at", None)
    return bool(user.must_change_password and isinstance(expires, datetime) and datetime.utcnow() > expires)


# ── User lookup helpers ───────────────────────────────────────────────────────

def get_user_by_username(db: Session, username: str) -> Optional[User]:
    """
    Look up an active (non-deleted) user by exact username.
    Returns None if the user does not exist or has been soft-deleted.
    """
    return db.query(User).filter(
        User.username == username,
        (User.is_deleted == False) | (User.is_deleted == None)
    ).first()


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """
    Look up an active (non-deleted) user by email address (case-insensitive).
    Returns None if the user does not exist or has been soft-deleted.
    """
    return db.query(User).filter(
        User.email.ilike(email),
        (User.is_deleted == False) | (User.is_deleted == None)
    ).first()


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    """
    Look up an active (non-deleted) user by primary key.
    Returns None if the user does not exist or has been soft-deleted.
    """
    return db.query(User).filter(
        User.id == user_id,
        (User.is_deleted == False) | (User.is_deleted == None)
    ).first()


# ── Authentication ────────────────────────────────────────────────────────────

def authenticate_user(db: Session, identifier: str, password: str) -> Optional[dict]:
    """
    Authenticate via email OR username (case-insensitive).
    Returns a token dict on success, None on failure.
    """
    from sqlalchemy.orm import joinedload
    from app.roles.models import Role

    identifier = identifier.strip()

    user = (
        db.query(User)
        .options(joinedload(User.roles).joinedload(Role.permissions))
        .filter(
            ((User.email.ilike(identifier)) | (User.username.ilike(identifier))),
            ((User.is_deleted == False) | (User.is_deleted == None))
        )
        .first()
    )

    if not user:
        return None

    if not verify_password(password, user.password_hash):
        return None

    # Reject deactivated accounts. Return the SAME generic failure as a wrong
    # password (caller raises 401 "Invalid credentials") so we never disclose
    # that the account merely exists-but-is-disabled (prevents enumeration).
    if user.is_active is False:
        return None

    # Checked only AFTER the password matched, so it can't be used to probe
    # which accounts exist.
    if temp_password_expired(user):
        raise TemporaryPasswordExpired()

    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    # Persist refresh token
    user.refresh_token = refresh_token
    db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": user,
    }


# ── Permissions ───────────────────────────────────────────────────────────────

def get_user_permissions(db: Session, user_id: int) -> List[str]:
    """Return a flat list of permission_name strings for a user (across all roles)."""
    from sqlalchemy.orm import joinedload
    from app.roles.models import Role

    user = (
        db.query(User)
        .options(joinedload(User.roles).joinedload(Role.permissions))
        .filter(
            User.id == user_id,
            (User.is_deleted == False) | (User.is_deleted == None)
        )
        .first()
    )
    if not user:
        return []

    # Super Admin Bypass — all permissions except employee self-service ones
    if getattr(user, "is_superadmin", False):
        from app.roles.models import Permission
        from app.roles.seed import SUPER_ADMIN_EXCLUDES
        all_perms = db.query(Permission).all()
        return [p.permission_name for p in all_perms
                if p.permission_name not in SUPER_ADMIN_EXCLUDES]

    perms: set[str] = set()
    for role in user.roles:
        for perm in role.permissions:
            perms.add(perm.permission_name)

    # Fallback — scalar role_id column
    if not perms and user.role_id:
        role = (
            db.query(Role)
            .options(joinedload(Role.permissions))
            .filter(Role.id == user.role_id)
            .first()
        )
        if role:
            for perm in role.permissions:
                perms.add(perm.permission_name)

    return list(perms)
