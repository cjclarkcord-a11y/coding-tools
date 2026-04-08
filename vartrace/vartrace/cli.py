"""CLI interface for vartrace."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .analyzer import Analyzer
from .collector import collect_file
from .graph import FlowGraph
from .resolver import ImportResolver


# ANSI color helpers
def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


_COLOR = _supports_color()


def _c(text: str, code: str) -> str:
    if not _COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def dim(t: str) -> str: return _c(t, "2")
def bold(t: str) -> str: return _c(t, "1")
def red(t: str) -> str: return _c(t, "31")
def yellow(t: str) -> str: return _c(t, "33")
def green(t: str) -> str: return _c(t, "32")
def cyan(t: str) -> str: return _c(t, "36")
def magenta(t: str) -> str: return _c(t, "35")


def build_graph(path: str) -> tuple[FlowGraph, str]:
    """Build the flow graph for a file or directory."""
    path = os.path.normpath(os.path.abspath(path))
    graph = FlowGraph()

    if os.path.isfile(path):
        root = os.path.dirname(path)
        collect_file(graph, path)
        return graph, root

    # Directory
    root = path
    resolver = ImportResolver(root)
    files = resolver.discover_files()

    if not files:
        print(f"No Python files found in {path}", file=sys.stderr)
        sys.exit(1)

    all_imports = []
    for f in files:
        try:
            collector = collect_file(graph, f)
            all_imports.extend(collector.unresolved_imports)
        except SyntaxError as e:
            print(f"  {yellow('skip')} {f} (syntax error: {e})", file=sys.stderr)
        except Exception as e:
            print(f"  {yellow('skip')} {f} ({e})", file=sys.stderr)

    # Cross-file resolution
    resolver.build_module_map(files)
    resolver.stitch_imports(graph, all_imports)

    return graph, root


def print_flow_chains(analyzer: Analyzer, var: str, root: str,
                      file: str | None = None) -> None:
    chains = analyzer.flow_chains(var, file)
    if not chains:
        print(f"  No flow chains found for {bold(var)}")
        return

    print(f"\n  {bold('Flow chains for')} {cyan(var)}:")
    seen = set()
    for chain in chains:
        key = tuple(n.id for n in chain)
        if key in seen:
            continue
        seen.add(key)

        parts = []
        for i, node in enumerate(chain):
            loc = node.loc.short(root)
            label = f"{node.name} {dim(f'({loc})')}"

            # Check if there's a transform/sink on the edge TO this node
            if i > 0:
                edges = analyzer.graph.incoming(node.id)
                for edge in edges:
                    if edge.src == chain[i - 1].id:
                        if edge.transform:
                            label = f"{node.name} [{magenta(edge.transform)}:{magenta(edge.transform_category or '')}] {dim(f'({loc})')}"
                        if edge.sink:
                            label = f"{node.name} [{red('SINK')}:{red(edge.sink_category or '')}] {dim(f'({loc})')}"
                        break
            parts.append(label)

        print(f"    {'  ->  '.join(parts)}")
    print()


def print_dead_variables(analyzer: Analyzer, root: str) -> None:
    dead = analyzer.dead_variables()
    if not dead:
        print(f"  {green('No dead variables found')}")
        return

    print(f"\n  {bold('Dead variables')} {dim(f'({len(dead)} found)')}:")
    for node in dead:
        loc = node.loc.short(root)
        kind = node.kind.name.lower()
        print(f"    {yellow(node.name)}  {dim(kind)}  {dim(f'({loc})')}")
    print()


def print_unused_imports(analyzer: Analyzer, root: str) -> None:
    unused = analyzer.unused_imports()
    if not unused:
        print(f"  {green('No unused imports found')}")
        return

    print(f"\n  {bold('Unused imports')} {dim(f'({len(unused)} found)')}:")
    for node in unused:
        loc = node.loc.short(root)
        ext = dim("[external]") if node.is_external else ""
        print(f"    {yellow(node.name)}  {dim(f'({loc})')} {ext}")
    print()


def print_unused_params(analyzer: Analyzer, root: str) -> None:
    unused = analyzer.unused_params()
    if not unused:
        print(f"  {green('No unused params found')}")
        return

    print(f"\n  {bold('Unused parameters')} {dim(f'({len(unused)} found)')}:")
    for node in unused:
        loc = node.loc.short(root)
        scope = dim(f"in {node.scope}")
        print(f"    {yellow(node.name)}  {dim(f'({loc})')} {scope}")
    print()


def print_transforms(analyzer: Analyzer, root: str,
                     var: str | None = None) -> None:
    transforms = analyzer.transformations(var)
    if not transforms:
        label = f" for {var}" if var else ""
        print(f"  {green(f'No transformations found{label}')}")
        return

    print(f"\n  {bold('Transformations')} {dim(f'({len(transforms)} found)')}:")
    for edge in transforms:
        src = analyzer.graph.nodes.get(edge.src)
        dst = analyzer.graph.nodes.get(edge.dst)
        if not src or not dst:
            continue
        src_loc = src.loc.short(root)
        dst_loc = dst.loc.short(root)
        print(f"    {src.name} {dim(f'({src_loc})')}  "
              f"--[{magenta(edge.transform or '?')}:{magenta(edge.transform_category or '')}]-->  "
              f"{dst.name} {dim(f'({dst_loc})')}")
    print()


def print_sinks(analyzer: Analyzer, root: str,
                var: str | None = None) -> None:
    sinks = analyzer.sinks(var)
    if not sinks:
        label = f" for {var}" if var else ""
        print(f"  {green(f'No sinks found{label}')}")
        return

    print(f"\n  {bold('Sinks')} {dim(f'({len(sinks)} found)')}:")
    for edge in sinks:
        src = analyzer.graph.nodes.get(edge.src)
        dst = analyzer.graph.nodes.get(edge.dst)
        if not src or not dst:
            continue
        src_loc = src.loc.short(root)
        print(f"    {src.name} {dim(f'({src_loc})')}  "
              f"--> [{red(edge.sink or '?')}:{red(edge.sink_category or '')}]")
    print()


def print_summary(analyzer: Analyzer) -> None:
    s = analyzer.summary()
    print(f"\n  {bold('Summary')}:")
    print(f"    Files analyzed:    {s['files']}")
    print(f"    Total bindings:    {s['total_nodes']}")
    print(f"    Total edges:       {s['total_edges']}")
    print(f"    Dead variables:    {yellow(str(s['dead_variables'])) if s['dead_variables'] else green('0')}")
    print(f"    Unused imports:    {yellow(str(s['unused_imports'])) if s['unused_imports'] else green('0')}")
    print(f"    Unused params:     {yellow(str(s['unused_params'])) if s['unused_params'] else green('0')}")
    print(f"    Transformations:   {s['transforms']}")
    print(f"    Sinks:             {s['sinks']}")
    print()


def output_json(analyzer: Analyzer, root: str, var: str | None) -> None:
    """Output all results as JSON."""
    result: dict = {"summary": analyzer.summary()}

    if var:
        chains = analyzer.flow_chains(var)
        result["flow_chains"] = [
            [{"name": n.name, "file": n.loc.short(root), "line": n.loc.line,
              "kind": n.kind.name}
             for n in chain]
            for chain in chains
        ]

    result["dead_variables"] = [
        {"name": n.name, "file": n.loc.short(root), "line": n.loc.line,
         "scope": n.scope}
        for n in analyzer.dead_variables()
    ]
    result["unused_imports"] = [
        {"name": n.name, "file": n.loc.short(root), "line": n.loc.line,
         "external": n.is_external}
        for n in analyzer.unused_imports()
    ]
    result["unused_params"] = [
        {"name": n.name, "file": n.loc.short(root), "line": n.loc.line,
         "scope": n.scope}
        for n in analyzer.unused_params()
    ]
    result["transformations"] = [
        {"from": analyzer.graph.nodes[e.src].name if e.src in analyzer.graph.nodes else "?",
         "to": analyzer.graph.nodes[e.dst].name if e.dst in analyzer.graph.nodes else "?",
         "transform": e.transform, "category": e.transform_category}
        for e in analyzer.transformations(var)
    ]
    result["sinks"] = [
        {"variable": analyzer.graph.nodes[e.src].name if e.src in analyzer.graph.nodes else "?",
         "sink": e.sink, "category": e.sink_category}
        for e in analyzer.sinks(var)
    ]

    print(json.dumps(result, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vartrace",
        description="Trace variable data flow through Python source code.",
    )
    parser.add_argument("path", help="Python file or directory to analyze")
    parser.add_argument("--var", "-v", help="Trace a specific variable name")
    parser.add_argument("--dead", action="store_true",
                        help="Report dead variables (assigned but never read)")
    parser.add_argument("--unused-imports", action="store_true",
                        help="Report unused imports")
    parser.add_argument("--unused-params", action="store_true",
                        help="Report unused function parameters")
    parser.add_argument("--transforms", action="store_true",
                        help="Report data transformations (hashing, encoding, etc.)")
    parser.add_argument("--sinks", action="store_true",
                        help="Report where data ends up (print, file, DB, etc.)")
    parser.add_argument("--all", "-a", action="store_true",
                        help="Run all reports")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable colored output")

    args = parser.parse_args()

    if args.no_color:
        global _COLOR
        _COLOR = False

    # Default: if no specific report requested, show all
    any_report = args.dead or args.unused_imports or args.unused_params \
        or args.transforms or args.sinks
    if not any_report and not args.var:
        args.all = True

    # If --var but no reports, show chain + transforms + sinks
    if args.var and not any_report and not args.all:
        show_var_default = True
    else:
        show_var_default = False

    print(f"\n  {bold('vartrace')} - analyzing {dim(args.path)}...\n")

    graph, root = build_graph(args.path)
    analyzer = Analyzer(graph)

    if args.json:
        output_json(analyzer, root, args.var)
        return

    print_summary(analyzer)

    if args.var:
        print_flow_chains(analyzer, args.var, root)
        if show_var_default or args.all or args.transforms:
            print_transforms(analyzer, root, args.var)
        if show_var_default or args.all or args.sinks:
            print_sinks(analyzer, root, args.var)
        if not show_var_default:
            if args.all or args.dead:
                print_dead_variables(analyzer, root)
            if args.all or args.unused_imports:
                print_unused_imports(analyzer, root)
            if args.all or args.unused_params:
                print_unused_params(analyzer, root)
    else:
        if args.all or args.dead:
            print_dead_variables(analyzer, root)
        if args.all or args.unused_imports:
            print_unused_imports(analyzer, root)
        if args.all or args.unused_params:
            print_unused_params(analyzer, root)
        if args.all or args.transforms:
            print_transforms(analyzer, root)
        if args.all or args.sinks:
            print_sinks(analyzer, root)
