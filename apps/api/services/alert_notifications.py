import logging
import asyncio
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Mapping, MutableMapping, Optional, Union

import httpx

from apps.api.services.anomaly_scoring import AlertCandidate
from apps.api.settings import settings
from apps.api.routes.ingest import broadcast

logger = logging.getLogger(__name__)

AlertLike = Union[AlertCandidate, Mapping[str, Any]]


def _normalize_alert(alert: AlertLike) -> Dict[str, Any]:
    """
    Convert an AlertCandidate or dict-like object into a plain dict.

    This lets callers pass either:
      - the AlertCandidate dataclass from the scoring service, or
      - a row/dict fetched from the `alerts` table.

    The returned dict is safe to use for formatting Slack messages or
    building SSE payloads.
    """
    if is_dataclass(alert):
        data = asdict(alert)
    else:
        # Make a shallow copy so callers can't accidentally mutate the source.
        data = dict(alert)

    # Normalise some common keys with sensible defaults to avoid KeyError.
    data.setdefault("org_id", None)
    data.setdefault("vendor_id", None)
    data.setdefault("invoice_id", None)
    data.setdefault("type", None)
    data.setdefault("severity", None)
    data.setdefault("message", "")
    data.setdefault("meta", {})

    # Ensure meta is always a dict-like structure.
    meta = data.get("meta") or {}
    if not isinstance(meta, Mapping):
        meta = {"raw_meta": meta}
    data["meta"] = dict(meta)

    return data


def build_invoice_link(invoice_id: Optional[str]) -> Optional[str]:
    """
    Build a deep link to the invoice detail page in the web app, if
    APP_BASE_URL is configured. Returns None if we don't have enough
    information to construct a link.
    """
    if not invoice_id:
        return None

    base_url = getattr(settings, "APP_BASE_URL", None)
    if not base_url:
        return None

    return f"{base_url.rstrip('/')}/invoices/{invoice_id}"


def build_slack_text(alert: AlertLike, invoice_url: Optional[str] = None) -> str:
    """
    Construct a human-readable Slack message for a single alert.

    The message is intentionally compact but still includes:
      - severity
      - type
      - vendor/invoice identifiers
      - the core message from the scoring rule
      - an optional link back to the app
    """
    data = _normalize_alert(alert)

    severity = (data.get("severity") or "info").upper()
    alert_type = data.get("type") or "alert"
    vendor_id = data.get("vendor_id") or "unknown-vendor"
    invoice_id = data.get("invoice_id") or "unknown-invoice"
    message = data.get("message") or ""

    prefix = f":rotating_light: [{severity}] {alert_type}"
    context = f"vendor={vendor_id}, invoice={invoice_id}"

    if invoice_url:
        return f"{prefix} – {context}\n{message}\n<{invoice_url}|Open in ProcureSight>"
    else:
        return f"{prefix} – {context}\n{message}"


async def send_alert_to_slack(alert: AlertLike, invoice_url: Optional[str] = None) -> None:
    """
    Send a single alert notification to Slack via an incoming webhook.

    Behaviour:
      - If SLACK_WEBHOOK_URL is not configured, this is a no-op.
      - Any network errors are logged but do not raise to callers.
    """
    webhook_url = getattr(settings, "SLACK_WEBHOOK_URL", None)
    if not webhook_url:
        logger.debug("SLACK_WEBHOOK_URL is not configured; skipping Slack notification.")
        return

    text = build_slack_text(alert, invoice_url=invoice_url)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(webhook_url, json={"text": text})
            resp.raise_for_status()
    except Exception:
        logger.exception("Failed to send Slack alert notification.")


def build_sse_payload(alert: AlertLike) -> Dict[str, Any]:
    """
    Build a minimal payload suitable for emitting as an SSE 'alert_created'
    event on /events.

    This does not actually broadcast anything; it just shapes the data.
    The SSE route/module is responsible for pushing this dict to connected
    clients.
    """
    data = _normalize_alert(alert)
    meta = data.get("meta", {}) or {}

    payload: Dict[str, Any] = {
        "type": "alert_created",
        "org_id": data.get("org_id"),
        "invoice_id": data.get("invoice_id"),
        "vendor_id": data.get("vendor_id"),
        "alert_type": data.get("type"),
        "severity": data.get("severity"),
        "message": data.get("message"),
    }

    # Optionally expose a few extra interesting meta fields if present.
    interesting_keys = ("invoice_no", "rule", "ratio")
    extra: Dict[str, Any] = {}
    for key in interesting_keys:
        if key in meta:
            extra[key] = meta[key]

    if extra:
        payload["meta"] = extra

    return payload


def send_alert_sse(alert: AlertLike) -> None:
    """
    Fire-and-forget helper to emit an 'alert_created' SSE event using the
    shared broadcast() helper from the ingest module.

    This is intentionally best-effort:
      - If there is no running event loop, we spin up a short-lived one to
        deliver the event.
      - If broadcasting fails, we log the exception but do not raise it back
        to callers. Alert creation should not be blocked by UI notification
        failures.
    """
    payload = build_sse_payload(alert)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running event loop (likely called from a sync context).
        try:
            asyncio.run(broadcast(payload))
        except Exception:
            logger.exception("Failed to broadcast SSE 'alert_created' event.")
        return

    # We are already in an async context; schedule the broadcast as a
    # background task and do not await it here.
    try:
        loop.create_task(broadcast(payload))
    except Exception:
        logger.exception("Failed to schedule SSE 'alert_created' event.")