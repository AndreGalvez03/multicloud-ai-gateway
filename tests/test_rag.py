from datetime import datetime

from aigw.rag import InMemoryVectorStore, chunk_text, hash_embedding


def test_chunks_cover_the_text_with_overlap() -> None:
    text = "a" * 1000
    chunks = chunk_text(text, size=400, overlap=50)
    assert len(chunks) > 1
    assert "".join(chunks) != text  # overlap means the join is longer
    assert chunks[0][-50:] == chunks[1][:50]
    assert chunk_text("   ") == []


def test_search_is_scoped_to_the_team() -> None:
    store = InMemoryVectorStore()
    now = datetime(2026, 10, 1, 12, 0, 0)
    refund = "Refunds are allowed for 30 days if the policy window is open."
    snacks = "The office snacks menu lists fruit on Friday."
    store.replace_document(
        team_id="payments",
        document_id="refunds",
        chunks=[(refund, hash_embedding(refund))],
        now=now,
    )
    store.replace_document(
        team_id="payments",
        document_id="snacks",
        chunks=[(snacks, hash_embedding(snacks))],
        now=now,
    )
    store.replace_document(
        team_id="growth",
        document_id="secret",
        chunks=[("refund policy window for growth only", hash_embedding("refund policy window"))],
        now=now,
    )
    hits = store.search(team_id="payments", embedding=hash_embedding("refund policy window"), k=2)
    assert hits
    assert hits[0].document_id == "refunds"
    assert all(hit.document_id != "secret" for hit in hits)
