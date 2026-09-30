import re
from datetime import date
from pydantic import BaseModel, EmailStr, Field, field_serializer, field_validator
from typing import Optional, List, Literal

# Same pattern the admin "Add Employee" form enforces, so a number accepted there
# is accepted here too: optional +, then 7-15 digits / spaces / dashes / parens.
PHONE_RE = re.compile(r"^\+?[0-9\s\-()]{7,15}$")
# Letters (any script) separated by single spaces, dots, apostrophes or hyphens.
NAME_RE = re.compile(r"^[^\W\d_]+(?:[ .'\-]+[^\W\d_]+)*\.?$")
BANK_ACCOUNT_RE = re.compile(r"^[0-9 \-]{4,50}$")


# ── Dev schemas (RBAC) ────────────────────────────────────────────────────────

class UserMe(BaseModel):
    id: int
    username: str
    email: str
    roles: List[str]
    permissions: List[str]
    features: dict = {}  # For future feature flags

    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    is_active: bool

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    user_id: Optional[int] = None


class UserPermissionsOut(BaseModel):
    user_id: int
    permissions: List[str]


# ── Auth dashboard schemas (Sanduni) ──────────────────────────────────────────

class UserResponse(BaseModel):
    id: int
    email: str
    username: Optional[str] = None
    is_active: bool
    role: str = "employee"
    role_id: Optional[int] = None
    position: Optional[str] = None
    permissions: List[str] = []
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    employee_id: Optional[str] = None
    department: Optional[str] = None
    phone_number: Optional[str] = None
    address: Optional[str] = None
    date_of_birth: Optional[str] = None
    emergency_contact_number: Optional[str] = None
    profile_image_url: Optional[str] = None
    two_factor_enabled: Optional[bool] = False
    must_change_password: Optional[bool] = False
    notification_preferences: Optional[dict] = None
    notification_retention_days: Optional[int] = None

    # Fields sourced from Employee model
    designation: Optional[str] = None
    joined_date: Optional[str] = None
    status: Optional[str] = None
    gender: Optional[str] = None
    marital_status: Optional[str] = None
    nationality: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_relation: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account_no: Optional[str] = None
    bank_branch: Optional[str] = None
    skills: Optional[str] = None
    qualifications: Optional[str] = None
    designation_history: Optional[List[dict]] = None

    model_config = {"from_attributes": True}

    @field_serializer("profile_image_url")
    def _serialize_profile_image_url(self, value: Optional[str]) -> Optional[str]:
        """Mint a fresh public URL from the stored key on every response.

        Ensures S3 pre-signed URLs (which expire after 1h) are never served
        stale, while leaving local "/uploads/..." paths unchanged.
        """
        from app.core.storage_service import resolve_public_url
        return resolve_public_url(value)


class UserProfileUpdate(BaseModel):
    # max_length values mirror the users/employees column limits (see
    # employees/schemas.py) so over-long input is a clean 422, not a DB 500.
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    phone_number: Optional[str] = Field(default=None, max_length=20)
    address: Optional[str] = Field(default=None, max_length=500)
    date_of_birth: Optional[str] = None
    emergency_contact_number: Optional[str] = Field(default=None, max_length=20)
    gender: Optional[str] = Field(default=None, max_length=20)
    marital_status: Optional[str] = Field(default=None, max_length=20)
    nationality: Optional[str] = Field(default=None, max_length=100)
    emergency_contact_name: Optional[str] = Field(default=None, max_length=100)
    emergency_contact_relation: Optional[str] = Field(default=None, max_length=50)
    bank_name: Optional[str] = Field(default=None, max_length=100)
    bank_account_no: Optional[str] = Field(default=None, max_length=50)
    bank_branch: Optional[str] = Field(default=None, max_length=100)
    skills: Optional[str] = Field(default=None, max_length=2000)
    qualifications: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("*", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("first_name", "last_name")
    @classmethod
    def _name(cls, v, info):
        label = info.field_name.replace("_", " ").capitalize()
        # The profile form always sends names, so blank means "erase my name".
        if v is not None and not v:
            raise ValueError(f"{label} cannot be empty")
        if v and not NAME_RE.match(v):
            raise ValueError(f"{label} may only contain letters, spaces, apostrophes, dots and hyphens")
        return v

    @field_validator("emergency_contact_name")
    @classmethod
    def _contact_name(cls, v):
        if v and not NAME_RE.match(v):
            raise ValueError("Emergency contact name may only contain letters, spaces, apostrophes, dots and hyphens")
        return v

    @field_validator("phone_number", "emergency_contact_number")
    @classmethod
    def _phone(cls, v):
        if v and not PHONE_RE.match(v):
            raise ValueError("Enter a valid phone number (7-15 digits, optional leading +)")
        return v

    @field_validator("bank_account_no")
    @classmethod
    def _bank_account(cls, v):
        if v and not BANK_ACCOUNT_RE.match(v):
            raise ValueError("Bank account number may only contain digits, spaces and dashes")
        return v

    @field_validator("date_of_birth")
    @classmethod
    def _dob(cls, v):
        # Stored as a string on users but as a DATE on employees, so anything
        # that isn't a real YYYY-MM-DD date must be rejected here.
        if v in (None, "", "None", "null"):
            return None
        try:
            d = date.fromisoformat(v)
        except ValueError:
            raise ValueError("Date of birth must be a valid date (YYYY-MM-DD)")
        if d > date.today():
            raise ValueError("Date of birth cannot be in the future")
        if d.year < 1900:
            raise ValueError("Date of birth is not realistic")
        return d.isoformat()


class UserPasswordUpdate(BaseModel):
    current_password: str = Field(..., max_length=256)
    new_password: str = Field(..., max_length=256)


class FirstLoginPasswordChange(BaseModel):
    """First-login change. No current password: the user just proved the
    temporary one at login, and the session can do nothing else until this."""
    new_password: str = Field(..., max_length=256)
    confirm_password: str = Field(..., max_length=256)


# Password-reset / 2FA bodies were untyped dicts. Fields stay Optional so the
# handlers keep returning their friendly 400 "X required" messages rather than
# a raw 422, but types and sizes are now bounded.
class SendOtpRequest(BaseModel):
    email: Optional[str] = Field(default=None, max_length=255)


class VerifyOtpRequest(BaseModel):
    email: Optional[str] = Field(default=None, max_length=255)
    otp: Optional[str] = Field(default=None, max_length=20)


class ResetPasswordRequest(BaseModel):
    email: Optional[str] = Field(default=None, max_length=255)
    password: Optional[str] = Field(default=None, max_length=256)


class TwoFactorLoginRequest(BaseModel):
    temp_token: Optional[str] = Field(default=None, max_length=4096)
    code: Optional[str] = Field(default=None, max_length=20)


class TwoFactorCodeRequest(BaseModel):
    code: Optional[str] = Field(default=None, max_length=20)


class TwoFactorDisableRequest(BaseModel):
    password: Optional[str] = Field(default=None, max_length=256)


class ChannelPreference(BaseModel):
    email: bool = True
    inApp: bool = True


class UserNotificationUpdate(BaseModel):
    # category key -> {email, inApp}. Typed so arbitrary JSON can't be stored on
    # the user row; keys are bounded rather than enumerated so a new
    # notification category doesn't need a schema change.
    notification_preferences: dict[str, ChannelPreference] = Field(..., max_length=50)
    # Days to keep notifications before permanent deletion.
    # None = never auto-delete. Restricted to the windows offered in the UI.
    notification_retention_days: Optional[Literal[30, 90, 180, 365]] = None


class LoginRequest(BaseModel):
    """Accepts either email or username in the `email` field, or the dedicated `username` field."""
    email: Optional[str] = Field(default=None, max_length=255)
    username: Optional[str] = Field(default=None, max_length=255)
    password: str = Field(..., max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
