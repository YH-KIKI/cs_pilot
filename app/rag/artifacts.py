"""Portable frozen document vectors; no provider calls during export or restore."""

import json
import math
from dataclasses import asdict
from pathlib import Path

from app.rag.chunks import ARTIFACTS, digest, write_json
from app.rag.embeddings import validate_vector
from app.rag.retrieval import PolicyIndex

FORMAT_VERSION = "policy-vectors-v1"


def export_vectors(index: PolicyIndex, output: Path = ARTIFACTS) -> dict:
    index._check_contents()
    # Chroma's persisted float32 values are the source of truth, not a live provider.
    stored = index.store.get(include=["embeddings"])
    vectors = dict(zip(stored["ids"], stored["embeddings"].tolist(), strict=True))
    rows = []
    for key, chunk in index.chunks.items():
        rows.append(
            {
                "chunk_id": key,
                "embedding_text_sha256": digest(chunk.embedding_text.encode("utf-8")),
                "vector": validate_vector(vectors[key], index.embeddings.spec.dimensions),
            }
        )
    content = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    manifest = {
        "format_version": FORMAT_VERSION,
        "corpus_version": index.manifest["corpus_version"],
        "chunking_version": index.manifest["chunking_version"],
        "chunks_sha256": index.manifest["chunks_sha256"],
        "spec": asdict(index.embeddings.spec),
        "fingerprint": index.fingerprint,
        "chunk_count": len(rows),
        "vectors_sha256": digest(content.encode("utf-8")),
        "distance_metric": "cosine",
    }
    output.mkdir(parents=True, exist_ok=True)
    temporary = output / "embeddings.jsonl.tmp"
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(output / "embeddings.jsonl")
    write_json(output / "index_manifest.json", manifest)
    return manifest


def restore_vectors(index: PolicyIndex, source: Path = ARTIFACTS) -> dict:
    manifest = json.loads((source / "index_manifest.json").read_text("utf-8"))
    expected = {
        "format_version": FORMAT_VERSION,
        "corpus_version": index.manifest["corpus_version"],
        "chunking_version": index.manifest["chunking_version"],
        "chunks_sha256": index.manifest["chunks_sha256"],
        "spec": asdict(index.embeddings.spec),
        "fingerprint": index.fingerprint,
        "chunk_count": len(index.chunks),
        "distance_metric": "cosine",
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("Frozen vector manifest does not match corpus/model")
    raw = (source / "embeddings.jsonl").read_bytes()
    if digest(raw) != manifest["vectors_sha256"]:
        raise ValueError("Frozen vector checksum mismatch")
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    if len(rows) != len(index.chunks) or {r["chunk_id"] for r in rows} != set(index.chunks):
        raise ValueError("Frozen vector IDs/count mismatch")
    vectors = {}
    for row in rows:
        chunk = index.chunks[row["chunk_id"]]
        if row["embedding_text_sha256"] != digest(chunk.embedding_text.encode("utf-8")):
            raise ValueError("Frozen vector input checksum mismatch")
        vectors[chunk.chunk_id] = validate_vector(row["vector"], index.embeddings.spec.dimensions)
    # Validate the entire bundle and existing data before adding anything. Never overwrite
    # conflicting records or delete another collection in order to restore.
    existing = index._check_contents(allow_partial=True)
    stored = index.store.get(include=["embeddings"])
    for key, vector in zip(stored["ids"], stored["embeddings"], strict=True):
        if not all(
            math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-7)
            for a, b in zip(vector, vectors[key], strict=True)
        ):
            raise ValueError("Existing index vectors conflict with frozen vectors")
    missing = [chunk for key, chunk in index.chunks.items() if key not in existing]
    if missing:
        index.store._collection.add(
            ids=[chunk.chunk_id for chunk in missing],
            embeddings=[vectors[chunk.chunk_id] for chunk in missing],
            documents=[chunk.embedding_text for chunk in missing],
            metadatas=[
                {"chunk_id": c.chunk_id, "rule_group_id": c.rule_group_id, "topic": c.topic}
                for c in missing
            ],
        )
    return index.mark_ready(new_chunks=len(missing))
