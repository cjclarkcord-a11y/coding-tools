"""Command-line interface for copypaste duplicate detector."""

from __future__ import annotations

import argparse
import json
import os
import sys

from copypaste import version
from copypaste.detector import scan, ScanResult, DuplicateGroup


# ── ANSI color helpers ────────────────────────────────────────────────

_USE_COLOR = True


def _supports_color() -> bool:
    """Heuristic: does the terminal likely support ANSI colors?"""
    if os.environ.get("NO_COLOR"):
        return False
    if sys.platform == "win32":
        return os.environ.get("TERM") == "xterm" or "WT_SESSION" in os.environ or "ANSICON" in os.environ
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    if _USE_COLOR:
        return f"\033[{code}m{text}\033[0m"
    return text


def _bold(t: str) -> str:
    return _c("1", t)


def _dim(t: str) -> str:
    return _c("2", t)


def _cyan(t: str) -> str:
    return _c("36", t)


def _yellow(t: str) -> str:
    return _c("33", t)


def _green(t: str) -> str:
    return _c("32", t)


def _red(t: str) -> str:
    return _c("31", t)


def _magenta(t: str) -> str:
    return _c("35", t)


# ── Output formatting ────────────────────────────────────────────────


def _relative(path: str, base: str) -> str:
    """Return a short relative path for display."""
    try:
        return os.path.relpath(path, base)
    except ValueError:
        return path


def _print_text(result: ScanResult, base_path: str) -> None:
    """Print human-readable colored output."""
    print()
    print(f"  {_bold('copypaste')} - scanning {_cyan(base_path)}")
    print()

    # Summary
    print(f"  {_bold('Summary:')}")
    print(f"    Files scanned:       {_green(str(result.files_scanned))}")
    print(f"    Duplicate groups:    {_yellow(str(len(result.groups)))}")
    print(f"    Total dup lines:     {_red(str(result.total_duplicate_lines))}")
    print()

    if not result.groups:
        print(f"  {_green('No duplicates found.')}")
        print()
        return

    for i, group in enumerate(result.groups, start=1):
        header = (
            f"  {_bold(f'Duplicate group {i}')} "
            f"({_yellow(f'{group.line_count} lines')} each, "
            f"{_magenta(f'{group.copy_count} copies')}):"
        )
        print(header)

        for region in group.regions:
            rel = _relative(region.filepath, base_path)
            print(f"    {_cyan(rel)}:{region.start_line}-{region.end_line}")

        # Preview
        if group.normalized_preview:
            print()
            print(f"    {_dim('Preview (normalized):')}")
            for line in group.normalized_preview[:5]:
                print(f"      {_dim(line)}")
            if len(group.normalized_preview) > 5:
                print(f"      {_dim('...')}")
        print()


def _print_json(result: ScanResult, base_path: str) -> None:
    """Print JSON output."""
    data = {
        "files_scanned": result.files_scanned,
        "duplicate_groups": len(result.groups),
        "total_duplicate_lines": result.total_duplicate_lines,
        "groups": [],
    }
    for group in result.groups:
        g = {
            "line_count": group.line_count,
            "copy_count": group.copy_count,
            "regions": [
                {
                    "file": _relative(r.filepath, base_path),
                    "start_line": r.start_line,
                    "end_line": r.end_line,
                }
                for r in group.regions
            ],
            "preview": group.normalized_preview[:5],
        }
        data["groups"].append(g)

    print(json.dumps(data, indent=2))


# ── CLI entry point ──────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="copypaste",
        description="Detect duplicate and near-duplicate code blocks across Python and MATLAB files.",
    )
    parser.add_argument(
        "path",
        help="File or directory to scan",
    )
    parser.add_argument(
        "--min-lines",
        type=int,
        default=5,
        help="Minimum block size in lines (default: 5)",
    )
    parser.add_argument(
        "--py-only",
        action="store_true",
        help="Only scan Python (.py) files",
    )
    parser.add_argument(
        "--m-only",
        action="store_true",
        help="Only scan MATLAB (.m) files",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"copypaste {version}",
    )

    args = parser.parse_args(argv)

    global _USE_COLOR
    if args.no_color or args.json_output:
        _USE_COLOR = False
    else:
        _USE_COLOR = _supports_color()

    path = os.path.abspath(args.path)
    if not os.path.exists(path):
        print(f"Error: path does not exist: {path}", file=sys.stderr)
        sys.exit(1)

    if args.py_only and args.m_only:
        print("Error: --py-only and --m-only are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    result = scan(
        path=path,
        min_lines=args.min_lines,
        py_only=args.py_only,
        m_only=args.m_only,
    )

    base_path = path if os.path.isdir(path) else os.path.dirname(path)

    if args.json_output:
        _print_json(result, base_path)
    else:
        _print_text(result, base_path)

    # Exit with code 1 if duplicates found (useful for CI)
    if result.groups:
        sys.exit(1)
    sys.exit(0)
