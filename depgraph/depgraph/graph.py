"""Dependency graph data structure and algorithms."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path


class DependencyGraph:
    """Directed graph of file dependencies with analysis algorithms."""

    def __init__(self) -> None:
        # adjacency list: source -> list of (target, edge_info)
        self._adj: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        # reverse adjacency: target -> list of (source, edge_info)
        self._rev: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        # all known nodes
        self._nodes: set[str] = set()

    def add_edge(self, source: str, target: str, **attrs) -> None:
        """Add a directed edge from source to target."""
        self._nodes.add(source)
        self._nodes.add(target)
        self._adj[source].append((target, attrs))
        self._rev[target].append((source, attrs))

    def add_node(self, node: str) -> None:
        """Add a node with no edges."""
        self._nodes.add(node)

    @property
    def nodes(self) -> set[str]:
        return set(self._nodes)

    def successors(self, node: str) -> list[str]:
        """Files that `node` depends on (fan-out targets)."""
        return [t for t, _ in self._adj.get(node, [])]

    def predecessors(self, node: str) -> list[str]:
        """Files that depend on `node` (fan-in sources)."""
        return [s for s, _ in self._rev.get(node, [])]

    def edges(self) -> list[tuple[str, str, dict]]:
        """All edges as (source, target, attrs)."""
        result = []
        for src, targets in self._adj.items():
            for tgt, attrs in targets:
                result.append((src, tgt, attrs))
        return result

    def out_edges(self, node: str) -> list[tuple[str, str, dict]]:
        """Outgoing edges from a node."""
        return [(node, t, a) for t, a in self._adj.get(node, [])]

    def in_edges(self, node: str) -> list[tuple[str, str, dict]]:
        """Incoming edges to a node."""
        return [(s, node, a) for s, a in self._rev.get(node, [])]

    # ------------------------------------------------------------------
    # Fan-in / Fan-out
    # ------------------------------------------------------------------

    def fan_in(self, node: str) -> int:
        """Number of unique files that depend on this node."""
        return len(set(self.predecessors(node)))

    def fan_out(self, node: str) -> int:
        """Number of unique files this node depends on."""
        return len(set(self.successors(node)))

    def fan_in_ranking(self) -> list[tuple[str, int]]:
        """All nodes sorted by fan-in descending."""
        ranking = [(n, self.fan_in(n)) for n in self._nodes]
        ranking.sort(key=lambda x: x[1], reverse=True)
        return ranking

    def fan_out_ranking(self) -> list[tuple[str, int]]:
        """All nodes sorted by fan-out descending."""
        ranking = [(n, self.fan_out(n)) for n in self._nodes]
        ranking.sort(key=lambda x: x[1], reverse=True)
        return ranking

    # ------------------------------------------------------------------
    # Strongly Connected Components (Tarjan's Algorithm)
    # ------------------------------------------------------------------

    def strongly_connected_components(self) -> list[list[str]]:
        """Find all SCCs using Tarjan's algorithm. Returns list of components."""
        index_counter = [0]
        stack: list[str] = []
        on_stack: set[str] = set()
        index_map: dict[str, int] = {}
        lowlink: dict[str, int] = {}
        result: list[list[str]] = []

        def strongconnect(v: str) -> None:
            index_map[v] = index_counter[0]
            lowlink[v] = index_counter[0]
            index_counter[0] += 1
            stack.append(v)
            on_stack.add(v)

            for w in self.successors(v):
                if w not in index_map:
                    strongconnect(w)
                    lowlink[v] = min(lowlink[v], lowlink[w])
                elif w in on_stack:
                    lowlink[v] = min(lowlink[v], index_map[w])

            # Root of an SCC
            if lowlink[v] == index_map[v]:
                component: list[str] = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    component.append(w)
                    if w == v:
                        break
                result.append(component)

        # Use iterative deepening to avoid recursion limit on large graphs
        import sys
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old_limit, len(self._nodes) + 1000))
        try:
            for node in self._nodes:
                if node not in index_map:
                    strongconnect(node)
        finally:
            sys.setrecursionlimit(old_limit)

        return result

    # ------------------------------------------------------------------
    # Cycle Detection
    # ------------------------------------------------------------------

    def find_cycles(self) -> list[list[str]]:
        """Find all elementary cycles using SCC decomposition + DFS.

        Returns a list of cycles, where each cycle is a list of nodes
        forming the cycle path (last node connects back to first).
        """
        cycles: list[list[str]] = []
        sccs = self.strongly_connected_components()

        for scc in sccs:
            if len(scc) < 2:
                # Check self-loop
                node = scc[0]
                if node in self.successors(node):
                    cycles.append([node, node])
                continue
            # Find cycles within this SCC using DFS
            scc_set = set(scc)
            sub_cycles = self._find_cycles_in_scc(scc, scc_set)
            cycles.extend(sub_cycles)

        return cycles

    def _find_cycles_in_scc(self, scc: list[str], scc_set: set[str]) -> list[list[str]]:
        """Find cycles within a single SCC using Johnson's algorithm (simplified)."""
        cycles: list[list[str]] = []
        # For practical purposes, limit cycle enumeration
        # Use DFS from each node in the SCC
        seen_cycles: set[tuple[str, ...]] = set()

        for start in scc:
            visited: set[str] = set()
            path: list[str] = []

            def dfs(node: str, depth: int = 0) -> None:
                if depth > len(scc) + 1:
                    return
                path.append(node)
                visited.add(node)

                for succ in self.successors(node):
                    if succ not in scc_set:
                        continue
                    if succ == start and len(path) > 1:
                        cycle = list(path) + [start]
                        # Normalize: rotate so smallest element is first
                        normalized = _normalize_cycle(cycle[:-1])
                        key = tuple(normalized)
                        if key not in seen_cycles:
                            seen_cycles.add(key)
                            cycles.append(cycle)
                    elif succ not in visited:
                        dfs(succ, depth + 1)

                path.pop()
                visited.discard(node)

            dfs(start)
            # Limit total cycles to avoid combinatorial explosion
            if len(cycles) > 100:
                break

        return cycles

    # ------------------------------------------------------------------
    # Cross-language edges
    # ------------------------------------------------------------------

    def cross_language_edges(self) -> list[tuple[str, str, dict]]:
        """Return only cross-language dependency edges."""
        return [
            (s, t, a)
            for s, t, a in self.edges()
            if a.get("cross_language", False)
        ]

    # ------------------------------------------------------------------
    # Dependency Tree
    # ------------------------------------------------------------------

    def dependency_tree(self, root: str, project_root: str = "") -> str:
        """Generate ASCII dependency tree from a root node."""
        lines: list[str] = []
        visited: set[str] = set()
        root_label = _short_path(root, project_root)
        lines.append(root_label)
        self._build_tree(root, "", True, lines, visited, project_root)
        return "\n".join(lines)

    def _build_tree(
        self,
        node: str,
        prefix: str,
        is_last: bool,
        lines: list[str],
        visited: set[str],
        project_root: str,
    ) -> None:
        visited.add(node)
        children = sorted(set(self.successors(node)))

        for i, child in enumerate(children):
            is_last_child = i == len(children) - 1
            connector = "\u2514\u2500\u2500 " if is_last_child else "\u251c\u2500\u2500 "
            extension = "    " if is_last_child else "\u2502   "
            label = _short_path(child, project_root)

            # Check for cycle
            if child in visited:
                # Check if it's a direct cycle back to an ancestor
                cycle_target = label
                lines.append(f"{prefix}{connector}{label}  [CYCLE -> {cycle_target}]")
                continue

            # Check if already shown (not a cycle, just a repeated dep)
            if child in visited:
                lines.append(f"{prefix}{connector}{label}  (already shown)")
                continue

            lines.append(f"{prefix}{connector}{label}")
            self._build_tree(child, prefix + extension, is_last_child, lines, visited, project_root)

        visited.discard(node)

    # ------------------------------------------------------------------
    # Layering Violations
    # ------------------------------------------------------------------

    def detect_layer_violations(self, layers: list[set[str]] | None = None) -> list[dict]:
        """Detect layering violations.

        If layers is None, attempts to infer layers from the graph topology.
        layers[0] = lowest level (utils), layers[-1] = highest level (api).

        A violation is when a lower-layer file depends on a higher-layer file,
        or when a file skips layers.
        """
        if layers is None:
            layers = self._infer_layers()
        if not layers:
            return []

        node_layer: dict[str, int] = {}
        for level, layer_nodes in enumerate(layers):
            for node in layer_nodes:
                node_layer[node] = level

        violations: list[dict] = []
        for src, tgt, attrs in self.edges():
            src_level = node_layer.get(src)
            tgt_level = node_layer.get(tgt)
            if src_level is None or tgt_level is None:
                continue
            # Higher level depending on same or higher is fine
            # Lower level depending on higher level is a violation
            if src_level < tgt_level:
                violations.append({
                    "source": src,
                    "target": tgt,
                    "source_layer": src_level,
                    "target_layer": tgt_level,
                    "type": "upward_dependency",
                })
            # Skip-layer: depends on something more than 1 layer below
            elif src_level - tgt_level > 1:
                violations.append({
                    "source": src,
                    "target": tgt,
                    "source_layer": src_level,
                    "target_layer": tgt_level,
                    "type": "skip_layer",
                })

        return violations

    def _infer_layers(self) -> list[set[str]]:
        """Infer layers by topological depth (longest path from sources)."""
        # Find nodes with no incoming edges (sources/roots)
        in_degree: dict[str, int] = {n: 0 for n in self._nodes}
        for src, targets in self._adj.items():
            for tgt, _ in targets:
                in_degree[tgt] = in_degree.get(tgt, 0) + 1

        # BFS to assign layers
        depth: dict[str, int] = {}
        queue: list[str] = []
        for n, deg in in_degree.items():
            if deg == 0:
                depth[n] = 0
                queue.append(n)

        while queue:
            node = queue.pop(0)
            for succ in self.successors(node):
                new_depth = depth[node] + 1
                if succ not in depth or depth[succ] < new_depth:
                    depth[succ] = new_depth
                    queue.append(succ)

        if not depth:
            return []

        max_depth = max(depth.values())
        # Invert: highest depth = lowest layer (most depended on)
        layers: list[set[str]] = [set() for _ in range(max_depth + 1)]
        for node, d in depth.items():
            # Reverse: items at max depth are at layer 0 (bottom)
            layers[max_depth - d].add(node)

        return layers

    # ------------------------------------------------------------------
    # Subgraph for a specific file
    # ------------------------------------------------------------------

    def file_subgraph(self, file_path: str) -> dict:
        """Get all dependencies to and from a specific file."""
        depends_on = [(t, a) for t, a in self._adj.get(file_path, [])]
        depended_by = [(s, a) for s, a in self._rev.get(file_path, [])]
        return {
            "file": file_path,
            "depends_on": depends_on,
            "depended_on_by": depended_by,
        }

    # ------------------------------------------------------------------
    # JSON export
    # ------------------------------------------------------------------

    def to_dict(self, project_root: str = "") -> dict:
        """Export graph as a JSON-serializable dict."""
        nodes = []
        for n in sorted(self._nodes):
            nodes.append({
                "path": n,
                "short": _short_path(n, project_root),
                "fan_in": self.fan_in(n),
                "fan_out": self.fan_out(n),
            })
        edges = []
        for s, t, a in self.edges():
            edges.append({
                "source": s,
                "target": t,
                **a,
            })
        return {"nodes": nodes, "edges": edges}


def _normalize_cycle(cycle: list[str]) -> list[str]:
    """Normalize a cycle by rotating so the smallest element is first."""
    if not cycle:
        return cycle
    min_idx = cycle.index(min(cycle))
    return cycle[min_idx:] + cycle[:min_idx]


def _short_path(full_path: str, project_root: str) -> str:
    """Shorten a path relative to the project root."""
    if project_root and full_path.startswith(project_root):
        rel = full_path[len(project_root):]
        # Strip leading separator
        rel = rel.lstrip("/").lstrip("\\")
        return rel if rel else full_path
    return Path(full_path).name
