"""Command-line interface for deadfiles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from deadfiles import version
from deadfiles.scanner import scan


# --- ANSI colour helpers (stdlib only) ---

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_WHITE = "\033[37m"


class _Colors:
    """Thin wrapper that can disable colour output."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        if self.enabled:
            return f"{code}{text}{_RESET}"
        return text

    def bold(self, text: str) -> str:
        return self._wrap(_BOLD, text)

    def dim(self, text: str) -> str:
        return self._wrap(_DIM, text)

    def red(self, text: str) -> str:
        return self._wrap(_RED, text)

    def green(self, text: str) -> str:
        return self._wrap(_GREEN, text)

    def yellow(self, text: str) -> str:
        return self._wrap(_YELLOW, text)

    def cyan(self, text: str) -> str:
        return self._wrap(_CYAN, text)

    def white(self, text: str) -> str:
        return self._wrap(_WHITE, text)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deadfiles",
        description="Find orphaned source files that nothing references.",
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Directory to scan",
    )
    parser.add_argument(
        "--py-only",
        action="store_true",
        default=False,
        help="Only scan Python (.py) files",
    )
    parser.add_argument(
        "--m-only",
        action="store_true",
        default=False,
        help="Only scan MATLAB (.m) files",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        default=False,
        help="Include test files in the dead-file check",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        dest="json_output",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable coloured output",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Show entry-point files and extra details",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"deadfiles {version}",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    target: Path = args.path.resolve()
    if not target.is_dir():
        print(f"Error: {target} is not a directory", file=sys.stderr)
        sys.exit(1)

    # Determine colour support
    use_color = not args.no_color and sys.stdout.isatty()
    c = _Colors(enabled=use_color)

    if not args.json_output:
        print()
        print(f"  {c.bold('deadfiles')} - scanning {c.cyan(str(target))}/...")
        print()

    result = scan(
        target,
        py_only=args.py_only,
        m_only=args.m_only,
        include_tests=args.include_tests,
    )

    # --- JSON output ---
    if args.json_output:
        json.dump(result.to_dict(), sys.stdout, indent=2)
        print()
        return

    # --- Coloured text output ---
    ref_count = result.total_referenced
    dead_count = result.total_dead

    print(f"  {c.bold('Summary:')}")
    print(f"    Files scanned:  {c.white(str(result.total_scanned)):>6}")
    print(f"    Referenced:     {c.green(str(ref_count)):>6}")
    print(f"    Dead files:     {c.red(str(dead_count)) if dead_count else c.green(str(dead_count)):>6}")
    print()

    # Verbose: show entry points
    if args.verbose and result.entry_points:
        print(f"  {c.bold('Entry points')} ({len(result.entry_points)} excluded):")
        for fp in sorted(result.entry_points):
            rel = fp.relative_to(result.root)
            print(f"    {c.dim(str(rel))}  {c.dim('(entry point, excluded)')}")
        print()

    if dead_count == 0:
        print(f"  {c.green('No dead files found.')}")
        print()
        return

    print(f"  {c.bold('Dead files')} ({dead_count} found):")
    for fp in result.dead_files:
        rel = fp.relative_to(result.root)
        refs = result.reference_count(fp)
        print(f"    {c.yellow(str(rel)):<40} {c.dim(f'({refs} references)')}")
    print()

    sys.exit(1)
