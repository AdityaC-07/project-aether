"""Email delivery for AETHER reports over SMTP."""

from __future__ import annotations

import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from typing import Any, Dict

from app.core.settings import AppSettings, get_settings
from app.reporting.exporters import build_export


def _attachment_parts(media_type: str) -> tuple[str, str]:
    if media_type.startswith("text/"):
        return "text", media_type.split("/")[-1]
    return "application", media_type.split("/")[-1]


def send_report_email(
    recipient: str,
    result: Dict[str, Any],
    input_text: str = "",
    fmt: str = "pdf",
    settings: AppSettings | None = None,
) -> Dict[str, Any]:
    """Send ``result`` as an attachment to ``recipient``.

    Returns a dict with ``success`` and a ``message``; on failure also a
    ``status_code`` suitable for an HTTP response.
    """
    settings = settings or get_settings()
    if not settings.smtp_configured:
        return {
            "success": False,
            "status_code": 400,
            "message": (
                "SMTP is not configured on the server. Set the AETHER_SMTP_* "
                "environment variables (at minimum AETHER_SMTP_HOST and "
                "AETHER_SMTP_FROM)."
            ),
        }
    if not recipient or "@" not in recipient:
        return {
            "success": False,
            "status_code": 400,
            "message": "A valid recipient email address is required.",
        }

    try:
        data, media_type, filename = build_export(result, input_text, fmt)
    except ValueError as exc:
        return {
            "success": False,
            "status_code": 400,
            "message": str(exc),
        }

    maintype, subtype = _attachment_parts(media_type)

    message = EmailMessage()
    message["Subject"] = f"Project AETHER — Analysis Report ({fmt.upper()})"
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(
        "Attached is your Project AETHER analysis report.\n"
        f"Format: {fmt.upper()}\n"
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        "— Project AETHER"
    )
    message.add_attachment(
        data,
        maintype=maintype,
        subtype=subtype,
        filename=filename,
    )

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            if settings.smtp_starttls:
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
        return {
            "success": True,
            "status_code": 200,
            "recipient": recipient,
            "format": fmt,
            "message": "Report sent successfully.",
        }
    except smtplib.SMTPException as exc:
        return {
            "success": False,
            "status_code": 502,
            "message": f"SMTP delivery failed: {exc}",
        }
    except Exception as exc:
        return {
            "success": False,
            "status_code": 500,
            "message": f"Email sending failed: {exc}",
        }
