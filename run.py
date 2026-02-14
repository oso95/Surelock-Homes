from __future__ import annotations

import argparse
import json

from agent.loop import run_investigation


def main() -> None:
    parser = argparse.ArgumentParser(description="Surelock Homes investigator runner")
    parser.add_argument("query")
    parser.add_argument("--offline", action="store_true", help="Run without external LLM tools")
    parser.add_argument("--max-turns", type=int, default=8)
    args = parser.parse_args()

    result = run_investigation(args.query, offline=args.offline, max_turns=args.max_turns)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

