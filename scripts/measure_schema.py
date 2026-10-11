"""Measure MCP tool schema token size. Run before deploy.

SPEC §3 target: ≤ 6k tokens for all 31 tool schemas combined.
Rough estimate: 1 token ≈ 4 characters.

Usage:
    PYTHONPATH=. CONNECTOR_SECRET=<32chars> DEFAULT_CAMPAIGN_ID=<uuid> python scripts/measure_schema.py
"""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("CONNECTOR_SECRET", "x" * 32)
os.environ.setdefault("DEFAULT_CAMPAIGN_ID", "00000000-0000-0000-0000-000000000000")

from server import mcp  # noqa: E402


def main() -> None:
    try:
        registry = mcp._tool_manager._tools  # type: ignore[attr-defined]
    except AttributeError:
        print("Cannot introspect FastMCP internals — update if API changed.", file=sys.stderr)
        sys.exit(1)

    schemas = []
    for name, tool in registry.items():
        schema: dict = {"name": name}
        if hasattr(tool, "description") and tool.description:
            schema["description"] = tool.description
        if hasattr(tool, "parameters"):
            schema["parameters"] = tool.parameters
        schemas.append(schema)

    serialized = json.dumps(schemas, separators=(",", ":"))
    char_count = len(serialized)
    token_estimate = char_count // 4

    print(f"Tools registered : {len(registry)}")
    print(f"Schema size      : {char_count:,} chars")
    print(f"Token estimate   : ~{token_estimate:,} tokens (target ≤ 6,000)")

    if token_estimate > 6000:
        print("⚠  Over budget — trim tool arg descriptions or combine tools before deploy.")
        sys.exit(1)
    else:
        print("✓  Within budget.")

    # Per-tool breakdown (sorted by size descending)
    tool_sizes = sorted(
        [(name, len(json.dumps(s, separators=(",", ":")))) for name, s in zip(registry.keys(), schemas)],
        key=lambda x: -x[1],
    )
    print("\nTop 10 by schema size:")
    for name, size in tool_sizes[:10]:
        print(f"  {size:>6} chars  {name}")


if __name__ == "__main__":
    main()
