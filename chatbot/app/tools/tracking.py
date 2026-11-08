"""Read configured order metadata; never query a courier or infer delivery from order status."""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from app.config import settings

SHIPMENT_LABELS = {
    "created": "spedizione creata",
    "accepted": "presa in carico",
    "in_transit": "in transito",
    "delivered": "consegnata",
    "exception": "anomalia segnalata dal tracking",
}


@dataclass(frozen=True)
class TrackingInfo:
    state: str | None
    delivered_at: datetime | None
    url: str | None
    incomplete: bool


def safe_tracking_url(value: str | None) -> str | None:
    if not value or len(value) > 2048 or any(
        c.isspace() or ord(c) < 32 or ord(c) == 127 or c in "\\<>\"" for c in value
    ):
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (parsed.scheme != "https" or not host or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            if ("." not in host or host.endswith((".local", ".localhost", ".internal"))
                    or any(not (c.isascii() and (c.isalnum() or c in ".-")) for c in host)
                    or any(not label or label.startswith("-") or label.endswith("-")
                           for label in host.split("."))):
                return None
    except ValueError:
        return None
    return value


def read_tracking(order: dict) -> TrackingInfo:
    """Only configured metadata keys and explicitly mapped shipment states are evidence."""
    metadata = order.get("meta_data", [])
    if not isinstance(metadata, list):
        return TrackingInfo(None, None, None, True)
    values = {}
    invalid = set()
    incomplete = False
    for name, key in (("date", settings.tracking_delivery_date_meta_key),
                      ("state", settings.tracking_status_meta_key),
                      ("url", settings.tracking_url_meta_key)):
        if not key:
            continue
        found = [item.get("value") for item in metadata
                 if isinstance(item, dict) and item.get("key") == key]
        if found:
            if len(found) == 1 and isinstance(found[0], str) and found[0].strip():
                values[name] = found[0]
            else:
                incomplete = True
                invalid.add(name)
    raw_state = values.get("state")
    state = settings.tracking_status_map.get(raw_state) if raw_state else None
    if raw_state and not state:
        incomplete = True
    delivered_at = None
    if values.get("date"):
        try:
            delivered_at = datetime.fromisoformat(values["date"].replace("Z", "+00:00"))
            zone = ZoneInfo(settings.wc_order_timezone)
            delivered_at = (delivered_at.astimezone(zone) if delivered_at.tzinfo
                            else delivered_at.replace(tzinfo=zone))
        except (ValueError, OverflowError):
            delivered_at = None
            incomplete = True
    if delivered_at:
        if (raw_state and state != "delivered") or "state" in invalid:
            delivered_at = None
            incomplete = True
        else:
            state = "delivered"
    if state == "delivered" and delivered_at is None:
        incomplete = True
    url = safe_tracking_url(values.get("url"))
    if (values.get("url") and not url) or (url and not state):
        incomplete = True
    return TrackingInfo(state, delivered_at, url, incomplete)
