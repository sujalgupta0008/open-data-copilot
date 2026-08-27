from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User
import re

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

def is_valid_email(email: str) -> bool:
    if not email or "@" not in email:
        return False
    # basic regex
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    return bool(re.match(pattern, email))

@router.post("/test/email")
async def test_email(payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    email = payload.get("email", "").strip() if payload else ""
    if not is_valid_email(email):
        raise HTTPException(status_code=400, detail="Invalid email format")
    from app.services.email_service import send_alert_email
    html = "<h3>Test alert from Open Data Copilot</h3><p>Your email integration is working!</p>"
    try:
        sent = await send_alert_email(email, "Test alert from Open Data Copilot", html)
        if sent:
            return {"sent": True}
        else:
            # If no SMTP configured, we consider it skipped but not error for test? Spec says return sent false with error
            return {"sent": False, "error": "Email not configured (SMTP_HOST/SENDGRID_API_KEY missing) — skipped"}
    except Exception as e:
        return {"sent": False, "error": str(e)[:200]}

@router.post("/test/slack")
async def test_slack(payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    webhook_url = payload.get("webhook_url", "").strip() if payload else ""
    if not webhook_url.startswith("https://hooks.slack.com/"):
        raise HTTPException(status_code=400, detail="Invalid webhook_url: must start with https://hooks.slack.com/")
    from app.services.slack_service import send_monitor_alert_slack
    try:
        sent = await send_monitor_alert_slack(webhook_url, {"dataset_name": "Test Dataset", "metric_name": "Test Metric", "current_value": 123, "threshold": 10, "status": "alert", "app_url": "https://app", "dataset_id": "test"})
        if not sent:
            # Try simple message fallback
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(webhook_url, json={"text": "✅ Test alert from Open Data Copilot — your Slack integration is working!"})
                if resp.status_code >= 400:
                    raise HTTPException(status_code=502, detail=f"Slack failed {resp.status_code}")
        return {"sent": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)[:200])
