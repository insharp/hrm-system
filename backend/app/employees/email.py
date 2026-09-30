import smtplib
import os
import html
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Explicitly load .env from the backend root
from pathlib import Path
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

SMTP_HOST = os.getenv("MAIL_SERVER")
port_val = os.getenv("MAIL_PORT")
SMTP_PORT = int(port_val) if port_val and port_val.isdigit() else 587
SMTP_USER = os.getenv("MAIL_USERNAME")
SMTP_PASSWORD = (os.getenv("MAIL_PASSWORD") or "").replace(" ", "")  # strip spaces from app password
SMTP_FROM = os.getenv("MAIL_FROM")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


def send_welcome_email(email: str, full_name: str, temp_password: str, expires_days: int = None):
    """
    Sends a welcome email with a temporary password and a link to the login page,
    where the user is forced to replace it on first login.
    If email sending fails, it logs the error but doesn't raise an exception.
    """
    # Only print the temporary password to the logs as a dev convenience — in
    # production logs are shipped/retained and must never hold credentials.
    log_password = os.getenv("ENVIRONMENT", "development").strip().lower() != "production"
    fallback_password = temp_password if log_password else "<hidden in production — the employee can use Forgot Password to set one>"
    # Re-load .env fresh every call so credential changes take effect without restart
    load_dotenv(dotenv_path=env_path, override=True)

    host = os.getenv("MAIL_SERVER")
    port_str = os.getenv("MAIL_PORT", "587")
    port = int(port_str) if port_str and port_str.isdigit() else 587
    user = os.getenv("MAIL_USERNAME")
    password = (os.getenv("MAIL_PASSWORD") or "").replace(" ", "")
    from_addr = os.getenv("MAIL_FROM")
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")

    if not all([host, port, user, password, from_addr]):
        missing = [k for k, v in {"MAIL_SERVER": host, "MAIL_USERNAME": user, "MAIL_PASSWORD": password, "MAIL_FROM": from_addr}.items() if not v]
        logger.error(f"SMTP configuration is incomplete. Missing: {', '.join(missing)}")
        logger.warning(f"[FALLBACK] Welcome email NOT sent for {email} ({full_name}). Temporary password (share manually): {fallback_password}")
        return

    subject = "Welcome to the HRM System!"
    login_url = f"{frontend_url}/login"
    safe_name = html.escape(full_name or "")
    safe_email = html.escape(email)
    safe_password = html.escape(temp_password)
    expiry_note = f" and expires after {int(expires_days)} days" if expires_days else ""

    html_content = f"""
    <html>
        <body>
            <h3>Welcome, {safe_name}!</h3>
            <p>Your account has been created successfully. Below are your login credentials:</p>
            <ul>
                <li><strong>Email:</strong> {safe_email}</li>
                <li><strong>Temporary Password:</strong> {safe_password}</li>
            </ul>
            <p>Please note that you <strong>must</strong> choose a new password the first time you log in. The temporary password stops working once you do{expiry_note}, so please do this as soon as possible and do not share this email.</p>
            <p>
                <a href="{login_url}" style="padding: 10px 20px; background-color: #EE7F22; color: white; text-decoration: none; border-radius: 5px; font-weight: bold;">
                    Log In &amp; Set Password
                </a>
            </p>
            <p>If the button above does not work, copy and paste this link into your browser:<br>
            {login_url}</p>
        </body>
    </html>
    """

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = email
    msg["Subject"] = subject
    msg.attach(MIMEText(html_content, "html"))

    try:
        logger.info(f"SMTP attempt → host={host} port={port} user={user}")
        if port == 465:
            # Direct SSL (port 465)
            with smtplib.SMTP_SSL(host, port) as server:
                server.login(user, password)
                server.send_message(msg)
        else:
            # STARTTLS (port 587 or 25)
            with smtplib.SMTP(host, port) as server:
                server.starttls()
                server.login(user, password)
                server.send_message(msg)
        logger.info(f"Welcome email sent successfully to {email}")
    except Exception as e:
        logger.error(f"Failed to send welcome email to {email}: {str(e)}")
        logger.warning(
            f"[FALLBACK] Email delivery failed for {email} ({full_name}). "
            f"Temporary password (share manually): {fallback_password}"
        )
