"""Analysis passes over the completed flow graph."""

from __future__ import annotations

from .graph import FlowGraph, FlowNode, FlowEdge, NodeKind


class Analyzer:
    def __init__(self, graph: FlowGraph) -> None:
        self.graph = graph

    def flow_chains(self, var_name: str,
                    file: str | None = None) -> list[list[FlowNode]]:
        """Find all forward chains from nodes matching var_name."""
        start_nodes = self.graph.nodes_by_name(var_name, file)
        all_chains: list[list[FlowNode]] = []
        for node in start_nodes:
            chains = self.graph.chain_forward(node.id)
            all_chains.extend(chains)
        return all_chains

    def trace_back(self, var_name: str,
                   file: str | None = None) -> list[list[FlowNode]]:
        """Find all backward chains to nodes matching var_name."""
        end_nodes = self.graph.nodes_by_name(var_name, file)
        all_chains: list[list[FlowNode]] = []
        for node in end_nodes:
            chains = self.graph.chain_backward(node.id)
            all_chains.extend(chains)
        return all_chains

    def dead_variables(self) -> list[FlowNode]:
        """Variables assigned but never read (no outgoing edges).

        Excludes: returns, sinks, imports, self/cls params, _ prefixed,
        and dunder names.
        """
        dead = []
        for node in self.graph.all_nodes():
            if node.kind in (NodeKind.RETURN, NodeKind.CALL_RESULT,
                             NodeKind.COMPREHENSION):
                continue
            if node.is_external:
                continue
            if node.name.startswith("_") or node.name in ("self", "cls"):
                continue
            # Skip self.x attribute assignments (they're used by the object)
            if node.name.startswith("self."):
                continue
            # Skip enum-style ALL_CAPS assignments (class constants)
            if node.name.isupper() and node.kind == NodeKind.ASSIGN:
                continue
            if not self.graph.outgoing(node.id):
                dead.append(node)
        return sorted(dead, key=lambda n: (n.loc.file, n.loc.line))

    def unused_imports(self) -> list[FlowNode]:
        """Imports that are never referenced."""
        unused = []
        for node in self.graph.all_nodes():
            if node.kind != NodeKind.IMPORT:
                continue
            if node.is_external and not self.graph.outgoing(node.id):
                unused.append(node)
            elif not node.is_external and not self.graph.outgoing(node.id):
                unused.append(node)
        return sorted(unused, key=lambda n: (n.loc.file, n.loc.line))

    def unused_params(self) -> list[FlowNode]:
        """Function parameters that are never used in the function body.

        Excludes self, cls, *args, **kwargs, and _-prefixed names.
        """
        unused = []
        for node in self.graph.all_nodes():
            if node.kind != NodeKind.PARAM:
                continue
            if node.name in ("self", "cls"):
                continue
            if node.name.startswith("_") or node.name.startswith("*"):
                continue
            if not self.graph.outgoing(node.id):
                unused.append(node)
        return sorted(unused, key=lambda n: (n.loc.file, n.loc.line))

    def transformations(self, var_name: str | None = None) -> list[FlowEdge]:
        """Edges where data is transformed (encoded, hashed, etc.)."""
        results = []
        for edge in self.graph.edges:
            if edge.transform_category is None:
                continue
            if var_name:
                src_node = self.graph.nodes.get(edge.src)
                dst_node = self.graph.nodes.get(edge.dst)
                if not (src_node and dst_node):
                    continue
                if src_node.name != var_name and dst_node.name != var_name:
                    continue
            results.append(edge)
        return results

    def sinks(self, var_name: str | None = None) -> list[FlowEdge]:
        """Edges where data flows into a sink (print, file, DB, etc.)."""
        results = []
        for edge in self.graph.edges:
            if edge.sink_category is None:
                continue
            if var_name:
                src_node = self.graph.nodes.get(edge.src)
                if not src_node:
                    continue
                # Check if this variable is in the chain leading to the sink
                if src_node.name != var_name:
                    # Check backward chain
                    chains = self.graph.chain_backward(edge.src)
                    found = False
                    for chain in chains:
                        if any(n.name == var_name for n in chain):
                            found = True
                            break
                    if not found:
                        continue
            results.append(edge)
        return results

    def summary(self) -> dict:
        """Quick stats about the graph."""
        return {
            "total_nodes": len(self.graph.nodes),
            "total_edges": len(self.graph.edges),
            "files": len(set(n.loc.file for n in self.graph.all_nodes())),
            "dead_variables": len(self.dead_variables()),
            "unused_imports": len(self.unused_imports()),
            "unused_params": len(self.unused_params()),
            "transforms": len(self.transformations()),
            "sinks": len(self.sinks()),
        }
