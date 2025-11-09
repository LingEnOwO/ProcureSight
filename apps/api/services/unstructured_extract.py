from __future__ import annotations
import io, json, os
import pdfplumber
from openai import OpenAI
from typing import Any, Dict
from ..models.invoice import Invoice
"""
Services for turning unstructured invoice documents (e.g. PDFs) into
structured Invoice objects.

This module is intentionally LLM-agnostic at v0.1: we provide a stub
`llm_extract_invoice_from_text` that can be replaced later with a real
LLM call. The rest of the pipeline (PDF → text → dict → Invoice) remains
the same.
"""


def extract_text_from_pdf(content: bytes) -> str:
    """
    Extract plain text from a PDF binary blob.

    For v0.1 we use pdfplumber for simplicity. In the future this function
    can be extended to:
      - fall back to an OCR engine (e.g., Tesseract) for scanned PDFs
      - call a managed service like AWS Textract and work from its blocks.

    Returns a single string built by concatenating page texts with newlines.
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
    """Call an LLM to extract structured invoice data from free-form text.

    The returned dict is expected to match the `Invoice` schema defined in
    apps/api/models/invoice.py. Callers are responsible for passing the
    result into `Invoice(**doc)` for schema validation.

    This implementation uses the OpenAI Chat Completions API. You must have
    the `openai` package installed and the `OPENAI_API_KEY` environment
    variable configured for this to work.
    """
    if not text.strip():
        raise ValueError("Empty text provided to llm_extract_invoice_from_text")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set; cannot call OpenAI LLM")

    client = OpenAI(api_key=api_key)

    system_prompt = (
        "You are an API service that extracts structured invoice data from "
        "raw text. Always respond with a single JSON object only, with no "
        "extra commentary or formatting. The JSON must match this schema:\n\n"
        "{\n"
        "  \"invoice_no\": string,\n"
        "  \"vendor\": string,\n"
        "  \"invoice_date\": string (YYYY-MM-DD),\n"
        "  \"due_date\": string or null (YYYY-MM-DD),\n"
        "  \"currency\": string (e.g. 'USD', 'EUR', 'JPY'),\n"
        "  \"subtotal\": number,\n"
        "  \"tax\": number,\n"
        "  \"total\": number,\n"
        "  \"lines\": [\n"
        "    {\n"
        "      \"sku\": string or null,\n"
        "      \"desc\": string,\n"
        "      \"qty\": number,\n"
        "      \"unit_price\": number,\n"
        "      \"line_total\": number\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "If a field is missing in the text, make a best-effort guess or set it "
        "to null where appropriate."
    )

    user_prompt = (
        "Extract the invoice fields described in the schema from the following "
        "text and return only the JSON object.\n\n" + text
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
        )
    except Exception as e:  # pragma: no cover - network / API errors
        raise RuntimeError(f"LLM extraction failed: {e}") from e

    content = response.choices[0].message.content
    # The model has been instructed to return pure JSON, but we defensively
    # attempt to locate the first JSON object in the response.
    content = content.strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Fallback: try to extract the JSON object delimiters
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise RuntimeError("LLM response did not contain valid JSON")
        try:
            return json.loads(content[start : end + 1])
        except json.JSONDecodeError as e:
            raise RuntimeError("Failed to parse JSON from LLM response") from e


def extract_invoice_from_pdf(content: bytes) -> Invoice:
    """
    High-level helper: go from raw PDF bytes to an `Invoice` model.

    Pipeline:
        PDF bytes ──> text (extract_text_from_pdf)
                  ──> dict (llm_extract_invoice_from_text)
                  ──> Invoice(**data)

    Any schema mismatches will raise a Pydantic ValidationError when
    constructing the Invoice; callers (e.g. routes) are expected to catch
    and translate that into an HTTP 422 or similar.
    """
    text = extract_text_from_pdf(content)
    doc = llm_extract_invoice_from_text(text)
    # Let Pydantic enforce the schema here; business validation happens
    # in services/validator.py via `validate_invoice`.
    return Invoice(**doc)
