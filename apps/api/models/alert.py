from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


# Simple container used by the pipeline to represent alerts that should be
# persisted into the `alerts` table. It lives in the models package rather than
# in any one producer so that every alert-producing entry point — and the
# repository that persists them — can depend on it without depending on each
# other.
@dataclass
class AlertCandidate:
    org_id: str
    invoice_id: str
    vendor_id: str
    type: str
    severity: str  # "low" | "medium" | "high" | "critical"
    message: str
    meta: Dict[str, Any]
