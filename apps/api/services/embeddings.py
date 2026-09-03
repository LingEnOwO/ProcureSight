"""
OpenAI embedding generation.

Provides embed_texts() for batched embedding calls. Raises LLMUnavailableError
when OPENAI_API_KEY is not configured so callers can degrade gracefully.
"""
from typing import List

from openai import OpenAI, APIError, APITimeoutError, RateLimitError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .llm_client import LLMUnavailableError
from ..settings import settings

_BATCH_SIZE = 100


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Return one embedding vector per input text.

    Batches requests to stay within API limits. Raises LLMUnavailableError if
    OPENAI_API_KEY is not set. Retries up to 3 times on transient API errors.
    """
    api_key = settings.openai_api_key
    if not api_key:
        raise LLMUnavailableError("OPENAI_API_KEY is not set")

    client = OpenAI(api_key=api_key)

    @retry(
        retry=retry_if_exception_type((APIError, APITimeoutError, RateLimitError)),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _call_batch(batch: List[str]) -> List[List[float]]:
        response = client.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=batch,
            dimensions=settings.EMBEDDING_DIMENSIONS,
        )
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]

    results: List[List[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        results.extend(_call_batch(texts[i : i + _BATCH_SIZE]))
    return results
