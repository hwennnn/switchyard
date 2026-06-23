from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
sys.path.insert(0, str(SRC))

from switchyard.cli import mcp_smoke  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke a Switchyard project's path-free MCP setup.")
    parser.add_argument("project", nargs="?", default=".", help="Project checkout or child directory to smoke.")
    parser.add_argument("--nested", help="Optional child directory, relative to the project argument, to run setup from.")
    parser.add_argument("--name", default="switchyard-smoke", help="Temporary MCP alias name.")
    parser.add_argument("--json", action="store_true", help="Print the smoke summary as JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    existing = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = str(SRC) if not existing else f"{SRC}{os.pathsep}{existing}"
    try:
        result = mcp_smoke(Path(args.project).expanduser(), args.nested, args.name)
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
            return 1
        raise SystemExit(str(exc))
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("OK   MCP project smoke")
        print(f"project: {result['project']}")
        print(f"cwd: {result['cwd']}")
        print(f"alias: {result['name']}")
        print(f"home: {result['home']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
