import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from langchain_core.embeddings import Embeddings

from app.rag.chunks import digest, write_json


class EmbeddingUnavailable(ValueError):
    """A cache miss requires an explicitly enabled provider."""


def validate_vector(vector: list, dimensions: int) -> list[float]:
    if len(vector) != dimensions:
        raise ValueError("Embedding dimension mismatch")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in vector):
        raise ValueError("Embedding must contain numbers")
    if not all(math.isfinite(value) for value in vector) or not any(vector):
        raise ValueError("Embedding must be finite and nonzero")
    return [float(value) for value in vector]


@dataclass(frozen=True)
class EmbeddingSpec:
    provider: str = "openai"
    model: str = "text-embedding-3-small"
    dimensions: int = 1536

    @property
    def namespace(self) -> str:
        return digest(json.dumps(asdict(self), sort_keys=True).encode())[:16]


class CachedEmbeddings(Embeddings):
    """Content-addressed cache, separate for each provider/model/dimension tuple."""

    def __init__(
        self, directory: Path, spec: EmbeddingSpec, backend: Callable[[], Embeddings]
    ) -> None:
        if spec.dimensions < 1:
            raise ValueError("Embedding dimensions must be positive")
        self.directory = directory / spec.namespace
        self.spec = spec
        self.backend = backend
        self.cache_hits = 0
        self.new_vectors = 0
        self.backend_batches = 0

    def _validate(self, vector: list) -> list[float]:
        return validate_vector(vector, self.spec.dimensions)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if any(not text.strip() for text in texts):
            raise ValueError("Empty embedding input")
        vectors = {}
        pending = {}
        for text in texts:
            key = digest(text.encode("utf-8"))
            if key in vectors or key in pending:
                continue
            path = self.directory / f"{key}.json"
            if path.exists():
                record = json.loads(path.read_text("utf-8"))
                if record["spec"] != asdict(self.spec) or record["text_sha256"] != key:
                    raise ValueError("Embedding cache identity mismatch")
                vectors[key] = self._validate(record["vector"])
                self.cache_hits += 1
            else:
                pending[key] = text
        if pending:
            # Lazy construction: cached vectors can be reused without an API key.
            values = self.backend().embed_documents(list(pending.values()))
            self.backend_batches += 1
            if len(values) != len(pending):
                raise ValueError("Embedding batch length mismatch")
            checked = [self._validate(vector) for vector in values]
            for key, vector in zip(pending, checked, strict=True):
                write_json(
                    self.directory / f"{key}.json",
                    {
                        "spec": asdict(self.spec),
                        "text_sha256": key,
                        "vector": vector,
                    },
                )
                vectors[key] = vector
                self.new_vectors += 1
        return [vectors[digest(text.encode("utf-8"))] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class OfflineTestEmbeddings(Embeddings):
    """Stable hash vectors for plumbing tests. No language/semantic retrieval quality."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [
            [(value - 127.5) / 127.5 for value in hashlib.sha256(text.encode()).digest()[:16]]
            for text in texts
        ]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def openai_backend(spec: EmbeddingSpec, *, allow_api: bool = False) -> Embeddings:
    if not allow_api:
        raise EmbeddingUnavailable("API calls disabled; enable only when explicitly requested")
    from langchain_openai import OpenAIEmbeddings

    from app.config import get_settings

    key = get_settings().openai_api_key.get_secret_value().strip()
    if not key:
        raise EmbeddingUnavailable("OPENAI_API_KEY is not configured")
    return OpenAIEmbeddings(
        model=spec.model,
        dimensions=spec.dimensions,
        api_key=key,
        max_retries=0,
        request_timeout=30,
        check_embedding_ctx_length=False,
    )
