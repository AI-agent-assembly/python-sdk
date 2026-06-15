#!/usr/bin/env bash
#
# Pin the aa-ffi-python git deps to the agent-assembly commit a release tag
# points at, so the maturin-built wheel always compiles against the SAME core
# release whose aasm-* binaries it bundles (binary_source_tag).
#
# Background (AAASM-2959): release-python.yml builds the PyPI wheel with maturin,
# which compiles aa-ffi-python (PyO3) from source against the git-SHA `rev`
# pins in native/aa-ffi-python/Cargo.toml (aa-core, aa-proto, aa-sdk-client).
# Those pins are only bumped to the just-released core commit by a SEPARATE PR
# that lands AFTER publish, so without this rewrite the published wheel would
# pin the PREVIOUS core release (one-cycle source-pin lag). This script makes
# the wheel self-consistent by rewriting the pins to binary_source_tag's commit
# in the CI working tree before each maturin build. It is an ephemeral edit —
# CI must NOT commit it back (the update-python-sdk-ffi-pin PR keeps master
# synced separately).
#
# Usage:
#   .github/scripts/pin-ffi-to-tag.sh <tag> [cargo_toml_path]
#
#   <tag>             agent-assembly release tag, e.g. v0.0.1-alpha.8
#   [cargo_toml_path] defaults to native/aa-ffi-python/Cargo.toml
#
# Resolves the tag to a full 40-hex commit SHA on
# ai-agent-assembly/agent-assembly, dereferencing annotated tags (the peeled
# `^{}` ref), and falling back to the lightweight tag ref if peeling yields
# nothing. Then rewrites every `rev = "<sha>"` on the aa-core / aa-proto /
# aa-sdk-client git dep lines to that SHA. Idempotent: re-running with the same
# tag is a no-op.

set -euo pipefail

TAG="${1:?usage: pin-ffi-to-tag.sh <tag> [cargo_toml_path]}"
CARGO_TOML="${2:-native/aa-ffi-python/Cargo.toml}"
REPO_URL="https://github.com/ai-agent-assembly/agent-assembly.git"

if [[ ! -f "$CARGO_TOML" ]]; then
  echo "::error::Cargo.toml not found at '$CARGO_TOML'" >&2
  exit 1
fi

# Resolve tag -> full commit SHA. Prefer the peeled (`^{}`) ref so annotated
# tags resolve to the commit they point at, not the tag object's own SHA.
# Fall back to the lightweight ref when the peeled form is empty.
sha="$(git ls-remote "$REPO_URL" "refs/tags/${TAG}^{}" | awk '{print $1}' | head -n1)"
if [[ -z "$sha" ]]; then
  sha="$(git ls-remote "$REPO_URL" "refs/tags/${TAG}" | awk '{print $1}' | head -n1)"
fi

if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "::error::could not resolve tag '${TAG}' to a 40-hex commit SHA on ${REPO_URL} (got '${sha}')" >&2
  exit 1
fi

echo "::notice::Pinning aa-ffi git deps to ${TAG} -> ${sha}"

# Rewrite the `rev = "..."` on each aa-core / aa-proto / aa-sdk-client git dep
# line, keyed on the dep name at line start so unrelated `rev`s are untouched.
# Done in Python (not sed) for portable, identical behaviour across the GNU-sed
# (ubuntu) and BSD-sed (macOS) build runners. Verifies exactly 3 deps were
# repinned so a silent no-op (e.g. a Cargo.toml refactor that broke the match)
# cannot let a stale-pinned wheel slip through.
SHA="$sha" CARGO_TOML="$CARGO_TOML" python3 - <<'PY'
import os
import re
import sys

sha = os.environ["SHA"]
path = os.environ["CARGO_TOML"]
deps = ("aa-core", "aa-proto", "aa-sdk-client")
# Match `<dep> = { ... rev = "<40-hex>" ... }` at line start.
line_re = re.compile(r'^(aa-(?:core|proto|sdk-client))\s*=.*$')
rev_re = re.compile(r'(rev\s*=\s*")[0-9a-fA-F]{40}(")')

with open(path, encoding="utf-8") as fh:
    lines = fh.readlines()

repinned = set()
for i, line in enumerate(lines):
    m = line_re.match(line)
    if not m:
        continue
    new_line, n = rev_re.subn(rf'\g<1>{sha}\g<2>', line)
    if n:
        lines[i] = new_line
        repinned.add(m.group(1))

if repinned != set(deps):
    missing = set(deps) - repinned
    sys.stderr.write(
        f"::error::expected to repin {sorted(deps)}, missing {sorted(missing)} in {path}\n"
    )
    sys.exit(1)

with open(path, "w", encoding="utf-8") as fh:
    fh.writelines(lines)
PY

echo "aa-ffi git deps pinned to ${sha}:"
grep -nE '^aa-(core|proto|sdk-client)[[:space:]]*=' "$CARGO_TOML"

# Sync the sibling Cargo.lock so it agrees with the freshly-pinned rev.
# Without this the manifest points at the new core commit while the lock
# still records the old one; the wheel build only tolerates that because it
# does not run `--locked` (cargo silently re-resolves). Syncing keeps the
# lock honest and lets the build be hardened with `--locked` later. The
# maturin build mounts this same checkout, so the synced lock is what it uses.
LOCKFILE="$(dirname "$CARGO_TOML")/Cargo.lock"
if [[ -f "$LOCKFILE" ]] && command -v cargo >/dev/null 2>&1; then
  echo "::notice::Syncing ${LOCKFILE} to ${sha}"
  cargo update --manifest-path "$CARGO_TOML" -p aa-core -p aa-proto -p aa-sdk-client
else
  echo "::warning::skipped Cargo.lock sync (cargo or ${LOCKFILE} missing); build will re-resolve"
fi
