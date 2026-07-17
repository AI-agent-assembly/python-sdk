"""Internal helpers shared across framework adapters.

This package holds framework-agnostic governance plumbing that would otherwise be
copy-pasted verbatim into each adapter's ``patch`` module. It is private (leading
underscore): adapters import from it, but it is not part of the public SDK API.
"""
