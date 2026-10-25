import json
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from chromadb.config import Settings as ChromaSettings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from pydantic import BaseModel, Field

from app.consultation_contract import PolicySource
from app.rag.chunks import PolicyChunk, digest, write_json
from app.rag.embeddings import CachedEmbeddings


class PolicyHit(BaseModel):
    source: PolicySource
    distance: float | None
    reason: Literal["retrieved", "related_condition"]


class PolicySearchResult(BaseModel):
    kind: Literal["candidates", "not_ready", "error"]
    query: str
    top_k: int = 4
    hits: list[PolicyHit] = Field(default_factory=list)
    seed_rule_groups: list[str] = Field(default_factory=list)
    embedding_provider: str
    answerability_assessed: Literal[False] = False
    message: str


class PolicyIndex:
    def __init__(
        self,
        chunks: list[PolicyChunk],
        manifest: dict,
        embeddings: CachedEmbeddings,
        directory: Path,
        *,
        client=None,
    ) -> None:
        self.chunks = {chunk.chunk_id: chunk for chunk in chunks}
        self.by_group = {chunk.rule_group_id: chunk for chunk in chunks}
        self.embeddings = embeddings
        self.manifest = manifest
        self.directory = directory
        self.fingerprint = digest(
            json.dumps(
                {
                    "chunks": manifest["chunks_sha256"],
                    "spec": asdict(embeddings.spec),
                },
                sort_keys=True,
            ).encode()
        )
        arguments = (
            {"client": client} if client is not None else {"persist_directory": str(directory)}
        )
        self.store = Chroma(
            collection_name="policies-" + self.fingerprint[:20],
            embedding_function=embeddings,
            collection_metadata={"hnsw:space": "cosine"},
            client_settings=ChromaSettings(anonymized_telemetry=False),
            **arguments,
        )

    def _check_contents(self, *, allow_partial: bool = False) -> set[str]:
        stored = self.store.get(include=["documents", "metadatas"])
        found = set(stored["ids"])
        if not found.issubset(self.chunks):
            raise ValueError("Index contains unknown chunks")
        if not allow_partial and found != set(self.chunks):
            raise ValueError("Policy index is incomplete; build it first")
        for key, text, metadata in zip(
            stored["ids"], stored["documents"], stored["metadatas"], strict=True
        ):
            chunk = self.chunks[key]
            expected = {
                "chunk_id": key,
                "rule_group_id": chunk.rule_group_id,
                "topic": chunk.topic,
            }
            if text != chunk.embedding_text or metadata != expected:
                raise ValueError("Index content does not match the frozen corpus")
        return found

    def build(self) -> dict:
        existing = self._check_contents(allow_partial=True)
        missing = [chunk for key, chunk in self.chunks.items() if key not in existing]
        if missing:
            self.store.add_documents(
                [
                    Document(
                        page_content=chunk.embedding_text,
                        metadata={
                            "chunk_id": chunk.chunk_id,
                            "rule_group_id": chunk.rule_group_id,
                            "topic": chunk.topic,
                        },
                    )
                    for chunk in missing
                ],
                ids=[chunk.chunk_id for chunk in missing],
            )
        self._check_contents()
        return self.mark_ready(new_chunks=len(missing))

    def mark_ready(self, *, new_chunks: int) -> dict:
        self._check_contents()
        status = {
            "fingerprint": self.fingerprint,
            "spec": asdict(self.embeddings.spec),
            "chunk_count": len(self.chunks),
            "new_chunks": new_chunks,
            "stage": "ready",
            "semantic_quality_evaluated": False,
        }
        write_json(self.directory / "index_manifest.json", status)
        return status

    def search(
        self,
        query: str,
        *,
        top_k: int = 4,
        topic: Literal["shipping", "cancellation", "returns"] | None = None,
    ) -> PolicySearchResult:
        query = query.strip()
        if not query or len(query) > 1000 or not 1 <= top_k <= 4:
            raise ValueError("Query must be 1..1000 chars; top_k must be 1..4")
        ready = json.loads((self.directory / "index_manifest.json").read_text("utf-8"))
        if ready["fingerprint"] != self.fingerprint or ready["stage"] != "ready":
            raise ValueError("Index manifest does not match the current corpus/model")
        self._check_contents()
        matches = self.store.similarity_search_with_score(
            query,
            k=min(top_k, len(self.chunks)),
            filter={"topic": topic} if topic else None,
        )
        selected = {}
        seeds = []
        for document, distance in matches:
            key = document.metadata["chunk_id"]
            chunk = self.chunks[key]
            seeds.append(chunk.rule_group_id)
            selected[key] = (chunk, float(distance), "retrieved")
        # Expand related conditions transitively without duplicate evidence or loops.
        queue = [value[0] for value in selected.values()]
        for chunk in queue:
            for group_id in chunk.related_rule_groups:
                related = self.by_group[group_id]
                if related.chunk_id not in selected:
                    selected[related.chunk_id] = (related, None, "related_condition")
                    queue.append(related)
        hits = [
            PolicyHit(
                source=PolicySource(
                    evidence_id="evidence-" + chunk.chunk_id,
                    document_id=chunk.document_id,
                    rule_group_id=chunk.rule_group_id,
                    chunk_id=chunk.chunk_id,
                    title=chunk.title,
                    heading=chunk.heading,
                    source_url=chunk.source_url,
                    collected_at=chunk.collected_at,
                    effective_date=chunk.effective_date,
                    excerpt=chunk.text,
                ),
                distance=distance,
                reason=reason,
            )
            for chunk, distance, reason in selected.values()
        ]
        return PolicySearchResult(
            kind="candidates",
            query=query,
            top_k=top_k,
            hits=hits,
            seed_rule_groups=seeds,
            embedding_provider=self.embeddings.spec.provider,
            message="검색 후보입니다. 거리는 정답 확률이 아니며 답변 가능 여부는 미판정입니다.",
        )
