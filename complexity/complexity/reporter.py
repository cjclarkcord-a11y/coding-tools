"""Ranking and reporting for complexity metrics."""

import json
import os
from dataclasses import dataclass, asdict


@dataclass
class UnifiedMetrics:
    name: str
    file: str
    line: int
    complexity: int
    max_depth: int
    length: int
    score: float

    @property
    def risk(self) -> str:
        if self.complexity <= 5:
            return "LOW"
        elif self.complexity <= 10:
            return "MODERATE"
        elif self.complexity <= 20:
            return "HIGH"
        else:
            return "VERY HIGH"


def unify_metrics(py_metrics, matlab_metrics) -> list[UnifiedMetrics]:
    """Convert Python and MATLAB metrics into a unified list."""
    results: list[UnifiedMetrics] = []
    for m in py_metrics:
        results.append(UnifiedMetrics(
            name=m.name, file=m.file, line=m.line,
            complexity=m.complexity, max_depth=m.max_depth,
            length=m.length, score=m.score,
        ))
    for m in matlab_metrics:
        results.append(UnifiedMetrics(
            name=m.name, file=m.file, line=m.line,
            complexity=m.complexity, max_depth=m.max_depth,
            length=m.length, score=m.score,
        ))
    return results


def sort_metrics(metrics: list[UnifiedMetrics], sort_by: str = "score") -> list[UnifiedMetrics]:
    """Sort metrics by the given key (descending)."""
    key_map = {
        "score": lambda m: m.score,
        "complexity": lambda m: m.complexity,
        "depth": lambda m: m.max_depth,
        "length": lambda m: m.length,
    }
    key_fn = key_map.get(sort_by, key_map["score"])
    return sorted(metrics, key=key_fn, reverse=True)


def filter_metrics(
    metrics: list[UnifiedMetrics],
    threshold: int | None = None,
    top: int | None = None,
    show_all: bool = False,
) -> list[UnifiedMetrics]:
    """Apply threshold and top-N filters."""
    if threshold is not None:
        metrics = [m for m in metrics if m.complexity >= threshold]
    if not show_all and top is not None:
        metrics = metrics[:top]
    return metrics


def _risk_color(risk: str, use_color: bool) -> tuple[str, str]:
    """Return (start_code, end_code) ANSI sequences for a risk level."""
    if not use_color:
        return "", ""
    codes = {
        "LOW": "\033[32m",          # green
        "MODERATE": "\033[33m",     # yellow
        "HIGH": "\033[31m",         # red
        "VERY HIGH": "\033[1;91m",  # bold bright red
    }
    return codes.get(risk, ""), "\033[0m"


def _relative_path(filepath: str, base_path: str) -> str:
    """Make filepath relative to base_path for cleaner display."""
    try:
        return os.path.relpath(filepath, base_path)
    except ValueError:
        return filepath


def format_json(metrics: list[UnifiedMetrics], file_count: int) -> str:
    """Format metrics as JSON."""
    data = {
        "summary": {
            "files_scanned": file_count,
            "functions_found": len(metrics),
            "average_complexity": round(
                sum(m.complexity for m in metrics) / len(metrics), 1
            ) if metrics else 0,
            "max_complexity": max(
                (m.complexity for m in metrics), default=0
            ),
        },
        "functions": [
            {
                "name": m.name,
                "file": m.file,
                "line": m.line,
                "complexity": m.complexity,
                "max_depth": m.max_depth,
                "length": m.length,
                "score": round(m.score, 1),
                "risk": m.risk,
            }
            for m in metrics
        ],
    }
    return json.dumps(data, indent=2)


def format_report(
    metrics: list[UnifiedMetrics],
    all_metrics: list[UnifiedMetrics],
    file_count: int,
    base_path: str,
    use_color: bool = True,
    sort_label: str = "score",
    top_n: int | None = 20,
    show_all: bool = False,
) -> str:
    """Format the full text report."""
    lines: list[str] = []

    # Header
    if use_color:
        lines.append(f"\n  \033[1mcomplexity\033[0m - scanning {base_path}")
    else:
        lines.append(f"\n  complexity - scanning {base_path}")

    # Summary
    total_funcs = len(all_metrics)
    avg_cc = round(
        sum(m.complexity for m in all_metrics) / total_funcs, 1
    ) if total_funcs else 0
    max_cc = max((m.complexity for m in all_metrics), default=0)

    lines.append("")
    lines.append("  Summary:")
    lines.append(f"    Files scanned:      {file_count}")
    lines.append(f"    Functions found:     {total_funcs}")
    lines.append(f"    Average complexity:  {avg_cc}")
    lines.append(f"    Max complexity:      {max_cc}")

    # Hotspots table
    if show_all:
        label = f"all {len(metrics)} by {sort_label}"
    elif top_n is not None:
        label = f"top {min(top_n, len(metrics))} by {sort_label}"
    else:
        label = f"by {sort_label}"

    lines.append("")
    lines.append(f"  Hotspots ({label}):")
    lines.append("")

    # Table header
    hdr = (
        f"  {'#':>3}  {'Score':>6}  {'CC':>4}  {'Depth':>5}  {'Lines':>5}  "
        f"{'Function':<33}  {'File'}"
    )
    lines.append(hdr)
    lines.append("  " + "-" * 75)

    for i, m in enumerate(metrics, 1):
        rel = _relative_path(m.file, base_path)
        file_loc = f"{rel}:{m.line}"
        start, end = _risk_color(m.risk, use_color)
        row = (
            f"  {i:>3}  {start}{m.score:>6.0f}{end}  "
            f"{start}{m.complexity:>4}{end}  "
            f"{m.max_depth:>5}  {m.length:>5}  "
            f"{m.name:<33}  {file_loc}"
        )
        lines.append(row)

    # Risk distribution
    risk_counts = {"LOW": 0, "MODERATE": 0, "HIGH": 0, "VERY HIGH": 0}
    for m in all_metrics:
        risk_counts[m.risk] += 1

    lines.append("")
    lines.append("  Risk distribution:")

    max_bar = 20
    max_count = max(risk_counts.values()) if any(risk_counts.values()) else 1

    risk_labels = [
        ("LOW", "1-5"),
        ("MODERATE", "6-10"),
        ("HIGH", "11-20"),
        ("VERY HIGH", "21+"),
    ]

    for risk, range_str in risk_labels:
        count = risk_counts[risk]
        pct = (count / total_funcs * 100) if total_funcs else 0
        bar_len = round(count / max_count * max_bar) if max_count > 0 else 0
        bar = "#" * bar_len

        start, end = _risk_color(risk, use_color)
        label = f"{risk} ({range_str})"
        lines.append(
            f"    {start}{label:<18}{end}  {count:>4}  {bar:<{max_bar}}  {pct:>3.0f}%"
        )

    lines.append("")
    return "\n".join(lines)
