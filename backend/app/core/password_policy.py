"""
core/password_policy.py — Single source of truth for password strength rules.

Every endpoint that sets a password (first-login change, settings change,
forgot-password reset) validates through `password_policy_errors` so the rules
can never drift between flows. The frontend mirrors these rules in
`frontend/lib/passwordPolicy.ts` for live feedback — keep the two in sync.
"""
import re
from typing import Iterable, List, Optional

MIN_LENGTH = 8
MAX_LENGTH = 128
# bcrypt only hashes the first 72 BYTES; anything longer is silently ignored
# (or rejected outright by bcrypt>=4.1), so cap the encoded length.
MAX_BYTES = 72
SPECIAL_CHARS = r"""!@#$%^&*()_+-=[]{};':"\|,.<>/?`~"""

# Passwords that satisfy the character-class rules yet are the first things an
# attacker tries. Compared case-insensitively.
_COMMON_PASSWORDS = {
    "password1!", "password@1", "password@123", "p@ssw0rd", "p@ssword1",
    "welcome@123", "welcome1!", "qwerty@123", "admin@123", "abc@1234",
    "changeme1!", "letmein1!", "iloveyou1!", "passw0rd!", "test@1234",
}


def password_policy_errors(
    password: Optional[str],
    *,
    email: Optional[str] = None,
    names: Iterable[Optional[str]] = (),
) -> List[str]:
    """Return a list of human-readable rule violations (empty list = valid)."""
    if not password:
        return ["Password is required."]

    errors: List[str] = []
    if len(password) < MIN_LENGTH:
        errors.append(f"Password must be at least {MIN_LENGTH} characters long.")
    if len(password) > MAX_LENGTH or len(password.encode("utf-8")) > MAX_BYTES:
        errors.append(f"Password must be at most {MAX_BYTES} characters long.")
    if password != password.strip():
        errors.append("Password must not start or end with a space.")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        errors.append("Password must contain at least one lowercase letter.")
    if not re.search(r"\d", password):
        errors.append("Password must contain at least one number.")
    if not any(ch in SPECIAL_CHARS for ch in password):
        errors.append("Password must contain at least one special character.")

    lowered = password.lower()
    if lowered in _COMMON_PASSWORDS:
        errors.append("This password is too common. Choose something harder to guess.")

    personal = []
    if email:
        personal.append(email.split("@")[0])
    personal.extend(n for n in names if n)
    for part in personal:
        part = part.strip().lower()
        if len(part) >= 3 and part in lowered:
            errors.append("Password must not contain your name or email address.")
            break

    return errors


def validate_password_or_raise(password: Optional[str], *, email=None, names=()) -> None:
    """Raise HTTP 400 with every violation joined, if the password is weak."""
    from fastapi import HTTPException, status

    errors = password_policy_errors(password, email=email, names=names)
    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=" ".join(errors))
