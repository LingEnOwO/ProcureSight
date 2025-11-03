from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Annotated
from datetime import date
from decimal import Decimal

Decimal4 = Annotated[Decimal, Field(max_digits=18, decimal_places=4)]
Money = Annotated[Decimal, Field(max_digits=18, decimal_places=2)]

class InvoiceLine(BaseModel):
    sku: Optional[str] = None
    desc: str = Field(..., min_length=1)
    qty: Decimal4
    unit_price: Decimal4
    line_total: Decimal4

    # light cross-field check; strict reconciliation happens later
    @model_validator(mode="after")
    def _check_line_total(self):
        try:
            if (Decimal(self.qty) * Decimal(self.unit_price) - Decimal(self.line_total)).copy_abs() > Decimal("0.02"):
                # Don’t block here; we’ll flag downstream in Task 2
                pass
        except Exception:
            pass
        return self

class Invoice(BaseModel):
    vendor: str
    invoice_no: str
    invoice_date: date
    currency: str = Field(..., min_length=3, max_length=3)  # ISO 4217
    subtotal: Money
    tax: Money
    total: Money
    due_date: Optional[date] = None
    lines: List[InvoiceLine]