from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import jwt, JWTError
from typing import List, Optional

from app.database.database import get_db
from app.auth.models import User
from app.core.jwt import SECRET_KEY, ALGORITHM

security = HTTPBearer(auto_error=False)

# Returned as the 403 detail while a first-login password change is pending;
# the frontend matches on this exact string to redirect to /change-password.
PASSWORD_CHANGE_REQUIRED = "PASSWORD_CHANGE_REQUIRED"
PASSWORD_CHANGE_ALLOWED_PATHS = {
    "/auth/me",
    "/auth/logout",
    "/auth/first-login/password",
}


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """
    Shared dependency: decodes JWT, returns the authenticated User object
    with roles and permissions eager-loaded to prevent lazy-load failures.
    Raises 401 if token is invalid or user not found.
    """
    from sqlalchemy.orm import joinedload
    token = credentials.credentials if credentials else request.query_params.get("token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        
        # Block temporary 2FA tokens from accessing regular endpoints
        if payload.get("type") == "2fa":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Temporary 2FA token cannot access this endpoint"
            )
        # Refresh tokens live 7 days and are only meant for /auth/refresh —
        # never accept one as a bearer access token.
        if payload.get("type") == "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # Eager-load roles → permissions so get_user_permissions never lazy-loads
    # on a potentially expired or closed session scope.
    from app.roles.models import Role
    user = (
        db.query(User)
        .options(joinedload(User.roles).joinedload(Role.permissions))
        .filter(User.id == int(user_id))
        .first()
    )
    if not user or user.is_active is False:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # First login with an emailed temporary password: nothing but the password
    # change (plus reading who you are and logging out) is allowed until the
    # user picks their own password.
    if getattr(user, "must_change_password", False) and request.url.path not in PASSWORD_CHANGE_ALLOWED_PATHS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=PASSWORD_CHANGE_REQUIRED)
    return user


def get_user_permissions(user: User, db: Session) -> List[str]:
    """
    Resolves permissions from the user's roles.
    Super Admins (is_superadmin=True) automatically get ALL permissions.

    Roles are assumed to be eager-loaded on the user object (done in
    get_current_user).  The role_id scalar column acts as a fallback for
    legacy rows that were never inserted into the user_roles join table.
    """
    # Super Admin Bypass — all permissions except employee self-service ones
    if getattr(user, "is_superadmin", False):
        from app.roles.models import Permission
        from app.roles.seed import SUPER_ADMIN_EXCLUDES
        all_perms = db.query(Permission).all()
        return [p.permission_name for p in all_perms
                if p.permission_name not in SUPER_ADMIN_EXCLUDES]

    from app.roles.models import Role as _Role
    from sqlalchemy.orm import joinedload as _jl

    permissions: set[str] = set()

    # Primary path — many-to-many user_roles join table (already eager-loaded)
    if user.roles:
        for role in user.roles:
            # permissions may be lazy if the user object came from a path that
            # didn't joinedload them; re-fetch with eager load to be safe.
            if role.permissions:
                for perm in role.permissions:
                    permissions.add(perm.permission_name)
            else:
                # Re-query this specific role with permissions eager-loaded
                r = db.query(_Role).options(_jl(_Role.permissions)).filter(_Role.id == role.id).first()
                if r:
                    for perm in r.permissions:
                        permissions.add(perm.permission_name)

    # Fallback — scalar role_id column (handles legacy / migration gaps)
    if not permissions and user.role_id:
        role = (
            db.query(_Role)
            .options(_jl(_Role.permissions))
            .filter(_Role.id == user.role_id)
            .first()
        )
        if role:
            for perm in role.permissions:
                permissions.add(perm.permission_name)

    return list(permissions)


def require_permission(permission: str):
    """
    Dependency factory that checks a single permission.
    Usage:  Depends(require_permission("messaging.send"))
    """
    def _check(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        perms = get_user_permissions(current_user, db)
        if permission not in perms:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission required: {permission}"
            )
        return current_user
    return _check


def require_any_permission(*permissions: str):
    """
    Dependency factory that passes if the user holds AT LEAST ONE
    of the given permissions.
    Usage:  Depends(require_any_permission("recruitment:view", "recruitment:manage"))
    """
    def _check(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        perms = get_user_permissions(current_user, db)
        if not any(p in perms for p in permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission required: one of {', '.join(permissions)}"
            )
        return current_user
    return _check
