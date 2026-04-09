"""CLI entry point for erroraudit."""

import argparse
import json
import os
import sys
from dataclasses import asdict

from erroraudit import version
from erroraudit.python_audit import audit_python_file
from erroraudit.python_audit import Issue as PyIssue
from erroraudit.matlab_audit import audit_matlab_file
from erroraudit.matlab_audit import Issue as MatlabIssue


# Unified Issue type (both modules use the same shape)
SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
SEVERITY_THRESHOLD = {"high": 0, "medium": 1, "low": 2}


class Colors:
    """ANSI color codes."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"


class NoColors:
    """No-op colors for --no-color mode."""

    RESET = ""
    BOLD = ""
    DIM = ""
    RED = ""
    YELLOW = ""
    BLUE = ""
    CYAN = ""
    WHITE = ""
    GRAY = ""


def _severity_color(severity: str, c: type) -> str:
    if severity == "HIGH":
        return c.RED
    elif severity == "MEDIUM":
        return c.YELLOW
    return c.BLUE


def _collect_files(path: str, py_only: bool, m_only: bool) -> tuple[list[str], list[str]]:
    """Collect .py and .m files from the given path."""
    py_files: list[str] = []
    m_files: list[str] = []

    if os.path.isfile(path):
        if path.endswith(".py") and not m_only:
            py_files.append(path)
        elif path.endswith(".m") and not py_only:
            m_files.append(path)
        return py_files, m_files

    for root, dirs, files in os.walk(path):
        # Skip hidden directories and common non-source dirs
        dirs[:] = [
            d for d in dirs
            if not d.startswith(".")
            and d not in ("__pycache__", "node_modules", ".git", "venv", ".venv", "env")
        ]
        for fname in files:
            fpath = os.path.join(root, fname)
            if fname.endswith(".py") and not m_only:
                py_files.append(fpath)
            elif fname.endswith(".m") and not py_only:
                m_files.append(fpath)

    return py_files, m_files


def _normalize_issue(issue) -> dict:
    """Convert an issue dataclass to a dict."""
    return {
        "file": issue.file,
        "line": issue.line,
        "severity": issue.severity,
        "title": issue.title,
        "description": issue.description,
        "code_lines": issue.code_lines,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="erroraudit",
        description="Audit error handling patterns in Python and MATLAB code",
    )
    parser.add_argument("path", help="File or directory to scan")
    parser.add_argument(
        "--severity",
        choices=["high", "medium", "low"],
        default="low",
        help="Minimum severity to report (default: low)",
    )
    parser.add_argument("--py-only", action="store_true", help="Scan Python files only")
    parser.add_argument("--m-only", action="store_true", help="Scan MATLAB files only")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Output as JSON")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")
    parser.add_argument("--version", action="version", version=f"erroraudit {version}")

    args = parser.parse_args(argv)

    if args.py_only and args.m_only:
        parser.error("Cannot use --py-only and --m-only together")

    path = os.path.abspath(args.path)
    if not os.path.exists(path):
        print(f"Error: path '{args.path}' does not exist", file=sys.stderr)
        sys.exit(1)

    c = NoColors if (args.no_color or args.json_output) else Colors

    # Collect files
    py_files, m_files = _collect_files(path, args.py_only, args.m_only)
    total_files = len(py_files) + len(m_files)

    if not args.json_output:
        display_path = args.path.rstrip("/\\")
        print(f"\n  {c.BOLD}erroraudit{c.RESET} {c.DIM}- scanning {display_path}/{c.RESET}\n")

    # Audit all files
    all_issues: list[dict] = []

    for fpath in py_files:
        issues = audit_python_file(fpath)
        for issue in issues:
            all_issues.append(_normalize_issue(issue))

    for fpath in m_files:
        issues = audit_matlab_file(fpath)
        for issue in issues:
            all_issues.append(_normalize_issue(issue))

    # Filter by severity
    threshold = SEVERITY_THRESHOLD[args.severity]
    all_issues = [i for i in all_issues if SEVERITY_ORDER[i["severity"]] <= threshold]

    # Sort: HIGH first, then MEDIUM, then LOW; within same severity by file then line
    all_issues.sort(key=lambda i: (SEVERITY_ORDER[i["severity"]], i["file"], i["line"]))

    # Count by severity
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for issue in all_issues:
        counts[issue["severity"]] += 1

    # JSON output
    if args.json_output:
        output = {
            "files_scanned": total_files,
            "issues_found": len(all_issues),
            "high": counts["HIGH"],
            "medium": counts["MEDIUM"],
            "low": counts["LOW"],
            "issues": all_issues,
        }
        print(json.dumps(output, indent=2))
        return

    # Summary
    print(f"  {c.BOLD}Summary:{c.RESET}")
    print(f"    Files scanned:  {c.WHITE}{total_files:>4}{c.RESET}")
    print(f"    Issues found:   {c.WHITE}{len(all_issues):>4}{c.RESET}")
    print(f"    {c.RED}High:{c.RESET}           {c.WHITE}{counts['HIGH']:>4}{c.RESET}")
    print(f"    {c.YELLOW}Medium:{c.RESET}         {c.WHITE}{counts['MEDIUM']:>4}{c.RESET}")
    print(f"    {c.BLUE}Low:{c.RESET}            {c.WHITE}{counts['LOW']:>4}{c.RESET}")
    print()

    if not all_issues:
        print(f"  {c.BOLD}No issues found.{c.RESET}\n")
        return

    # Print issues
    for issue in all_issues:
        sev = issue["severity"]
        sev_color = _severity_color(sev, c)
        # Make file path relative to the scan path for readability
        try:
            rel = os.path.relpath(issue["file"], path)
        except ValueError:
            rel = issue["file"]

        print(f"  {sev_color}{c.BOLD}{sev}{c.RESET}  {c.CYAN}{rel}{c.RESET}:{c.WHITE}{issue['line']}{c.RESET}")
        print(f"    {issue['title']} - {issue['description']}")
        for code_line in issue["code_lines"]:
            print(f"    {c.DIM}|{c.RESET}  {code_line}")
        print()
