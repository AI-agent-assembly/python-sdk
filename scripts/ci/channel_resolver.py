#!/usr/bin/env python3
"""Resolve the ``stable`` and ``pre-release`` mike channels from the full set
of release version tags (AAASM-2750).

The deploy script (``deploy-release-version-documentation.sh``) calls this on
every release with the *complete* list of mike version ids that currently exist
on gh-pages (enumerated via ``mike list``), plus the just-released tag. This
helper recomputes BOTH channels from that full set so that:

  * ``stable``      -> the newest stable (``vX.Y.Z``) tag, if any.
  * ``pre-release`` -> the newest pre-release (``vX.Y.Z-<pre>``) tag, but ONLY
    if it is strictly greater (semver precedence) than the newest stable. When a
    stable release supersedes the newest pre-release, ``pre-release`` is removed
    (the underlying version stays as an archived, reachable mike version — only
    the moving alias is dropped).

Semver precedence (PEP-440-agnostic; we compare the git tag form):

  * ``X.Y.Z-<pre> < X.Y.Z`` (a pre-release precedes its stable).
  * Among pre-releases the dot-separated identifiers are compared left to right;
    numeric identifiers compare numerically, alphanumeric compare lexically, and
    a numeric identifier has lower precedence than an alphanumeric one.

So: ``v0.1.0-alpha.5 < v0.1.0-alpha.6 < v0.1.0-beta.1 < v0.1.0-beta.2 <
v0.1.0-rc.1 < v0.1.0``.

When there is no stable tag the stable precedence is treated as -inf, so any
pre-release shows.

Usage:
    channel_resolver.py resolve <tag> [<tag> ...]

Emits shell-eval-friendly ``KEY=VALUE`` lines on stdout:

    STABLE_VERSION=<tag-or-empty>
    PRERELEASE_VERSION=<tag-or-empty>
    PRERELEASE_SHOWN=<true|false>
    DEFAULT_CHANNEL=<stable|pre-release|latest>
"""

from __future__ import annotations

import re
import sys

# vX.Y.Z optionally followed by -<prerelease>. We deliberately ignore build
# metadata (+...) — release tags here don't carry it.
_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-(.+))?$")


def parse_tag(tag: str) -> tuple[tuple[int, int, int], list[object] | None] | None:
    """Parse a ``vX.Y.Z`` / ``vX.Y.Z-<pre>`` tag.

    Returns ``((major, minor, patch), pre)`` where ``pre`` is ``None`` for a
    stable release or a list of identifiers (str / int) for a pre-release.
    Returns ``None`` if the tag is not a recognised release tag.
    """
    m = _TAG_RE.match(tag.strip())
    if m is None:
        return None
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    pre_raw = m.group(4)
    if pre_raw is None:
        return ((major, minor, patch), None)
    identifiers: list[object] = []
    for ident in pre_raw.split("."):
        if ident.isdigit():
            identifiers.append(int(ident))
        else:
            identifiers.append(ident)
    return ((major, minor, patch), identifiers)


def _pre_key(pre: list[object]) -> list[tuple[int, object]]:
    """Build a sortable key for a list of pre-release identifiers.

    Numeric identifiers have lower precedence than alphanumeric ones, so we tag
    numerics with 0 and alphanumerics with 1; within a kind they compare
    naturally.
    """
    key: list[tuple[int, object]] = []
    for ident in pre:
        if isinstance(ident, int):
            key.append((0, ident))
        else:
            key.append((1, ident))
    return key


def precedence_key(tag: str) -> tuple[tuple[int, int, int], int, list[tuple[int, object]]]:
    """Return a total-order key implementing semver precedence for a release
    tag. A stable release sorts ABOVE every pre-release of the same X.Y.Z.
    """
    parsed = parse_tag(tag)
    if parsed is None:
        raise ValueError(f"not a release tag: {tag!r}")
    (core, pre) = parsed
    # is_stable=1 sorts above is_stable=0 for the same core triple. A pre-release
    # also needs a key shape that sorts below any stable, hence the second slot.
    if pre is None:
        return (core, 1, [])
    return (core, 0, _pre_key(pre))


def resolve(tags: list[str]) -> dict[str, object]:
    """Resolve channels from the full set of release tags.

    Unrecognised tags (e.g. ``latest``, ``master``, the ``stable`` /
    ``pre-release`` alias rows themselves) are ignored.
    """
    stables: list[str] = []
    prereleases: list[str] = []
    for tag in tags:
        parsed = parse_tag(tag)
        if parsed is None:
            continue
        if parsed[1] is None:
            stables.append(tag)
        else:
            prereleases.append(tag)

    newest_stable = max(stables, key=precedence_key) if stables else None
    newest_pre = max(prereleases, key=precedence_key) if prereleases else None

    prerelease_shown = False
    prerelease_version = ""
    if newest_pre is not None:
        prerelease_shown = newest_stable is None or precedence_key(newest_pre) > precedence_key(newest_stable)
        if prerelease_shown:
            prerelease_version = newest_pre

    if newest_stable is not None:
        default_channel = "stable"
    elif prerelease_shown:
        default_channel = "pre-release"
    else:
        default_channel = "latest"

    return {
        "STABLE_VERSION": newest_stable or "",
        "PRERELEASE_VERSION": prerelease_version,
        "PRERELEASE_SHOWN": "true" if prerelease_shown else "false",
        "DEFAULT_CHANNEL": default_channel,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] != "resolve":
        sys.stderr.write(__doc__ or "")
        return 2
    tags = argv[2:]
    result = resolve(tags)
    for key in ("STABLE_VERSION", "PRERELEASE_VERSION", "PRERELEASE_SHOWN", "DEFAULT_CHANNEL"):
        print(f"{key}={result[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
