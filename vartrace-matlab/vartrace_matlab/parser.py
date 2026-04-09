"""MATLAB source code parser.

Regex-based line-by-line parser that understands MATLAB syntax:
- function signatures (input/output params)
- assignments (=)
- for/while loops
- function calls
- global/persistent declarations
- load/save statements
- struct field access
- multi-line continuation (...)

No MATLAB AST is available in Python, so this is heuristic-based.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .graph import (
    EdgeKind, FlowEdge, FlowGraph, FlowNode, Location, NodeKind,
)
from .sinks import SINKS, TRANSFORMS

# Regex patterns for MATLAB syntax
RE_FUNCTION = re.compile(
    r"^\s*function\s+"
    r"(?:"
    r"(?:\[([^\]]*)\]|(\w+))"   # output args: [a, b] or single
    r"\s*=\s*)?"
    r"(\w+)"                     # function name
    r"\s*(?:\(([^)]*)\))?"       # input args (optional)
    r"\s*$"
)
RE_ASSIGN = re.compile(
    r"^\s*"
    r"(?:\[([^\]]*)\]|(\w[\w.]*(?:\{[^}]*\}|\([^)]*\))*))"  # LHS: [a,b] or var or var.field or var{i}
    r"\s*=\s*"
    r"(.+)"                      # RHS
    r"\s*;?\s*$"
)
RE_FOR = re.compile(
    r"^\s*for\s+(\w+)\s*=\s*(.+?)\s*$"
)
RE_GLOBAL = re.compile(
    r"^\s*global\s+(.+?)\s*;?\s*$"
)
RE_PERSISTENT = re.compile(
    r"^\s*persistent\s+(.+?)\s*;?\s*$"
)
RE_LOAD = re.compile(
    r"^\s*load\s*\(?['\"]?([^'\")\s;]+)['\"]?\)?\s*(.*?)\s*;?\s*$"
)
# Match function calls as statements: func(args) or func args
RE_CALL_STMT = re.compile(
    r"^\s*(\w+)\s*\(([^)]*)\)\s*;?\s*$"
)
# Match function call in expression: name(...)
RE_CALL_EXPR = re.compile(
    r"(\w+)\s*\(([^)]*)\)"
)
# Match identifiers (variable names) in expressions
RE_IDENTIFIER = re.compile(
    r"\b([a-zA-Z_]\w*)\b"
)
# Line continuation
RE_CONTINUATION = re.compile(r"\.\.\.\s*$")
# Comment
RE_COMMENT = re.compile(r"%.*$")
# String literals - strip them to avoid false matches
RE_STRING_SQ = re.compile(r"'[^']*'")
RE_STRING_DQ = re.compile(r'"[^"]*"')
# End keywords
RE_END_BLOCK = re.compile(r"^\s*(end|endfunction)\s*;?\s*$")

# MATLAB built-in names to ignore as variable references
BUILTINS = {
    "true", "false", "pi", "inf", "Inf", "nan", "NaN", "eps",
    "i", "j",  # imaginary unit (ambiguous, but commonly built-in)
    "end", "if", "else", "elseif", "while", "for", "switch", "case",
    "otherwise", "try", "catch", "return", "break", "continue",
    "function", "classdef", "properties", "methods", "events",
    "enumeration", "arguments",
}


def _strip_strings_and_comments(line: str) -> str:
    """Remove string literals and comments to avoid false matches."""
    line = RE_COMMENT.sub("", line)
    line = RE_STRING_DQ.sub('""', line)
    line = RE_STRING_SQ.sub("''", line)
    return line


def _extract_identifiers(expr: str) -> list[str]:
    """Extract variable names from a MATLAB expression."""
    cleaned = _strip_strings_and_comments(expr)
    names = RE_IDENTIFIER.findall(cleaned)
    return [n for n in names if n not in BUILTINS and not n[0].isdigit()]


def _extract_call_info(expr: str) -> list[tuple[str, str | None, str | None]]:
    """Extract function calls and classify as transform/sink.
    Returns list of (func_name, transform_category, sink_category)."""
    cleaned = _strip_strings_and_comments(expr)
    results = []
    for match in RE_CALL_EXPR.finditer(cleaned):
        func_name = match.group(1)
        if func_name in BUILTINS:
            continue
        transform_cat = TRANSFORMS.get(func_name)
        sink_cat = SINKS.get(func_name)
        if transform_cat or sink_cat:
            results.append((func_name, transform_cat, sink_cat))
    return results


class MatlabCollector:
    """Parse a MATLAB .m file and populate a FlowGraph."""

    def __init__(self, graph: FlowGraph, file_path: str) -> None:
        self.graph = graph
        self.file = os.path.normpath(file_path)
        self.file_stem = Path(file_path).stem
        self._scope_stack: list[str] = [self.file_stem]
        # scope -> {var_name -> node_id}
        self._bindings: list[dict[str, str]] = [{}]
        self._counter = 0
        # Track function definitions for cross-file resolution
        self.functions: dict[str, dict] = {}  # func_name -> {inputs, outputs, file, line}
        # Track calls to external functions
        self.external_calls: list[dict] = []

    @property
    def scope(self) -> str:
        return ">".join(self._scope_stack)

    def _make_id(self, name: str, line: int) -> str:
        self._counter += 1
        return f"{self.file}:{line}:{name}#{self._counter}"

    def _loc(self, line: int) -> Location:
        return Location(self.file, line)

    def _push_scope(self, name: str) -> None:
        self._scope_stack.append(name)
        self._bindings.append({})

    def _pop_scope(self) -> None:
        if len(self._scope_stack) > 1:
            self._scope_stack.pop()
            self._bindings.pop()

    def _current_binding(self, name: str) -> str | None:
        for scope_bindings in reversed(self._bindings):
            if name in scope_bindings:
                return scope_bindings[name]
        return None

    def _set_binding(self, name: str, node_id: str) -> None:
        self._bindings[-1][name] = node_id

    def _add_node(self, name: str, line: int, kind: NodeKind) -> FlowNode:
        nid = self._make_id(name, line)
        node = FlowNode(id=nid, name=name, loc=self._loc(line),
                         kind=kind, scope=self.scope)
        self.graph.add_node(node)
        return node

    def _link_rhs_to_target(self, target_id: str, rhs_expr: str, line: int,
                             transform: str | None = None,
                             transform_cat: str | None = None,
                             sink: str | None = None,
                             sink_cat: str | None = None) -> None:
        """Create edges from RHS variable references to the target node."""
        rhs_names = _extract_identifiers(rhs_expr)
        for name in rhs_names:
            src_id = self._current_binding(name)
            if src_id and src_id != target_id:
                self.graph.add_edge(FlowEdge(
                    src=src_id, dst=target_id,
                    kind=EdgeKind.ASSIGN,
                    transform=transform,
                    transform_category=transform_cat,
                    sink=sink,
                    sink_category=sink_cat,
                ))

    def parse(self, source: str) -> None:
        """Parse MATLAB source and build the flow graph."""
        lines = source.splitlines()
        i = 0
        func_depth = 0  # track nested function/end blocks

        while i < len(lines):
            raw_line = lines[i]
            line_num = i + 1

            # Handle line continuation (...)
            full_line = raw_line
            while RE_CONTINUATION.search(full_line):
                full_line = RE_CONTINUATION.sub("", full_line)
                i += 1
                if i < len(lines):
                    full_line += " " + lines[i].strip()
                else:
                    break

            stripped = _strip_strings_and_comments(full_line).strip()
            if not stripped:
                i += 1
                continue

            # function definition
            m = RE_FUNCTION.match(stripped)
            if m:
                out_multi, out_single, func_name, in_args = m.groups()
                outputs = []
                if out_multi:
                    outputs = [o.strip() for o in out_multi.split(",") if o.strip()]
                elif out_single:
                    outputs = [out_single]
                inputs = []
                if in_args:
                    inputs = [a.strip() for a in in_args.split(",") if a.strip()]

                # Track for cross-file resolution
                self.functions[func_name] = {
                    "inputs": inputs,
                    "outputs": outputs,
                    "file": self.file,
                    "line": line_num,
                }

                # If this isn't the first function (i.e., a local/nested function),
                # pop the previous scope
                if func_depth > 0:
                    self._pop_scope()
                func_depth += 1

                self._push_scope(func_name)

                # Create input param nodes
                for param in inputs:
                    node = self._add_node(param, line_num, NodeKind.INPUT_PARAM)
                    self._set_binding(param, node.id)

                # Create output param nodes (they'll be linked when assigned)
                for out in outputs:
                    node = self._add_node(out, line_num, NodeKind.OUTPUT_PARAM)
                    self._set_binding(out, node.id)

                i += 1
                continue

            # end block
            if RE_END_BLOCK.match(stripped):
                # Only pop scope for function ends, not if/for/while ends
                # Heuristic: if we're inside a function and this could be its end
                # This is imperfect without full parsing, but reasonable
                i += 1
                continue

            # global declaration
            m = RE_GLOBAL.match(stripped)
            if m:
                names = m.group(1).split()
                for name in names:
                    name = name.strip()
                    if name:
                        node = self._add_node(name, line_num, NodeKind.GLOBAL_DECL)
                        self._set_binding(name, node.id)
                i += 1
                continue

            # persistent declaration
            m = RE_PERSISTENT.match(stripped)
            if m:
                names = m.group(1).split()
                for name in names:
                    name = name.strip()
                    if name:
                        node = self._add_node(name, line_num, NodeKind.PERSISTENT_DECL)
                        self._set_binding(name, node.id)
                i += 1
                continue

            # load statement
            m = RE_LOAD.match(stripped)
            if m:
                _load_file = m.group(1)
                var_list = m.group(2).strip()
                if var_list:
                    names = var_list.split()
                    for name in names:
                        name = name.strip().strip("'\"")
                        if name and RE_IDENTIFIER.match(name):
                            node = self._add_node(name, line_num, NodeKind.LOAD_TARGET)
                            self._set_binding(name, node.id)
                i += 1
                continue

            # for loop
            m = RE_FOR.match(stripped)
            if m:
                var_name = m.group(1)
                iter_expr = m.group(2)
                node = self._add_node(var_name, line_num, NodeKind.FOR_TARGET)
                self._set_binding(var_name, node.id)
                self._link_rhs_to_target(node.id, iter_expr, line_num)
                i += 1
                continue

            # assignment
            m = RE_ASSIGN.match(stripped)
            if m:
                multi_lhs, single_lhs, rhs = m.groups()
                rhs = rhs.rstrip(";").strip()

                # Get transform/sink info from RHS calls
                calls = _extract_call_info(rhs)
                transform = None
                transform_cat = None
                sink = None
                sink_cat = None
                if calls:
                    # Use the outermost call's classification
                    for fname, tcat, scat in calls:
                        if tcat:
                            transform = fname
                            transform_cat = tcat
                        if scat:
                            sink = fname
                            sink_cat = scat

                if multi_lhs:
                    # [a, b, c] = func(...)
                    targets = [t.strip() for t in multi_lhs.split(",") if t.strip()]
                    # Filter out ~ (ignored outputs)
                    for tname in targets:
                        if tname == "~":
                            continue
                        # Strip struct field access for binding name
                        base_name = tname.split(".")[0].split("{")[0].split("(")[0]
                        node = self._add_node(base_name, line_num, NodeKind.ASSIGN)
                        self._set_binding(base_name, node.id)
                        self._link_rhs_to_target(node.id, rhs, line_num,
                                                  transform, transform_cat,
                                                  sink, sink_cat)
                elif single_lhs:
                    tname = single_lhs.strip()
                    base_name = tname.split(".")[0].split("{")[0].split("(")[0]
                    node = self._add_node(base_name, line_num, NodeKind.ASSIGN)
                    self._set_binding(base_name, node.id)
                    self._link_rhs_to_target(node.id, rhs, line_num,
                                              transform, transform_cat,
                                              sink, sink_cat)

                i += 1
                continue

            # Standalone function call (statement): func(args);
            m = RE_CALL_STMT.match(stripped)
            if m:
                func_name = m.group(1)
                args_str = m.group(2)

                sink_cat = SINKS.get(func_name)
                if sink_cat:
                    sink_node = self._add_node(
                        f"<sink:{func_name}>", line_num,
                        NodeKind.FUNCTION_CALL_RESULT)
                    arg_names = _extract_identifiers(args_str)
                    for aname in arg_names:
                        src_id = self._current_binding(aname)
                        if src_id:
                            self.graph.add_edge(FlowEdge(
                                src=src_id, dst=sink_node.id,
                                kind=EdgeKind.CALL_ARG,
                                sink=func_name,
                                sink_category=sink_cat,
                            ))
                else:
                    # Track as external call for cross-file resolution
                    self.external_calls.append({
                        "func_name": func_name,
                        "args": _extract_identifiers(args_str),
                        "line": line_num,
                        "file": self.file,
                    })

                i += 1
                continue

            # If none of the above matched, scan for sink calls in the line
            # (handles cases like: if func(x) > 0, etc.)
            for call_match in RE_CALL_EXPR.finditer(stripped):
                func_name = call_match.group(1)
                args_str = call_match.group(2)
                sink_cat = SINKS.get(func_name)
                if sink_cat:
                    sink_node = self._add_node(
                        f"<sink:{func_name}>", line_num,
                        NodeKind.FUNCTION_CALL_RESULT)
                    arg_names = _extract_identifiers(args_str)
                    for aname in arg_names:
                        src_id = self._current_binding(aname)
                        if src_id:
                            self.graph.add_edge(FlowEdge(
                                src=src_id, dst=sink_node.id,
                                kind=EdgeKind.CALL_ARG,
                                sink=func_name,
                                sink_category=sink_cat,
                            ))

            i += 1


def collect_file(graph: FlowGraph, file_path: str) -> MatlabCollector:
    """Parse a MATLAB .m file and collect its flow graph data."""
    source = Path(file_path).read_text(encoding="utf-8", errors="replace")
    collector = MatlabCollector(graph, file_path)
    collector.parse(source)
    return collector
