#!/usr/bin/env bash
#
# Unit tests for `.github/scripts/tag-to-pep440.sh`.
#
# Exercises the conversion function that release-python.yml's `resolve`
# job sources to turn an agent-assembly release tag into a PEP 440
# version string. Because the workflow sources the same file, these
# tests cover the actual code path CI runs, not a copy of the regex.
#
# Run locally:
#   bash .github/scripts/test_tag_to_pep440.sh
#
# Run from CI: see .github/workflows/release-python-conversion-test.yml.
#
# Exits 0 when every fixture passes, 1 otherwise. Prints a per-fixture
# OK/FAIL line plus a final pass/fail/total summary.
#
# Refs AAASM-2863.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=.github/scripts/tag-to-pep440.sh
source "${SCRIPT_DIR}/tag-to-pep440.sh"

pass=0
fail=0
total=0

# assert_eq <label> <expected> <actual>
assert_eq() {
    local label="$1"
    local expected="$2"
    local actual="$3"
    total=$((total + 1))
    if [[ "$expected" == "$actual" ]]; then
        printf 'OK    %-50s -> %s\n' "$label" "$actual"
        pass=$((pass + 1))
    else
        printf 'FAIL  %-50s expected=%q actual=%q\n' "$label" "$expected" "$actual" >&2
        fail=$((fail + 1))
    fi
}

# check <tag> <expected_pep440>
check() {
    local tag="$1"
    local expected="$2"
    local actual
    actual="$(tag_to_pep440 "$tag")"
    assert_eq "$tag" "$expected" "$actual"
}

echo "== tag_to_pep440 fixtures =="

# AAASM-2863 acceptance criteria — six fixture categories from the
# ticket description, exact strings from the AC bullet list.

# Stable form (no pre-release suffix).
check "v0.0.1"               "0.0.1"

# Alpha pre-release, single + double digit.
check "v0.0.1-alpha.1"       "0.0.1a1"
check "v0.0.1-alpha.10"      "0.0.1a10"

# Beta pre-release.
check "v0.0.1-beta.2"        "0.0.1b2"

# Release candidate.
check "v0.0.1-rc.3"          "0.0.1rc3"

# Multi-digit version components in the base version + a large
# pre-release counter — guards against accidental greedy matching
# clobbering the minor/patch numbers.
check "v1.23.456-alpha.789"  "1.23.456a789"

# --- Extra coverage beyond the AC minimum ---
#
# These are not strictly required by the ticket but document the
# script's intended behaviour for edge cases the workflow may meet.

# A "v" prefix is stripped, even when there is no pre-release.
check "v10.20.30"            "10.20.30"

# An unknown pre-release type passes through unchanged: the script
# is a pure transformation; PEP 440 validation lives in the workflow.
# Documenting this prevents anyone "fixing" the regex to swallow it.
check "v0.0.1-dev.1"         "0.0.1-dev.1"

# Beta + rc with multi-digit counters mirror alpha.10 for symmetry.
check "v0.0.1-beta.42"       "0.0.1b42"
check "v0.0.1-rc.99"         "0.0.1rc99"

# Empty input is an error — the workflow relies on this to fail fast
# rather than emit an empty pypi_version.
echo "== empty-input guard =="
total=$((total + 1))
if err="$(tag_to_pep440 "" 2>&1 >/dev/null)"; then
    printf 'FAIL  empty input should have exited non-zero (stderr=%q)\n' "$err" >&2
    fail=$((fail + 1))
else
    printf 'OK    empty input rejected (stderr=%q)\n' "$err"
    pass=$((pass + 1))
fi

echo
echo "Summary: ${pass} passed, ${fail} failed, ${total} total"
if (( fail > 0 )); then
    exit 1
fi
