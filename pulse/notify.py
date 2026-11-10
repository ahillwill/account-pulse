"""Send the digest by email over SMTP (works with a Gmail app password)."""

import os
import smtplib
import ssl
from email.message import EmailMessage


def send_digest(subject, body_html, body_text):
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    to = [a.strip() for a in os.environ.get("DIGEST_TO", "").split(",") if a.strip()]
    if not (user and password and to):
        return False, "email not configured (set SMTP_USER, SMTP_PASSWORD, DIGEST_TO)"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Account Pulse <{user}>"
    msg["To"] = ", ".join(to)
    msg.set_content(body_text)
    msg.add_alternative(body_html, subtype="html")

    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    try:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as server:
            server.login(user, password)
            server.send_message(msg)
        return True, f"sent to {len(to)} recipient(s)"
    except Exception as e:
        return False, f"email failed: {str(e)[:140]}"
