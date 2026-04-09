"""Flow graph data model for MATLAB variable tracing.

Same SSA-style approach as the Python version: nodes are variable bindings
at specific source locations, edges are data flow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Iterator


class NodeKind(Enum):
    ASSIGN = auto()
    INPUT_PARAM = auto()
    OUTPUT_PARAM = auto()
    FOR_TARGET = auto()
    GLOBAL_DECL = auto()
    PERSISTENT_DECL = auto()
    LOAD_TARGET = auto()      # variable loaded from .mat file
    FUNCTION_CALL_RESULT = auto()


class EdgeKind(Enum):
    ASSIGN = auto()
    PARAM_PASS = auto()
    RETURN = auto()
    CALL_RESULT = auto()
    CALL_ARG = auto()
    CROSS_FILE = auto()


@dataclass(frozen=True)
class Location:
    file: str
    line: int

    def __str__(self) -> str:
        return f"{self.file}:{self.line}"

    def short(self, root: str = "") -> str:
        f = self.file
        if root and f.startswith(root):
            f = f[len(root):].lstrip("/\\")
        return f"{f}:{self.line}"


@dataclass
class FlowNode:
    id: str
    name: str
    loc: Location
    kind: NodeKind
    scope: str           # "filename>function_name" or "filename" for scripts

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FlowNode):
            return NotImplemented
        return self.id == other.id


@dataclass
class FlowEdge:
    src: str
    dst: str
    kind: EdgeKind
    transform: str | None = None
    transform_category: str | None = None
    sink: str | None = None
    sink_category: str | None = None


class FlowGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, FlowNode] = {}
        self.edges: list[FlowEdge] = []
        self._fwd: dict[str, list[FlowEdge]] = {}
        self._rev: dict[str, list[FlowEdge]] = {}

    def add_node(self, node: FlowNode) -> None:
        self.nodes[node.id] = node
        if node.id not in self._fwd:
            self._fwd[node.id] = []
        if node.id not in self._rev:
            self._rev[node.id] = []

    def add_edge(self, edge: FlowEdge) -> None:
        self.edges.append(edge)
        self._fwd.setdefault(edge.src, []).append(edge)
        self._rev.setdefault(edge.dst, []).append(edge)

    def successors(self, node_id: str) -> list[FlowNode]:
        return [self.nodes[e.dst] for e in self._fwd.get(node_id, [])
                if e.dst in self.nodes]

    def predecessors(self, node_id: str) -> list[FlowNode]:
        return [self.nodes[e.src] for e in self._rev.get(node_id, [])
                if e.src in self.nodes]

    def outgoing(self, node_id: str) -> list[FlowEdge]:
        return self._fwd.get(node_id, [])

    def incoming(self, node_id: str) -> list[FlowEdge]:
        return self._rev.get(node_id, [])

    def nodes_by_name(self, name: str, file: str | None = None) -> list[FlowNode]:
        results = []
        for node in self.nodes.values():
            if node.name == name:
                if file is None or node.loc.file == file:
                    results.append(node)
        return sorted(results, key=lambda n: (n.loc.file, n.loc.line))

    def chain_forward(self, node_id: str, max_depth: int = 50) -> list[list[FlowNode]]:
        chains: list[list[FlowNode]] = []
        visited: set[str] = set()

        def dfs(nid: str, path: list[FlowNode]) -> None:
            if nid in visited or len(path) > max_depth:
                return
            visited.add(nid)
            node = self.nodes.get(nid)
            if node is None:
                return
            path.append(node)
            succs = self._fwd.get(nid, [])
            if not succs:
                chains.append(list(path))
            else:
                for edge in succs:
                    dfs(edge.dst, path)
            path.pop()
            visited.discard(nid)

        dfs(node_id, [])
        return chains

    def chain_backward(self, node_id: str, max_depth: int = 50) -> list[list[FlowNode]]:
        chains: list[list[FlowNode]] = []
        visited: set[str] = set()

        def dfs(nid: str, path: list[FlowNode]) -> None:
            if nid in visited or len(path) > max_depth:
                return
            visited.add(nid)
            node = self.nodes.get(nid)
            if node is None:
                return
            path.append(node)
            preds = self._rev.get(nid, [])
            if not preds:
                chains.append(list(reversed(path)))
            else:
                for edge in preds:
                    dfs(edge.src, path)
            path.pop()
            visited.discard(nid)

        dfs(node_id, [])
        return chains

    def all_nodes(self) -> Iterator[FlowNode]:
        yield from self.nodes.values()
