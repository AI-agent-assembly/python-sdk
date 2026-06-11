#!/usr/bin/env bash
#
# Cut an immutable, versioned docs snapshot on a new official release and
# promote it to be the default that readers see at /python-sdk/.
#
# This is the ONLY path that freezes a concrete version number. The first
# frozen snapshot is therefore cut at the v0.1.0 release — master pushes only
# ever update the live "latest" version (see
# deploy-latest-version-documentation.sh).
#
# Behaviour:
#   - Reads the just-released version from pyproject.toml (the release workflow
#     syncs it from the dispatch tag before this script runs).
#   - Runs `mkdocs build --strict` first as a guard so a broken build never
#     reaches gh-pages.
#   - Calls `mike deploy --push --update-aliases <version> stable latest` to
#     publish the frozen <version> and retarget both the "stable" and "latest"
#     aliases onto it.
#   - Calls `mike set-default --push stable` so the bare /python-sdk/ URL
#     redirects readers to the stable version.
#
# Required environment:
#   - GH_TOKEN (or GITHUB_TOKEN) — push access to the gh-pages branch.
#   - Working directory must be the repo root with the release tag checked out.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${PROJECT_ROOT}"

VERSION=$(python3 - <<'PY'
import re
import sys
from pathlib import Path

text = Path("pyproject.toml").read_text(encoding="utf-8")
match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
if not match:
    sys.exit("ERROR: could not find version = \"...\" in pyproject.toml")
print(match.group(1))
PY
)

echo "👷  Deploying docs for version=${VERSION} under alias=stable (default)"

# Configure git author for the gh-pages commit mike creates.
git config --global user.name "github-actions[bot]"
git config --global user.email "41898282+github-actions[bot]@users.noreply.github.com"

# Make sure the gh-pages branch is locally available — mike pushes to it.
# See https://github.com/jimporter/mike?tab=readme-ov-file#deploying-via-ci
git fetch remote gh-pages --depth=1 2>/dev/null || \
    git fetch origin gh-pages --depth=1 2>/dev/null || true

# Pre-flight: fail fast if the build itself is broken.
mkdocs build --strict

# Freeze the released version + retarget both "stable" and "latest" aliases
# onto it atomically.
mike deploy --push --update-aliases "${VERSION}" stable latest

# Make "stable" the default so /python-sdk/ redirects to /python-sdk/stable/.
mike set-default --push stable

echo "🍻 Stable documentation deployed for ${VERSION}."
