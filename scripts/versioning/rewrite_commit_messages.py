#!/usr/bin/env python3
"""Rewrite git commit messages using scripts/versioning/commit_messages.json."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
MAPPING_FILE = Path(__file__).resolve().parent / "commit_messages.json"


def main() -> int:
    mapping = json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    commit = os.environ.get("GIT_COMMIT") or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()
    new_message = mapping.get(commit)
    if new_message is None:
        print(f"No mapped message for commit {commit}", file=sys.stderr)
        return 1
    sys.stdout.write(new_message)
    if not new_message.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
