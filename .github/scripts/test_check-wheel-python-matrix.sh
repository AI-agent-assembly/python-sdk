#!/usr/bin/env bash
#
# Unit tests for `.github/scripts/check-wheel-python-matrix.sh`.
#
# Drives the drift guard that keeps the release wheel matrix in sync with the
# Python support pyproject.toml declares (AAASM-4446 / AAASM-4453). Sources the
# same file CI runs, then exercises it against synthetic pyproject/workflow
# fixtures for both the passing and the drifting cases — plus one run against
# the repo's real files to prove the shipped config actually passes.
#
# Run locally:
#   bash .github/scripts/test_check-wheel-python-matrix.sh
#
# Run from CI: see .github/workflows/wheel-python-matrix.yml.
#
# Exits 0 when every case passes, 1 otherwise.
#
# Refs AAASM-4453.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# shellcheck source=.github/scripts/check-wheel-python-matrix.sh
source "${SCRIPT_DIR}/check-wheel-python-matrix.sh"

# Literal GitHub Actions env reference — kept in a single-quoted variable so
# bash never tries to expand `${{ ... }}`. The non-expansion is the point here.
# shellcheck disable=SC2016
ENVREF='${{ env.PYTHON_INTERPRETERS }}'

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

pass=0
fail=0
total=0

# assert_exit <label> <expected_rc> <actual_rc>
assert_exit() {
    local label="$1" expected="$2" actual="$3"
    total=$((total + 1))
    if [[ "$expected" == "$actual" ]]; then
        printf 'OK    %-52s rc=%s\n' "$label" "$actual"
        pass=$((pass + 1))
    else
        printf 'FAIL  %-52s expected rc=%s actual rc=%s\n' "$label" "$expected" "$actual" >&2
        fail=$((fail + 1))
    fi
}

# write_pyproject <path> <requires-python> <classifier-minor>...
write_pyproject() {
    local path="$1" requires="$2"; shift 2
    {
        echo '[project]'
        echo "requires-python = \"$requires\""
        echo 'classifiers = ['
        echo '    "Programming Language :: Python :: 3",'
        local v
        for v in "$@"; do
            echo "    \"Programming Language :: Python :: $v\","
        done
        echo ']'
    } > "$path"
}

# write_workflow <path> <PYTHON_INTERPRETERS value> [interpreter-arg]
# interpreter-arg defaults to the env reference (the correct, non-drifting form).
write_workflow() {
    local path="$1" interpreters="$2" arg="${3:-$ENVREF}"
    {
        echo 'env:'
        echo "  PYTHON_INTERPRETERS: '$interpreters'"
        echo 'jobs:'
        echo '  build-macos:'
        echo '    steps:'
        echo "      - run: maturin build --release --interpreter $arg"
    } > "$path"
}

# run_guard <pyproject> <workflow> -> echoes the guard's exit code
run_guard() {
    check_wheel_python_matrix "$1" "$2" >/dev/null 2>&1
    echo "$?"
}

echo "== real repo files (shipped config must pass) =="
assert_exit "real pyproject.toml + release-python.yml" 0 \
    "$(run_guard "${REPO_ROOT}/pyproject.toml" "${REPO_ROOT}/.github/workflows/release-python.yml")"

echo "== synthetic: matching matrix passes =="
write_pyproject "${WORKDIR}/ok.toml" ">=3.12,<4.0" 3.12 3.13 3.14
write_workflow  "${WORKDIR}/ok.yml"  "3.12 3.13 3.14"
assert_exit "classifiers == built, floor == min" 0 \
    "$(run_guard "${WORKDIR}/ok.toml" "${WORKDIR}/ok.yml")"

echo "== synthetic: drift is caught =="
# Classifier claims a version the matrix does not build (the AAASM-4446 shape).
write_pyproject "${WORKDIR}/extra_classifier.toml" ">=3.12,<4.0" 3.12 3.13 3.14
write_workflow  "${WORKDIR}/short_matrix.yml" "3.12"
assert_exit "classifiers superset of built (cp313/cp314 unbuilt)" 1 \
    "$(run_guard "${WORKDIR}/extra_classifier.toml" "${WORKDIR}/short_matrix.yml")"

# Matrix builds a version pyproject does not advertise.
write_pyproject "${WORKDIR}/narrow_classifier.toml" ">=3.12,<4.0" 3.12 3.13
write_workflow  "${WORKDIR}/wide_matrix.yml" "3.12 3.13 3.14"
assert_exit "built superset of classifiers" 1 \
    "$(run_guard "${WORKDIR}/narrow_classifier.toml" "${WORKDIR}/wide_matrix.yml")"

echo "== synthetic: requires-python floor drift is caught =="
# Floor says >=3.13 but 3.12 is still built + classified.
write_pyproject "${WORKDIR}/floor.toml" ">=3.13,<4.0" 3.12 3.13
write_workflow  "${WORKDIR}/floor.yml"  "3.12 3.13"
assert_exit "requires-python floor > lowest built version" 1 \
    "$(run_guard "${WORKDIR}/floor.toml" "${WORKDIR}/floor.yml")"

echo "== synthetic: hardcoded --interpreter literal is caught =="
write_pyproject "${WORKDIR}/lit.toml" ">=3.12,<4.0" 3.12 3.13 3.14
write_workflow  "${WORKDIR}/lit.yml"  "3.12 3.13 3.14" "3.12 3.13 3.14"
assert_exit "job hardcodes --interpreter versions" 1 \
    "$(run_guard "${WORKDIR}/lit.toml" "${WORKDIR}/lit.yml")"

echo "== synthetic: unparseable inputs fail loud, not vacuously pass =="
# pyproject with only the bare ":: 3" classifier (no minor versions).
write_pyproject "${WORKDIR}/noclass.toml" ">=3.12,<4.0"
write_workflow  "${WORKDIR}/noclass.yml"  "3.12"
assert_exit "no Python minor classifiers" 1 \
    "$(run_guard "${WORKDIR}/noclass.toml" "${WORKDIR}/noclass.yml")"

# workflow with no PYTHON_INTERPRETERS env at all.
write_pyproject "${WORKDIR}/nolist.toml" ">=3.12,<4.0" 3.12
printf 'env:\n  OTHER: x\n' > "${WORKDIR}/nolist.yml"
assert_exit "no PYTHON_INTERPRETERS in workflow" 1 \
    "$(run_guard "${WORKDIR}/nolist.toml" "${WORKDIR}/nolist.yml")"

echo
echo "Summary: ${pass} passed, ${fail} failed, ${total} total"
if (( fail > 0 )); then
    exit 1
fi
