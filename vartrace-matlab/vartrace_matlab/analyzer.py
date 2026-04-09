"""Analysis passes over the completed MATLAB flow graph."""

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
        """Variables assigned but never read.

        Excludes: output params, sinks, global/persistent declarations,
        ignored outputs (~), and common loop vars.
        """
        dead = []
        for node in self.graph.all_nodes():
            if node.kind in (NodeKind.OUTPUT_PARAM, NodeKind.FUNCTION_CALL_RESULT,
                             NodeKind.GLOBAL_DECL, NodeKind.PERSISTENT_DECL):
                continue
            if node.name.startswith("<"):
                continue
            if node.name.startswith("~"):
                continue
            # Skip common acceptable unused patterns
            if node.name in ("ans", "nargin", "nargout", "varargin", "varargout"):
                continue
            if not self.graph.outgoing(node.id):
                dead.append(node)
        return sorted(dead, key=lambda n: (n.loc.file, n.loc.line))

    def unused_inputs(self) -> list[FlowNode]:
        """Function input parameters that are never used."""
        unused = []
        for node in self.graph.all_nodes():
            if node.kind != NodeKind.INPUT_PARAM:
                continue
            if node.name in ("varargin", "nargin", "nargout"):
                continue
            if not self.graph.outgoing(node.id):
                unused.append(node)
        return sorted(unused, key=lambda n: (n.loc.file, n.loc.line))

    def unused_outputs(self) -> list[FlowNode]:
        """Function output parameters that are declared but never assigned to
        (no incoming edges beyond the initial declaration)."""
        unused = []
        for node in self.graph.all_nodes():
            if node.kind != NodeKind.OUTPUT_PARAM:
                continue
            if node.name in ("varargout",):
                continue
            # Check if there's a later ASSIGN node with the same name in the same scope
            has_assignment = False
            for other in self.graph.all_nodes():
                if (other.kind == NodeKind.ASSIGN
                        and other.name == node.name
                        and other.loc.file == node.loc.file
                        and other.scope == node.scope):
                    has_assignment = True
                    break
            if not has_assignment and not self.graph.incoming(node.id):
                unused.append(node)
        return sorted(unused, key=lambda n: (n.loc.file, n.loc.line))

    def globals_and_persistents(self) -> list[FlowNode]:
        """List all global and persistent variable declarations."""
        results = []
        for node in self.graph.all_nodes():
            if node.kind in (NodeKind.GLOBAL_DECL, NodeKind.PERSISTENT_DECL):
                results.append(node)
        return sorted(results, key=lambda n: (n.loc.file, n.loc.line))

    def transformations(self, var_name: str | None = None) -> list[FlowEdge]:
        """Edges where data is transformed."""
        results = []
        for edge in self.graph.edges:
            if edge.transform_category is None:
                continue
            if var_name:
                src = self.graph.nodes.get(edge.src)
                dst = self.graph.nodes.get(edge.dst)
                if not (src and dst):
                    continue
                if src.name != var_name and dst.name != var_name:
                    continue
            results.append(edge)
        return results

    def sinks(self, var_name: str | None = None) -> list[FlowEdge]:
        """Edges where data flows into a sink."""
        results = []
        for edge in self.graph.edges:
            if edge.sink_category is None:
                continue
            if var_name:
                src = self.graph.nodes.get(edge.src)
                if not src:
                    continue
                if src.name != var_name:
                    chains = self.graph.chain_backward(edge.src)
                    found = any(
                        any(n.name == var_name for n in chain)
                        for chain in chains
                    )
                    if not found:
                        continue
            results.append(edge)
        return results

    def summary(self) -> dict:
        return {
            "total_nodes": len(self.graph.nodes),
            "total_edges": len(self.graph.edges),
            "files": len(set(n.loc.file for n in self.graph.all_nodes())),
            "dead_variables": len(self.dead_variables()),
            "unused_inputs": len(self.unused_inputs()),
            "unused_outputs": len(self.unused_outputs()),
            "globals_persistents": len(self.globals_and_persistents()),
            "transforms": len(self.transformations()),
            "sinks": len(self.sinks()),
        }
