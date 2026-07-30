"""Outbound email for HeyPorts (SOS alerts, contact-us, password resets).

Configured via environment:
    SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD,
    SMTP_FROM (default no-reply@heyports.com), SMTP_USE_TLS (default true),
    SUPPORT_EMAIL (default support@heyports.com)

When SMTP_HOST is unset (local dev), messages are logged instead of sent so
flows remain testable without a mail server.
"""
import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Iterable, Optional, Union

logger = logging.getLogger("heyports.email")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "no-reply@heyports.com")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() not in ("0", "false", "no")

SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "support@heyports.com")


def is_configured() -> bool:
    return bool(SMTP_HOST)


def send_email(
    to: Union[str, Iterable[str]],
    subject: str,
    body: str,
    html_body: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> bool:
    """Send an email; returns True on success.

    Never raises — callers (SOS, contact, resets) must not fail because the
    mail server is down; failures are logged for ops follow-up.
    """
    recipients = [to] if isinstance(to, str) else [r for r in to if r]
    recipients = sorted(set(recipients))
    if not recipients:
        return False

    if not is_configured():
        logger.warning(
            "SMTP not configured — email not sent.\n  To: %s\n  Subject: %s\n  Body:\n%s",
            ", ".join(recipients), subject, body,
        )
        # Dev convenience: also echo to stdout so local flows are visible.
        print(f"[EMAIL:DEV] to={recipients} subject={subject!r}\n{body}")
        return False

    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            if SMTP_USE_TLS:
                server.starttls()
            if SMTP_USER:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        logger.info("Email sent to %s: %s", recipients, subject)
        return True
    except Exception:
        logger.exception("Failed to send email to %s (%s)", recipients, subject)
        return False


# ---------- message builders ----------

def send_sos_alert(
    *,
    ship_email: str,
    crew_name: str,
    crew_email: str,
    vessel: Optional[str],
    port_name: Optional[str],
    lat: Optional[float],
    lng: Optional[float],
) -> bool:
    """SOS alert to the ship's configured email + HeyPorts support."""
    location = "Location not available"
    maps_line = ""
    if lat is not None and lng is not None:
        location = f"{lat}, {lng}"
        maps_line = f"Map: https://maps.google.com/?q={lat},{lng}\n"
    body = (
        "EMERGENCY — SOS ALERT\n\n"
        f"Crew member: {crew_name} ({crew_email})\n"
        f"Vessel: {vessel or 'N/A'}\n"
        f"Port: {port_name or 'N/A'}\n"
        f"Location: {location}\n"
        f"{maps_line}\n"
        "This crew member has triggered an SOS from the HeyPorts app and may "
        "need immediate assistance. Please try to contact them right away.\n\n"
        "— HeyPorts Safety"
    )
    return send_email(
        [ship_email, SUPPORT_EMAIL],
        f"SOS ALERT — {crew_name}{f' ({vessel})' if vessel else ''}",
        body,
        reply_to=crew_email,
    )


def send_contact_message(
    *, first_name: str, last_name: str, email: str, phone: str, message: str,
) -> bool:
    """Forward a contact-us submission to HeyPorts support."""
    body = (
        "New contact form submission\n\n"
        f"Name: {first_name} {last_name}\n"
        f"Email: {email}\n"
        f"Phone: {phone}\n\n"
        f"Message:\n{message}\n"
    )
    return send_email(
        SUPPORT_EMAIL,
        f"Contact Us — {first_name} {last_name}",
        body,
        reply_to=email,
    )


def send_email_verification_code(*, to: str, code: str) -> bool:
    body = (
        "Welcome to HeyPorts!\n\n"
        f"Your email verification code is: {code}\n\n"
        "Enter this code to finish creating your account. It expires in 10 "
        "minutes. If you didn't request this, you can ignore this email.\n\n"
        "— HeyPorts"
    )
    return send_email(to, "Your HeyPorts verification code", body)


def send_password_reset_code(*, to: str, name: Optional[str], code: str) -> bool:
    body = (
        f"Hi {name or 'there'},\n\n"
        f"Your HeyPorts password reset code is: {code}\n\n"
        "The code expires in 15 minutes. If you didn't request this, you can "
        "safely ignore this email — your password will remain unchanged.\n\n"
        "— HeyPorts"
    )
    return send_email(to, "HeyPorts password reset code", body)
