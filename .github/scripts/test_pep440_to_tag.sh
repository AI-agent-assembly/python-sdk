#!/usr/bin/env bash
#
# Unit tests for `.github/scripts/pep440-to-tag.sh`.
#
# Exercises the conversion function that release-python.yml's `resolve`
# job sources to turn a published PEP 440 version back into the canonical
# SemVer release tag the create-github-release job cuts. Because the
# workflow sources the same file, these tests cover the actual code path
# CI runs, not a copy of the regex.
#
# Run locally:
#   bash .github/scripts/test_pep440_to_tag.sh
#
# Run from CI: see .github/workflows/release-python-conversion-test.yml.
#
# Exits 0 when every fixture passes, 1 otherwise.
#
# Refs AAASM-2956.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=.github/scripts/pep440-to-tag.sh
source "${SCRIPT_DIR}/pep440-to-tag.sh"
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

# check <pep440> <expected_tag>
check() {
    local version="$1"
    local expected="$2"
    local actual
    actual="$(pep440_to_tag "$version")"
    assert_eq "$version" "$expected" "$actual"
}

echo "== pep440_to_tag fixtures =="

# Stable form (no pre-release suffix).
check "0.0.1"        "v0.0.1"

# Alpha pre-release, single + double digit.
check "0.0.1a1"      "v0.0.1-alpha.1"
check "0.0.1a10"     "v0.0.1-alpha.10"

# Beta — the version this ticket backfills (0.0.1b1 -> v0.0.1-beta.1).
check "0.0.1b1"      "v0.0.1-beta.1"
check "0.0.1b2"      "v0.0.1-beta.2"

# Release candidate.
check "0.0.1rc3"     "v0.0.1-rc.3"

# Multi-digit base components + large pre-release counter — guard against
# greedy matching clobbering the minor/patch numbers.
check "1.23.456a789" "v1.23.456-alpha.789"

# A stray leading "v" the caller passed by mistake is tolerated.
check "v0.0.1b1"     "v0.0.1-beta.1"

echo "== roundtrip with tag_to_pep440 =="
# Every canonical tag must survive a tag -> pep440 -> tag roundtrip.
for tag in v0.0.1 v0.0.1-alpha.8 v0.0.1-beta.1 v0.0.1-rc.3 v1.23.456-alpha.789; do
    pep="$(tag_to_pep440 "$tag")"
    back="$(pep440_to_tag "$pep")"
    assert_eq "roundtrip ${tag}" "$tag" "$back"
done

echo "== empty-input guard =="
total=$((total + 1))
if err="$(pep440_to_tag "" 2>&1 >/dev/null)"; then
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
