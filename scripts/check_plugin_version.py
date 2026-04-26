#!/usr/bin/env python3
"""Keep plugins/claude-code/.claude-plugin/plugin.json version in sync with pyproject.toml.

Default: rewrite plugin.json to match pyproject.toml. Exit 1 if a change was made
(so pre-commit prompts the user to `git add` and retry).

With --check: never modify files, exit 1 on drift. Used by CI.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
PLUGIN_JSON = ROOT / "plugins" / "claude-code" / ".claude-plugin" / "plugin.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail on drift, do not modify")
    args = parser.parse_args()

    match = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(), re.MULTILINE)
    if match is None:
        print("could not find version in pyproject.toml", file=sys.stderr)
        return 1
    py_version = match.group(1)

    data = json.loads(PLUGIN_JSON.read_text())
    plugin_version = data.get("version")

    if py_version == plugin_version:
        return 0

    rel = PLUGIN_JSON.relative_to(ROOT)
    if args.check:
        print(
            f"version drift: pyproject.toml={py_version}, {rel}={plugin_version}",
            file=sys.stderr,
        )
        return 1

    data["version"] = py_version
    PLUGIN_JSON.write_text(json.dumps(data, indent=2) + "\n")
    print(
        f"bumped {rel}: {plugin_version} -> {py_version}\n`git add {rel}` and retry the commit.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
