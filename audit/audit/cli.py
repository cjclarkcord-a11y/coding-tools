#!/usr/bin/env python3
"""
Code Audit Runner - runs all analysis tools and produces a condensed summary.

Usage:
    audit <path>                    # full audit, summary to stdout
    audit <path> -o report.txt      # save full report to file
    audit <path> --json             # JSON output
    audit <path> --quick            # skip slow tools (copypaste, staletrack)
    audit <path> --py-only          # Python only
    audit <path> --m-only           # MATLAB only
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# ── Tool registry ────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "complexity",
        "cmd": ["complexity", "{path}", "--no-color"],
        "category": "Complexity",
        "slow": False,
        "lang": "both",
    },
    {
        "name": "vartrace",
        "cmd": ["vartrace", "{path}", "--no-color"],
        "category": "Variable Flow",
        "slow": False,
        "lang": "python",
    },
    {
        "name": "vartrace-matlab",
        "cmd": ["vartrace-matlab", "{path}", "--no-color"],
        "category": "Variable Flow (MATLAB)",
        "slow": False,
        "lang": "matlab",
    },
    {
        "name": "erroraudit",
        "cmd": ["erroraudit", "{path}", "--no-color"],
        "category": "Error Handling",
        "slow": False,
        "lang": "both",
    },
    {
        "name": "deadfiles",
        "cmd": ["deadfiles", "{path}", "--no-color"],
        "category": "Dead Files",
        "slow": False,
        "lang": "both",
    },
    {
        "name": "secretscan",
        "cmd": ["secretscan", "{path}", "--no-color"],
        "category": "Secrets",
        "slow": False,
        "lang": "both",
    },
    {
        "name": "depgraph",
        "cmd": ["depgraph", "{path}", "--no-color"],
        "category": "Dependencies",
        "slow": False,
        "lang": "both",
    },
    {
        "name": "copypaste",
        "cmd": ["copypaste", "{path}", "--no-color"],
        "category": "Duplicate Code",
        "slow": True,
        "lang": "both",
    },
    {
        "name": "staletrack",
        "cmd": ["staletrack", "{path}", "--no-color"],
        "category": "Stale Comments",
        "slow": True,
        "lang": "both",
    },
    {
        "name": "vulture",
        "cmd": ["vulture", "{path}"],
        "category": "Dead Code (vulture)",
        "slow": False,
        "lang": "python",
    },
    {
        "name": "bandit",
        "cmd": ["bandit", "-r", "{path}", "-q", "--severity-level", "medium"],
        "category": "Security (bandit)",
        "slow": False,
        "lang": "python",
    },
    {
        "name": "radon-cc",
        "cmd": ["radon", "cc", "{path}", "-s", "-n", "C", "--no-assert"],
        "category": "Complexity (radon CC >= C)",
        "slow": False,
        "lang": "python",
    },
    {
        "name": "radon-mi",
        "cmd": ["radon", "mi", "{path}", "-s", "-n", "B"],
        "category": "Maintainability (radon MI < B)",
        "slow": False,
        "lang": "python",
    },
    {
        "name": "ruff",
        "cmd": ["ruff", "check", "{path}", "--no-fix", "--output-format", "concise"],
        "category": "Lint (ruff)",
        "slow": False,
        "lang": "python",
    },
    {
        "name": "mh_lint",
        "cmd": ["mh_lint", "{path}"],
        "category": "Lint (MISS_HIT)",
        "slow": False,
        "lang": "matlab",
    },
    {
        "name": "mh_metric",
        "cmd": ["mh_metric", "{path}"],
        "category": "Metrics (MISS_HIT)",
        "slow": False,
        "lang": "matlab",
    },
]


# ── Runner ───────────────────────────────────────────────────────────────

def run_tool(tool: dict, path: str, timeout: int = 120) -> dict:
    """Run a single tool and capture output."""
    cmd = [c.replace("{path}", path) for c in tool["cmd"]]
    start = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        elapsed = time.time() - start
        output = result.stdout + result.stderr
        return {
            "name": tool["name"],
            "category": tool["category"],
            "exit_code": result.returncode,
            "output": output.strip(),
            "elapsed": round(elapsed, 1),
            "error": None,
        }
    except FileNotFoundError:
        return {
            "name": tool["name"],
            "category": tool["category"],
            "exit_code": -1,
            "output": "",
            "elapsed": 0,
            "error": "not installed",
        }
    except subprocess.TimeoutExpired:
        return {
            "name": tool["name"],
            "category": tool["category"],
            "exit_code": -1,
            "output": "",
            "elapsed": timeout,
            "error": f"timeout ({timeout}s)",
        }
    except Exception as e:
        return {
            "name": tool["name"],
            "category": tool["category"],
            "exit_code": -1,
            "output": "",
            "elapsed": 0,
            "error": str(e),
        }


def extract_summary_line(output: str) -> str:
    """Extract the most informative summary from tool output."""
    lines = output.splitlines()

    # Look for Summary section
    in_summary = False
    summary_lines = []
    for line in lines:
        stripped = line.strip()
        if "Summary" in stripped and not stripped.startswith("#"):
            in_summary = True
            continue
        if in_summary:
            if stripped and not stripped.startswith("=") and not stripped.startswith("-"):
                summary_lines.append(stripped)
            if len(summary_lines) >= 10:
                break
            if not stripped and summary_lines:
                break

    if summary_lines:
        return " | ".join(summary_lines)

    # Fallback: count lines as rough indicator
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return "clean"
    if len(non_empty) <= 3:
        return " ".join(l.strip() for l in non_empty)
    return f"{len(non_empty)} output lines"


def extract_issue_count(output: str) -> int:
    """Try to extract the number of issues found."""
    import re
    # Look for common patterns: "X found", "X issues", "X errors", "X warnings"
    for pattern in [
        r"(\d+)\s+found",
        r"Issues?\s+found:?\s*(\d+)",
        r"(\d+)\s+issues?",
        r"(\d+)\s+errors?",
        r"(\d+)\s+warnings?",
        r"Dead variables:\s*(\d+)",
        r"Unused imports:\s*(\d+)",
        r"Unused params?:\s*(\d+)",
        r"Dead files:\s*(\d+)",
        r"Duplicate groups:\s*(\d+)",
        r"Circular deps:\s*(\d+)",
        r"Critical:\s*(\d+)",
        r"High:\s*(\d+)",
    ]:
        matches = re.findall(pattern, output, re.IGNORECASE)
        for m in matches:
            val = int(m)
            if val > 0:
                return val
    return 0


def extract_top_issues(output: str, max_lines: int = 10) -> list[str]:
    """Extract the most important findings, capped at max_lines."""
    lines = output.splitlines()
    issues = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip headers, separators, and tool banners
        if any(skip in stripped for skip in [
            "scanning", "analyzing", "Summary", "====", "----",
            "Files scanned", "Files analyzed", "Total bindings",
            "Total edges", "Total dup",
        ]):
            continue
        # Capture severity-tagged lines
        if any(tag in stripped for tag in [
            "HIGH", "MEDIUM", "CRITICAL", "LOW", "CYCLE",
            "VERY HIGH", "ANCIENT", "STALE",
        ]):
            issues.append(stripped)
        # Capture specific finding lines (indented with file:line references)
        elif ":" in stripped and any(c.isdigit() for c in stripped):
            # Looks like a file:line reference
            if len(stripped) < 200:  # skip huge lines
                issues.append(stripped)

    return issues[:max_lines]


# ── Report generation ────────────────────────────────────────────────────

def generate_report(results: list[dict], path: str, elapsed_total: float) -> str:
    """Generate the condensed summary report."""
    lines = []
    lines.append("=" * 70)
    lines.append(f"  CODE AUDIT REPORT")
    lines.append(f"  Target: {path}")
    lines.append(f"  Time: {elapsed_total:.1f}s total")
    lines.append("=" * 70)
    lines.append("")

    # ── Scorecard ──
    lines.append("  SCORECARD")
    lines.append("  " + "-" * 50)

    total_issues = 0
    tool_summaries = []

    for r in results:
        if r["error"]:
            status = f"SKIP ({r['error']})"
            count = 0
        elif r["exit_code"] == 0 and not r["output"]:
            status = "CLEAN"
            count = 0
        else:
            count = extract_issue_count(r["output"])
            if count == 0 and r["exit_code"] == 0:
                status = "CLEAN"
            elif count == 0 and r["output"]:
                # Has output but no counted issues - check if it's findings
                out_lines = [l for l in r["output"].splitlines() if l.strip()]
                if len(out_lines) > 5:
                    status = f"~{len(out_lines)} lines"
                    count = len(out_lines)
                else:
                    status = "CLEAN"
            else:
                status = f"{count} issues"
            total_issues += count

        tool_summaries.append((r["category"], status, count, r["elapsed"]))

    for category, status, count, elapsed in tool_summaries:
        marker = "!!" if count > 10 else "! " if count > 0 else "  "
        lines.append(f"  {marker} {category:<30} {status:<20} ({elapsed}s)")

    lines.append("  " + "-" * 50)
    lines.append(f"  TOTAL ISSUES: {total_issues}")
    lines.append("")

    # ── Top findings per tool ──
    lines.append("  KEY FINDINGS")
    lines.append("  " + "-" * 50)

    any_findings = False
    for r in results:
        if r["error"] or not r["output"]:
            continue
        issues = extract_top_issues(r["output"], max_lines=5)
        if issues:
            any_findings = True
            lines.append(f"\n  [{r['category']}]")
            for issue in issues:
                lines.append(f"    {issue}")

    if not any_findings:
        lines.append("  No significant findings.")

    lines.append("")

    # ── Per-tool summaries ──
    lines.append("  TOOL SUMMARIES")
    lines.append("  " + "-" * 50)

    for r in results:
        if r["error"]:
            continue
        summary = extract_summary_line(r["output"])
        if summary and summary != "clean":
            lines.append(f"  [{r['name']}] {summary}")

    lines.append("")
    lines.append("=" * 70)
    lines.append("  END OF REPORT")
    lines.append("=" * 70)

    return "\n".join(lines)


def generate_json_report(results: list[dict], path: str,
                          elapsed_total: float) -> str:
    """Generate JSON report."""
    report = {
        "target": path,
        "elapsed_total": round(elapsed_total, 1),
        "tools": [],
    }
    total_issues = 0
    for r in results:
        count = extract_issue_count(r["output"]) if not r["error"] else 0
        total_issues += count
        top = extract_top_issues(r["output"], 10) if not r["error"] else []
        report["tools"].append({
            "name": r["name"],
            "category": r["category"],
            "issues": count,
            "elapsed": r["elapsed"],
            "error": r["error"],
            "top_findings": top,
            "summary": extract_summary_line(r["output"]) if not r["error"] else None,
        })
    report["total_issues"] = total_issues
    return json.dumps(report, indent=2)


# ── Full report (saved to file, not shown) ───────────────────────────────

def generate_full_report(results: list[dict], path: str) -> str:
    """Full verbose report with all tool output - for saving to file."""
    lines = []
    lines.append("=" * 70)
    lines.append(f"  FULL AUDIT REPORT - {path}")
    lines.append("=" * 70)

    for r in results:
        lines.append("")
        lines.append(f"{'=' * 70}")
        lines.append(f"  TOOL: {r['name']} ({r['category']})")
        lines.append(f"  Exit code: {r['exit_code']} | Time: {r['elapsed']}s")
        if r["error"]:
            lines.append(f"  Error: {r['error']}")
        lines.append(f"{'=' * 70}")
        if r["output"]:
            lines.append(r["output"])
        else:
            lines.append("  (no output)")

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="audit",
        description="Run all code analysis tools and produce a condensed summary.",
    )
    parser.add_argument("path", help="File or directory to audit")
    parser.add_argument("-o", "--output", help="Save full report to file")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--quick", action="store_true",
                        help="Skip slow tools (copypaste, staletrack)")
    parser.add_argument("--py-only", action="store_true", help="Python only")
    parser.add_argument("--m-only", action="store_true", help="MATLAB only")
    parser.add_argument("--timeout", type=int, default=120,
                        help="Per-tool timeout in seconds (default: 120)")

    args = parser.parse_args()
    path = os.path.abspath(args.path)

    if not os.path.exists(path):
        print(f"Error: {path} does not exist", file=sys.stderr)
        sys.exit(1)

    # Filter tools based on flags
    tools = []
    has_py = False
    has_m = False
    if os.path.isfile(path):
        has_py = path.endswith(".py")
        has_m = path.endswith(".m")
    else:
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in {
                ".git", "__pycache__", ".venv", "node_modules"}]
            for f in files:
                if f.endswith(".py"):
                    has_py = True
                if f.endswith(".m"):
                    has_m = True
            if has_py and has_m:
                break

    if args.py_only:
        has_m = False
    if args.m_only:
        has_py = False

    for tool in TOOLS:
        if args.quick and tool["slow"]:
            continue
        if tool["lang"] == "python" and not has_py:
            continue
        if tool["lang"] == "matlab" and not has_m:
            continue
        tools.append(tool)

    # Run tools
    print(f"\n  audit - running {len(tools)} tools on {path}...\n",
          file=sys.stderr)

    results = []
    start_total = time.time()

    for i, tool in enumerate(tools, 1):
        print(f"  [{i}/{len(tools)}] {tool['name']}...", end="",
              file=sys.stderr, flush=True)
        result = run_tool(tool, path, args.timeout)
        status = "done" if not result["error"] else result["error"]
        print(f" {status} ({result['elapsed']}s)", file=sys.stderr)
        results.append(result)

    elapsed_total = time.time() - start_total

    # Generate reports
    if args.json:
        print(generate_json_report(results, path, elapsed_total))
    else:
        print(generate_report(results, path, elapsed_total))

    # Save full report if requested
    if args.output:
        full = generate_full_report(results, path)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(full)
        print(f"\n  Full report saved to: {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
