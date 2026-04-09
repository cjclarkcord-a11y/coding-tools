"""CLI interface with colored output for staletrack."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from staletrack import version
from staletrack.scanner import CommentedCodeBlock, MarkerItem, ScanResult, scan


# ANSI color codes
class _Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_CYAN = "\033[96m"


_NO_COLORS = type("NoColors", (), {k: "" for k in vars(_Colors) if not k.startswith("_")})()


def _staleness_color(staleness: str, c: object) -> str:
    """Return color code for a staleness category."""
    match staleness:
        case "ANCIENT":
            return c.BRIGHT_RED  # type: ignore[attr-defined]
        case "STALE":
            return c.YELLOW  # type: ignore[attr-defined]
        case "AGING":
            return c.BRIGHT_YELLOW  # type: ignore[attr-defined]
        case "FRESH":
            return c.BRIGHT_GREEN  # type: ignore[attr-defined]
        case _:
            return c.WHITE  # type: ignore[attr-defined]


def _keyword_color(keyword: str, c: object) -> str:
    """Return color code for a marker keyword."""
    kw = keyword.upper()
    if kw in ("FIXME", "HACK", "XXX"):
        return c.RED  # type: ignore[attr-defined]
    if kw == "TODO":
        return c.CYAN  # type: ignore[attr-defined]
    return c.MAGENTA  # type: ignore[attr-defined]


def _relative_path(filepath: Path, root: Path) -> str:
    """Get path relative to scan root, for display."""
    try:
        return str(filepath.relative_to(root))
    except ValueError:
        return str(filepath)


def _sort_items(
    items: list[MarkerItem | CommentedCodeBlock],
    sort_by: str,
) -> list[MarkerItem | CommentedCodeBlock]:
    """Sort items by the given key."""
    def _age_key(item: MarkerItem | CommentedCodeBlock) -> int:
        blame = item.blame
        if blame is None:
            return 0  # unknown age sorts first (freshest)
        return blame.age_seconds

    def _file_key(item: MarkerItem | CommentedCodeBlock) -> tuple[str, int]:
        if isinstance(item, MarkerItem):
            return (str(item.filepath), item.line_number)
        return (str(item.filepath), item.start_line)

    def _type_key(item: MarkerItem | CommentedCodeBlock) -> tuple[int, str, int]:
        if isinstance(item, CommentedCodeBlock):
            type_order = 1
            kw = "COMMENTED CODE"
        else:
            type_order = 0
            kw = item.keyword
        line = item.line_number if isinstance(item, MarkerItem) else item.start_line
        return (type_order, kw, line)

    match sort_by:
        case "age":
            return sorted(items, key=_age_key, reverse=True)  # oldest first
        case "file":
            return sorted(items, key=_file_key)
        case "type":
            return sorted(items, key=_type_key)
        case _:
            return sorted(items, key=_age_key, reverse=True)


def _filter_stale(items: list[MarkerItem | CommentedCodeBlock]) -> list[MarkerItem | CommentedCodeBlock]:
    """Keep only items older than 180 days."""
    return [
        item for item in items
        if item.blame is not None and item.blame.staleness in ("STALE", "ANCIENT")
    ]


def _format_json(result: ScanResult, root: Path) -> str:
    """Format scan results as JSON."""
    items = []
    for m in result.markers:
        entry: dict = {
            "type": "marker",
            "keyword": m.keyword,
            "file": _relative_path(m.filepath, root),
            "line": m.line_number,
            "text": m.text,
        }
        if m.blame:
            entry["age"] = m.blame.age_text
            entry["author"] = m.blame.author
            entry["staleness"] = m.blame.staleness
            entry["timestamp"] = m.blame.timestamp
        items.append(entry)

    for b in result.commented_blocks:
        entry = {
            "type": "commented_code",
            "file": _relative_path(b.filepath, root),
            "start_line": b.start_line,
            "end_line": b.end_line,
            "line_count": b.line_count,
            "preview": b.lines[:4],
        }
        if b.blame:
            entry["age"] = b.blame.age_text
            entry["author"] = b.blame.author
            entry["staleness"] = b.blame.staleness
            entry["timestamp"] = b.blame.timestamp
        items.append(entry)

    output = {
        "version": version,
        "files_scanned": result.files_scanned,
        "summary": {
            "todos": len(result.todos),
            "fixmes": len(result.fixmes),
            "hacks": len(result.hacks),
            "commented_code_blocks": len(result.commented_blocks),
            "commented_code_lines": result.commented_line_count,
        },
        "items": items,
    }
    return json.dumps(output, indent=2)


def _print_output(result: ScanResult, root: Path, args: argparse.Namespace) -> None:
    """Print formatted output to stdout."""
    c = _NO_COLORS if args.no_color else _Colors()

    if args.json:
        print(_format_json(result, root))
        return

    # Header
    print(f"\n  {c.BOLD}staletrack{c.RESET} - scanning {_relative_path(root, root.parent)}/...\n")

    # Summary
    print(f"  {c.BOLD}Summary:{c.RESET}")
    print(f"    Files scanned:  {c.BOLD}{result.files_scanned:>4}{c.RESET}")
    print(f"    TODOs:          {c.BOLD}{len(result.todos):>4}{c.RESET}")
    print(f"    FIXMEs:         {c.BOLD}{len(result.fixmes):>4}{c.RESET}")
    print(f"    HACKs:          {c.BOLD}{len(result.hacks):>4}{c.RESET}")
    blocks = len(result.commented_blocks)
    lines = result.commented_line_count
    print(f"    Commented code: {c.BOLD}{blocks:>4}{c.RESET} blocks ({lines} lines)")
    print()

    # Collect and sort items
    items: list[MarkerItem | CommentedCodeBlock] = result.all_items

    if args.stale_only:
        items = _filter_stale(items)

    items = _sort_items(items, args.sort)

    if not items:
        print(f"  {c.DIM}No items found.{c.RESET}\n")
        return

    # Print each item
    for item in items:
        blame = item.blame
        staleness = blame.staleness if blame else "UNKNOWN"
        sc = _staleness_color(staleness, c)
        staleness_label = f"{sc}{c.BOLD}{staleness:<8}{c.RESET}"

        if isinstance(item, MarkerItem):
            kc = _keyword_color(item.keyword, c)
            location = f"{_relative_path(item.filepath, root)}:{item.line_number}"
            age_info = ""
            if blame:
                age_info = f"  ({blame.age_text}, by {blame.author})"
            print(f"  {staleness_label}  {kc}{c.BOLD}{item.keyword}{c.RESET}  {c.DIM}{location}{c.RESET}{age_info}")
            if item.text:
                print(f"    {c.DIM}\"{item.text}\"{c.RESET}")
            print()

        elif isinstance(item, CommentedCodeBlock):
            location = f"{_relative_path(item.filepath, root)}:{item.start_line}-{item.end_line}"
            age_info = ""
            if blame:
                age_info = f"  ({blame.age_text}, by {blame.author})"
            print(f"  {staleness_label}  {c.MAGENTA}{c.BOLD}COMMENTED CODE{c.RESET}  {c.DIM}{location}{c.RESET}{age_info}")
            print(f"    {item.line_count} lines of commented-out code")
            # Show preview (up to 4 lines, then ...)
            preview_lines = item.lines[:4]
            for pline in preview_lines:
                print(f"    {c.DIM}|  {pline.rstrip()}{c.RESET}")
            if len(item.lines) > 4:
                print(f"    {c.DIM}|  ...{c.RESET}")
            print()

    # Age distribution
    _print_age_distribution(items, c)


def _print_age_distribution(
    items: list[MarkerItem | CommentedCodeBlock],
    c: object,
) -> None:
    """Print a bar chart of age distribution."""
    counts = {"FRESH": 0, "AGING": 0, "STALE": 0, "ANCIENT": 0, "UNKNOWN": 0}
    for item in items:
        if item.blame:
            counts[item.blame.staleness] += 1
        else:
            counts["UNKNOWN"] += 1

    total = len(items)
    if total == 0:
        return

    print(f"  {c.BOLD}Age distribution:{c.RESET}")  # type: ignore[attr-defined]

    categories = [
        ("FRESH", "<30d"),
        ("AGING", "30-180d"),
        ("STALE", "180d-1y"),
        ("ANCIENT", ">1y"),
    ]

    max_bar = 20
    for cat, label in categories:
        count = counts[cat]
        pct = (count / total * 100) if total > 0 else 0
        bar_len = round(count / total * max_bar) if total > 0 else 0
        bar = "\u2588" * bar_len
        sc = _staleness_color(cat, c)
        reset = c.RESET  # type: ignore[attr-defined]
        dim = c.DIM  # type: ignore[attr-defined]
        print(f"    {sc}{cat:<8}{reset} ({label:>8}): {count:>4}  {sc}{bar}{reset}  {dim}{pct:.0f}%{reset}")

    if counts["UNKNOWN"] > 0:
        unk = counts["UNKNOWN"]
        pct = unk / total * 100
        dim = c.DIM  # type: ignore[attr-defined]
        reset = c.RESET  # type: ignore[attr-defined]
        print(f"    {dim}UNKNOWN  (no git):  {unk:>4}  {pct:.0f}%{reset}")

    print()


def main(argv: list[str] | None = None) -> None:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="staletrack",
        description="Track stale TODOs, FIXMEs, and commented-out code with git blame ages.",
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Directory or file to scan",
    )
    parser.add_argument(
        "--todos",
        action="store_true",
        help="Only show TODO/FIXME/HACK markers",
    )
    parser.add_argument(
        "--commented-code",
        action="store_true",
        help="Only show commented-out code blocks",
    )
    parser.add_argument(
        "--stale-only",
        action="store_true",
        help="Only show items older than 180 days",
    )
    parser.add_argument(
        "--sort",
        choices=["age", "file", "type"],
        default="age",
        help="Sort results by: age (oldest first), file, type (default: age)",
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
        version=f"staletrack {version}",
    )

    args = parser.parse_args(argv)

    scan_path = args.path.resolve()
    if not scan_path.exists():
        print(f"Error: path does not exist: {scan_path}", file=sys.stderr)
        sys.exit(1)

    result = scan(
        root=scan_path,
        py_only=args.py_only,
        m_only=args.m_only,
        todos_only=args.todos,
        commented_code_only=args.commented_code,
    )

    _print_output(result, scan_path, args)
