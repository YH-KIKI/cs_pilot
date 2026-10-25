import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, HttpUrl

from app.config import ROOT

ARTIFACTS = ROOT / "artifacts"
CHUNKING_VERSION = "rule-group-v1"


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    temporary.replace(path)


class PolicyChunk(BaseModel):
    chunk_id: str
    corpus_version: str
    rule_group_id: str
    document_id: str
    topic: Literal["shipping", "cancellation", "returns"]
    title: str
    heading: str
    source_url: HttpUrl
    collected_at: AwareDatetime
    effective_date: date | None = None
    text: str = Field(min_length=1, max_length=4000)
    text_sha256: str
    related_rule_groups: list[str]

    @property
    def embedding_text(self) -> str:
        # Only official text and its headings. Never embed the reviewer's commentary.
        return f"{self.title}\n{self.heading}\n{self.text}"


def prepare_chunks(
    policy_root: Path = ROOT / "data/policies", output: Path = ARTIFACTS
) -> list[PolicyChunk]:
    manifest = json.loads((policy_root / "manifest.json").read_text("utf-8"))
    curated = policy_root / manifest["curated_path"]
    if digest(curated.read_bytes()) != manifest["curated_sha256"]:
        raise ValueError("Curated policy checksum mismatch")
    documents = {doc["document_id"]: doc for doc in manifest["documents"]}
    for document in documents.values():
        if digest((policy_root / document["raw_path"]).read_bytes()) != document["raw_sha256"]:
            raise ValueError("Raw source checksum mismatch")
    data = json.loads(curated.read_text("utf-8"))
    if data["corpus_version"] != manifest["corpus_version"]:
        raise ValueError("Corpus version mismatch")
    chunks = []
    for rule in data["rule_groups"]:
        document = documents[rule["document_id"]]
        for field in ("title", "source_url", "collected_at", "effective_date", "raw_sha256"):
            if rule[field] != document[field]:
                raise ValueError(f"Policy metadata mismatch: {field}")
        if digest(rule["text"].encode("utf-8")) != rule["text_sha256"]:
            raise ValueError("Rule text checksum mismatch")
        # The 11 reviewed units fit below 4,000 chars: do not split exceptions away.
        identity = f"{CHUNKING_VERSION}:{data['corpus_version']}:{rule['rule_group_id']}"
        identity += ":" + digest(f"{rule['title']}\n{rule['heading']}\n{rule['text']}".encode())
        chunks.append(
            PolicyChunk(
                chunk_id="policy-" + digest(identity.encode())[:24],
                corpus_version=data["corpus_version"],
                **{
                    key: rule[key]
                    for key in PolicyChunk.model_fields
                    if key not in ("chunk_id", "corpus_version")
                },
            )
        )
    groups = {chunk.rule_group_id for chunk in chunks}
    if len(groups) != len(chunks):
        raise ValueError("Duplicate rule groups")
    if any(not set(chunk.related_rule_groups).issubset(groups) for chunk in chunks):
        raise ValueError("Missing related rule group")
    output.mkdir(parents=True, exist_ok=True)
    content = "".join(chunk.model_dump_json() + "\n" for chunk in chunks)
    (output / "policy_chunks.jsonl").write_text(content, encoding="utf-8", newline="\n")
    write_json(
        output / "chunks_manifest.json",
        {
            "corpus_version": data["corpus_version"],
            "chunking_version": CHUNKING_VERSION,
            "chunks_sha256": digest(content.encode("utf-8")),
            "chunk_count": len(chunks),
            "curated_sha256": manifest["curated_sha256"],
            "stage": "prepared_no_vectors",
        },
    )
    return chunks


def load_chunks(directory: Path = ARTIFACTS) -> tuple[list[PolicyChunk], dict]:
    manifest = json.loads((directory / "chunks_manifest.json").read_text("utf-8"))
    raw = (directory / "policy_chunks.jsonl").read_bytes()
    if digest(raw) != manifest["chunks_sha256"]:
        raise ValueError("Chunk artifact checksum mismatch")
    chunks = [PolicyChunk.model_validate_json(line) for line in raw.decode("utf-8").splitlines()]
    if len(chunks) != manifest["chunk_count"] or not chunks:
        raise ValueError("Chunk count mismatch")
    if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
        raise ValueError("Duplicate chunk IDs")
    groups = {chunk.rule_group_id for chunk in chunks}
    if len(groups) != len(chunks):
        raise ValueError("Duplicate rule groups")
    if any(not set(chunk.related_rule_groups).issubset(groups) for chunk in chunks):
        raise ValueError("Missing related rule group")
    for chunk in chunks:
        if chunk.corpus_version != manifest["corpus_version"]:
            raise ValueError("Chunk corpus version mismatch")
        if digest(chunk.text.encode("utf-8")) != chunk.text_sha256:
            raise ValueError("Chunk text checksum mismatch")
    return chunks, manifest
