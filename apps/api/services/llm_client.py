"""
LLM client for generating alert explanations.

Uses the same OpenAI client pattern as unstructured_extract.py.
If OPENAI_API_KEY is not set, raises LLMUnavailableError so the caller
can fall back to deterministic template-based explanations.
"""
import json
import os
from typing import Any, Dict

from openai import OpenAI, APIError, APITimeoutError, RateLimitError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


class LLMUnavailableError(Exception):
    pass


_EXPLANATION_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "evidence": {
            "type": "array",
            "items": {"type": "string"},
        },
        "why_it_matters": {"type": "string"},
        "recommended_action": {"type": "string"},
        "confidence": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
    },
    "required": ["summary", "evidence", "why_it_matters", "recommended_action", "confidence"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You are a procurement analyst assistant. Given an anomaly alert and supporting "
    "invoice evidence, produce a concise, factual explanation for a reviewer. "
    "Be professional and direct. Do not invent data not present in the evidence. "
    "If evidence is insufficient, say so clearly. "
    "Output only valid JSON matching the provided schema."
)


def generate_explanation(prompt: str) -> Dict[str, Any]:
    """Call GPT-4o to generate a structured alert explanation.

    Raises LLMUnavailableError if OPENAI_API_KEY is not configured.
    Retries up to 3 times on transient API errors.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise LLMUnavailableError("OPENAI_API_KEY is not set")

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
            temperature=0.0,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "alert_explanation",
                    "strict": True,
                    "schema": _EXPLANATION_JSON_SCHEMA,
                },
            },
        )
        content = response.choices[0].message.content
        return json.loads(content)

    return _call()
