#!/usr/bin/env bash
#
# Build and deploy the docs site under the "latest" alias on every push to master.
#
# Behaviour:
#   - Reads the project version from pyproject.toml.
#   - Runs `mkdocs build --strict` first as a guard so a broken build never
#     reaches gh-pages.
#   - Calls `mike deploy --push --update-aliases <version> latest` to publish
#     under both the concrete version (e.g. 0.0.0) and the "latest" alias.
#
# Required environment:
#   - GH_TOKEN (or GITHUB_TOKEN) — push access to the gh-pages branch.
#   - Working directory must be the repo root with checked-out master.

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

echo "👷  Deploying docs for version=${VERSION} under alias=latest"

# Configure git author for the gh-pages commit mike creates.
git config --global user.name "github-actions[bot]"
git config --global user.email "41898282+github-actions[bot]@users.noreply.github.com"

# Make sure the gh-pages branch is locally available — mike pushes to it.
# See https://github.com/jimporter/mike?tab=readme-ov-file#deploying-via-ci
git fetch remote gh-pages --depth=1 2>/dev/null || \
    git fetch origin gh-pages --depth=1 2>/dev/null || true

# Pre-flight: fail fast if the build itself is broken.
mkdocs build --strict

# Push the version + retarget the "latest" alias atomically.
mike deploy --push --update-aliases "${VERSION}" latest

echo "🍻 Latest documentation deployed for ${VERSION}."
