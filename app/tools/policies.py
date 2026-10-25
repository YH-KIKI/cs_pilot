from langchain.tools import tool
from pydantic import field_validator

from app.config import ROOT, get_settings
from app.consultation_contract import SearchToolInput, Topic
from app.rag.chunks import load_chunks
from app.rag.embeddings import CachedEmbeddings, EmbeddingSpec, openai_backend
from app.rag.retrieval import PolicyIndex, PolicySearchResult


class SearchPolicyInput(SearchToolInput):
    topic: Topic | None = None

    @field_validator("query")
    @classmethod
    def nonblank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Query must not be blank")
        return value.strip()


def search_policy_result(query: str, topic: Topic | None = None) -> PolicySearchResult:
    validated = SearchPolicyInput(query=query, topic=topic)
    query = validated.query
    topic = validated.topic
    # The real tool never falls back to synthetic vectors or live web search.
    settings = get_settings()
    spec = EmbeddingSpec(model=settings.openai_embedding_model)
    directory = ROOT / "data/runtime/chroma"
    if not (directory / "index_manifest.json").exists():
        return PolicySearchResult(
            kind="not_ready",
            query=query,
            embedding_provider="openai",
            message="실제 정책 임베딩 인덱스가 아직 준비되지 않았습니다.",
        )
    try:
        chunks, manifest = load_chunks()
        cache = CachedEmbeddings(
            ROOT / ".cache/rag-embeddings",
            spec,
            lambda: openai_backend(spec, allow_api=settings.rag_allow_api),
        )
        index = PolicyIndex(chunks, manifest, cache, directory)
        return index.search(query, topic=topic)
    except (FileNotFoundError, ValueError):
        return PolicySearchResult(
            kind="not_ready",
            query=query,
            embedding_provider="openai",
            message="인덱스·캐시를 확인하세요. API 호출은 명시적으로 켜기 전까지 비활성입니다.",
        )
    except Exception:
        # Do not expose provider errors, keys, local paths or raw exception payloads.
        return PolicySearchResult(
            kind="error",
            query=query,
            embedding_provider="openai",
            message="정책 검색 중 오류가 발생했습니다. 근거 없음과 구분해 확인하세요.",
        )


@tool(args_schema=SearchPolicyInput)
def search_policy(query: str, topic: Topic | None = None) -> dict:
    """Search the preloaded Apple KR policy corpus and return candidate evidence and sources."""
    return search_policy_result(query, topic).model_dump(mode="json")
