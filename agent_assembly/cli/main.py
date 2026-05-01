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


def _handle_adapter_validate(args: argparse.Namespace) -> int:
    """Run adapter validation and return an exit code."""
    from agent_assembly.cli.adapter_validator import load_adapter_class, validate_adapter
    from agent_assembly.cli.output import format_results

    try:
        cls = load_adapter_class(args.path_or_module)
    except (ImportError, FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    results = validate_adapter(cls, args.path_or_module)
    print(format_results(results))

    all_passed = all(r.passed for r in results)
    return 0 if all_passed else 1


def main() -> None:
    """Parse CLI arguments and dispatch to the appropriate handler."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "adapter" and getattr(args, "adapter_command", None) == "validate":
        sys.exit(_handle_adapter_validate(args))
    else:
        parser.print_help()
        sys.exit(1)
