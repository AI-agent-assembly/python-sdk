#!/usr/bin/env bash
#
# Drift guard: fail when the release wheel-build interpreter matrix diverges
# from the Python support pyproject.toml declares.
#
# AAASM-4446 shipped rc3 with cp312-only wheels while pyproject claimed
# 3.12/3.13/3.14, so a 3.13 install silently fell back to a native-core-less
# sdist and governance registration became a no-op. The root cause was a
# hand-maintained build matrix drifting from `requires-python` + the Python
# classifiers with nothing checking they agree. This script is that check.
#
# It compares three facts and fails (non-zero) on any mismatch:
#   1. The "Programming Language :: Python :: 3.x" classifiers in pyproject.
#   2. The PYTHON_INTERPRETERS list in release-python.yml (the versions every
#      wheel job actually builds for — see that file's single-source comment).
#   3. The `requires-python` lower bound in pyproject.
# The built set must equal the classifier set, and the requires-python floor
# must equal the lowest built version. It also fails if any wheel job hardcodes
# a literal `--interpreter <version>` list, bypassing the single source.
#
# Run locally:
#   bash .github/scripts/check-wheel-python-matrix.sh
#
# Run from CI: see .github/workflows/wheel-python-matrix.yml (runs on every PR
# that touches pyproject.toml or the release workflow, not only at release).
#
# Usage (CLI, paths optional — default to the repo's files; overridable so the
# fixture suite can point at temp copies):
#   .github/scripts/check-wheel-python-matrix.sh [pyproject.toml] [release-python.yml]
#
# Owner: python-sdk release pipeline (AAASM-4453).

# Print each "3.<minor>" declared by a Python classifier, numerically sorted,
# deduped. The bare ":: 3" classifier (no minor) is intentionally excluded.
extract_classifier_versions() {
    local pyproject="$1"
    grep -oE 'Programming Language :: Python :: 3\.[0-9]+' "$pyproject" \
        | grep -oE '3\.[0-9]+' \
        | sort -t. -k2,2n -u
}

# Print the lower-bound "3.<minor>" from `requires-python = ">=3.X,<4.0"`.
extract_requires_python_floor() {
    local pyproject="$1"
    grep -E '^[[:space:]]*requires-python[[:space:]]*=' "$pyproject" \
        | grep -oE '>=[[:space:]]*3\.[0-9]+' \
        | grep -oE '3\.[0-9]+' \
        | head -n1
}

# Print each version in the workflow's PYTHON_INTERPRETERS env value,
# numerically sorted, deduped.
extract_built_interpreters() {
    local workflow="$1"
    grep -E '^[[:space:]]*PYTHON_INTERPRETERS[[:space:]]*:' "$workflow" \
        | head -n1 \
        | grep -oE "'[^']*'" \
        | tr -d "'" \
        | tr ' ' '\n' \
        | grep -E '^3\.[0-9]+$' \
        | sort -t. -k2,2n -u
}

# check_wheel_python_matrix <pyproject_path> <workflow_path>
# Returns 0 when the matrix matches declared support, non-zero otherwise.
check_wheel_python_matrix() {
    local pyproject="${1:-pyproject.toml}"
    local workflow="${2:-.github/workflows/release-python.yml}"
    local rc=0

    if [[ ! -f "$pyproject" ]]; then
        echo "::error::pyproject not found: $pyproject" >&2
        return 1
    fi
    if [[ ! -f "$workflow" ]]; then
        echo "::error::release workflow not found: $workflow" >&2
        return 1
    fi

    local classifiers built floor
    classifiers="$(extract_classifier_versions "$pyproject")"
    built="$(extract_built_interpreters "$workflow")"
    floor="$(extract_requires_python_floor "$pyproject")"

    # A parse miss must fail loud, never pass vacuously — an empty extraction
    # would otherwise make two empty strings compare equal.
    if [[ -z "$classifiers" ]]; then
        echo "::error::no 'Programming Language :: Python :: 3.x' classifiers found in $pyproject" >&2
        return 1
    fi
    if [[ -z "$built" ]]; then
        echo "::error::no PYTHON_INTERPRETERS list found in $workflow" >&2
        return 1
    fi
    if [[ -z "$floor" ]]; then
        echo "::error::could not parse requires-python lower bound in $pyproject" >&2
        return 1
    fi

    # Core drift check: the versions wheels are built for must equal the
    # versions pyproject advertises support for.
    if [[ "$classifiers" != "$built" ]]; then
        {
            echo "::error::wheel build matrix diverges from pyproject Python classifiers"
            printf 'pyproject classifiers : %s\n' "$(echo "$classifiers" | paste -sd' ' -)"
            printf 'built (PYTHON_INTERPRETERS): %s\n' "$(echo "$built" | paste -sd' ' -)"
        } >&2
        rc=1
    fi

    # A requires-python floor bump without dropping the matching classifier +
    # wheel (or vice versa) is itself a support-claim drift — catch it.
    local min_built
    min_built="$(echo "$built" | head -n1)"
    if [[ "$floor" != "$min_built" ]]; then
        echo "::error::requires-python floor (>=$floor) != lowest built interpreter ($min_built)" >&2
        rc=1
    fi

    # No wheel job may hardcode a literal `--interpreter <version>` list: that
    # would let one platform silently drift from the single source of truth,
    # which is exactly the failure mode this guard exists to prevent.
    local literal
    literal="$(grep -nE -- '--interpreter[[:space:]]+[0-9]' "$workflow" || true)"
    if [[ -n "$literal" ]]; then
        {
            echo "::error::a wheel job hardcodes --interpreter versions instead of \${{ env.PYTHON_INTERPRETERS }}:"
            printf '%s\n' "$literal"
        } >&2
        rc=1
    fi

    if [[ "$rc" -eq 0 ]]; then
        echo "OK: wheel build matrix matches pyproject Python support ($(echo "$built" | paste -sd' ' -)); requires-python floor >=$floor"
    fi
    return "$rc"
}

# When executed directly, run the check as a CLI. When sourced, define the
# functions only and let the caller (the fixture suite) drive them.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -uo pipefail
    check_wheel_python_matrix "${1:-}" "${2:-}"
fi
