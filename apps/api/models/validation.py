from typing import List, Optional
from pydantic import BaseModel, Field
from .invoice import Invoice

class ValidationIssue(BaseModel):
    field: str          # e.g. "lines[3].line_total" or "subtotal"
    code: str           # e.g. "LINE_TOTAL_MISMATCH"
    message: str        # human-readable explanation
    diff: Optional[float] = None  # numeric difference when it makes sense

class ValidationReport(BaseModel):
    errors: List[ValidationIssue] = Field(default_factory=list)
    warnings: List[ValidationIssue] = Field(default_factory=list)
    normalized_invoice: Invoice  # often same as input, sometimes with tiny fixes

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)
    
    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)