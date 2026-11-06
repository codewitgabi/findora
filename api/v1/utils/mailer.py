import smtplib
from email.message import EmailMessage

from starlette.concurrency import run_in_threadpool

from api.v1.utils.config import config
from api.v1.utils.logger import get_logger

logger = get_logger("mailer")


def _send(to: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = config.SMTP_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as smtp:
        if config.SMTP_USE_TLS:
            smtp.starttls()
        if config.SMTP_USERNAME:
            smtp.login(config.SMTP_USERNAME, config.SMTP_PASSWORD or "")
        smtp.send_message(message)


async def send_email(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns False (and logs) instead of raising.

    Without ``SMTP_HOST`` configured (local development) the email is written to the
    log so flows such as password reset can still be exercised.
    """
    if not config.SMTP_HOST:
        logger.warning(
            "SMTP not configured; email not sent",
            extra={"to": to, "subject": subject, "body": body},
        )
        return False
    try:
        await run_in_threadpool(_send, to, subject, body)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("Email delivery failed", extra={"to": to, "error": str(exc)})
        return False
