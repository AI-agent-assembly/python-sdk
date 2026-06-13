#!/usr/bin/env bash
#
# Convert an agent-assembly release tag to a PEP 440 version string.
#
# Examples:
#   v0.0.1           -> 0.0.1
#   v0.0.1-alpha.8   -> 0.0.1a8
#   v0.0.1-beta.2    -> 0.0.1b2
#   v0.0.1-rc.3      -> 0.0.1rc3
#
# Usage (CLI):
#   .github/scripts/tag-to-pep440.sh v0.0.1-alpha.8
#
# Usage (library — preferred from CI/workflows):
#   source .github/scripts/tag-to-pep440.sh
#   pypi_version="$(tag_to_pep440 "v0.0.1-alpha.8")"
#
# This is the single source of truth for the conversion. The
# release-python.yml `resolve` job sources this file so the test
# harness exercises the exact code path the workflow runs.
#
# Owner: python-sdk release pipeline (AAASM-2857, hardened in AAASM-2863).

# Conversion function. Reads the tag from $1 and prints the PEP 440 form
# to stdout. Returns non-zero only if the input is empty (sed itself is
# a pure transformation; unknown pre-release shapes are passed through
# unchanged so callers can layer their own validation).
tag_to_pep440() {
    local tag="${1-}"
    if [[ -z "$tag" ]]; then
        echo "tag_to_pep440: missing tag argument" >&2
        return 1
    fi
    local stripped="${tag#v}"
    printf '%s\n' "$stripped" | sed -E 's/-alpha\.([0-9]+)/a\1/; s/-beta\.([0-9]+)/b\1/; s/-rc\.([0-9]+)/rc\1/'
}

# When executed directly (not sourced), behave as a CLI: take the tag
# as $1 and print the converted version. When sourced, define the
# function only and let the caller drive it.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -euo pipefail
    tag_to_pep440 "${1-}"
fi
