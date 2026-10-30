"""Prepare fixed demo data before the deployment server accepts requests."""

from pathlib import Path

from app.config import ROOT, Settings
from app.rag.artifacts import restore_vectors
from app.rag.chunks import ARTIFACTS, load_chunks
from app.rag.embeddings import CachedEmbeddings, EmbeddingSpec, openai_backend
from app.rag.retrieval import PolicyIndex
from scripts.init_orders_db import build_database


def prepare_runtime(
    settings: Settings,
    *,
    index_directory: Path = ROOT / "data/runtime/chroma",
    artifact_directory: Path = ARTIFACTS,
) -> dict:
    db_digest = build_database(settings.db_path)
    chunks, manifest = load_chunks(artifact_directory)
    spec = EmbeddingSpec(model=settings.openai_embedding_model)
    embeddings = CachedEmbeddings(
        ROOT / ".cache/rag-embeddings",
        spec,
        # Startup must remain offline even when requests are allowed to use the API.
        lambda: openai_backend(spec, allow_api=False),
    )
    index = PolicyIndex(chunks, manifest, embeddings, index_directory)
    policy = restore_vectors(index, artifact_directory)
    return {
        "database_sha256": db_digest,
        "policy_fingerprint": policy["fingerprint"],
        "policy_chunks": policy["chunk_count"],
        "restored_chunks": policy["new_chunks"],
        "embedding_backend_batches": embeddings.backend_batches,
    }
