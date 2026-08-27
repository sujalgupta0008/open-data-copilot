import logging
import re
import socket
import ipaddress
from urllib.parse import urlparse
import httpx

logger = logging.getLogger("slack")

# Strict regex: require exact host + path prefix services|workflows
SLACK_WEBHOOK_RE = re.compile(r"^https://hooks\.slack\.com/(services|workflows)/.+$")

def is_valid_slack_webhook(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    # strict regex requires https://hooks.slack.com/(services|workflows)/
    if not SLACK_WEBHOOK_RE.match(url):
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    # hostname must be exactly hooks.slack.com (case-insensitive)
    if (parsed.hostname or "").lower() != "hooks.slack.com":
        return False
    # no embedded userinfo
    if parsed.username or parsed.password:
        return False
    # only default https port
    if parsed.port not in (None, 443):
        return False
    # scheme must be https (redundant with regex but explicit)
    if parsed.scheme != "https":
        return False
    # no fragment
    if parsed.fragment:
        return False
    return True

def _is_private_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        return False

def _validate_webhook_no_private_ip(url: str) -> bool:
    """C2: DNS rebinding / SSRF guard — block private-range resolution."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            return False
        # resolve; block if any addr is private/loopback/link-local
        infos = socket.getaddrinfo(host, None)
        for _fam, _type, _proto, _canon, sockaddr in infos:
            ip_str = sockaddr[0]
            if _is_private_ip(ip_str):
                logger.warning(f"Blocked webhook resolving to private IP {ip_str} for host {host}")
                return False
        return True
    except socket.gaierror as e:
        # fail-closed: do not allow webhook if DNS fails
        logger.warning(f"Webhook DNS validation failed: {e}")
        return False
    except Exception as e:
        logger.warning(f"Webhook IP validation error: {e}")
        return False

async def send_monitor_alert_slack(webhook_url: str, data: dict):
    if not is_valid_slack_webhook(webhook_url):
        logger.warning(f"Invalid slack webhook: {webhook_url[:30]}")
        return False
    if not _validate_webhook_no_private_ip(webhook_url):
        logger.warning(f"Blocked slack webhook with private IP: {webhook_url[:30]}")
        return False
    dataset_name = data.get("dataset_name", "Dataset")
    metric_name = data.get("metric_name", "Metric")
    current_value = data.get("current_value", "")
    threshold = data.get("threshold", "")
    status = data.get("status", "alert")
    app_url = data.get("app_url", "https://app")
    dataset_id = data.get("dataset_id", "")
    is_recovery = status in ("recovery", "healthy")
    if is_recovery:
        header = f"✅ Monitor Recovered — {dataset_name}"
        status_text = "🟢 HEALTHY"
        color = "#10b981"
    else:
        header = f"⚠️ Monitor Alert — {dataset_name}"
        status_text = "🔴 ALERT"
        color = "#ef4444"
    blocks = [
        {"type":"header","text":{"type":"plain_text","text": header[:150] }},
        {"type":"section","fields":[
            {"type":"mrkdwn","text":f"*Metric:*\n{metric_name}"},
            {"type":"mrkdwn","text":f"*Value:*\n{current_value}"},
            {"type":"mrkdwn","text":f"*Threshold:*\n{threshold}%"},
            {"type":"mrkdwn","text":f"*Status:*\n{status_text}"}
        ]},
        {"type":"actions","elements":[
            {"type":"button","text":{"type":"plain_text","text":"Investigate →"},"url":f"{app_url}/datasets/{dataset_id}?tab=govern&sub=monitoring"}
        ]}
    ]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json={"blocks": blocks})
            if resp.status_code >= 400:
                logger.warning(f"Slack failed {resp.status_code}: {resp.text[:200]}")
                return False
            logger.info(f"Slack alert sent to {webhook_url[:30]}")
            return True
    except Exception as e:
        logger.warning(f"Slack error: {e}")
        return False
