"""
Email service with pluggable provider abstraction.

Providers:
  - ConsoleProvider: Logs emails to console + file (default, for development)
  - SMTPProvider: Standard SMTP (Gmail, Outlook, etc.)
  - SendGridProvider: SendGrid API

To switch providers, set EMAIL_PROVIDER env var or update EMAIL_CONFIG.
"""

import os
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — override via environment variables
# ---------------------------------------------------------------------------
EMAIL_CONFIG = {
    "provider": os.getenv("EMAIL_PROVIDER", "console"),  # console | smtp | sendgrid
    "from_email": os.getenv("EMAIL_FROM", "assessments@riskq.local"),
    "from_name": os.getenv("EMAIL_FROM_NAME", "RiskQ Assessments"),
    # SMTP settings
    "smtp_host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
    "smtp_port": int(os.getenv("SMTP_PORT", "587")),
    "smtp_username": os.getenv("SMTP_USERNAME", ""),
    "smtp_password": os.getenv("SMTP_PASSWORD", ""),
    "smtp_use_tls": os.getenv("SMTP_USE_TLS", "true").lower() == "true",
    # SendGrid settings
    "sendgrid_api_key": os.getenv("SENDGRID_API_KEY", ""),
}


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------
class EmailProvider(ABC):
    @abstractmethod
    def send(self, to_email: str, to_name: str, subject: str,
             html_body: str, text_body: str | None = None) -> dict:
        """Send an email. Returns dict with status info."""
        ...


# ---------------------------------------------------------------------------
# Console provider — logs everything, sends nothing
# ---------------------------------------------------------------------------
class ConsoleProvider(EmailProvider):
    LOG_FILE = "email_log.json"

    def send(self, to_email: str, to_name: str, subject: str,
             html_body: str, text_body: str | None = None) -> dict:
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "to_email": to_email,
            "to_name": to_name,
            "from_email": EMAIL_CONFIG["from_email"],
            "from_name": EMAIL_CONFIG["from_name"],
            "subject": subject,
            "html_body": html_body,
            "text_body": text_body,
        }

        # Log to console
        logger.info("=" * 60)
        logger.info("EMAIL SENT (console provider — not actually delivered)")
        logger.info(f"  To:      {to_name} <{to_email}>")
        logger.info(f"  From:    {EMAIL_CONFIG['from_name']} <{EMAIL_CONFIG['from_email']}>")
        logger.info(f"  Subject: {subject}")
        logger.info("=" * 60)

        # Append to log file
        log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), self.LOG_FILE)
        entries = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as f:
                    entries = json.load(f)
            except (json.JSONDecodeError, IOError):
                entries = []
        entries.append(entry)
        with open(log_path, "w") as f:
            json.dump(entries, f, indent=2)

        return {"status": "logged", "provider": "console", "log_file": log_path}


# ---------------------------------------------------------------------------
# SMTP provider — uncomment and configure when ready
# ---------------------------------------------------------------------------
class SMTPProvider(EmailProvider):
    def send(self, to_email: str, to_name: str, subject: str,
             html_body: str, text_body: str | None = None) -> dict:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{EMAIL_CONFIG['from_name']} <{EMAIL_CONFIG['from_email']}>"
        msg["To"] = f"{to_name} <{to_email}>"

        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(EMAIL_CONFIG["smtp_host"], EMAIL_CONFIG["smtp_port"]) as server:
            if EMAIL_CONFIG["smtp_use_tls"]:
                server.starttls()
            if EMAIL_CONFIG["smtp_username"]:
                server.login(EMAIL_CONFIG["smtp_username"], EMAIL_CONFIG["smtp_password"])
            server.send_message(msg)

        return {"status": "sent", "provider": "smtp"}


# ---------------------------------------------------------------------------
# SendGrid provider — pip install sendgrid when ready
# ---------------------------------------------------------------------------
class SendGridProvider(EmailProvider):
    def send(self, to_email: str, to_name: str, subject: str,
             html_body: str, text_body: str | None = None) -> dict:
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail, Email, To, Content
        except ImportError:
            raise RuntimeError("sendgrid package not installed. Run: pip install sendgrid")

        message = Mail(
            from_email=Email(EMAIL_CONFIG["from_email"], EMAIL_CONFIG["from_name"]),
            to_emails=To(to_email, to_name),
            subject=subject,
            html_content=Content("text/html", html_body),
        )
        if text_body:
            message.add_content(Content("text/plain", text_body))

        client = SendGridAPIClient(EMAIL_CONFIG["sendgrid_api_key"])
        response = client.send(message)

        return {"status": "sent", "provider": "sendgrid", "status_code": response.status_code}


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------
_PROVIDERS = {
    "console": ConsoleProvider,
    "smtp": SMTPProvider,
    "sendgrid": SendGridProvider,
}


def get_email_provider() -> EmailProvider:
    provider_name = EMAIL_CONFIG["provider"]
    cls = _PROVIDERS.get(provider_name)
    if not cls:
        raise ValueError(f"Unknown email provider: {provider_name}. Valid: {list(_PROVIDERS.keys())}")
    return cls()


# ---------------------------------------------------------------------------
# Email template builder
# ---------------------------------------------------------------------------
def build_assessment_email_html(
    vendor_name: str,
    assessment_title: str,
    assessment_url: str,
    sender_name: str | None = None,
    custom_message: str | None = None,
    expires_at: datetime | None = None,
) -> tuple[str, str]:
    """Build HTML and plain-text email for an assessment invitation.
    Returns (html_body, text_body).
    """
    sender_line = f" on behalf of {sender_name}" if sender_name else ""
    expiry_line = ""
    expiry_text = ""
    if expires_at:
        expiry_line = f"""
        <tr><td style="padding: 12px 0; color: #6b7280; font-size: 14px;">
            <strong>Deadline:</strong> {expires_at.strftime('%B %d, %Y')}
        </td></tr>"""
        expiry_text = f"\nDeadline: {expires_at.strftime('%B %d, %Y')}"

    custom_html = ""
    custom_text = ""
    if custom_message:
        custom_html = f"""
        <tr><td style="padding: 0 0 20px 0;">
            <div style="background-color: #f9fafb; border-left: 4px solid #6366f1; padding: 16px; border-radius: 4px; color: #374151; font-size: 14px; line-height: 1.6;">
                {custom_message}
            </div>
        </td></tr>"""
        custom_text = f"\nMessage: {custom_message}"

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin: 0; padding: 0; background-color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f3f4f6; padding: 40px 20px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
    <!-- Header -->
    <tr><td style="background: linear-gradient(135deg, #4f46e5, #6366f1); padding: 32px 40px; text-align: center;">
        <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">RiskQ</h1>
        <p style="margin: 8px 0 0 0; color: #c7d2fe; font-size: 14px;">Vendor Risk Assessment</p>
    </td></tr>

    <!-- Body -->
    <tr><td style="padding: 40px;">
        <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td style="padding-bottom: 24px;">
                <h2 style="margin: 0 0 8px 0; color: #111827; font-size: 20px;">You've been invited to complete an assessment</h2>
                <p style="margin: 0; color: #6b7280; font-size: 15px; line-height: 1.6;">
                    Hi,<br><br>
                    You have been invited{sender_line} to complete the following vendor risk assessment for <strong>{vendor_name}</strong>.
                </p>
            </td></tr>

            <!-- Assessment details -->
            <tr><td style="padding: 20px; background-color: #f9fafb; border-radius: 8px; margin-bottom: 24px;">
                <table width="100%" cellpadding="0" cellspacing="0">
                    <tr><td style="padding: 4px 0; color: #374151; font-size: 14px;">
                        <strong>Assessment:</strong> {assessment_title}
                    </td></tr>
                    <tr><td style="padding: 4px 0; color: #374151; font-size: 14px;">
                        <strong>Vendor:</strong> {vendor_name}
                    </td></tr>
                    {expiry_line}
                </table>
            </td></tr>

            {custom_html}

            <!-- CTA Button -->
            <tr><td style="padding: 28px 0; text-align: center;">
                <a href="{assessment_url}" style="display: inline-block; background: linear-gradient(135deg, #4f46e5, #6366f1); color: #ffffff; text-decoration: none; padding: 14px 40px; border-radius: 8px; font-size: 16px; font-weight: 600; letter-spacing: 0.5px;">
                    Start Assessment
                </a>
            </td></tr>

            <tr><td style="padding-top: 8px; color: #9ca3af; font-size: 13px; text-align: center;">
                Or copy this link: <a href="{assessment_url}" style="color: #6366f1; word-break: break-all;">{assessment_url}</a>
            </td></tr>
        </table>
    </td></tr>

    <!-- Footer -->
    <tr><td style="background-color: #f9fafb; padding: 24px 40px; border-top: 1px solid #e5e7eb;">
        <p style="margin: 0 0 8px 0; color: #9ca3af; font-size: 12px; text-align: center;">
            This is an automated message from RiskQ. Please do not reply to this email.
        </p>
        <p style="margin: 0; color: #9ca3af; font-size: 12px; text-align: center;">
            If you did not expect this assessment, please contact your account representative.
        </p>
    </td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""

    text_body = f"""You've been invited to complete an assessment

Hi,

You have been invited{sender_line} to complete a vendor risk assessment for {vendor_name}.

Assessment: {assessment_title}
Vendor: {vendor_name}{expiry_text}{custom_text}

Start the assessment here: {assessment_url}

---
This is an automated message from RiskQ.
If you did not expect this assessment, please contact your account representative.
"""

    return html_body, text_body


# ---------------------------------------------------------------------------
# High-level send function
# ---------------------------------------------------------------------------
def send_assessment_invitation(
    to_email: str,
    to_name: str,
    vendor_name: str,
    assessment_title: str,
    assessment_url: str,
    sender_name: str | None = None,
    custom_message: str | None = None,
    expires_at: datetime | None = None,
) -> dict:
    """Send an assessment invitation email. Returns provider result dict."""
    html_body, text_body = build_assessment_email_html(
        vendor_name=vendor_name,
        assessment_title=assessment_title,
        assessment_url=assessment_url,
        sender_name=sender_name,
        custom_message=custom_message,
        expires_at=expires_at,
    )

    subject = f"Assessment Request: {assessment_title} — {vendor_name}"

    provider = get_email_provider()
    result = provider.send(
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
    )

    logger.info(f"Email sent via {result.get('provider')}: {to_email} — {subject}")
    return result


# ---------------------------------------------------------------------------
# Reminder email template
# ---------------------------------------------------------------------------
def build_reminder_email_html(
    vendor_name: str,
    assessment_title: str,
    assessment_url: str,
    reminder_number: int,
    days_waiting: int,
    expires_at: datetime | None = None,
) -> tuple[str, str]:
    """Build HTML and plain-text for a reminder email."""
    expiry_line = ""
    expiry_text = ""
    urgency_color = "#f59e0b"  # amber
    if expires_at:
        from datetime import datetime as dt
        days_left = (expires_at - dt.utcnow()).days
        expiry_line = f"""
        <tr><td style="padding: 4px 0; color: #374151; font-size: 14px;">
            <strong>Expires:</strong> {expires_at.strftime('%B %d, %Y')} ({days_left} days remaining)
        </td></tr>"""
        expiry_text = f"\nExpires: {expires_at.strftime('%B %d, %Y')} ({days_left} days remaining)"
        if days_left <= 7:
            urgency_color = "#ef4444"  # red

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin: 0; padding: 0; background-color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f3f4f6; padding: 40px 20px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
    <!-- Header -->
    <tr><td style="background: linear-gradient(135deg, {urgency_color}, #f97316); padding: 32px 40px; text-align: center;">
        <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">RiskQ</h1>
        <p style="margin: 8px 0 0 0; color: #ffffff; font-size: 14px; opacity: 0.9;">Assessment Reminder #{reminder_number}</p>
    </td></tr>

    <!-- Body -->
    <tr><td style="padding: 40px;">
        <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td style="padding-bottom: 24px;">
                <h2 style="margin: 0 0 8px 0; color: #111827; font-size: 20px;">Friendly Reminder</h2>
                <p style="margin: 0; color: #6b7280; font-size: 15px; line-height: 1.6;">
                    Hi,<br><br>
                    We're following up on the vendor risk assessment for <strong>{vendor_name}</strong> that was sent {days_waiting} days ago. We haven't received your response yet.
                </p>
            </td></tr>

            <tr><td style="padding: 20px; background-color: #fffbeb; border-left: 4px solid {urgency_color}; border-radius: 4px; margin-bottom: 24px;">
                <table width="100%" cellpadding="0" cellspacing="0">
                    <tr><td style="padding: 4px 0; color: #374151; font-size: 14px;">
                        <strong>Assessment:</strong> {assessment_title}
                    </td></tr>
                    <tr><td style="padding: 4px 0; color: #374151; font-size: 14px;">
                        <strong>Vendor:</strong> {vendor_name}
                    </td></tr>
                    <tr><td style="padding: 4px 0; color: #374151; font-size: 14px;">
                        <strong>Waiting:</strong> {days_waiting} days
                    </td></tr>
                    {expiry_line}
                </table>
            </td></tr>

            <!-- CTA Button -->
            <tr><td style="padding: 28px 0; text-align: center;">
                <a href="{assessment_url}" style="display: inline-block; background: linear-gradient(135deg, {urgency_color}, #f97316); color: #ffffff; text-decoration: none; padding: 14px 40px; border-radius: 8px; font-size: 16px; font-weight: 600;">
                    Complete Assessment Now
                </a>
            </td></tr>

            <tr><td style="padding-top: 8px; color: #9ca3af; font-size: 13px; text-align: center;">
                Or copy this link: <a href="{assessment_url}" style="color: #6366f1; word-break: break-all;">{assessment_url}</a>
            </td></tr>
        </table>
    </td></tr>

    <!-- Footer -->
    <tr><td style="background-color: #f9fafb; padding: 24px 40px; border-top: 1px solid #e5e7eb;">
        <p style="margin: 0; color: #9ca3af; font-size: 12px; text-align: center;">
            This is an automated reminder from RiskQ. Please do not reply to this email.
        </p>
    </td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""

    text_body = f"""Reminder: Assessment still awaiting your response

Hi,

We're following up on the vendor risk assessment for {vendor_name} that was sent {days_waiting} days ago.

Assessment: {assessment_title}
Vendor: {vendor_name}
Waiting: {days_waiting} days{expiry_text}

Complete the assessment here: {assessment_url}

---
This is an automated reminder from RiskQ.
"""

    return html_body, text_body


# ---------------------------------------------------------------------------
# Escalation email template (sent to internal analyst/manager)
# ---------------------------------------------------------------------------
def build_escalation_email_html(
    vendor_name: str,
    assessment_title: str,
    vendor_profile_url: str,
    reminder_count: int,
    days_waiting: int,
    sent_to_email: str,
) -> tuple[str, str]:
    """Build HTML and plain-text for an internal escalation email."""
    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin: 0; padding: 0; background-color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f3f4f6; padding: 40px 20px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
    <tr><td style="background: linear-gradient(135deg, #dc2626, #ef4444); padding: 32px 40px; text-align: center;">
        <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">RiskQ</h1>
        <p style="margin: 8px 0 0 0; color: #ffffff; font-size: 14px; opacity: 0.9;">Escalation Notice</p>
    </td></tr>

    <tr><td style="padding: 40px;">
        <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td style="padding-bottom: 24px;">
                <h2 style="margin: 0 0 8px 0; color: #111827; font-size: 20px;">Vendor Non-Response Escalation</h2>
                <p style="margin: 0; color: #6b7280; font-size: 15px; line-height: 1.6;">
                    The following assessment has not received a response after <strong>{reminder_count} automated reminders</strong> over <strong>{days_waiting} days</strong>. Manual follow-up may be required.
                </p>
            </td></tr>

            <tr><td style="padding: 20px; background-color: #fef2f2; border-left: 4px solid #dc2626; border-radius: 4px;">
                <table width="100%" cellpadding="0" cellspacing="0">
                    <tr><td style="padding: 4px 0; color: #374151; font-size: 14px;"><strong>Vendor:</strong> {vendor_name}</td></tr>
                    <tr><td style="padding: 4px 0; color: #374151; font-size: 14px;"><strong>Assessment:</strong> {assessment_title}</td></tr>
                    <tr><td style="padding: 4px 0; color: #374151; font-size: 14px;"><strong>Sent to:</strong> {sent_to_email}</td></tr>
                    <tr><td style="padding: 4px 0; color: #374151; font-size: 14px;"><strong>Reminders sent:</strong> {reminder_count}</td></tr>
                    <tr><td style="padding: 4px 0; color: #374151; font-size: 14px;"><strong>Days waiting:</strong> {days_waiting}</td></tr>
                </table>
            </td></tr>

            <tr><td style="padding: 28px 0; text-align: center;">
                <a href="{vendor_profile_url}" style="display: inline-block; background: linear-gradient(135deg, #4f46e5, #6366f1); color: #ffffff; text-decoration: none; padding: 14px 40px; border-radius: 8px; font-size: 16px; font-weight: 600;">
                    View Vendor Profile
                </a>
            </td></tr>
        </table>
    </td></tr>

    <tr><td style="background-color: #f9fafb; padding: 24px 40px; border-top: 1px solid #e5e7eb;">
        <p style="margin: 0; color: #9ca3af; font-size: 12px; text-align: center;">
            This is an automated escalation from RiskQ. Consider reaching out to the vendor directly.
        </p>
    </td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""

    text_body = f"""ESCALATION: Vendor non-response

Vendor: {vendor_name}
Assessment: {assessment_title}
Sent to: {sent_to_email}
Reminders sent: {reminder_count}
Days waiting: {days_waiting}

View vendor profile: {vendor_profile_url}

Manual follow-up may be required.
"""

    return html_body, text_body


# ---------------------------------------------------------------------------
# High-level send functions for reminders
# ---------------------------------------------------------------------------
def send_assessment_reminder(
    to_email: str,
    to_name: str,
    vendor_name: str,
    assessment_title: str,
    assessment_url: str,
    reminder_number: int,
    days_waiting: int,
    expires_at: datetime | None = None,
) -> dict:
    """Send an assessment reminder email."""
    html_body, text_body = build_reminder_email_html(
        vendor_name=vendor_name,
        assessment_title=assessment_title,
        assessment_url=assessment_url,
        reminder_number=reminder_number,
        days_waiting=days_waiting,
        expires_at=expires_at,
    )

    subject = f"Reminder #{reminder_number}: {assessment_title} — {vendor_name}"

    provider = get_email_provider()
    result = provider.send(to_email=to_email, to_name=to_name,
                           subject=subject, html_body=html_body, text_body=text_body)
    logger.info(f"Reminder #{reminder_number} sent via {result.get('provider')}: {to_email}")
    return result


def send_escalation_notice(
    to_email: str,
    vendor_name: str,
    assessment_title: str,
    vendor_profile_url: str,
    reminder_count: int,
    days_waiting: int,
    sent_to_email: str,
) -> dict:
    """Send an internal escalation notice."""
    html_body, text_body = build_escalation_email_html(
        vendor_name=vendor_name,
        assessment_title=assessment_title,
        vendor_profile_url=vendor_profile_url,
        reminder_count=reminder_count,
        days_waiting=days_waiting,
        sent_to_email=sent_to_email,
    )

    subject = f"ESCALATION: No response from {vendor_name} — {assessment_title}"

    provider = get_email_provider()
    result = provider.send(to_email=to_email, to_name="Risk Analyst",
                           subject=subject, html_body=html_body, text_body=text_body)
    logger.info(f"Escalation sent via {result.get('provider')}: {to_email}")
    return result
