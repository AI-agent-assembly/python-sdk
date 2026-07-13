#!/usr/bin/env python3
"""Generate the per-framework quick-start tab block in ``docs/quick-start.md``.

WHY THIS EXISTS
---------------
Quick-start §3 "Govern your first agent" (AAASM-4513) shows one ``pymdownx.tabbed``
tab per supported Python framework, and every tab's code must be the *governance
slice of a runnable example* — not a hand-maintained copy that silently rots (the
AAASM-4451 stale-sample class). The snippets are vendored from the
``ai-agent-assembly/examples`` repo into ``quickstart_snippets/`` (committed,
because ``examples`` is a separate repo and the MkDocs build must stay hermetic).
This script is the single point that turns those vendored inputs into the tab
block, written into a bounded ``BEGIN/END GENERATED`` region of the doc so the tab
list is data-driven from ``quickstart_snippets/manifest.json`` — never hand-listed.

A CI drift check (``.github/workflows/quickstart-tabs-check.yml``) re-runs this
script and fails if the committed ``docs/quick-start.md`` differs, so the doc can
never drift from the vendored snippets + manifest.

DESIGN CONSTRAINTS (mirrors the examples ``extract_snippets.py`` gate)
----------------------------------------------------------------------
* Standard library only — the CI drift check needs no install step.
* Idempotent: running twice produces no diff. The drift check enforces this.
* Data-driven: the tab list is exactly ``manifest.json``'s ``frameworks`` array,
  in listed order, so a framework added upstream appears once it is re-vendored.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Region markers delimiting the generated block inside docs/quick-start.md. The
# markers must already exist in the doc; this script only rewrites what is
# between them, leaving the surrounding prose under human control.
BEGIN_MARKER = "<!-- BEGIN GENERATED: quickstart-framework-tabs -->"
END_MARKER = "<!-- END GENERATED: quickstart-framework-tabs -->"


class GenerateError(RuntimeError):
    """A missing input or a malformed target region — fail the drift check loudly."""


def _repo_root_from_script() -> Path:
    # This file lives at <repo>/scripts/generate_quickstart_tabs.py.
    return Path(__file__).resolve().parent.parent


def _indent_tab_body(line: str) -> str:
    """Indent one tab-body line by 4 spaces, keeping blank lines empty.

    ``pymdownx.tabbed`` treats 4-space-indented content as the tab body (the same
    convention the pip/uv install tabs in this file already use). Blank lines stay
    empty so the output carries no trailing whitespace.
    """

    return f"    {line}" if line else ""


def render_tab(label: str, code: str) -> str:
    """Render one ``=== "<label>"`` tab wrapping *code* in a python fence."""

    body = ["```python", *code.splitlines(), "```"]
    lines = [f'=== "{label}"', "", *[_indent_tab_body(b) for b in body]]
    return "\n".join(lines)


def build_block(vendor_dir: Path) -> str:
    """Build the full generated block (markers included) from the vendored inputs."""

    manifest_path = vendor_dir / "manifest.json"
    if not manifest_path.is_file():
        raise GenerateError(f"missing vendored manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frameworks = manifest.get("frameworks")
    if not frameworks:
        raise GenerateError(f"{manifest_path}: 'frameworks' is empty or missing")

    tabs: list[str] = []
    for entry in frameworks:
        framework_id = entry["framework_id"]
        snippet_path = vendor_dir / f"{framework_id}.py"
        if not snippet_path.is_file():
            raise GenerateError(f"manifest lists '{framework_id}' but its snippet is missing: " f"{snippet_path}")
        code = snippet_path.read_text(encoding="utf-8").rstrip("\n")
        tabs.append(render_tab(entry["label"], code))

    return "\n".join([BEGIN_MARKER, "", "\n\n".join(tabs), "", END_MARKER])


def apply_block(doc_text: str, block: str) -> str:
    """Return *doc_text* with the region between the markers replaced by *block*."""

    start = doc_text.find(BEGIN_MARKER)
    end = doc_text.find(END_MARKER)
    if start == -1 or end == -1:
        raise GenerateError(
            f"markers not found in doc — expected both {BEGIN_MARKER!r} and "
            f"{END_MARKER!r}. Add them to the doc first."
        )
    if end < start:
        raise GenerateError("END marker precedes BEGIN marker in the doc")
    end += len(END_MARKER)
    return doc_text[:start] + block + doc_text[end:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=_repo_root_from_script(),
        help="Path to the repository root (defaults to the script's parent).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit 1 if the doc is out of sync with the snippets.",
    )
    args = parser.parse_args(argv)

    vendor_dir = args.repo_root / "quickstart_snippets"
    doc_path = args.repo_root / "docs" / "quick-start.md"

    try:
        block = build_block(vendor_dir)
        doc_text = doc_path.read_text(encoding="utf-8")
        updated = apply_block(doc_text, block)
    except GenerateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if updated == doc_text:
        print(f"Up to date: {doc_path.name} already matches the vendored snippets.")
        return 0

    if args.check:
        print(
            f"error: {doc_path} is out of sync with quickstart_snippets/. "
            "Run: python scripts/generate_quickstart_tabs.py",
            file=sys.stderr,
        )
        return 1

    doc_path.write_text(updated, encoding="utf-8")
    print(f"Rewrote {doc_path.relative_to(args.repo_root)} from the vendored snippets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
