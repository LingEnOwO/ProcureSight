"""
Vector similarity search over doc_chunks.

search_chunks() is the primary interface. It embeds the query, runs a cosine
similarity search, and returns the top-k matching chunks. Returns an empty list
if embeddings are unavailable (graceful degradation).
"""
from typing import Any, Dict, List, Optional

import psycopg

from .embeddings import embed_texts
from .llm_client import LLMUnavailableError
from ..services.doc_indexer import _format_vector


def search_chunks(
    conn: psycopg.Connection,
    org_id: str,
    query: str,
    source_types: Optional[List[str]] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Return top-k doc_chunks most similar to query.

    Parameters
    ----------
    conn:
        Sync psycopg3 connection. The org GUC should be set if RLS is active.
    org_id:
        Organisation scope.
    query:
        Natural-language search query to embed.
    source_types:
        Optional list of source_type values to filter by (e.g. ['contract']).
        If None, searches across all source types.
    limit:
        Maximum number of results to return.

    Returns
    -------
    List of dicts: {id, source_type, source_name, chunk_text, meta_json, similarity}.
    Returns [] on embedding failure so callers degrade gracefully.
    """
    try:
        vectors = embed_texts([query])
    except LLMUnavailableError:
        return []

    vector_str = _format_vector(vectors[0])
    if vector_str is None:
        return []

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              id,
              source_type,
              source_name,
              chunk_text,
              meta_json,
              1 - (embedding <=> %s::vector) AS similarity
            FROM doc_chunks
            WHERE org_id = %s
              AND (%s::text[] IS NULL OR source_type = ANY(%s::text[]))
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (
                vector_str,
                org_id,
                source_types,
                source_types,
                vector_str,
                limit,
            ),
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
