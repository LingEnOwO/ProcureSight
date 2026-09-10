from typing import Any, Dict, List, Optional, Sequence

from psycopg.rows import dict_row


async def search_chunks_by_embedding(
    db: Any,
    *,
    org_id: str,
    embedding: Sequence[float],
    source_types: Optional[List[str]] = None,
    limit: int = 5,
    min_similarity: float,
) -> List[Dict[str, Any]]:
    """
    Return the doc_chunks closest to `embedding` by cosine distance, nearest first.

    Only chunks whose similarity is at least `min_similarity` are returned. The
    floor is applied inside the query rather than by the caller because it and
    `limit` decide together which rows come back — filtering afterwards would
    yield a different set.

    `source_types` of None means every source type.
    """
    vector_str = "[" + ",".join(str(v) for v in embedding) + "]"
    query = """
        SELECT
          id,
          source_type,
          source_name,
          chunk_text,
          meta_json,
          1 - (embedding <=> %(vec)s::vector) AS similarity
        FROM doc_chunks
        WHERE org_id = %(org_id)s
          AND embedding IS NOT NULL
          AND (%(types)s::text[] IS NULL OR source_type = ANY(%(types)s::text[]))
          AND 1 - (embedding <=> %(vec)s::vector) >= %(min_sim)s
        ORDER BY embedding <=> %(vec)s::vector
        LIMIT %(limit)s
    """
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            query,
            {
                "vec": vector_str,
                "org_id": org_id,
                "types": source_types,
                "limit": limit,
                "min_sim": min_similarity,
            },
        )
        return await cur.fetchall()
