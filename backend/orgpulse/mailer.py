"""Account emails (verification and password-reset links) over SMTP."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from html import escape

from orgpulse.config import get_settings

log = logging.getLogger(__name__)


class MailNotConfigured(RuntimeError):
    pass


def can_send() -> bool:
    s = get_settings()
    return bool(s.smtp_host and s.smtp_from) or s.auth_email_log_links


def send_link(to: str, subject: str, intro: str, link: str, action: str) -> None:
    """One short email with one button. Without SMTP, development may log the link instead."""
    settings = get_settings()
    if not (settings.smtp_host and settings.smtp_from):
        if settings.auth_email_log_links:
            log.warning("AUTH_EMAIL_LOG_LINKS (development only): %s for %s: %s", action, to, link)
            return
        raise MailNotConfigured("set SMTP_HOST and SMTP_FROM so Org+ can email sign-in links")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["To"] = to
    msg["From"] = settings.smtp_from
    msg.set_content(f"{intro}\n\n{action}: {link}\n\nIf this wasn't you, ignore this email.")
    msg.add_alternative(
        f"""<div style="font-family:system-ui,sans-serif;max-width:480px">
<p>{escape(intro)}</p>
<p><a href="{escape(link)}" style="display:inline-block;background:#1c5cab;color:#fff;
padding:10px 18px;border-radius:8px;text-decoration:none">{escape(action)}</a></p>
<p style="color:#666;font-size:13px">If this wasn't you, ignore this email.</p></div>""",
        subtype="html",
    )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)
    log.info("sent %s email to %s", action, to)
