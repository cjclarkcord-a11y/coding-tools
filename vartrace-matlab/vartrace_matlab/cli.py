"""CLI interface for vartrace-matlab."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .analyzer import Analyzer
from .graph import FlowGraph, NodeKind
from .parser import collect_file
from .resolver import MatlabResolver


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
def blue(t: str) -> str: return _c(t, "34")


def build_graph(path: str) -> tuple[FlowGraph, str]:
    """Build the flow graph for a .m file or directory."""
    path = os.path.normpath(os.path.abspath(path))
    graph = FlowGraph()

    if os.path.isfile(path):
        root = os.path.dirname(path)
        collect_file(graph, path)
        return graph, root

    root = path
    resolver = MatlabResolver(root)
    files = resolver.discover_files()

    if not files:
        print(f"No .m files found in {path}", file=sys.stderr)
        sys.exit(1)

    all_functions: dict[str, dict] = {}
    all_calls: list[dict] = []

    for f in files:
        try:
            collector = collect_file(graph, f)
            all_functions.update(collector.functions)
            all_calls.extend(collector.external_calls)
        except Exception as e:
            print(f"  {yellow('skip')} {f} ({e})", file=sys.stderr)

    # Cross-file resolution
    resolver.build_function_map(files, all_functions)
    resolver.stitch_calls(graph, all_calls)

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

            if i > 0:
                edges = analyzer.graph.incoming(node.id)
                for edge in edges:
                    if edge.src == chain[i - 1].id:
                        if edge.transform:
                            label = (f"{node.name} "
                                     f"[{magenta(edge.transform)}:"
                                     f"{magenta(edge.transform_category or '')}] "
                                     f"{dim(f'({loc})')}")
                        if edge.sink:
                            label = (f"{node.name} "
                                     f"[{red('SINK')}:"
                                     f"{red(edge.sink_category or '')}] "
                                     f"{dim(f'({loc})')}")
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


def print_unused_inputs(analyzer: Analyzer, root: str) -> None:
    unused = analyzer.unused_inputs()
    if not unused:
        print(f"  {green('No unused input params found')}")
        return

    print(f"\n  {bold('Unused input parameters')} {dim(f'({len(unused)} found)')}:")
    for node in unused:
        loc = node.loc.short(root)
        scope = dim(f"in {node.scope}")
        print(f"    {yellow(node.name)}  {dim(f'({loc})')} {scope}")
    print()


def print_unused_outputs(analyzer: Analyzer, root: str) -> None:
    unused = analyzer.unused_outputs()
    if not unused:
        print(f"  {green('No unused output params found')}")
        return

    print(f"\n  {bold('Unused output parameters')} {dim(f'({len(unused)} found)')}:")
    for node in unused:
        loc = node.loc.short(root)
        scope = dim(f"in {node.scope}")
        print(f"    {yellow(node.name)}  {dim(f'({loc})')} {scope}")
    print()


def print_globals(analyzer: Analyzer, root: str) -> None:
    gp = analyzer.globals_and_persistents()
    if not gp:
        print(f"  {green('No global/persistent variables found')}")
        return

    print(f"\n  {bold('Global & persistent variables')} {dim(f'({len(gp)} found)')}:")
    for node in gp:
        loc = node.loc.short(root)
        kind = "global" if node.kind == NodeKind.GLOBAL_DECL else "persistent"
        scope = dim(f"in {node.scope}")
        print(f"    {blue(node.name)}  {dim(kind)}  {dim(f'({loc})')} {scope}")
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
              f"--[{magenta(edge.transform or '?')}:"
              f"{magenta(edge.transform_category or '')}]-->  "
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
        if not src:
            continue
        src_loc = src.loc.short(root)
        print(f"    {src.name} {dim(f'({src_loc})')}  "
              f"--> [{red(edge.sink or '?')}:{red(edge.sink_category or '')}]")
    print()


def print_summary(analyzer: Analyzer) -> None:
    s = analyzer.summary()
    print(f"\n  {bold('Summary')}:")
    print(f"    Files analyzed:      {s['files']}")
    print(f"    Total bindings:      {s['total_nodes']}")
    print(f"    Total edges:         {s['total_edges']}")
    print(f"    Dead variables:      {yellow(str(s['dead_variables'])) if s['dead_variables'] else green('0')}")
    print(f"    Unused inputs:       {yellow(str(s['unused_inputs'])) if s['unused_inputs'] else green('0')}")
    print(f"    Unused outputs:      {yellow(str(s['unused_outputs'])) if s['unused_outputs'] else green('0')}")
    print(f"    Global/persistent:   {blue(str(s['globals_persistents'])) if s['globals_persistents'] else '0'}")
    print(f"    Transformations:     {s['transforms']}")
    print(f"    Sinks:               {s['sinks']}")
    print()


def output_json(analyzer: Analyzer, root: str, var: str | None) -> None:
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
    result["unused_inputs"] = [
        {"name": n.name, "file": n.loc.short(root), "line": n.loc.line,
         "scope": n.scope}
        for n in analyzer.unused_inputs()
    ]
    result["unused_outputs"] = [
        {"name": n.name, "file": n.loc.short(root), "line": n.loc.line,
         "scope": n.scope}
        for n in analyzer.unused_outputs()
    ]
    result["globals_persistents"] = [
        {"name": n.name, "file": n.loc.short(root), "line": n.loc.line,
         "scope": n.scope, "kind": n.kind.name}
        for n in analyzer.globals_and_persistents()
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
        prog="vartrace-matlab",
        description="Trace variable data flow through MATLAB source code.",
    )
    parser.add_argument("path", help="MATLAB .m file or directory to analyze")
    parser.add_argument("--var", "-v", help="Trace a specific variable name")
    parser.add_argument("--dead", action="store_true",
                        help="Report dead variables (assigned but never read)")
    parser.add_argument("--unused-inputs", action="store_true",
                        help="Report unused function input parameters")
    parser.add_argument("--unused-outputs", action="store_true",
                        help="Report unused function output parameters")
    parser.add_argument("--globals", action="store_true",
                        help="Report global and persistent variable declarations")
    parser.add_argument("--transforms", action="store_true",
                        help="Report data transformations")
    parser.add_argument("--sinks", action="store_true",
                        help="Report where data ends up (disp, plot, save, etc.)")
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

    any_report = (args.dead or args.unused_inputs or args.unused_outputs
                  or args.globals or args.transforms or args.sinks)
    if not any_report and not args.var:
        args.all = True

    if args.var and not any_report and not args.all:
        show_var_default = True
    else:
        show_var_default = False

    print(f"\n  {bold('vartrace-matlab')} - analyzing {dim(args.path)}...\n")

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
            if args.all or args.unused_inputs:
                print_unused_inputs(analyzer, root)
            if args.all or args.unused_outputs:
                print_unused_outputs(analyzer, root)
            if args.all or args.globals:
                print_globals(analyzer, root)
    else:
        if args.all or args.dead:
            print_dead_variables(analyzer, root)
        if args.all or args.unused_inputs:
            print_unused_inputs(analyzer, root)
        if args.all or args.unused_outputs:
            print_unused_outputs(analyzer, root)
        if args.all or args.globals:
            print_globals(analyzer, root)
        if args.all or args.transforms:
            print_transforms(analyzer, root)
        if args.all or args.sinks:
            print_sinks(analyzer, root)
