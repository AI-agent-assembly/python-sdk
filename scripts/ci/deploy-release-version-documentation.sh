#!/usr/bin/env bash
#
# Cut an immutable, versioned docs snapshot on a new release and move the
# correct moving channel alias onto it.
#
# Channel model (AAASM-2750)
# --------------------------
# The site exposes three *moving* channel aliases plus the frozen, immutable
# per-release versions they point at:
#
#   latest (master)   — tracks master HEAD; re-deployed on every master push by
#                       deploy-latest-version-documentation.sh (never here).
#   pre-release (<tag>) — newest pre-release tag (e.g. v0.0.1-alpha.5).
#   stable (<tag>)      — newest stable tag (e.g. v0.1.0); does NOT exist until
#                         a stable release ships.
#
# This script handles a single release. The channel is chosen from the *real*
# git release tag:
#
#   ^v[0-9]+\.[0-9]+\.[0-9]+$    -> stable
#   ^v[0-9]+\.[0-9]+\.[0-9]+-.+  -> pre-release
#
# Behaviour:
#   - Reads the real release tag from $RELEASE_TAG (handed in by the docs
#     workflow, which sources it from the release-tag artifact that
#     release-python.yml publishes). The tag — not the PEP-440 pyproject
#     version — is what the version selector label shows, because the tag is
#     the human-facing release identity (recon confirmed `v0.0.1-alpha.5` is a
#     valid mike version id).
#   - Runs `mkdocs build --strict` first as a guard so a broken build never
#     reaches gh-pages.
#   - Calls `mike deploy --push --update-aliases <tag> <channel>
#     --title "<channel> (<tag>)"` to freeze the immutable <tag> snapshot and
#     move the channel alias onto it. The title is what readers see in the
#     selector, e.g. "stable (v0.1.0)" / "pre-release (v0.0.1-alpha.5)".
#   - Sets the site default so the bare /python-sdk/ URL redirects readers to
#     the most authoritative channel that exists: stable, else pre-release,
#     else latest.
#
# Required environment:
#   - RELEASE_TAG — the real git release tag (e.g. v0.0.1-alpha.5 or v0.1.0).
#   - GH_TOKEN (or GITHUB_TOKEN) — push access to the gh-pages branch.
#   - Working directory must be the repo root.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${PROJECT_ROOT}"

if [ -z "${RELEASE_TAG:-}" ]; then
    echo "ERROR: RELEASE_TAG is empty — cannot determine the release channel." >&2
    exit 1
fi

# Classify the channel from the real tag shape.
if [[ "${RELEASE_TAG}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    CHANNEL="stable"
elif [[ "${RELEASE_TAG}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+-.+ ]]; then
    CHANNEL="pre-release"
else
    echo "ERROR: RELEASE_TAG='${RELEASE_TAG}' does not match a stable" \
         "(vX.Y.Z) or pre-release (vX.Y.Z-...) tag shape." >&2
    exit 1
fi

echo "👷  Release tag=${RELEASE_TAG} → channel=${CHANNEL}"

# Configure git author for the gh-pages commit mike creates.
git config --global user.name "github-actions[bot]"
git config --global user.email "41898282+github-actions[bot]@users.noreply.github.com"

# Make sure the gh-pages branch is locally available — mike reads and pushes
# to it. See https://github.com/jimporter/mike?tab=readme-ov-file#deploying-via-ci
git fetch remote gh-pages --depth=1 2>/dev/null || \
    git fetch origin gh-pages --depth=1 2>/dev/null || true

# Pre-flight: fail fast if the build itself is broken.
mkdocs build --strict

# Freeze the immutable <tag> snapshot and move the channel alias onto it. The
# title is what the version selector shows, e.g. "stable (v0.1.0)".
mike deploy --push --update-aliases \
    --title "${CHANNEL} (${RELEASE_TAG})" \
    "${RELEASE_TAG}" "${CHANNEL}"

# Pick the default (root-redirect target) by authority: stable beats
# pre-release beats latest. `mike list` enumerates the channels/versions that
# currently exist on gh-pages, including the one we just deployed.
EXISTING="$(mike list 2>/dev/null || true)"
if echo "${EXISTING}" | grep -qw "stable"; then
    DEFAULT="stable"
elif echo "${EXISTING}" | grep -qw "pre-release"; then
    DEFAULT="pre-release"
else
    DEFAULT="latest"
fi

echo "🎯  Setting default channel (root redirect) to '${DEFAULT}'"
mike set-default --push "${DEFAULT}"

echo "🍻 Release documentation deployed: ${CHANNEL} (${RELEASE_TAG}); default=${DEFAULT}."
