"""Verify/restore frozen data, then replace this process with one Uvicorn server."""

import argparse
import json
import os
import sys

from app.config import ROOT, get_settings
from app.runtime import prepare_runtime

STATIC_DIR = ROOT / "app/static"
FRONTEND_DIST = ROOT / "frontend/dist"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true", help="Prepare data without serving")
    args = parser.parse_args()
    if not args.prepare_only:
        try:
            port = int(os.environ.get("PORT", "8000"))
            if not 1 <= port <= 65535:
                raise ValueError("Out of range")
        except ValueError:
            parser.error("PORT must be an integer between 1 and 65535")
        dist = STATIC_DIR if (STATIC_DIR / "index.html").is_file() else FRONTEND_DIST
        if not (dist / "index.html").is_file() or not (dist / "assets").is_dir():
            parser.error("Built React UI is missing; build frontend before starting this service")
    report = prepare_runtime(get_settings())
    print("Runtime ready: " + json.dumps(report, ensure_ascii=False), flush=True)
    if not args.prepare_only:
        os.execv(
            sys.executable,
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                str(port),
                "--workers",
                "1",
            ],
        )


if __name__ == "__main__":
    main()
