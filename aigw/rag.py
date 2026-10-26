"""Minimal RAG: chunk text, embed it, store vectors per team.

PgVectorStore is used when the database is Postgres. Tests and the sqlite
fallback use an in-memory cosine store with the same interface. Embeddings
come from the gateway's embedding route so residency rules still apply.
"""

from __future__ import annotations

import hashlib
import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.engine import Engine

TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class SearchHit:
    document_id: str
    content: str
    score: float


def chunk_text(text: str, size: int = 480, overlap: int = 80) -> list[str]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("chunk size must be positive and larger than overlap")
    cleaned = text.strip()
    if not cleaned:
        return []
    if len(cleaned) <= size:
        return [cleaned]
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + size)
        chunks.append(cleaned[start:end])
        if end == len(cleaned):
            break
        start = end - overlap
    return chunks


def hash_embedding(text: str, dim: int = 64) -> list[float]:
    """Deterministic bag-of-tokens embedding.

    The mock provider implements the same function so local RAG retrieves
    related chunks without a hosted embedding model. Keep the two copies identical.
    """
    if dim <= 0:
        raise ValueError("dimension must be positive")
    vector = [0.0] * dim
    tokens = TOKEN.findall(text.lower()) or ["empty"]
    for token in tokens:
        digest = hashlib.sha256(token.encode()).digest()
        bucket = int.from_bytes(digest[:2], "big") % dim
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine(left: list[float] | tuple[float, ...], right: list[float] | tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._rows: list[tuple[str, str, str, str, tuple[float, ...]]] = []

    def replace_document(
        self,
        *,
        team_id: str,
        document_id: str,
        chunks: list[tuple[str, list[float]]],
        now: datetime,
    ) -> int:
        self._rows = [row for row in self._rows if not (row[1] == team_id and row[2] == document_id)]
        for content, embedding in chunks:
            self._rows.append((str(uuid.uuid4()), team_id, document_id, content, tuple(embedding)))
        del now
        return len(chunks)

    def search(self, *, team_id: str, embedding: list[float], k: int) -> list[SearchHit]:
        scored = [
            SearchHit(document_id=row[2], content=row[3], score=cosine(row[4], embedding))
            for row in self._rows
            if row[1] == team_id
        ]
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:k]


class PgVectorStore:
    def __init__(self, engine: Engine, dim: int) -> None:
        self.engine = engine
        self.dim = dim

    def ensure(self) -> None:
        with self.engine.begin() as conn:
            conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
            conn.exec_driver_sql(
                f"""
                CREATE TABLE IF NOT EXISTS rag_chunks (
                    id TEXT PRIMARY KEY,
                    team_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    embedding vector({int(self.dim)}) NOT NULL,
                    created_at TIMESTAMP NOT NULL
                )
                """
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_rag_chunks_team ON rag_chunks (team_id, document_id)"
            )

    def replace_document(
        self,
        *,
        team_id: str,
        document_id: str,
        chunks: list[tuple[str, list[float]]],
        now: datetime,
    ) -> int:
        with self.engine.begin() as conn:
            conn.exec_driver_sql(
                "DELETE FROM rag_chunks WHERE team_id = %(team)s AND document_id = %(doc)s",
                {"team": team_id, "doc": document_id},
            )
            for content, embedding in chunks:
                if len(embedding) != self.dim:
                    raise ValueError("embedding dimension does not match the vector column")
                literal = "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"
                conn.exec_driver_sql(
                    """
                    INSERT INTO rag_chunks (id, team_id, document_id, content, embedding, created_at)
                    VALUES (%(id)s, %(team)s, %(doc)s, %(content)s, %(embedding)s::vector, %(ts)s)
                    """,
                    {
                        "id": str(uuid.uuid4()),
                        "team": team_id,
                        "doc": document_id,
                        "content": content,
                        "embedding": literal,
                        "ts": now,
                    },
                )
        return len(chunks)

    def search(self, *, team_id: str, embedding: list[float], k: int) -> list[SearchHit]:
        literal = "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"
        with self.engine.begin() as conn:
            result = conn.exec_driver_sql(
                """
                SELECT document_id, content, 1 - (embedding <=> %(query)s::vector) AS score
                FROM rag_chunks
                WHERE team_id = %(team)s
                ORDER BY embedding <=> %(query)s::vector
                LIMIT %(k)s
                """,
                {"query": literal, "team": team_id, "k": int(k)},
            )
            return [SearchHit(document_id=row[0], content=row[1], score=float(row[2])) for row in result]
