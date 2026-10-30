"""Keep reviewed policy dependencies visible through answer generation."""

from app.consultation_contract import AppliedPolicy, PolicySource
from app.rag.chunks import load_chunks


def related_policy_requirements(sources: list[PolicySource]) -> list[dict]:
    if not sources:
        return []
    chunks, _ = load_chunks()
    by_chunk = {chunk.chunk_id: chunk for chunk in chunks}
    by_group = {source.rule_group_id: source.evidence_id for source in sources}
    requirements = []
    for source in sources:
        chunk = by_chunk[source.chunk_id]
        if not chunk.related_rule_groups:
            continue
        requirements.append(
            {
                "evidence_id": source.evidence_id,
                "rule_group_id": source.rule_group_id,
                "related_rule_groups": chunk.related_rule_groups,
                "related_evidence_ids": [
                    by_group[group] for group in chunk.related_rule_groups if group in by_group
                ],
                "missing_rule_groups": [
                    group for group in chunk.related_rule_groups if group not in by_group
                ],
            }
        )
    return requirements


def missing_related_rule_groups(
    policies: list[AppliedPolicy], sources: list[PolicySource]
) -> list[str]:
    applied_ids = {key for policy in policies for key in policy.evidence_ids}
    applied_groups = {
        source.rule_group_id for source in sources if source.evidence_id in applied_ids
    }
    return sorted(
        {
            group
            for requirement in related_policy_requirements(sources)
            if requirement["evidence_id"] in applied_ids
            for group in requirement["related_rule_groups"]
            if group not in applied_groups
        }
    )
