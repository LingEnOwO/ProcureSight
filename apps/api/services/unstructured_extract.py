from __future__ import annotations
import io, json, os
import pdfplumber
from openai import OpenAI, APIError, APITimeoutError, RateLimitError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from typing import Any, Dict
from ..models.invoice import Invoice

"""
Services for turning unstructured invoice documents (e.g. PDFs) into
structured Invoice objects.

Uses GPT-4o with json_schema structured output for guaranteed valid JSON,
and tenacity retry with exponential backoff for transient API errors.
"""

# JSON Schema passed to OpenAI structured outputs (strict mode).
# All properties must be in `required`; nullable fields use anyOf + null.
_INVOICE_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "invoice_no": {"type": "string"},
        "vendor": {"type": "string"},
        "invoice_date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
        "due_date": {
            "anyOf": [
                {"type": "string", "description": "ISO date YYYY-MM-DD"},
                {"type": "null"},
            ]
        },
        "currency": {"type": "string", "description": "ISO 4217 code, e.g. USD"},
        "subtotal": {"type": "number"},
        "tax": {"type": "number"},
        "total": {"type": "number"},
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sku": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "desc": {"type": "string"},
                    "qty": {"type": "number"},
                    "unit_price": {"type": "number"},
                    "line_total": {"type": "number"},
                },
                "required": ["sku", "desc", "qty", "unit_price", "line_total"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "invoice_no", "vendor", "invoice_date", "due_date",
        "currency", "subtotal", "tax", "total", "lines",
    ],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You are an invoice data extraction API. Extract all invoice fields from the "
    "provided text and return them as a JSON object matching the given schema. "
    "Use null for fields that are genuinely absent in the source document."
)


def extract_text_from_pdf(content: bytes) -> str:
    """Extract plain text from a PDF binary blob using pdfplumber.

    For scanned PDFs that yield no text, consider adding an OCR fallback
    (e.g. Tesseract or AWS Textract) here.
    """
    if not content:
        raise ValueError("Empty PDF content provided to extract_text_from_pdf")

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        texts = []
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if page_text:
                texts.append(page_text)
        return "\n\n".join(texts)


def llm_extract_invoice_from_text(text: str) -> Dict[str, Any]:
    """Call GPT-4o with structured output to extract invoice data from free-form text.

    Uses `response_format: json_schema` (strict mode) so the response is
    guaranteed to match _INVOICE_JSON_SCHEMA — no manual JSON parsing needed.
    Retries up to 3 times on transient API errors with exponential backoff.
    """
    if not text.strip():
        raise ValueError("Empty text provided to llm_extract_invoice_from_text")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set; cannot call OpenAI LLM")

    client = OpenAI(api_key=api_key)

    @retry(
        retry=retry_if_exception_type((APIError, APITimeoutError, RateLimitError)),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _call() -> Dict[str, Any]:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "invoice_extraction",
                    "strict": True,
                    "schema": _INVOICE_JSON_SCHEMA,
                },
            },
            temperature=0.0,
        )
        return json.loads(response.choices[0].message.content)

    return _call()


def extract_invoice_from_pdf(content: bytes) -> Invoice:
    """Go from raw PDF bytes to a validated Invoice model.

    Pipeline:
        PDF bytes → text  (extract_text_from_pdf)
                  → dict  (llm_extract_invoice_from_text)
                  → Invoice(**data)

    Pydantic enforces the schema on Invoice construction; business-rule
    validation (e.g. line total reconciliation) happens in services/validator.py.
    """
    text = extract_text_from_pdf(content)
    doc = llm_extract_invoice_from_text(text)
    return Invoice(**doc)
