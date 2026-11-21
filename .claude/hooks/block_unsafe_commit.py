#!/usr/bin/env python3
"""PreToolUse hook: block git commits that include cache files or evidence outside synthetic dirs.

Exit 2 blocks the Bash call and shows stderr to Claude. Only guards commits Claude makes;
the user's own terminal commits are covered by .gitignore, not by this hook.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import PurePosixPath

EVIDENCE_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".heic", ".eml", ".msg"}
ALLOWED_EVIDENCE_DIRS = ("eval/data/", "demo/")
COMMIT_RE = re.compile(r"\bgit\b[^;&|]*\bcommit\b")
ALL_FLAG_RE = re.compile(r"\s(--all|-[a-zA-Z]*a[a-zA-Z]*)\b")


def git_paths(*args: str) -> list[str]:
    cwd = os.environ.get("CLAUDE_PROJECT_DIR") or None
    result = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd)
    return result.stdout.splitlines() if result.returncode == 0 else []


def violations(paths: list[str]) -> list[str]:
    bad = []
    for path in paths:
        if path.startswith(".cache/") or "/.cache/" in path:
            bad.append(f"{path} (cache)")
        elif PurePosixPath(path).suffix.lower() in EVIDENCE_EXT and not path.startswith(ALLOWED_EVIDENCE_DIRS):
            bad.append(f"{path} (evidence file outside eval/data/ or demo/)")
    return bad


def main() -> int:
    command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    if not COMMIT_RE.search(command):
        return 0
    paths = git_paths("diff", "--cached", "--name-only")
    if ALL_FLAG_RE.search(command):
        paths += git_paths("diff", "--name-only")
    bad = violations(paths)
    if bad:
        print("Commit blocked (no cache or real client documents):\n  " + "\n  ".join(bad), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
