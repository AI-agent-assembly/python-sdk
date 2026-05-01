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

    subparsers.add_parser("adapter", help="Adapter management commands")

    return parser
