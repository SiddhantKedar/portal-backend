# core/whatsapp.py
"""Thin AiSensy WhatsApp client. One send function, used by daily reports and OTP.
API key from settings (.env); never hardcoded. Callers build templateParams in the
exact {{1}}..{{n}} order of the approved template."""

import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

AISENSY_URL = "https://backend.aisensy.com/campaign/t1/api/v2"
REQUEST_TIMEOUT_SECONDS = 15
# NOTE : no sender-name field exists. AiSensy's `userName` is the RECIPIENT
# contact name; sender is fixed by the connected WhatsApp number. (SENDER_NAME removed.)


def send_template(destination, campaign_name, template_params,
                  user_name=None, fallback_values=None):
    """
    Send an approved AiSensy template.

    destination:      WhatsApp number, country code + number, no '+' (e.g. 918424882274).
    campaign_name:    AiSensy campaign name (must match the dashboard, not the template name).
    template_params:  list of strings, positional for {{1}}, {{2}}, ...
    user_name:        AiSensy CONTACT name for this destination — AiSensy creates/updates
                      the contact under this name, so pass the recipient's real name.
                      Falls back to the destination number if omitted.
    fallback_values:  optional dict for paramsFallbackValue.

    Returns (ok: bool, detail: str). Never raises — logs and returns False on failure,
    so one bad send never kills a batch.
    """
    api_key = getattr(settings, "AISENSY_API_KEY", None)
    if not api_key:
        logger.error("AISENSY_API_KEY not configured")
        return False, "missing api key"

    if not destination:
        return False, "no destination"

    dest = str(destination).strip()

    payload = {
        "apiKey": api_key,
        "campaignName": campaign_name,
        "destination": dest,
        "userName": (user_name or dest),   # AiSensy contact name, NOT a sender field
        "templateParams": [str(p) for p in template_params],
        "source": "enerlynx-backend",
    }
    if fallback_values:
        payload["paramsFallbackValue"] = fallback_values

    try:
        resp = requests.post(AISENSY_URL, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        logger.error("AiSensy request failed for %s: %s", dest, e)
        return False, f"request error: {e}"

    if resp.status_code == 200:
        logger.info("WhatsApp sent to %s (campaign=%s)", dest, campaign_name)
        return True, "sent"

    logger.error("AiSensy %s for %s: %s", resp.status_code, dest, resp.text[:300])
    return False, f"http {resp.status_code}: {resp.text[:200]}"