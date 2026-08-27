import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
import httpx

logger = logging.getLogger("email")

def _is_valid_email(email: str) -> bool:
    if not email or "@" not in email:
        return False
    parts = email.split("@")
    if len(parts) != 2:
        return False
    if "." not in parts[1]:
        return False
    if len(email) > 320:
        return False
    return True

async def send_alert_email(to: str, subject: str, html_body: str) -> bool:
    if not _is_valid_email(to):
        logger.warning(f"Invalid email {to}, skipping")
        return False
    # Check SendGrid mode first
    sendgrid_key = os.getenv("SENDGRID_API_KEY", "").strip()
    if sendgrid_key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                payload = {
                    "personalizations": [{"to": [{"email": to}]}],
                    "from": {"email": os.getenv("SMTP_FROM", "noreply@opendatacopilot.com")},
                    "subject": subject,
                    "content": [{"type": "text/html", "value": html_body}]
                }
                headers = {"Authorization": f"Bearer {sendgrid_key}", "Content-Type": "application/json"}
                resp = await client.post("https://api.sendgrid.com/v3/mail/send", json=payload, headers=headers)
                if resp.status_code in (200, 201, 202):
                    logger.info(f"SendGrid email sent to {to}")
                    return True
                else:
                    logger.warning(f"SendGrid failed {resp.status_code}: {resp.text[:200]}")
                    # fallback to SMTP if available?
                    if not os.getenv("SMTP_HOST"):
                        return False
        except Exception as e:
            logger.warning(f"SendGrid error: {e}")
            # try SMTP fallback if configured
            if not os.getenv("SMTP_HOST"):
                return False

    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = os.getenv("SMTP_PORT", "").strip()
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "noreply@opendatacopilot.com").strip()

    if not smtp_host:
        logger.warning("No email configured (SMTP_HOST or SENDGRID_API_KEY), skipping email")
        return False
    try:
        port = int(smtp_port) if smtp_port else 587
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_from
        msg["To"] = to
        msg.attach(MIMEText(html_body, "html"))
        # timeout 10s, 1 retry
        for attempt in range(2):
            try:
                if port == 465:
                    context = ssl.create_default_context()
                    with smtplib.SMTP_SSL(smtp_host, port, context=context, timeout=10) as server:
                        if smtp_user and smtp_pass:
                            server.login(smtp_user, smtp_pass)
                        server.sendmail(smtp_from, to, msg.as_string())
                else:
                    with smtplib.SMTP(smtp_host, port, timeout=10) as server:
                        server.ehlo()
                        try:
                            context = ssl.create_default_context()
                            server.starttls(context=context)
                            server.ehlo()
                        except:
                            pass
                        if smtp_user and smtp_pass:
                            server.login(smtp_user, smtp_pass)
                        server.sendmail(smtp_from, to, msg.as_string())
                logger.info(f"Email sent to {to} via SMTP")
                return True
            except Exception as e:
                if attempt == 1:
                    raise
                logger.warning(f"SMTP attempt {attempt} failed: {e}, retrying")
        return False
    except Exception as e:
        logger.warning(f"SMTP failed to {to}: {e}")
        return False

def build_alert_email(metric_name: str, dataset_name: str, current_value: float, threshold: float, status: str, timestamp: str, app_url: str = "https://app"):
    is_recovery = status == "recovery" or status == "healthy"
    if is_recovery:
        subject = f"✅ Recovered: {metric_name} on {dataset_name}"
        header = "✅ Recovered"
        header_color = "#10b981"
        status_text = "RECOVERED"
    else:
        subject = f"⚠️ Monitor Alert: {metric_name} on {dataset_name}"
        header = "⚠️ Monitor Alert"
        header_color = "#ef4444"
        status_text = "ALERT"
    html = f"""
<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #0f172a;">
<div style="background: {header_color}; color: white; padding: 16px; border-radius: 12px 12px 0 0; text-align: center;">
<h2 style="margin:0;">{header}</h2>
<div style="font-size: 12px; opacity: 0.9;">Open Data Copilot</div>
</div>
<div style="border: 1px solid #e2e8f0; border-top: none; padding: 20px; border-radius: 0 0 12px 12px;">
<p><strong>Dataset:</strong> {dataset_name}</p>
<p><strong>Metric:</strong> {metric_name}</p>
<p><strong>Current Value:</strong> {current_value}</p>
<p><strong>Threshold:</strong> {threshold}%</p>
<p><strong>Status:</strong> <span style="background: {header_color}; color: white; padding: 2px 8px; border-radius: 999px; font-size: 11px;">{status_text}</span></p>
<p><strong>Checked at:</strong> {timestamp}</p>
<div style="margin: 20px 0; text-align: center;">
<a href="{app_url}" style="background: #0b0d18; color: white; padding: 10px 20px; border-radius: 999px; text-decoration: none; font-size: 13px;">Investigate →</a>
</div>
<hr style="border: none; border-top: 1px solid #e2e8f0; margin: 16px 0;" />
<p style="font-size: 11px; color: #64748b;">To stop alerts: manage monitors in Open Data Copilot</p>
</div>
</body>
</html>
"""
    return subject, html
