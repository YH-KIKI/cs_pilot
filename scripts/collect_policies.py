"""Collect exactly three Apple KR policy pages; never follows links or embeds text."""

import argparse
import hashlib
import json
from datetime import UTC, datetime

import httpx
from bs4 import BeautifulSoup

from app.config import ROOT

POLICY_ROOT = ROOT / "data/policies"
PAGES = (
    ("apple-kr-orders", "주문 확인 및 변경", "viewing_changing_orders"),
    ("apple-kr-shipping", "배송 및 픽업", "shipping_delivery"),
    ("apple-kr-returns", "반품 및 환불", "returns_refund"),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="New immutable corpus version")
    args = parser.parse_args()
    if not args.version.replace("-", "").isalnum():
        raise ValueError("Invalid version")
    target = POLICY_ROOT / "raw" / args.version
    if target.exists():
        raise FileExistsError("Snapshot exists; use a new version instead of overwriting")
    target.mkdir(parents=True)
    documents = []
    with httpx.Client(timeout=40, follow_redirects=True) as client:
        for document_id, title, slug in PAGES:
            url = f"https://www.apple.com/kr/shop/help/{slug}"
            response = client.get(url, headers={"User-Agent": "CS-Pilot-policy-snapshot/0.1"})
            response.raise_for_status()
            if response.url.host != "www.apple.com":
                raise ValueError("Unexpected redirect host")
            html = response.content
            soup = BeautifulSoup(html, "html.parser")
            h1 = soup.find("h1")
            if not h1:
                raise ValueError(f"Policy heading missing: {document_id}")
            html_path = target / f"{document_id}.html"
            html_path.write_bytes(html)
            # Human-readable heading/paragraph list for review; raw DOM remains the authority.
            lines = [
                element.get_text(" ", strip=True)
                for element in soup.find_all(["h1", "h2", "h3", "p", "li"])
            ]
            text_path = target / f"{document_id}.txt"
            text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            documents.append(
                {
                    "document_id": document_id,
                    "title": title,
                    "source_url": url,
                    "resolved_url": str(response.url),
                    "locale": "ko-KR",
                    "collected_at": datetime.now(UTC).isoformat(),
                    "effective_date": None,
                    "collection_method": "http",
                    "http_status": response.status_code,
                    "raw_path": html_path.relative_to(POLICY_ROOT).as_posix(),
                    "raw_sha256": hashlib.sha256(html).hexdigest(),
                    "review_text_path": text_path.relative_to(POLICY_ROOT).as_posix(),
                    "page_heading": h1.get_text(" ", strip=True),
                }
            )
            print(f"Collected {document_id}: {len(html)} bytes")
    (target / "collection.json").write_text(
        json.dumps(
            {
                "corpus_version": args.version,
                "documents": documents,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
