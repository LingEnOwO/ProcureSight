"""
Document chunking and indexing pipeline.

Reads .txt and .md files from a directory, splits them into overlapping
text chunks, generates embeddings, and upserts into doc_chunks. Idempotent:
re-running will update existing chunks in place.
"""
import json
import os
from pathlib import Path
from typing import List, Tuple

import psycopg

from .embeddings import embed_texts
from .llm_client import LLMUnavailableError


def _chunk_text(text: str, chunk_size: int = 400, overlap: int = 80) -> List[str]:
    """Split text into overlapping fixed-size character chunks.

    Prefers splitting on paragraph boundaries (double newline). Falls back to
    fixed-window sliding when a paragraph is too long.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    current = ""

    for para in paragraphs:
        if len(para) <= chunk_size:
            if len(current) + len(para) + 2 <= chunk_size:
                current = f"{current}\n\n{para}".strip() if current else para
            else:
                if current:
                    chunks.append(current)
                current = para
        else:
            # Paragraph is too long — flush current then slide over the paragraph
            if current:
                chunks.append(current)
                current = ""
            start = 0
            while start < len(para):
                end = start + chunk_size
                chunks.append(para[start:end])
                start += chunk_size - overlap

    if current:
        chunks.append(current)

    return [c for c in chunks if c.strip()]


def index_documents(
    conn: psycopg.Connection,
    org_id: str,
    docs_dir: str,
    source_type: str,
    chunk_size: int = 400,
    overlap: int = 80,
) -> dict:
    """Chunk, embed, and upsert every .txt and .md file in docs_dir.

    Parameters
    ----------
    conn:
        Sync psycopg3 connection (no RLS GUC required — uses superuser URL).
    org_id:
        Organisation to scope chunks to.
    docs_dir:
        Directory containing source documents.
    source_type:
        Label stored on each chunk: 'contract' or 'policy'.
    chunk_size:
        Target character count per chunk.
    overlap:
        Character overlap between consecutive chunks.

    Returns
    -------
    dict with keys 'indexed' (chunks written) and 'files' (files processed).
    """
    docs_path = Path(docs_dir)
    files = sorted(
        f for f in docs_path.iterdir()
        if f.is_file() and f.suffix.lower() in {".txt", ".md"}
    )

    total_indexed = 0
    files_processed = 0

    for filepath in files:
        source_name = filepath.name
        text = filepath.read_text(encoding="utf-8", errors="replace")
        chunks = _chunk_text(text, chunk_size=chunk_size, overlap=overlap)
        if not chunks:
            continue

        try:
            vectors = embed_texts(chunks)
        except LLMUnavailableError:
            # Store chunks without embeddings so the table is populated;
            # vector search will simply return no results until re-indexed.
            vectors = [None] * len(chunks)

        with conn.cursor() as cur:
            for idx, (chunk_text, vector) in enumerate(zip(chunks, vectors)):
                vector_str = _format_vector(vector)
                cur.execute(
                    """
                    INSERT INTO doc_chunks
                      (org_id, source_type, source_name, chunk_index, chunk_text, embedding, meta_json)
                    VALUES (%s, %s, %s, %s, %s, %s::vector, %s)
                    ON CONFLICT (org_id, source_type, source_name, chunk_index)
                    DO UPDATE SET
                      chunk_text = EXCLUDED.chunk_text,
                      embedding  = EXCLUDED.embedding,
                      meta_json  = EXCLUDED.meta_json
                    """,
                    (
                        org_id,
                        source_type,
                        source_name,
                        idx,
                        chunk_text,
                        vector_str,
                        json.dumps({"file": source_name, "chunk_index": idx}),
                    ),
                )
                total_indexed += 1

        conn.commit()
        files_processed += 1
        print(f"  indexed {len(chunks)} chunks from {source_name}")

    return {"indexed": total_indexed, "files": files_processed}


def _format_vector(vector) -> str | None:
    """Format a float list as a pgvector literal string, or None if absent."""
    if vector is None:
        return None
    return "[" + ",".join(str(v) for v in vector) + "]"
