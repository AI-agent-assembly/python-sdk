"""CLI entry point for Agent Assembly SDK tools."""

from __future__ import annotations

import argparse
import sys


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with the adapter subcommand."""
    parser = argparse.ArgumentParser(
        prog="aasm",
        description="Agent Assembly SDK command-line tools.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    adapter_parser = subparsers.add_parser(
        "adapter", help="Adapter management commands"
    )
    adapter_subparsers = adapter_parser.add_subparsers(
        dest="adapter_command", help="Adapter subcommands"
    )

    validate_parser = adapter_subparsers.add_parser(
        "validate", help="Validate a community adapter against the FrameworkAdapter contract"
    )
    validate_parser.add_argument(
        "path_or_module",
        help="File path or dotted module name of the adapter to validate",
    )

    return parser
