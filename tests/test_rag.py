import json

import chromadb
import pytest
from chromadb.config import Settings
from pydantic import ValidationError

from app.config import ROOT
from app.rag.artifacts import export_vectors, restore_vectors
from app.rag.chunks import digest, load_chunks, prepare_chunks
from app.rag.embeddings import (
    CachedEmbeddings,
    EmbeddingSpec,
    EmbeddingUnavailable,
    OfflineTestEmbeddings,
    openai_backend,
)
from app.rag.evaluation import evaluate_retrieval, rule_group_recall
from app.rag.retrieval import PolicyIndex
from app.tools import policies


def forbidden_backend():
    pytest.fail("An offline check must not construct an API backend")


def test_recall_all_any_and_empty_references():
    assert rule_group_recall(["a", "b"], ["a", "a"]) == 0.5
    assert rule_group_recall(["a", "b"], ["b"], match="any") == 1.0
    assert rule_group_recall(["a"], ["b"]) == 0.0
    with pytest.raises(ValueError, match="No positive"):
        rule_group_recall([], [])


def offline_cache(path):
    return CachedEmbeddings(
        path,
        EmbeddingSpec(provider="offline_test", model="sha256-test-v1", dimensions=16),
        OfflineTestEmbeddings,
    )


def test_whole_rules_provenance_and_deterministic_artifacts(tmp_path):
    chunks = prepare_chunks(output=tmp_path)
    first = (tmp_path / "policy_chunks.jsonl").read_bytes()
    assert len(chunks) == 11
    rules = json.loads((ROOT / "data/policies/curated/rule_groups.json").read_text("utf-8"))[
        "rule_groups"
    ]
    for chunk, rule in zip(chunks, rules, strict=True):
        assert chunk.text == rule["text"]
        assert chunk.embedding_text == f"{rule['title']}\n{rule['heading']}\n{rule['text']}"
        assert rule["review_summary"] not in chunk.embedding_text
        assert str(chunk.source_url) == rule["source_url"]
        assert chunk.collected_at.isoformat() == rule["collected_at"]
        assert chunk.effective_date is None
        assert chunk.text_sha256 == digest(chunk.text.encode())
    cancellation = next(c for c in chunks if c.rule_group_id == "order-cancellation")
    assert all(term in cancellation.text for term in ["출고 준비 중", "Visa", "단일 품목"])
    prepare_chunks(output=tmp_path)
    assert (tmp_path / "policy_chunks.jsonl").read_bytes() == first
    assert load_chunks(tmp_path)[0] == chunks
    (tmp_path / "policy_chunks.jsonl").write_bytes(first + b" ")
    with pytest.raises(ValueError, match="checksum"):
        load_chunks(tmp_path)


def test_cache_reuses_duplicates_across_instances_without_backend(tmp_path):
    cache = offline_cache(tmp_path)
    vectors = cache.embed_documents(["alpha", "beta", "alpha"])
    assert vectors[0] == vectors[2]
    assert cache.new_vectors == 2
    assert cache.backend_batches == 1
    restored = CachedEmbeddings(tmp_path, cache.spec, forbidden_backend)
    assert restored.embed_documents(["beta", "alpha"]) == [vectors[1], vectors[0]]
    assert restored.new_vectors == 0
    assert restored.cache_hits == 2
    real = CachedEmbeddings(tmp_path, EmbeddingSpec(), forbidden_backend)
    assert real.directory != cache.directory


def test_cache_rejects_corruption_and_disabled_api(tmp_path):
    cache = offline_cache(tmp_path)
    cache.embed_query("alpha")
    path = cache.directory / f"{digest(b'alpha')}.json"
    record = json.loads(path.read_text())
    record["vector"] = [0.0] * 16
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="nonzero"):
        cache.embed_query("alpha")
    with pytest.raises(EmbeddingUnavailable, match="disabled"):
        openai_backend(EmbeddingSpec())


@pytest.fixture
def policy_index(tmp_path):
    chunks = prepare_chunks(output=tmp_path / "chunks")
    _, manifest = load_chunks(tmp_path / "chunks")
    cache = offline_cache(tmp_path / "cache")
    client = chromadb.EphemeralClient(Settings(anonymized_telemetry=False))
    index = PolicyIndex(chunks, manifest, cache, tmp_path / "index", client=client)
    try:
        yield index, chunks
    finally:
        client.delete_collection(index.store._collection.name)


def test_chroma_idempotence_sources_relations_and_filters(policy_index):
    index, chunks = policy_index
    assert index.build()["new_chunks"] == 11
    assert index.build()["new_chunks"] == 0
    assert index.embeddings.new_vectors == 11
    target = next(c for c in chunks if c.rule_group_id == "returns-process")
    result = index.search(target.embedding_text, top_k=1)
    assert result.seed_rule_groups == ["returns-process"]
    assert {h.source.rule_group_id for h in result.hits} == {"returns-process", "returns-standard"}
    assert len({h.source.evidence_id for h in result.hits}) == 2
    assert result.answerability_assessed is False
    for hit in result.hits:
        original = index.by_group[hit.source.rule_group_id]
        assert hit.source.excerpt == original.text
        assert hit.source.source_url == original.source_url
        assert hit.source.collected_at == original.collected_at
        assert hit.source.effective_date is None
    filtered = index.search(target.embedding_text, topic="shipping")
    assert all(index.by_group[g].topic == "shipping" for g in filtered.seed_rule_groups)
    with pytest.raises(ValueError, match="Synthetic"):
        evaluate_retrieval(index, {})


def test_index_rejects_corrupt_filter_metadata_and_manifest(policy_index):
    index, chunks = policy_index
    index.build()
    chunk = chunks[0]
    index.store._collection.update(ids=[chunk.chunk_id], metadatas=[{"topic": "bad"}])
    with pytest.raises(ValueError, match="frozen corpus"):
        index.search("query")
    path = index.directory / "index_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["fingerprint"] = "wrong"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest"):
        index.search("query")


def test_real_tool_does_not_use_offline_index(tmp_path, monkeypatch):
    (tmp_path / "data/runtime/chroma-offline").mkdir(parents=True)
    monkeypatch.setattr(policies, "ROOT", tmp_path)
    monkeypatch.setattr(policies, "openai_backend", forbidden_backend)
    result = policies.search_policy_result("policy query")
    assert result.kind == "not_ready"
    assert result.embedding_provider == "openai"
    assert result.hits == []


def test_frozen_vectors_restore_without_backend_and_repeat(policy_index, tmp_path):
    index, chunks = policy_index
    index.build()
    source = tmp_path / "frozen"
    manifest = export_vectors(index, source)
    first = (source / "embeddings.jsonl").read_bytes()
    assert export_vectors(index, source) == manifest
    assert (source / "embeddings.jsonl").read_bytes() == first
    query = chunks[0].embedding_text
    before = index.search(query)
    # Keep the query cache, but prevent any embedding backend construction.
    index.embeddings.backend = forbidden_backend
    index.store.delete(ids=list(index.chunks))
    assert index.store._collection.count() == 0
    assert restore_vectors(index, source)["new_chunks"] == 11
    assert restore_vectors(index, source)["new_chunks"] == 0
    after = index.search(query)
    assert after.seed_rule_groups == before.seed_rule_groups
    assert [h.source for h in after.hits] == [h.source for h in before.hits]


@pytest.mark.parametrize("damage", ["bytes", "model", "dimension", "input", "ids"])
def test_invalid_frozen_bundle_rejected_before_insertion(policy_index, tmp_path, damage):
    index, _ = policy_index
    index.build()
    source = tmp_path / "frozen"
    manifest = export_vectors(index, source)
    path = source / "embeddings.jsonl"
    rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    if damage == "model":
        manifest["spec"]["model"] = "wrong-model"
    elif damage == "dimension":
        rows[0]["vector"] = [1.0]
    elif damage == "input":
        rows[0]["embedding_text_sha256"] = "wrong-input"
    elif damage == "ids":
        rows[0]["chunk_id"] = rows[1]["chunk_id"]
    content = "".join(json.dumps(row) + "\n" for row in rows)
    if damage == "bytes":
        content += " "
    path.write_text(content, encoding="utf-8", newline="\n")
    if damage != "bytes":
        manifest["vectors_sha256"] = digest(content.encode())
    (source / "index_manifest.json").write_text(json.dumps(manifest))
    index.store.delete(ids=list(index.chunks))
    with pytest.raises(ValueError):
        restore_vectors(index, source)
    assert index.store._collection.count() == 0


@pytest.mark.parametrize("query", ["   ", "x" * 1001, 123])
def test_tool_invalid_input_rejected_before_index_access(query):
    with pytest.raises(ValidationError):
        policies.search_policy.invoke({"query": query})


@pytest.mark.parametrize("failure,kind", [(ValueError, "not_ready"), (RuntimeError, "error")])
def test_tool_errors_are_distinct_and_do_not_expose_exception(tmp_path, monkeypatch, failure, kind):
    directory = tmp_path / "data/runtime/chroma"
    directory.mkdir(parents=True)
    (directory / "index_manifest.json").write_text("{}")
    monkeypatch.setattr(policies, "ROOT", tmp_path)

    def broken_load():
        raise failure("private-local-path-and-provider-payload")

    monkeypatch.setattr(policies, "load_chunks", broken_load)
    result = policies.search_policy.invoke({"query": "valid query"})
    assert result["kind"] == kind
    assert result["hits"] == []
    assert "private-local" not in str(result)


def test_versioned_real_bundle_restores_with_empty_cache_and_no_api(tmp_path):
    chunks, manifest = load_chunks()
    cache = CachedEmbeddings(tmp_path / "empty-cache", EmbeddingSpec(), forbidden_backend)
    client = chromadb.EphemeralClient(Settings(anonymized_telemetry=False))
    index = PolicyIndex(chunks, manifest, cache, tmp_path / "real-index", client=client)
    try:
        assert restore_vectors(index)["new_chunks"] == 11
        assert restore_vectors(index)["new_chunks"] == 0
        first = json.loads((ROOT / "artifacts/embeddings.jsonl").read_text().splitlines()[0])
        result = index.store._collection.query(query_embeddings=[first["vector"]], n_results=1)
        assert result["ids"][0] == [first["chunk_id"]]
        assert cache.new_vectors == cache.backend_batches == 0
        assert not cache.directory.exists()
    finally:
        client.delete_collection(index.store._collection.name)
