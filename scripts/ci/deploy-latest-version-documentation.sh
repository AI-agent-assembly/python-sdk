#!/usr/bin/env bash
#
# Deploy the docs site to the live "latest" version on every push to master.
#
# "latest" tracks master HEAD: it is re-deployed in place on each push and is
# NOT a frozen snapshot of any concrete release. Concrete, immutable version
# snapshots (e.g. 0.1.0) are cut only at release time by
# deploy-stable-version-documentation.sh — never here.
#
# Behaviour:
#   - Runs `mkdocs build --strict` first as a guard so a broken build never
#     reaches gh-pages.
#   - Calls `mike deploy --push latest` to publish/overwrite the "latest"
#     version in place. No concrete version number is minted on master pushes.
#
# Required environment:
#   - GH_TOKEN (or GITHUB_TOKEN) — push access to the gh-pages branch.
#   - Working directory must be the repo root with checked-out master.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${PROJECT_ROOT}"

echo "👷  Deploying docs to the live \"latest\" version (tracks master HEAD)"

# Configure git author for the gh-pages commit mike creates.
git config --global user.name "github-actions[bot]"
git config --global user.email "41898282+github-actions[bot]@users.noreply.github.com"

# Make sure the gh-pages branch is locally available — mike pushes to it.
# See https://github.com/jimporter/mike?tab=readme-ov-file#deploying-via-ci
git fetch remote gh-pages --depth=1 2>/dev/null || \
    git fetch origin gh-pages --depth=1 2>/dev/null || true

# Pre-flight: fail fast if the build itself is broken.
mkdocs build --strict

# Re-deploy "latest" in place. Master pushes never freeze a concrete version;
# the first frozen snapshot is cut at the v0.1.0 release.
mike deploy --push latest

echo "🍻 Latest documentation deployed (live, tracking master)."
