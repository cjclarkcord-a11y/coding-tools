"""AST visitor that builds the flow graph for a single file."""

from __future__ import annotations

import ast
from pathlib import Path

from .graph import EdgeKind, FlowEdge, FlowGraph, FlowNode, Location, NodeKind
from .sinks import SINKS, TRANSFORMS


class FlowCollector(ast.NodeVisitor):
    """Walk a file's AST and populate a FlowGraph."""

    def __init__(self, graph: FlowGraph, file_path: str) -> None:
        self.graph = graph
        self.file = file_path
        self._scope_stack: list[str] = [Path(file_path).stem]
        # scope -> {var_name -> node_id of most recent binding}
        self._bindings: list[dict[str, str]] = [{}]
        self._node_counter = 0
        # Track unresolved imports for the resolver
        self.unresolved_imports: list[dict] = []

    @property
    def scope(self) -> str:
        return ".".join(self._scope_stack)

    def _make_id(self, name: str, line: int, col: int) -> str:
        self._node_counter += 1
        return f"{self.file}:{line}:{col}:{name}#{self._node_counter}"

    def _loc(self, node: ast.AST) -> Location:
        return Location(self.file, getattr(node, "lineno", 0),
                        getattr(node, "col_offset", 0))

    def _push_scope(self, name: str) -> None:
        self._scope_stack.append(name)
        self._bindings.append({})

    def _pop_scope(self) -> None:
        self._scope_stack.pop()
        self._bindings.pop()

    def _current_binding(self, name: str) -> str | None:
        """Look up the most recent binding for name, searching outward."""
        for scope_bindings in reversed(self._bindings):
            if name in scope_bindings:
                return scope_bindings[name]
        return None

    def _set_binding(self, name: str, node_id: str) -> None:
        self._bindings[-1][name] = node_id

    def _add_node(self, name: str, loc: Location, kind: NodeKind) -> FlowNode:
        nid = self._make_id(name, loc.line, loc.col)
        node = FlowNode(id=nid, name=name, loc=loc, kind=kind, scope=self.scope)
        self.graph.add_node(node)
        return node

    def _extract_rhs_names(self, node: ast.AST) -> list[str]:
        """Extract all Name references read in an expression."""
        names = []
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                names.append(child.id)
        return names

    def _get_call_info(self, call: ast.Call) -> tuple[str, str | None, str | None]:
        """Extract function name and check for transform/sink.
        Returns (func_name, transform_category, sink_category)."""
        func_name = ""
        full_path = ""
        if isinstance(call.func, ast.Attribute):
            func_name = call.func.attr
            # Build dotted path for context-aware matching
            parts = []
            node = call.func
            while isinstance(node, ast.Attribute):
                parts.append(node.attr)
                node = node.value
            if isinstance(node, ast.Name):
                parts.append(node.id)
            full_path = ".".join(reversed(parts))
        elif isinstance(call.func, ast.Name):
            func_name = call.func.id
            full_path = func_name

        transform_cat = TRANSFORMS.get(func_name)
        sink_cat = SINKS.get(func_name)

        # Disambiguate common false positives using full path context
        if sink_cat and func_name in ("get", "post", "put", "patch", "delete"):
            # Only count as HTTP sink if called on requests/session/client objects
            # NOT dict.get, os.environ.get, etc.
            http_indicators = ("requests", "session", "client", "http", "api", "aiohttp")
            if not any(ind in full_path.lower() for ind in http_indicators):
                sink_cat = None

        return func_name, transform_cat, sink_cat

    def _process_assignment(self, targets: list[str], value: ast.AST,
                            loc: Location, kind: NodeKind = NodeKind.ASSIGN) -> None:
        """Handle an assignment: create nodes, link from RHS bindings."""
        # Check if RHS is a call with transforms/sinks
        func_name = None
        transform_cat = None
        sink_cat = None
        if isinstance(value, ast.Call):
            func_name, transform_cat, sink_cat = self._get_call_info(value)

        rhs_names = self._extract_rhs_names(value)

        for target_name in targets:
            # Link old binding -> new (reassignment edge)
            old_binding = self._current_binding(target_name)

            new_node = self._add_node(target_name, loc, kind)
            self._set_binding(target_name, new_node.id)

            # Create edges from RHS names to this assignment
            for rhs_name in rhs_names:
                src_id = self._current_binding(rhs_name)
                if src_id and src_id != new_node.id:
                    edge = FlowEdge(
                        src=src_id, dst=new_node.id,
                        kind=EdgeKind.ASSIGN,
                        transform=func_name if transform_cat else None,
                        transform_category=transform_cat,
                        sink=func_name if sink_cat else None,
                        sink_category=sink_cat,
                    )
                    self.graph.add_edge(edge)

    def _extract_targets(self, node: ast.AST) -> list[str]:
        """Extract target variable names from assignment targets."""
        names = []
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Tuple) or isinstance(node, ast.List):
            for elt in node.elts:
                names.extend(self._extract_targets(elt))
        elif isinstance(node, ast.Starred):
            names.extend(self._extract_targets(node.value))
        # Skip Attribute, Subscript targets - we track simple names only
        return names

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            # Handle self.x = y as a "use" of y (attribute store)
            if isinstance(target, ast.Attribute):
                rhs_names = self._extract_rhs_names(node.value)
                for rhs_name in rhs_names:
                    src_id = self._current_binding(rhs_name)
                    if src_id:
                        # Create a synthetic node for the attribute target
                        attr_name = f"self.{target.attr}" if isinstance(target.value, ast.Name) \
                            else target.attr
                        attr_node = self._add_node(attr_name, self._loc(node), NodeKind.ASSIGN)
                        self._set_binding(attr_name, attr_node.id)
                        self.graph.add_edge(FlowEdge(
                            src=src_id, dst=attr_node.id,
                            kind=EdgeKind.ATTR_ACCESS,
                        ))
                continue

            names = self._extract_targets(target)
            self._process_assignment(names, node.value, self._loc(node))
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value and node.target:
            names = self._extract_targets(node.target)
            self._process_assignment(names, node.value, self._loc(node))
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        names = self._extract_targets(node.target)
        self._process_assignment(names, node.value, self._loc(node),
                                 kind=NodeKind.AUG_ASSIGN)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._push_scope(node.name)
        # Create PARAM nodes for arguments
        for arg in node.args.args:
            if arg.arg in ("self", "cls"):
                # Still create binding so references resolve, but skip reporting
                param_node = self._add_node(arg.arg, self._loc(arg), NodeKind.PARAM)
                self._set_binding(arg.arg, param_node.id)
                continue
            param_node = self._add_node(arg.arg, self._loc(arg), NodeKind.PARAM)
            self._set_binding(arg.arg, param_node.id)

        for arg in node.args.kwonlyargs:
            param_node = self._add_node(arg.arg, self._loc(arg), NodeKind.PARAM)
            self._set_binding(arg.arg, param_node.id)

        if node.args.vararg:
            arg = node.args.vararg
            param_node = self._add_node(f"*{arg.arg}", self._loc(arg), NodeKind.PARAM)
            self._set_binding(arg.arg, param_node.id)

        if node.args.kwarg:
            arg = node.args.kwarg
            param_node = self._add_node(f"**{arg.arg}", self._loc(arg), NodeKind.PARAM)
            self._set_binding(arg.arg, param_node.id)

        # Process defaults that reference existing bindings
        for default in node.args.defaults + node.args.kw_defaults:
            if default is not None:
                pass  # defaults are evaluated in enclosing scope, skip for now

        self.generic_visit(node)
        self._pop_scope()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._push_scope(node.name)
        self.generic_visit(node)
        self._pop_scope()

    def visit_Return(self, node: ast.Return) -> None:
        if node.value:
            rhs_names = self._extract_rhs_names(node.value)
            loc = self._loc(node)
            ret_node = self._add_node("<return>", loc, NodeKind.RETURN)

            func_name = None
            transform_cat = None
            sink_cat = None
            if isinstance(node.value, ast.Call):
                func_name, transform_cat, sink_cat = self._get_call_info(node.value)

            for rhs_name in rhs_names:
                src_id = self._current_binding(rhs_name)
                if src_id:
                    edge = FlowEdge(
                        src=src_id, dst=ret_node.id,
                        kind=EdgeKind.RETURN,
                        transform=func_name if transform_cat else None,
                        transform_category=transform_cat,
                    )
                    self.graph.add_edge(edge)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        names = self._extract_targets(node.target)
        loc = self._loc(node)
        iter_names = self._extract_rhs_names(node.iter)

        for name in names:
            new_node = self._add_node(name, loc, NodeKind.FOR_TARGET)
            self._set_binding(name, new_node.id)

            for iter_name in iter_names:
                src_id = self._current_binding(iter_name)
                if src_id:
                    self.graph.add_edge(FlowEdge(
                        src=src_id, dst=new_node.id,
                        kind=EdgeKind.ASSIGN,
                    ))

        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars:
                names = self._extract_targets(item.optional_vars)
                loc = self._loc(node)
                rhs_names = self._extract_rhs_names(item.context_expr)
                for name in names:
                    new_node = self._add_node(name, loc, NodeKind.WITH_TARGET)
                    self._set_binding(name, new_node.id)
                    for rhs_name in rhs_names:
                        src_id = self._current_binding(rhs_name)
                        if src_id:
                            self.graph.add_edge(FlowEdge(
                                src=src_id, dst=new_node.id,
                                kind=EdgeKind.ASSIGN,
                            ))
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_Import(self, node: ast.Import) -> None:
        loc = self._loc(node)
        for alias in node.names:
            local_name = alias.asname or alias.name.split(".")[-1]
            imp_node = self._add_node(local_name, loc, NodeKind.IMPORT)
            self._set_binding(local_name, imp_node.id)
            self.unresolved_imports.append({
                "node_id": imp_node.id,
                "module": alias.name,
                "name": None,
                "local_name": local_name,
                "file": self.file,
            })

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        loc = self._loc(node)
        module = node.module or ""
        level = node.level or 0

        for alias in node.names:
            if alias.name == "*":
                continue  # skip star imports
            local_name = alias.asname or alias.name
            imp_node = self._add_node(local_name, loc, NodeKind.IMPORT)
            self._set_binding(local_name, imp_node.id)
            self.unresolved_imports.append({
                "node_id": imp_node.id,
                "module": module,
                "name": alias.name,
                "local_name": local_name,
                "level": level,
                "file": self.file,
            })

    def visit_Call(self, node: ast.Call) -> None:
        """Track calls to sinks - create edges from arguments to the sink."""
        func_name, transform_cat, sink_cat = self._get_call_info(node)

        if sink_cat:
            loc = self._loc(node)
            sink_node = self._add_node(f"<sink:{func_name}>", loc, NodeKind.CALL_RESULT)

            # Link all arguments to the sink
            for arg in node.args:
                for name in self._extract_rhs_names(arg):
                    src_id = self._current_binding(name)
                    if src_id:
                        self.graph.add_edge(FlowEdge(
                            src=src_id, dst=sink_node.id,
                            kind=EdgeKind.CALL_ARG,
                            sink=func_name,
                            sink_category=sink_cat,
                        ))

            for kw in node.keywords:
                if kw.value:
                    for name in self._extract_rhs_names(kw.value):
                        src_id = self._current_binding(name)
                        if src_id:
                            self.graph.add_edge(FlowEdge(
                                src=src_id, dst=sink_node.id,
                                kind=EdgeKind.CALL_ARG,
                                sink=func_name,
                                sink_category=sink_cat,
                            ))

        # Don't call generic_visit here - the parent will handle child traversal
        # But we do need to visit arguments for nested calls
        for arg in node.args:
            self.visit(arg)
        for kw in node.keywords:
            if kw.value:
                self.visit(kw.value)
        # Visit the function expression itself for chained calls
        self.visit(node.func)

    def visit_Expr(self, node: ast.Expr) -> None:
        """Handle expression statements like standalone function calls."""
        # For bare calls like print(x), visit_Call handles it
        if isinstance(node.value, ast.Call):
            self.visit_Call(node.value)
        else:
            self.generic_visit(node)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node)

    def _visit_comprehension(self, node: ast.AST) -> None:
        for generator in node.generators:  # type: ignore[attr-defined]
            names = self._extract_targets(generator.target)
            loc = self._loc(generator)
            for name in names:
                comp_node = self._add_node(name, loc, NodeKind.COMPREHENSION)
                self._set_binding(name, comp_node.id)
                iter_names = self._extract_rhs_names(generator.iter)
                for iter_name in iter_names:
                    src_id = self._current_binding(iter_name)
                    if src_id:
                        self.graph.add_edge(FlowEdge(
                            src=src_id, dst=comp_node.id,
                            kind=EdgeKind.ASSIGN,
                        ))
        self.generic_visit(node)


def collect_file(graph: FlowGraph, file_path: str) -> FlowCollector:
    """Parse a Python file and collect its flow graph data."""
    source = Path(file_path).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source, filename=file_path)
    collector = FlowCollector(graph, file_path)
    collector.visit(tree)
    return collector
