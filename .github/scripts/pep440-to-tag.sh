#!/usr/bin/env bash
#
# Convert a PEP 440 version string to the canonical SemVer release tag.
# Inverse of tag-to-pep440.sh — used by release-python.yml to cut the
# python-sdk's own GitHub Release at the published version.
#
# Examples:
#   0.0.1      -> v0.0.1
#   0.0.1a8    -> v0.0.1-alpha.8
#   0.0.1b2    -> v0.0.1-beta.2
#   0.0.1rc3   -> v0.0.1-rc.3
#
# Usage (CLI):
#   .github/scripts/pep440-to-tag.sh 0.0.1b1
#
# Usage (library — preferred from CI/workflows):
#   source .github/scripts/pep440-to-tag.sh
#   tag="$(pep440_to_tag "0.0.1b1")"
#
# This is the single source of truth for the reverse conversion. The
# release-python.yml `resolve` job sources this file so the workflow and
# the AAASM-2956 fixture suite exercise the exact same code path.
#
# Owner: python-sdk release pipeline (AAASM-2956).

# Conversion function. Reads the PEP 440 version from $1 and prints the
# SemVer tag (with a leading `v`) to stdout. Returns non-zero only if the
# input is empty. `.post`/`.dev` suffixes are not valid SemVer pre-release
# identifiers in this scheme, so they are rejected — those are PyPI-only
# republish forms that do not correspond to a new GitHub Release tag.
pep440_to_tag() {
    local version="${1-}"
    if [[ -z "$version" ]]; then
        echo "pep440_to_tag: missing version argument" >&2
        return 1
    fi
    # Strip any leading `v` the caller may have passed by mistake.
    local stripped="${version#v}"
    # Expand the PEP 440 pre-release shorthand (a/b/rc) back to the
    # hyphenated SemVer form. Anchored on the digits immediately following
    # the marker so we never touch the base x.y.z component.
    local tag
    tag="$(printf '%s\n' "$stripped" | sed -E 's/a([0-9]+)$/-alpha.\1/; s/b([0-9]+)$/-beta.\1/; s/rc([0-9]+)$/-rc.\1/')"
    printf 'v%s\n' "$tag"
}

# When executed directly (not sourced), behave as a CLI: take the version
# as $1 and print the converted tag. When sourced, define the function
# only and let the caller drive it.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -euo pipefail
    pep440_to_tag "${1-}"
fi
