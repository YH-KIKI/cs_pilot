"""Deterministically extract reviewed rule groups from an immutable local snapshot."""

import hashlib
import json
from datetime import UTC, datetime

from bs4 import BeautifulSoup, Tag

from scripts.collect_policies import POLICY_ROOT


def extract(soup: BeautifulSoup, heading_text: str, mode: str) -> tuple[str, str | None]:
    heading = next(
        (h for h in soup.find_all(["h2", "h3"]) if h.get_text(" ", strip=True) == heading_text),
        None,
    )
    if heading is None:
        raise ValueError(f"Heading missing: {heading_text}")
    anchor = None
    if mode == "agreement":
        container = heading.find_parent(class_="as-shopagreement-item")
        if container is None:
            raise ValueError("Agreement container missing")
        elements = container.find_all(["p", "li"])
    elif mode == "subsection":
        elements = []
        for sibling in heading.next_siblings:
            if not isinstance(sibling, Tag):
                continue
            if sibling.name in ("h2", "h3"):
                break
            if sibling.name in ("p", "li"):
                elements.append(sibling)
            else:
                elements.extend(sibling.find_all(["p", "li"]))
    else:
        container = heading.find_parent(class_="rf-helpdetails-categorylist")
        if container is None:
            raise ValueError("Help section container missing")
        anchor = container.get("id")
        content = container.find(class_="rf-helpdetails-categoryrightpanel")
        if content is None:
            raise ValueError("Help section body missing")
        elements = []
        for element in content.find_all(["p", "li", "h3"]):
            if mode == "prefix" and element.name == "h3":
                break
            elements.append(element)
    # Some source markup nests lists inside paragraphs. Keep leaf blocks once.
    elements = [element for element in elements if not element.find(["p", "li", "h3"])]
    lines = [element.get_text(" ", strip=True) for element in elements]
    text = "\n".join(line for line in lines if line)
    if not text:
        raise ValueError(f"Empty extraction: {heading_text}")
    return text, anchor


def main() -> None:
    selection = json.loads((POLICY_ROOT / "selection.json").read_text(encoding="utf-8"))
    collection_path = POLICY_ROOT / "raw" / selection["corpus_version"] / "collection.json"
    collection = json.loads(collection_path.read_text(encoding="utf-8"))
    documents = {doc["document_id"]: doc for doc in collection["documents"]}
    groups = []
    reviewed_at = datetime.now(UTC).isoformat()
    curated_dir = POLICY_ROOT / "curated"
    curated_dir.mkdir(exist_ok=True)
    markdown = {
        document_id: [f"# {doc['title']}", f"원문: {doc['source_url']}"]
        for document_id, doc in documents.items()
    }
    for rule in selection["rules"]:
        doc = documents[rule["document_id"]]
        raw = (POLICY_ROOT / doc["raw_path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != doc["raw_sha256"]:
            raise ValueError("Raw snapshot checksum mismatch")
        soup = BeautifulSoup(raw, "html.parser")
        text, anchor = extract(soup, rule["heading"], rule["mode"])
        group = {
            **rule,
            "text": text,
            "title": doc["title"],
            "source_url": doc["source_url"],
            "source_anchor": anchor,
            "collected_at": doc["collected_at"],
            "effective_date": None,
            "raw_sha256": doc["raw_sha256"],
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "related_rule_groups": ["returns-standard"]
            if rule["rule_group_id"] == "returns-process"
            else [],
        }
        groups.append(group)
        markdown[doc["document_id"]].extend(
            [
                f"## {rule['heading']} [{rule['rule_group_id']}]",
                text,
                f"> 검수 메모(공식 본문 아님): {rule['review_summary']}",
            ]
        )
    for document_id, lines in markdown.items():
        (curated_dir / f"{document_id}.md").write_text(
            "\n\n".join(lines) + "\n", encoding="utf-8", newline="\n"
        )
    rules_path = curated_dir / "rule_groups.json"
    rules_path.write_text(
        json.dumps(
            {
                "corpus_version": selection["corpus_version"],
                "rule_groups": groups,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    manifest = {
        **collection,
        "reviewed_at": reviewed_at,
        "review_method": "assistant_source_comparison",
        "reviewed_by": "Codex (not a human policy owner)",
        "effective_date_note": "원문에 명시된 시행일 없음. 수집일은 시행일이 아님.",
        "rule_group_count": len(groups),
        "curated_path": "curated/rule_groups.json",
        "curated_sha256": hashlib.sha256(rules_path.read_bytes()).hexdigest(),
        "scope": ["shipping", "cancellation", "returns"],
        "excluded": ["pickup", "payment_refund_schedule", "price_protection", "warranty"],
        "stage": "reviewed_not_embedded",
    }
    (POLICY_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Curated {len(groups)} rule groups; no embeddings generated")


if __name__ == "__main__":
    main()
