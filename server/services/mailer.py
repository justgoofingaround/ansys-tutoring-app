"""Outbound mail seam (registration confirmation links).

Mirrors services/chatbot_service.py: routers talk to a Mailer protocol, the
real implementation is chosen per deployment, and tests inject FakeMailer
through Settings.mailer so no SMTP server is needed.

NYU note: the pilot host has restricted egress, so SMTP may be unavailable.
With SMTP_HOST unset the LoggingMailer writes the confirmation URL to the
server log instead of sending it, and the instructor can still admit a student
with the manual "mark verified" action on the roster — a mail outage degrades
to instructor approval rather than blocking the lab.
"""

import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

log = logging.getLogger("tutoring_hub.mail")

SUBJECT = "Confirm your ME-UY 4214 Tutoring Hub account"
RESET_SUBJECT = "Reset your ME-UY 4214 Tutoring Hub password"

BODY = """Hi {name},

Confirm your Tutoring Hub account for ME-UY 4214 by opening this link:

{url}

The link can only be used once and expires in {hours} hours. It opens only on
the NYU network or VPN, so use a lab machine or connect to the VPN first.

If you weren't expecting this email you can ignore it — the account stays
inactive until the link is opened.
"""


RESET_BODY = """Hi {name},

Someone asked to reset the password for your Tutoring Hub account. To choose a
new one, open this link:

{url}

The link can only be used once and expires in {hours} hours. It opens only on
the NYU network or VPN.

If this wasn't you, ignore this email — your password stays as it is.
"""


class Mailer(Protocol):
    # False when "sending" only records the message somewhere local, so callers
    # can tell the student the truth instead of promising mail that is not
    # coming. See LoggingMailer.
    delivers: bool

    def send_verification(self, to_addr: str, name: str, url: str, hours: int) -> None: ...

    def send_password_reset(self, to_addr: str, name: str, url: str, hours: int) -> None: ...


class LoggingMailer:
    """No SMTP configured: log the link rather than silently dropping it. Used
    in dev, and on any deployment where outbound mail is blocked."""

    delivers = False

    def __init__(self):
        self.sent: list[dict] = []

    def send_verification(self, to_addr, name, url, hours):
        self.sent.append({"to": to_addr, "name": name, "url": url, "kind": "verify"})
        log.warning(
            "SMTP not configured — not sending mail. Confirmation link for %s: %s",
            to_addr, url,
        )

    def send_password_reset(self, to_addr, name, url, hours):
        self.sent.append({"to": to_addr, "name": name, "url": url, "kind": "reset"})
        log.warning(
            "SMTP not configured — not sending mail. Password reset link for %s: %s",
            to_addr, url,
        )


class SmtpMailer:
    """Real delivery through a relay (NYU's, once credentials are available)."""

    delivers = True

    def __init__(self, host, port=587, user=None, password=None, from_addr=None, use_tls=True):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.from_addr = from_addr or user or "noreply@meuy4214.poly.edu"
        self.use_tls = use_tls

    def _send(self, to_addr, subject, body):
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = to_addr
        msg.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=20) as smtp:
            smtp.ehlo()
            # Upgrade when the server offers it, rather than assuming: internal
            # relays often speak plain SMTP on the LAN, and an unconditional
            # STARTTLS fails against them.
            if self.use_tls and smtp.has_extn("starttls"):
                smtp.starttls()
                smtp.ehlo()
            if self.user:
                smtp.login(self.user, self.password or "")
            smtp.send_message(msg)

    def send_verification(self, to_addr, name, url, hours):
        self._send(to_addr, SUBJECT, BODY.format(name=name or "there", url=url, hours=hours))

    def send_password_reset(self, to_addr, name, url, hours):
        self._send(
            to_addr, RESET_SUBJECT,
            RESET_BODY.format(name=name or "there", url=url, hours=hours),
        )


class FakeMailer:
    """Test seam: records messages, sends nothing. Reports itself as delivering
    so tests exercise the normal "we emailed you" path."""

    delivers = True

    def __init__(self):
        self.sent: list[dict] = []

    def send_verification(self, to_addr, name, url, hours):
        self.sent.append({"to": to_addr, "name": name, "url": url, "hours": hours,
                          "kind": "verify"})

    def send_password_reset(self, to_addr, name, url, hours):
        self.sent.append({"to": to_addr, "name": name, "url": url, "hours": hours,
                          "kind": "reset"})


def get_mailer(settings) -> Mailer:
    """Settings.mailer (test seam), else SMTP when configured, else logging."""
    if settings.mailer is not None:
        return settings.mailer
    if settings.smtp_host:
        return SmtpMailer(
            settings.smtp_host, settings.smtp_port, settings.smtp_user,
            settings.smtp_password, settings.smtp_from,
        )
    return LoggingMailer()
