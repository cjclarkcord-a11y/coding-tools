"""Command-line interface for depgraph."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from depgraph import version
from depgraph.graph import DependencyGraph, _short_path
from depgraph.python_deps import extract_python_deps
from depgraph.matlab_deps import extract_matlab_deps, clear_cache
from depgraph.cross_lang import extract_cross_lang_deps


# ------------------------------------------------------------------
# Color helpers
# ------------------------------------------------------------------

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


_NO_COLOR = _Colors()
for attr in dir(_NO_COLOR):
    if not attr.startswith("_"):
        setattr(_NO_COLOR, attr, "")


def _get_colors(use_color: bool) -> _Colors:
    if use_color:
        return _Colors()
    nc = _Colors()
    for attr in ("RESET", "BOLD", "DIM", "RED", "GREEN", "YELLOW", "BLUE", "MAGENTA", "CYAN", "WHITE"):
        setattr(nc, attr, "")
    return nc


# ------------------------------------------------------------------
# File scanning
# ------------------------------------------------------------------

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".tox", ".mypy_cache", ".pytest_cache", "venv", "env"}


def _scan_files(root: Path, py_only: bool = False, m_only: bool = False) -> list[Path]:
    """Recursively find .py and .m files under root."""
    files: list[Path] = []
    _walk(root, files, py_only, m_only)
    return files


def _walk(directory: Path, files: list[Path], py_only: bool, m_only: bool) -> None:
    try:
        entries = sorted(directory.iterdir())
    except PermissionError:
        return
    for entry in entries:
        if entry.name in SKIP_DIRS:
            continue
        if entry.is_dir():
            _walk(entry, files, py_only, m_only)
        elif entry.is_file():
            if m_only and entry.suffix == ".m":
                files.append(entry)
            elif py_only and entry.suffix == ".py":
                files.append(entry)
            elif not py_only and not m_only and entry.suffix in (".py", ".m"):
                files.append(entry)


# ------------------------------------------------------------------
# Graph construction
# ------------------------------------------------------------------

def build_graph(root: Path, py_only: bool = False, m_only: bool = False) -> tuple[DependencyGraph, dict]:
    """Scan files and build the dependency graph. Returns (graph, stats)."""
    clear_cache()
    files = _scan_files(root, py_only=py_only, m_only=m_only)
    graph = DependencyGraph()
    stats = {
        "files_scanned": len(files),
        "dependencies": 0,
        "cross_language": 0,
        "py_files": 0,
        "m_files": 0,
    }

    for f in files:
        graph.add_node(str(f))
        if f.suffix == ".py":
            stats["py_files"] += 1
        elif f.suffix == ".m":
            stats["m_files"] += 1

    for f in files:
        deps: list[dict] = []
        if f.suffix == ".py" and not m_only:
            deps.extend(extract_python_deps(f, root))
        elif f.suffix == ".m" and not py_only:
            deps.extend(extract_matlab_deps(f, root))

        # Cross-language deps for MATLAB files
        if f.suffix == ".m" and not py_only and not m_only:
            cross_deps = extract_cross_lang_deps(f, root)
            for d in cross_deps:
                graph.add_edge(
                    d["source"], d["target"],
                    type=d["type"], raw=d["raw"], cross_language=True,
                )
                stats["cross_language"] += 1
                stats["dependencies"] += 1

        for d in deps:
            graph.add_edge(
                d["source"], d["target"],
                type=d["type"], raw=d["raw"],
                cross_language=d.get("cross_language", False),
            )
            stats["dependencies"] += 1

    return graph, stats


# ------------------------------------------------------------------
# Output formatting
# ------------------------------------------------------------------

def _print_summary(graph: DependencyGraph, stats: dict, c: _Colors, project_root: str) -> None:
    fan_in_ranking = graph.fan_in_ranking()
    fan_out_ranking = graph.fan_out_ranking()
    max_fi = fan_in_ranking[0] if fan_in_ranking else ("?", 0)
    max_fo = fan_out_ranking[0] if fan_out_ranking else ("?", 0)
    cycles = graph.find_cycles()

    print(f"\n  {c.BOLD}Summary:{c.RESET}")
    print(f"    Files scanned:       {c.CYAN}{stats['files_scanned']}{c.RESET}")
    print(f"    Dependencies:        {c.CYAN}{stats['dependencies']}{c.RESET}")
    print(f"    Cross-language:      {c.CYAN}{stats['cross_language']}{c.RESET}")
    n_cycles = len(cycles)
    cycle_color = c.RED if n_cycles > 0 else c.GREEN
    print(f"    Circular deps:       {cycle_color}{n_cycles} cycle{'s' if n_cycles != 1 else ''}{c.RESET}")
    print(f"    Max fan-in:          {c.YELLOW}{max_fi[1]}{c.RESET} ({_short_path(max_fi[0], project_root)})")
    print(f"    Max fan-out:         {c.YELLOW}{max_fo[1]}{c.RESET} ({_short_path(max_fo[0], project_root)})")


def _print_cycles(graph: DependencyGraph, c: _Colors, project_root: str) -> None:
    cycles = graph.find_cycles()
    if not cycles:
        print(f"\n  {c.GREEN}No circular dependencies found.{c.RESET}")
        return
    print(f"\n  {c.BOLD}{c.RED}Circular dependencies ({len(cycles)} cycle{'s' if len(cycles) != 1 else ''}):{c.RESET}")
    for i, cycle in enumerate(cycles, 1):
        parts = [_short_path(n, project_root) for n in cycle]
        chain = f" {c.RED}->{c.RESET} ".join(parts)
        print(f"    {c.BOLD}CYCLE {i}:{c.RESET} {chain}")


def _print_fan_in(graph: DependencyGraph, threshold: int, c: _Colors, project_root: str) -> None:
    ranking = graph.fan_in_ranking()
    filtered = [(n, fi) for n, fi in ranking if fi >= threshold]
    if not filtered:
        print(f"\n  {c.DIM}No files with fan-in >= {threshold}.{c.RESET}")
        return
    print(f"\n  {c.BOLD}High fan-in (most depended on):{c.RESET}")
    for node, fi in filtered:
        label = _short_path(node, project_root)
        print(f"    {c.YELLOW}{label:<30}{c.RESET} {fi} file{'s' if fi != 1 else ''} depend on this")


def _print_fan_out(graph: DependencyGraph, threshold: int, c: _Colors, project_root: str) -> None:
    ranking = graph.fan_out_ranking()
    filtered = [(n, fo) for n, fo in ranking if fo >= threshold]
    if not filtered:
        print(f"\n  {c.DIM}No files with fan-out >= {threshold}.{c.RESET}")
        return
    print(f"\n  {c.BOLD}High fan-out (most dependencies):{c.RESET}")
    for node, fo in filtered:
        label = _short_path(node, project_root)
        print(f"    {c.YELLOW}{label:<30}{c.RESET} {fo} dependenc{'ies' if fo != 1 else 'y'}")


def _print_clusters(graph: DependencyGraph, c: _Colors, project_root: str) -> None:
    sccs = graph.strongly_connected_components()
    # Only show SCCs with more than 1 node (tightly coupled)
    clusters = [scc for scc in sccs if len(scc) > 1]
    if not clusters:
        print(f"\n  {c.GREEN}No tightly coupled clusters found.{c.RESET}")
        return
    clusters.sort(key=len, reverse=True)
    print(f"\n  {c.BOLD}Tightly coupled clusters ({len(clusters)}):{c.RESET}")
    for i, cluster in enumerate(clusters, 1):
        names = [_short_path(n, project_root) for n in sorted(cluster)]
        print(f"    {c.MAGENTA}Cluster {i}{c.RESET} ({len(cluster)} files):")
        for name in names:
            print(f"      - {name}")


def _print_cross_lang(graph: DependencyGraph, c: _Colors, project_root: str) -> None:
    edges = graph.cross_language_edges()
    if not edges:
        print(f"\n  {c.DIM}No cross-language dependencies found.{c.RESET}")
        return
    print(f"\n  {c.BOLD}Cross-language dependencies:{c.RESET}")
    for src, tgt, attrs in edges:
        src_label = _short_path(src, project_root)
        raw = attrs.get("raw", tgt)
        print(f"    {c.CYAN}{src_label}{c.RESET} -> {c.MAGENTA}{raw}{c.RESET}")


def _print_file_info(graph: DependencyGraph, file_name: str, c: _Colors, project_root: str) -> None:
    # Find the matching node
    matches = [n for n in graph.nodes if n.endswith(file_name) or Path(n).name == file_name]
    if not matches:
        print(f"\n  {c.RED}File '{file_name}' not found in the dependency graph.{c.RESET}")
        return
    for match in matches:
        info = graph.file_subgraph(match)
        label = _short_path(match, project_root)
        print(f"\n  {c.BOLD}Dependencies for {label}:{c.RESET}")
        print(f"\n    {c.BOLD}Depends on ({len(info['depends_on'])}):{c.RESET}")
        for tgt, attrs in info["depends_on"]:
            tgt_label = _short_path(tgt, project_root)
            dep_type = attrs.get("type", "?")
            print(f"      -> {c.CYAN}{tgt_label}{c.RESET}  ({dep_type})")
        print(f"\n    {c.BOLD}Depended on by ({len(info['depended_on_by'])}):{c.RESET}")
        for src, attrs in info["depended_on_by"]:
            src_label = _short_path(src, project_root)
            dep_type = attrs.get("type", "?")
            print(f"      <- {c.YELLOW}{src_label}{c.RESET}  ({dep_type})")


def _print_tree(graph: DependencyGraph, c: _Colors, project_root: str) -> None:
    # Find roots (nodes with no incoming edges, or highest fan-out)
    ranking = graph.fan_out_ranking()
    if not ranking:
        print(f"\n  {c.DIM}No files to show.{c.RESET}")
        return
    # Use the top fan-out node as root, or nodes with zero fan-in
    fan_in_map = {n: graph.fan_in(n) for n in graph.nodes}
    roots = [n for n, fi in fan_in_map.items() if fi == 0 and graph.fan_out(n) > 0]
    if not roots:
        # Fall back to highest fan-out
        roots = [ranking[0][0]]
    roots.sort()

    print(f"\n  {c.BOLD}Dependency tree:{c.RESET}")
    for root in roots:
        tree = graph.dependency_tree(root, project_root)
        for line in tree.splitlines():
            print(f"    {line}")
        print()


def _print_json(graph: DependencyGraph, stats: dict, project_root: str) -> None:
    cycles = graph.find_cycles()
    sccs = [scc for scc in graph.strongly_connected_components() if len(scc) > 1]
    output = {
        "stats": stats,
        "graph": graph.to_dict(project_root),
        "cycles": [
            [_short_path(n, project_root) for n in cycle]
            for cycle in cycles
        ],
        "clusters": [
            [_short_path(n, project_root) for n in scc]
            for scc in sccs
        ],
        "cross_language": [
            {
                "source": _short_path(s, project_root),
                "target": _short_path(t, project_root),
                "raw": a.get("raw", ""),
            }
            for s, t, a in graph.cross_language_edges()
        ],
    }
    print(json.dumps(output, indent=2))


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    # Ensure stdout can handle Unicode box-drawing characters on Windows
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        import io
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True,
        )

    parser = argparse.ArgumentParser(
        prog="depgraph",
        description="Map file dependencies, detect circular imports, find coupling hotspots.",
    )
    parser.add_argument(
        "path",
        type=str,
        help="Project root directory to scan",
    )
    parser.add_argument("--cycles", action="store_true", help="Only show circular dependencies")
    parser.add_argument("--fan-in", type=int, default=None, metavar="N",
                        help="Show files with fan-in >= N")
    parser.add_argument("--fan-out", type=int, default=None, metavar="N",
                        help="Show files with fan-out >= N")
    parser.add_argument("--clusters", action="store_true", help="Show strongly connected components")
    parser.add_argument("--file", type=str, default=None, metavar="FILE",
                        help="Show all deps to/from a specific file")
    parser.add_argument("--cross-lang", action="store_true", help="Only show cross-language dependencies")
    parser.add_argument("--tree", action="store_true", help="Show dependency tree (ASCII art)")
    parser.add_argument("--py-only", action="store_true", help="Python files only")
    parser.add_argument("--m-only", action="store_true", help="MATLAB files only")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")
    parser.add_argument("--version", action="version", version=f"depgraph {version}")

    args = parser.parse_args(argv)

    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"Error: '{args.path}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    use_color = not args.no_color and not args.json and sys.stdout.isatty()
    c = _get_colors(use_color)

    project_root = str(root) + ("/" if not str(root).endswith("/") else "")

    if not args.json:
        print(f"\n  {c.BOLD}depgraph{c.RESET} - scanning {c.CYAN}{args.path}{c.RESET}/...")

    graph, stats = build_graph(root, py_only=args.py_only, m_only=args.m_only)

    if args.json:
        _print_json(graph, stats, project_root)
        return

    # Determine what to show
    specific_view = any([args.cycles, args.fan_in is not None, args.fan_out is not None,
                         args.clusters, args.file, args.cross_lang, args.tree])

    if not specific_view:
        # Full analysis
        _print_summary(graph, stats, c, project_root)
        _print_cycles(graph, c, project_root)
        fi_threshold = max(1, stats["files_scanned"] // 10) if stats["files_scanned"] > 10 else 1
        _print_fan_in(graph, fi_threshold, c, project_root)
        fo_threshold = max(1, stats["files_scanned"] // 10) if stats["files_scanned"] > 10 else 1
        _print_fan_out(graph, fo_threshold, c, project_root)
        _print_clusters(graph, c, project_root)
        if stats["cross_language"] > 0:
            _print_cross_lang(graph, c, project_root)
        _print_tree(graph, c, project_root)
    else:
        if args.cycles:
            _print_cycles(graph, c, project_root)
        if args.fan_in is not None:
            _print_fan_in(graph, args.fan_in, c, project_root)
        if args.fan_out is not None:
            _print_fan_out(graph, args.fan_out, c, project_root)
        if args.clusters:
            _print_clusters(graph, c, project_root)
        if args.file:
            _print_file_info(graph, args.file, c, project_root)
        if args.cross_lang:
            _print_cross_lang(graph, c, project_root)
        if args.tree:
            _print_tree(graph, c, project_root)

    print()
