"""Cross-file import resolution.

Two-pass approach:
1. Collect all files independently.
2. Stitch cross-file edges by resolving imports.
"""

from __future__ import annotations

import os
from pathlib import Path

from .graph import EdgeKind, FlowEdge, FlowGraph, NodeKind


class ImportResolver:
    def __init__(self, root: str) -> None:
        self.root = os.path.normpath(root)
        self._module_to_file: dict[str, str] = {}

    def discover_files(self) -> list[str]:
        """Find all .py files under root."""
        py_files = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            # Skip hidden dirs, __pycache__, .git, etc.
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(".") and d != "__pycache__"
                           and d != "node_modules" and d != ".venv"
                           and d != "venv" and d != "env"]
            for fn in filenames:
                if fn.endswith(".py"):
                    py_files.append(os.path.normpath(os.path.join(dirpath, fn)))
        return py_files

    def build_module_map(self, files: list[str]) -> None:
        """Build a mapping from dotted module names to file paths."""
        for fpath in files:
            rel = os.path.relpath(fpath, self.root).replace("\\", "/")
            # Remove .py extension
            if rel.endswith(".py"):
                rel = rel[:-3]
            # __init__ -> package itself
            if rel.endswith("/__init__"):
                rel = rel[:-9]
            module_name = rel.replace("/", ".")
            self._module_to_file[module_name] = fpath

    def resolve_module(self, module_name: str, from_file: str | None = None,
                       level: int = 0) -> str | None:
        """Resolve a module name to a file path."""
        if level > 0 and from_file:
            # Relative import
            pkg_dir = os.path.dirname(from_file)
            for _ in range(level - 1):
                pkg_dir = os.path.dirname(pkg_dir)
            if module_name:
                candidate = os.path.join(pkg_dir, module_name.replace(".", os.sep))
            else:
                candidate = pkg_dir
            # Check for package or module
            for suffix in [".py", "/__init__.py", os.sep + "__init__.py"]:
                full = os.path.normpath(candidate + suffix) if suffix == ".py" \
                    else os.path.normpath(candidate + suffix)
                if os.path.isfile(full):
                    return full
            return None

        # Absolute import
        if module_name in self._module_to_file:
            return self._module_to_file[module_name]

        # Try partial match (from pkg.mod import name - mod might be the file)
        parts = module_name.split(".")
        for i in range(len(parts), 0, -1):
            partial = ".".join(parts[:i])
            if partial in self._module_to_file:
                return self._module_to_file[partial]

        return None

    def stitch_imports(self, graph: FlowGraph,
                       all_imports: list[dict]) -> None:
        """Create cross-file edges for resolved imports."""
        for imp in all_imports:
            module = imp.get("module", "")
            name = imp.get("name")  # None for 'import x'
            level = imp.get("level", 0)
            from_file = imp.get("file")
            node_id = imp["node_id"]

            target_file = self.resolve_module(module, from_file, level)
            if not target_file:
                # Mark as external
                if node_id in graph.nodes:
                    graph.nodes[node_id].is_external = True
                continue

            # Find matching top-level binding in the target file
            if name:
                # from x import name - look for 'name' defined in target file
                candidates = [
                    n for n in graph.nodes.values()
                    if n.loc.file == os.path.normpath(target_file)
                    and n.name == name
                    and n.kind in (NodeKind.ASSIGN, NodeKind.IMPORT,
                                   NodeKind.PARAM)
                ]
                if candidates:
                    # Use the last definition (most recent in file)
                    target_node = max(candidates, key=lambda n: n.loc.line)
                    graph.add_edge(FlowEdge(
                        src=target_node.id,
                        dst=node_id,
                        kind=EdgeKind.IMPORT,
                    ))
                    continue

            # For 'import module' or unresolved 'from module import name',
            # just mark as resolved but don't create edge
            # (the import node exists, but we can't pinpoint the source)
