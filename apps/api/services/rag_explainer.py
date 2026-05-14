"""
RAG explanation orchestrator.

Flow: load alert → retrieve evidence → build prompt → call LLM (or fallback)
      → save explanation → return response.
"""
import json
from decimal import Decimal
from typing import Any, Dict, Optional
from psycopg import Connection

from ..repos.alert_explanations import get_alert, save_explanation
from .evidence_retrieval import retrieve_evidence
from .llm_client import generate_explanation, LLMUnavailableError


SUPPORTED_TYPES = {"unit_price_delta", "vendor_volume_spike", "duplicate_invoice"}


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _fmt(val: Any, prefix: str = "$") -> str:
    if val is None:
        return "N/A"
    try:
        return f"{prefix}{float(val):,.2f}"
    except (TypeError, ValueError):
        return str(val)


def _build_prompt(alert: Dict[str, Any], evidence: Dict[str, Any]) -> str:
    alert_type = alert["type"]
    severity = alert.get("severity", "unknown")
    vendor = alert.get("vendor_name") or "Unknown vendor"
    lines = [
        f"Alert type: {alert_type}",
        f"Severity: {severity}",
        f"Vendor: {vendor}",
        f"Alert message: {alert.get('message', '')}",
        "",
        "Evidence (retrieved from invoice history):",
        json.dumps(evidence, indent=2, default=str),
        "",
        "Produce a reviewer-facing explanation in JSON format.",
        "Include: summary, evidence (list of factual statements), why_it_matters, recommended_action, confidence.",
        "Do not invent data not present in the evidence above.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Deterministic fallback templates
# ---------------------------------------------------------------------------

def _fallback_unit_price_delta(alert: Dict[str, Any], evidence: Dict[str, Any]) -> Dict[str, Any]:
    m = evidence.get("metrics") or {}
    vendor = alert.get("vendor_name") or "the vendor"
    sku = m.get("sku") or m.get("desc") or "the item"
    current = _fmt(m.get("unit_price"))
    median = _fmt(m.get("median_unit_price"))
    ratio = m.get("ratio")
    ratio_str = f"{float(ratio):.1f}×" if ratio is not None else "significantly"
    sample = m.get("sample_size", "unknown")
    return {
        "summary": (
            f"This invoice was flagged because the unit price for {sku} is "
            f"{ratio_str} higher than {vendor}'s historical median."
        ),
        "evidence": [
            f"Current unit price: {current}.",
            f"Historical median unit price: {median} (based on {sample} prior samples).",
        ],
        "why_it_matters": (
            "An unusually high unit price may indicate a pricing error, incorrect SKU "
            "mapping, or a vendor overcharge."
        ),
        "recommended_action": (
            "Review the source invoice and confirm the quoted unit price with the vendor "
            "before approving payment."
        ),
        "confidence": "high",
    }


def _fallback_vendor_volume_spike(alert: Dict[str, Any], evidence: Dict[str, Any]) -> Dict[str, Any]:
    m = evidence.get("metrics") or {}
    vendor = alert.get("vendor_name") or "the vendor"
    current = _fmt(m.get("invoice_total"))
    median = _fmt(m.get("baseline_median_total"))
    ratio = m.get("ratio")
    ratio_str = f"{float(ratio):.1f}×" if ratio is not None else "significantly"
    count = m.get("invoice_count", "unknown")
    window = m.get("baseline_window", "recent period")
    return {
        "summary": (
            f"This invoice total is {ratio_str} higher than {vendor}'s "
            f"median invoice total over the {window} baseline window."
        ),
        "evidence": [
            f"Current invoice total: {current}.",
            f"Baseline median invoice total: {median} across {count} invoices in the {window} window.",
        ],
        "why_it_matters": (
            "A sudden spike in invoice volume may indicate a billing error, duplicate "
            "charge, or unauthorised spend."
        ),
        "recommended_action": (
            "Verify that goods or services were received at the quantities reflected "
            "in this invoice before approving payment."
        ),
        "confidence": "high",
    }


def _fallback_duplicate_invoice(alert: Dict[str, Any], evidence: Dict[str, Any]) -> Dict[str, Any]:
    vendor = alert.get("vendor_name") or "the vendor"
    current = evidence.get("current_invoice") or {}
    dup = evidence.get("duplicate_invoice") or {}
    matched = evidence.get("matched_fields") or []
    invoice_no = current.get("invoice_no") or "unknown"
    dup_date = str(dup.get("invoice_date", "unknown date"))
    fields_str = ", ".join(matched) if matched else "invoice number"
    return {
        "summary": (
            f"Invoice #{invoice_no} from {vendor} appears to be a duplicate of an "
            f"existing invoice filed on {dup_date}."
        ),
        "evidence": [
            f"Matched fields: {fields_str}.",
            f"Existing invoice date: {dup_date}.",
            f"Existing invoice total: {_fmt(dup.get('total'))}.",
        ],
        "why_it_matters": (
            "Processing a duplicate invoice may result in double payment to the vendor."
        ),
        "recommended_action": (
            "Compare both invoices and confirm with the vendor whether this is a "
            "resubmission or an error before approving payment."
        ),
        "confidence": "high",
    }


def _generate_fallback(alert: Dict[str, Any], evidence: Dict[str, Any]) -> Dict[str, Any]:
    alert_type = alert.get("type", "")
    if alert_type == "unit_price_delta":
        return _fallback_unit_price_delta(alert, evidence)
    if alert_type == "vendor_volume_spike":
        return _fallback_vendor_volume_spike(alert, evidence)
    if alert_type == "duplicate_invoice":
        return _fallback_duplicate_invoice(alert, evidence)
    return {
        "summary": alert.get("message") or "An anomaly was detected.",
        "evidence": [],
        "why_it_matters": "Review the alert details for more information.",
        "recommended_action": "Investigate this alert before approving the related invoice.",
        "confidence": "low",
    }


# ---------------------------------------------------------------------------
# Text renderer
# ---------------------------------------------------------------------------

def _render_text(llm_output: Dict[str, Any]) -> str:
    parts = []
    if llm_output.get("summary"):
        parts.append(f"Summary:\n{llm_output['summary']}")
    evidence_items = llm_output.get("evidence") or []
    if evidence_items:
        evidence_block = "\n".join(f"• {e}" for e in evidence_items)
        parts.append(f"Evidence:\n{evidence_block}")
    if llm_output.get("why_it_matters"):
        parts.append(f"Why it matters:\n{llm_output['why_it_matters']}")
    if llm_output.get("recommended_action"):
        parts.append(f"Recommended action:\n{llm_output['recommended_action']}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Response builder
# ---------------------------------------------------------------------------

def _build_response(
    alert: Dict[str, Any],
    evidence: Dict[str, Any],
    llm_output: Dict[str, Any],
    explanation_text: str,
    cached: bool,
    source: str = "llm",
) -> Dict[str, Any]:
    # Normalise evidence for the API response
    current = evidence.get("current_invoice") or evidence.get("duplicate_invoice") or {}
    historical = (
        evidence.get("historical_lines")
        or evidence.get("historical_invoices")
        or []
    )
    metrics = evidence.get("metrics") or {}

    return {
        "alert_id": str(alert["id"]),
        "alert_type": alert["type"],
        "severity": alert.get("severity"),
        "explanation": explanation_text,
        "source": source,
        "llm_output": llm_output,
        "evidence": {
            "current_invoice": current,
            "historical_examples": historical,
            "metrics": metrics,
        },
        "cached": cached,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def explain_alert(
    conn: Connection,
    org_id: str,
    alert_id: str,
    force: bool = False,
) -> Dict[str, Any]:
    """Generate (or return cached) explanation for the given alert.

    Parameters
    ----------
    conn:
        Active psycopg connection with org GUC already set by the route.
    org_id:
        Organisation scope — must match the alert's org_id.
    alert_id:
        UUID of the alert to explain.
    force:
        If True, regenerate even if a cached explanation exists.

    Returns
    -------
    dict with alert_id, alert_type, severity, explanation, evidence, cached.

    Raises
    ------
    ValueError if the alert is not found or the type is unsupported.
    """
    alert = get_alert(conn, org_id, alert_id)
    if alert is None:
        raise ValueError(f"Alert {alert_id} not found for org {org_id}")

    if alert["type"] not in SUPPORTED_TYPES:
        raise ValueError(f"Unsupported alert type: {alert['type']}")

    # Return cached explanation if available and not forced
    if alert.get("explanation_text") and not force:
        cached_json = alert.get("explanation_json") or {}
        return _build_response(
            alert=alert,
            evidence={},
            llm_output=cached_json,
            explanation_text=alert["explanation_text"],
            cached=True,
            source=cached_json.get("source", "llm"),
        )

    evidence = retrieve_evidence(conn, alert)
    prompt = _build_prompt(alert, evidence)

    try:
        llm_output = generate_explanation(prompt)
        llm_output["source"] = "llm"
    except LLMUnavailableError:
        llm_output = _generate_fallback(alert, evidence)
        llm_output["source"] = "template"

    explanation_text = _render_text(llm_output)
    save_explanation(conn, org_id, alert_id, explanation_text, llm_output)

    return _build_response(
        alert=alert,
        evidence=evidence,
        llm_output=llm_output,
        explanation_text=explanation_text,
        cached=False,
        source=llm_output["source"],
    )
