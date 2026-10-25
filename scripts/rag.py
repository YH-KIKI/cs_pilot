"""Prepare policy chunks or explicitly test/build/search the index. Default: no API calls."""

import argparse
import json
from pathlib import Path

from app.config import ROOT, get_settings
from app.rag.artifacts import export_vectors, restore_vectors
from app.rag.chunks import load_chunks, prepare_chunks, write_json
from app.rag.embeddings import (
    CachedEmbeddings,
    EmbeddingSpec,
    OfflineTestEmbeddings,
    openai_backend,
)
from app.rag.evaluation import evaluate_retrieval
from app.rag.retrieval import PolicyIndex


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["prepare", "offline-smoke", "build", "search", "evaluate", "export", "restore"],
    )
    parser.add_argument(
        "--allow-api", action="store_true", help="Permit actual OpenAI cache misses"
    )
    parser.add_argument("--query")
    parser.add_argument("--index-dir", type=Path, help="Runtime index path under data/runtime")
    args = parser.parse_args()
    if args.command == "prepare":
        chunks = prepare_chunks()
        print(f"Prepared {len(chunks)} whole-rule chunks; no embeddings or API calls")
        return
    chunks, manifest = load_chunks()
    offline = args.command == "offline-smoke"
    spec = (
        EmbeddingSpec(provider="offline_test", model="sha256-test-v1", dimensions=16)
        if offline
        else (EmbeddingSpec(model=get_settings().openai_embedding_model))
    )
    cache = CachedEmbeddings(
        ROOT / ".cache/rag-embeddings",
        spec,
        OfflineTestEmbeddings
        if offline
        else lambda: openai_backend(spec, allow_api=args.allow_api),
    )
    directory = ROOT / ("data/runtime/chroma-offline" if offline else "data/runtime/chroma")
    if args.index_dir:
        directory = args.index_dir.resolve()
        if not directory.is_relative_to((ROOT / "data/runtime").resolve()):
            parser.error("--index-dir must stay under data/runtime")
    index = PolicyIndex(chunks, manifest, cache, directory)
    if args.command == "export":
        if spec.provider != "openai":
            parser.error("Only real document vectors may be exported to deployment artifacts")
        print(json.dumps(export_vectors(index), ensure_ascii=False, indent=2))
    elif args.command == "restore":
        print(json.dumps(restore_vectors(index), ensure_ascii=False, indent=2))
    elif args.command == "build":
        print(json.dumps(index.build(), ensure_ascii=False, indent=2))
    elif offline:
        first = index.build()
        second = index.build()
        assert second["new_chunks"] == 0
        candidate = next(chunk for chunk in chunks if chunk.rule_group_id == "returns-process")
        result = index.search(candidate.embedding_text, top_k=1)
        assert result.seed_rule_groups == ["returns-process"]
        assert {hit.source.rule_group_id for hit in result.hits} == {
            "returns-process",
            "returns-standard",
        }
        report = {
            "provider": "offline_test",
            "paid_api_calls": 0,
            "chunks": len(chunks),
            "first_build_new_chunks": first["new_chunks"],
            "second_build_new_chunks": second["new_chunks"],
            "exact_input_vector_lookup": "passed",
            "related_conditions": "passed",
            "semantic_recall_at_4": None,
            "semantic_quality": "not_evaluated",
            "real_openai_index": "not_touched_by_this_check",
            "cache_new_vectors": cache.new_vectors,
        }
        write_json(ROOT / ".cache/rag-offline-report.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.command == "search":
        if not args.query:
            parser.error("--query is required")
        print(index.search(args.query).model_dump_json(indent=2))
    else:
        suite = json.loads((ROOT / "data/eval/cases.json").read_text("utf-8"))
        report = evaluate_retrieval(index, suite)
        write_json(ROOT / "docs/retrieval-evaluation.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
