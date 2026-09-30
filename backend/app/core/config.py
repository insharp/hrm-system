"""
Centralized application configuration.
All environment variable access should go through this module.
"""
import os
from dotenv import load_dotenv

load_dotenv(override=True)

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:password@localhost:5432/hrm_db"
)

# ── AI Service (internal) ────────────────────────────────────────────────────
# The AI screening service runs as a separate process on port 8001.
AI_SERVICE_URL: str = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:8001")

# ── Multi-Provider AI Configuration ──────────────────────────────────────────
# Set these three vars in backend/.env to switch between AI providers.
#
#   AI_PROVIDER = gemini | openai | claude
#   AI_MODEL    = any model name supported by the chosen provider
#   AI_API_KEY  = API key for the chosen provider
#
# Examples:
#   AI_PROVIDER=gemini   AI_MODEL=gemini-2.5-flash
#   AI_PROVIDER=openai   AI_MODEL=gpt-4o-mini
#   AI_PROVIDER=claude   AI_MODEL=claude-3-5-haiku-20241022

AI_PROVIDER: str = os.getenv("AI_PROVIDER", "gemini")
AI_MODEL: str    = os.getenv("AI_MODEL",    "gemini-2.5-flash")
AI_API_KEY: str  = os.getenv("AI_API_KEY",  "")

# Backward-compat alias: old deployments may only have GEMINI_API_KEY set.
# If AI_API_KEY is blank but GEMINI_API_KEY exists, use that.
if not AI_API_KEY:
    AI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Expose the old name so any code still importing it won't break.
GEMINI_API_KEY: str = AI_API_KEY

# ── Google reCAPTCHA v2 ───────────────────────────────────────────────────────
# Set RECAPTCHA_SECRET_KEY in your .env file.
# Leave empty to disable verification in local dev (non-empty = always verified).
RECAPTCHA_SECRET_KEY: str = os.getenv("RECAPTCHA_SECRET_KEY", "")

# ── Email (SMTP) ──────────────────────────────────────────────────────────────
MAIL_USERNAME: str = os.getenv("MAIL_USERNAME", "")
MAIL_PASSWORD: str = os.getenv("MAIL_PASSWORD", "")
MAIL_FROM: str = os.getenv("MAIL_FROM", "noreply@hrm.com")
MAIL_PORT: int = int(os.getenv("MAIL_PORT", "587"))
MAIL_SERVER: str = os.getenv("MAIL_SERVER", "smtp.gmail.com")

# ── CORS ──────────────────────────────────────────────────────────────────────
CORS_ORIGINS: list[str] = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000"
).split(",")


def _as_bool(value: str, default: bool = False) -> bool:
    """Parse a truthy/falsey environment string ("1", "true", "yes", "on")."""
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# ── Auth cookie security ──────────────────────────────────────────────────────
# The refresh-token cookie must be sent over HTTPS only in production. In local
# dev (plain HTTP) `secure=True` would stop the browser from ever storing the
# cookie, so this defaults to False and MUST be set to True in production.
#
#   COOKIE_SECURE=true      → only sent over HTTPS (production)
#   COOKIE_SAMESITE=lax     → lax | strict | none  (use "none" for cross-site,
#                             which also requires COOKIE_SECURE=true)
COOKIE_SECURE: bool = _as_bool(os.getenv("COOKIE_SECURE"), default=False)
COOKIE_SAMESITE: str = os.getenv("COOKIE_SAMESITE", "lax").strip().lower()

# ── Rate limiting (brute-force protection) ────────────────────────────────────
# Simple in-process limiter for sensitive auth endpoints. Set RATE_LIMIT_ENABLED
# to false to disable entirely (e.g. for load tests).
RATE_LIMIT_ENABLED: bool = _as_bool(os.getenv("RATE_LIMIT_ENABLED"), default=True)
# "max attempts" per "window seconds", per client IP, per endpoint scope.
LOGIN_RATE_LIMIT: int = int(os.getenv("LOGIN_RATE_LIMIT", "5"))
LOGIN_RATE_WINDOW_SECONDS: int = int(os.getenv("LOGIN_RATE_WINDOW_SECONDS", "60"))
OTP_RATE_LIMIT: int = int(os.getenv("OTP_RATE_LIMIT", "5"))
OTP_RATE_WINDOW_SECONDS: int = int(os.getenv("OTP_RATE_WINDOW_SECONDS", "300"))
# Only honour X-Forwarded-For when the API sits behind a reverse proxy that SETS
# it (nginx, a load balancer). Otherwise any client can send a fake header per
# request and dodge the per-IP limits. Behind a proxy, set this to true — or
# every user shares the proxy's IP and one person's typos lock out everyone.
TRUST_PROXY_HEADERS: bool = _as_bool(os.getenv("TRUST_PROXY_HEADERS"), default=False)

# ── First-login temporary passwords ───────────────────────────────────────────
# How long an emailed temporary password stays usable before HR has to resend
# login details (or the employee uses Forgot Password).
TEMP_PASSWORD_EXPIRE_DAYS: int = max(1, int(os.getenv("TEMP_PASSWORD_EXPIRE_DAYS", "7")))

# ── File Storage ──────────────────────────────────────────────────────────────
UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads/cvs")

# ── Storage Backend ───────────────────────────────────────────────────────────
# Set STORAGE_BACKEND=local  to use local filesystem (default, no AWS needed).
# Set STORAGE_BACKEND=s3     to use AWS S3 (or MinIO for local S3 testing).
#
# S3 / MinIO configuration (only required when STORAGE_BACKEND=s3):
#   AWS_S3_BUCKET         — name of the S3 bucket (e.g. "hrm-uploads")
#   AWS_ACCESS_KEY_ID     — AWS access key (or MinIO access key)
#   AWS_SECRET_ACCESS_KEY — AWS secret key (or MinIO secret key)
#   AWS_REGION            — AWS region (e.g. "us-east-1"). For MinIO, any value.
#   AWS_S3_ENDPOINT_URL   — Override endpoint. Leave empty for real AWS.
#                           For MinIO: "http://localhost:9000"
#
STORAGE_BACKEND: str = os.getenv("STORAGE_BACKEND", "local")
AWS_S3_BUCKET: str = os.getenv("AWS_S3_BUCKET", "")
AWS_ACCESS_KEY_ID: str = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")
AWS_S3_ENDPOINT_URL: str = os.getenv("AWS_S3_ENDPOINT_URL", "")  # blank = real AWS

# ── IMAP (Document email poller) ──────────────────────────────────────────────
IMAP_SERVER: str = os.getenv("IMAP_SERVER", "imap.gmail.com")
IMAP_USER: str = os.getenv("IMAP_USER", os.getenv("MAIL_USERNAME", ""))
IMAP_PASSWORD: str = os.getenv("IMAP_PASSWORD", os.getenv("MAIL_PASSWORD", ""))
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))

# ── Document storage ──────────────────────────────────────────────────────────
UPLOAD_DIR_DOCUMENTS: str = os.getenv("UPLOAD_DIR_DOCUMENTS", "uploads/documents")
UPLOAD_DIR_TEMPLATES: str = os.getenv("UPLOAD_DIR_TEMPLATES", "uploads/templates")
UPLOAD_DIR_GENERATED: str = os.getenv("UPLOAD_DIR_GENERATED", "uploads/generated_documents")
MAX_FILE_SIZE_BYTES: int = int(os.getenv("MAX_FILE_SIZE_BYTES", str(10 * 1024 * 1024)))
# External document requests are low-urgency (HR actions them over hours), so a
# few minutes between polls is plenty and avoids hammering Gmail's IMAP login limits.
EMAIL_POLL_INTERVAL_SECONDS: int = int(os.getenv("EMAIL_POLL_INTERVAL_SECONDS", "300"))


class _Settings:
    """Compatibility shim so document services can call get_settings()."""
    imap_server: str = IMAP_SERVER
    imap_user: str = IMAP_USER
    imap_password: str = IMAP_PASSWORD
    smtp_server: str = MAIL_SERVER
    smtp_port: int = SMTP_PORT
    upload_dir_documents: str = UPLOAD_DIR_DOCUMENTS
    upload_dir_templates: str = UPLOAD_DIR_TEMPLATES
    upload_dir_generated: str = UPLOAD_DIR_GENERATED
    max_file_size_bytes: int = MAX_FILE_SIZE_BYTES
    email_poll_interval_seconds: int = EMAIL_POLL_INTERVAL_SECONDS

    def __init__(self):
        self.imap_server = IMAP_SERVER
        self.imap_user = IMAP_USER
        self.imap_password = IMAP_PASSWORD
        self.smtp_server = MAIL_SERVER
        self.smtp_port = SMTP_PORT
        self.upload_dir_documents = UPLOAD_DIR_DOCUMENTS
        self.upload_dir_templates = UPLOAD_DIR_TEMPLATES
        self.upload_dir_generated = UPLOAD_DIR_GENERATED
        self.max_file_size_bytes = MAX_FILE_SIZE_BYTES
        self.email_poll_interval_seconds = EMAIL_POLL_INTERVAL_SECONDS


_settings_instance = _Settings()

def get_settings() -> _Settings:
    return _settings_instance
