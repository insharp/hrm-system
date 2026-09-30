from sqlalchemy import Column, String, Integer, Boolean, DateTime, func, Table, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database.base import Base
from app.database.soft_delete import SoftDeleteMixin
from app.roles.models import user_roles  # noqa: F401 — ensures table is registered


class User(Base, SoftDeleteMixin):
    __tablename__ = "users"
    # Uniqueness is enforced by PARTIAL unique indexes scoped to live rows
    # (WHERE is_deleted = false), so a soft-deleted account no longer blocks a
    # new employee from reusing the same email / username / employee_id.
    __table_args__ = (
        Index("ix_users_email_active", "email", unique=True, postgresql_where=text("is_deleted = false")),
        Index("ix_users_username_active", "username", unique=True, postgresql_where=text("is_deleted = false")),
        Index("ix_users_employee_id_active", "employee_id", unique=True, postgresql_where=text("is_deleted = false")),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False)
    username = Column(String(100), nullable=True)
    password_hash = Column("hashed_password", String(255), nullable=False)  # DB col: hashed_password
    is_active = Column(Boolean, default=True)
    is_superadmin = Column(Boolean, default=False)
    # Set when an account is created with an emailed temporary password. While
    # true, the API only allows the first-login password change (see
    # core/deps.get_current_user), so whoever can read the welcome email can't
    # use the account.
    must_change_password = Column(Boolean, default=False, server_default=text("false"), nullable=False)
    # When the emailed temporary password stops working (naive UTC). NULL = no
    # temporary password outstanding.
    temp_password_expires_at = Column(DateTime, nullable=True)
    # is_deleted is provided by SoftDeleteMixin
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    refresh_token = Column(String, nullable=True)

    # Role & Position (string kept for backward compat; role_id is the authoritative FK)
    role = Column(String, default="employee")
    position = Column(String, nullable=True)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=True)

    # Profile Fields
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    employee_id = Column(String, nullable=True)  # uniqueness via ix_users_employee_id_active
    department = Column(String, nullable=True)
    phone_number = Column(String, nullable=True)
    address = Column(String, nullable=True)
    date_of_birth = Column(String, nullable=True)
    emergency_contact_number = Column(String, nullable=True)
    profile_image_url = Column(String, nullable=True)

    # 2FA
    two_factor_enabled = Column(Boolean, default=False)
    totp_secret = Column(String, nullable=True)

    # Notification preferences
    notification_preferences = Column(JSONB, nullable=True)
    # How long to keep notifications before permanent deletion, in days.
    # NULL = keep forever (never auto-delete). Purged items are unrecoverable.
    notification_retention_days = Column(Integer, nullable=True)

    # Relationships (RBAC via join table — from dev)
    roles = relationship("Role", secondary=user_roles, back_populates="users")
    employee = relationship("Employee", back_populates="user", uselist=False)

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False) # 'LOGIN_SUCCESS', 'LOGIN_FAILED', 'LOGOUT'
    ip_address = Column(String, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User")

class OTPRecord(Base):
    __tablename__ = "otp_records"
    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False, index=True)
    otp = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    verified = Column(Boolean, default=False)
    attempts = Column(Integer, default=0, server_default=text("0"), nullable=False)  # wrong guesses so far
    created_at = Column(DateTime, default=datetime.utcnow)
