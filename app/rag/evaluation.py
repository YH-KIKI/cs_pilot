from app.rag.retrieval import PolicyIndex


def rule_group_recall(expected: list[str], actual: list[str], *, match: str = "all") -> float:
    if not expected:
        raise ValueError("No positive references: do not count this as retrieval success")
    expected_set = set(expected)
    overlap = expected_set.intersection(actual)
    if match == "any":
        return float(bool(overlap))
    if match != "all":
        raise ValueError("Unknown matching mode")
    return len(overlap) / len(expected_set)


def evaluate_retrieval(index: PolicyIndex, suite: dict) -> dict:
    if index.embeddings.spec.provider != "openai":
        raise ValueError("Synthetic vectors cannot produce a real retrieval quality report")
    if {chunk.corpus_version for chunk in index.chunks.values()} != {suite["corpus_version"]}:
        raise ValueError("Evaluation corpus version mismatch")
    rows = []
    for case in suite["cases"]:
        expected = case["expected"]
        if case["mode"] != "integration" or not expected["rule_groups"]:
            continue
        result = index.search(case["question"])
        expanded = [hit.source.rule_group_id for hit in result.hits]
        options = {"match": expected.get("rule_group_match", "all")}
        rows.append(
            {
                "case_id": case["id"],
                "expected": expected["rule_groups"],
                "seed_groups": result.seed_rule_groups,
                "expanded_groups": expanded,
                "seed_recall_at_4": rule_group_recall(
                    expected["rule_groups"], result.seed_rule_groups, **options
                ),
                "expanded_recall_at_4": rule_group_recall(
                    expected["rule_groups"], expanded, **options
                ),
            }
        )
    if not rows:
        raise ValueError("No eligible positive retrieval cases")
    return {
        "corpus_version": suite["corpus_version"],
        "seed_version": suite["seed_version"],
        "reference_time": suite["reference_time"],
        "model": index.embeddings.spec.model,
        "dimensions": index.embeddings.spec.dimensions,
        "index_fingerprint": index.fingerprint,
        "top_k": 4,
        "evaluated_cases": len(rows),
        "seed_recall_at_4": sum(row["seed_recall_at_4"] for row in rows) / len(rows),
        "expanded_recall_at_4": sum(row["expanded_recall_at_4"] for row in rows) / len(rows),
        "negative_queries_and_agent_behavior": "not_assessed_by_recall",
        "cases": rows,
    }
