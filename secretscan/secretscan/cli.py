"""Command-line interface for secretscan."""

from __future__ import annotations

import argparse
import json
import os
import sys

from secretscan import version
from secretscan.scanner import ScanResult, scan

# ── ANSI colour helpers ──────────────────────────────────────────────────

_COLORS = {
    "reset":    "\033[0m",
    "bold":     "\033[1m",
    "dim":      "\033[2m",
    "red":      "\033[91m",
    "yellow":   "\033[93m",
    "cyan":     "\033[96m",
    "magenta":  "\033[95m",
    "green":    "\033[92m",
    "white":    "\033[97m",
}

SEVERITY_STYLE = {
    "CRITICAL": ("red", "bold"),
    "HIGH":     ("yellow", "bold"),
    "MEDIUM":   ("magenta",),
    "LOW":      ("cyan",),
}


def _c(text: str, *styles: str, use_color: bool = True) -> str:
    if not use_color:
        return text
    prefix = "".join(_COLORS.get(s, "") for s in styles)
    return f"{prefix}{text}{_COLORS['reset']}"


# ── Formatters ────────────────────────────────────────────────────────────

def _format_text(result: ScanResult, path: str, use_color: bool = True) -> str:
    lines: list[str] = []
    lines.append("")
    lines.append(f"  {_c('secretscan', 'bold', 'cyan', use_color=use_color)}"
                 f" - scanning {_c(path, 'dim', use_color=use_color)}")
    lines.append("")

    if not result.findings:
        lines.append(f"  {_c('No secrets detected.', 'green', use_color=use_color)}")
        lines.append("")
    else:
        for finding in result.findings:
            sev = finding.severity
            styles = SEVERITY_STYLE.get(sev, ())
            sev_label = _c(sev, *styles, use_color=use_color)

            # Build a relative display path when possible.
            try:
                display_path = os.path.relpath(finding.filepath, os.path.abspath(path))
            except ValueError:
                display_path = finding.filepath

            lines.append(f"  {sev_label}  {_c(display_path, 'white', 'bold', use_color=use_color)}"
                         f":{finding.line_number}")
            lines.append(f"    {finding.label}: {finding.truncated_match()}")
            lines.append("")

    # Summary
    lines.append(f"  {_c('Summary:', 'bold', use_color=use_color)}")
    lines.append(f"    Files scanned:  {result.files_scanned:>4}")
    lines.append(f"    Critical:       {_c(str(result.count_by_severity('CRITICAL')).rjust(4), 'red', use_color=use_color)}")
    lines.append(f"    High:           {_c(str(result.count_by_severity('HIGH')).rjust(4), 'yellow', use_color=use_color)}")
    lines.append(f"    Medium:         {_c(str(result.count_by_severity('MEDIUM')).rjust(4), 'magenta', use_color=use_color)}")
    lines.append(f"    Low:            {_c(str(result.count_by_severity('LOW')).rjust(4), 'cyan', use_color=use_color)}")
    lines.append("")
    return "\n".join(lines)


def _format_json(result: ScanResult) -> str:
    payload = {
        "files_scanned": result.files_scanned,
        "findings": [
            {
                "file": f.filepath,
                "line": f.line_number,
                "severity": f.severity,
                "label": f.label,
                "match": f.truncated_match(),
            }
            for f in result.findings
        ],
        "summary": {
            "critical": result.count_by_severity("CRITICAL"),
            "high": result.count_by_severity("HIGH"),
            "medium": result.count_by_severity("MEDIUM"),
            "low": result.count_by_severity("LOW"),
        },
    }
    return json.dumps(payload, indent=2)


# ── CLI entry point ───────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="secretscan",
        description="Scan source code for hardcoded secrets and credentials.",
    )
    parser.add_argument("path", help="File or directory to scan")
    parser.add_argument(
        "--severity",
        choices=["low", "medium", "high", "critical"],
        default="low",
        help="Minimum severity level to report (default: low)",
    )
    parser.add_argument("--json", dest="json_output", action="store_true",
                        help="Output results as JSON")
    parser.add_argument("--no-color", dest="no_color", action="store_true",
                        help="Disable colored output")
    parser.add_argument("--version", action="version", version=f"%(prog)s {version}")

    args = parser.parse_args(argv)

    if not os.path.exists(args.path):
        print(f"Error: path '{args.path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    result = scan(args.path, min_severity=args.severity)

    if args.json_output:
        print(_format_json(result))
    else:
        use_color = not args.no_color and sys.stdout.isatty()
        print(_format_text(result, args.path, use_color=use_color))

    # Exit with non-zero if any findings at HIGH or above.
    if any(f.severity in ("CRITICAL", "HIGH") for f in result.findings):
        sys.exit(1)
