"""CLI entry point for the complexity tool."""

import argparse
import os
import sys

from complexity.python_metrics import scan_python_files
from complexity.matlab_metrics import scan_matlab_files
from complexity.reporter import (
    unify_metrics,
    sort_metrics,
    filter_metrics,
    format_json,
    format_report,
)


def _count_files(path: str, py: bool = True, matlab: bool = True) -> int:
    """Count the number of files that would be scanned."""
    count = 0
    if os.path.isfile(path):
        if py and path.endswith(".py"):
            count += 1
        if matlab and path.endswith(".m"):
            count += 1
    elif os.path.isdir(path):
        for root, _dirs, files in os.walk(path):
            for fname in files:
                if py and fname.endswith(".py"):
                    count += 1
                if matlab and fname.endswith(".m"):
                    count += 1
    return count


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        prog="complexity",
        description="Find complexity hotspots in Python and MATLAB code.",
    )
    parser.add_argument(
        "path",
        help="File or directory to scan",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of top hotspots to show (default: 20)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="show_all",
        help="Show all functions",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=None,
        help="Only show functions with complexity >= threshold",
    )
    parser.add_argument(
        "--sort",
        choices=["score", "complexity", "depth", "length"],
        default="score",
        help="Sort key (default: score)",
    )
    parser.add_argument(
        "--py-only",
        action="store_true",
        help="Scan Python files only",
    )
    parser.add_argument(
        "--m-only",
        action="store_true",
        help="Scan MATLAB files only",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output as JSON",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output",
    )

    args = parser.parse_args(argv)

    path = os.path.abspath(args.path)
    if not os.path.exists(path):
        print(f"Error: path '{args.path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    scan_py = not args.m_only
    scan_m = not args.py_only

    # Collect metrics
    py_metrics = scan_python_files(path) if scan_py else []
    m_metrics = scan_matlab_files(path) if scan_m else []

    file_count = _count_files(path, py=scan_py, matlab=scan_m)
    all_metrics = unify_metrics(py_metrics, m_metrics)

    # Sort and filter
    sorted_all = sort_metrics(all_metrics, args.sort)
    displayed = filter_metrics(
        sorted_all,
        threshold=args.threshold,
        top=args.top,
        show_all=args.show_all,
    )

    # Determine color usage
    use_color = not args.no_color and sys.stdout.isatty()

    if args.json_output:
        print(format_json(displayed, file_count))
    else:
        report = format_report(
            metrics=displayed,
            all_metrics=all_metrics,
            file_count=file_count,
            base_path=path if os.path.isdir(path) else os.path.dirname(path),
            use_color=use_color,
            sort_label=args.sort,
            top_n=args.top,
            show_all=args.show_all,
        )
        print(report)
