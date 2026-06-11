#!/usr/bin/env python3
"""Unit tests for the channel-resolution logic (AAASM-2750).

Runs the ``resolve`` function over the scenarios mandated by the ticket and
asserts both channels are computed correctly from the FULL version set, proving
the semver gate that hides ``pre-release`` once a stable supersedes it.

Run directly: ``python3 scripts/ci/test_channel_resolver.py``
or under pytest:  ``pytest scripts/ci/test_channel_resolver.py``
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from channel_resolver import precedence_key, resolve  # noqa: E402

# Base set: a stable v0.0.2 plus the full v0.1.0 pre-release ladder.
SCENARIO_1 = [
    "v0.0.2",
    "v0.1.0-alpha.5",
    "v0.1.0-alpha.6",
    "v0.1.0-beta.1",
    "v0.1.0-beta.2",
    "v0.1.0-rc.1",
]
# Scenario 2: the v0.1.0 stable ships and supersedes the whole pre-release ladder.
SCENARIO_2 = SCENARIO_1 + ["v0.1.0"]
# Scenario 3: a fresh v0.2.0 pre-release opens, now ahead of stable v0.1.0 again.
SCENARIO_3 = SCENARIO_2 + ["v0.2.0-alpha.1"]


def _check(name: str, got: object, want: object) -> bool:
    ok = got == want
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}: got={got!r} want={want!r}")
    return ok


def test_precedence_ladder() -> None:
    """Sanity-check the semver comparator's ordering before exercising resolve."""
    ladder = [
        "v0.1.0-alpha.5",
        "v0.1.0-alpha.6",
        "v0.1.0-beta.1",
        "v0.1.0-beta.2",
        "v0.1.0-rc.1",
        "v0.1.0",
    ]
    keys = [precedence_key(t) for t in ladder]
    assert keys == sorted(keys), "semver ladder is not strictly increasing"
    # Strictly increasing: every adjacent pair must be <, never == (no ties).
    for lower, higher in zip(keys, keys[1:], strict=False):
        assert lower < higher, "semver ladder has a tie or inversion"


def test_scenario_1_prerelease_ahead() -> None:
    """Pre-release ladder is ahead of the lone stable -> both channels show."""
    r = resolve(SCENARIO_1)
    assert r["PRERELEASE_VERSION"] == "v0.1.0-rc.1"
    assert r["STABLE_VERSION"] == "v0.0.2"
    assert r["PRERELEASE_SHOWN"] == "true"
    assert r["DEFAULT_CHANNEL"] == "stable"


def test_scenario_2_stable_supersedes() -> None:
    """v0.1.0 stable supersedes the ladder -> pre-release alias is dropped."""
    r = resolve(SCENARIO_2)
    assert r["STABLE_VERSION"] == "v0.1.0"
    assert r["PRERELEASE_VERSION"] == ""
    assert r["PRERELEASE_SHOWN"] == "false"
    assert r["DEFAULT_CHANNEL"] == "stable"


def test_scenario_3_new_prerelease_ahead() -> None:
    """A new v0.2.0-alpha.1 is ahead of stable v0.1.0 -> pre-release returns."""
    r = resolve(SCENARIO_3)
    assert r["PRERELEASE_VERSION"] == "v0.2.0-alpha.1"
    assert r["STABLE_VERSION"] == "v0.1.0"
    assert r["PRERELEASE_SHOWN"] == "true"
    assert r["DEFAULT_CHANNEL"] == "stable"


def test_no_stable_any_prerelease_shows() -> None:
    """No stable at all -> stable precedence is -inf -> pre-release shows."""
    r = resolve(["v0.1.0-alpha.1"])
    assert r["STABLE_VERSION"] == ""
    assert r["PRERELEASE_VERSION"] == "v0.1.0-alpha.1"
    assert r["PRERELEASE_SHOWN"] == "true"
    assert r["DEFAULT_CHANNEL"] == "pre-release"


def _run_standalone() -> int:
    """Human-readable scenario runner used when invoked directly (not pytest)."""
    all_ok = True

    print("Scenario 1: {v0.0.2, v0.1.0-alpha.5..rc.1} -> pre-release ahead of stable")
    r1 = resolve(SCENARIO_1)
    all_ok &= _check("pre-release", r1["PRERELEASE_VERSION"], "v0.1.0-rc.1")
    all_ok &= _check("stable", r1["STABLE_VERSION"], "v0.0.2")
    all_ok &= _check("pre-release shown", r1["PRERELEASE_SHOWN"], "true")

    print("Scenario 2: + v0.1.0 -> stable supersedes ladder, pre-release HIDDEN")
    r2 = resolve(SCENARIO_2)
    all_ok &= _check("stable", r2["STABLE_VERSION"], "v0.1.0")
    all_ok &= _check("pre-release", r2["PRERELEASE_VERSION"], "")
    all_ok &= _check("pre-release shown", r2["PRERELEASE_SHOWN"], "false")

    print("Scenario 3: + v0.2.0-alpha.1 -> new pre-release ahead of stable again")
    r3 = resolve(SCENARIO_3)
    all_ok &= _check("pre-release", r3["PRERELEASE_VERSION"], "v0.2.0-alpha.1")
    all_ok &= _check("stable", r3["STABLE_VERSION"], "v0.1.0")
    all_ok &= _check("pre-release shown", r3["PRERELEASE_SHOWN"], "true")

    print()
    print("RESULT:", "ALL PASS" if all_ok else "FAILURES PRESENT")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
