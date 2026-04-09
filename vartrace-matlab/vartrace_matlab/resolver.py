"""Cross-file resolution for MATLAB.

MATLAB resolution is simpler than Python's import system:
- Each .m file defines either a function (same name as file) or a script
- Functions call other functions by name - MATLAB searches the path
- For our purposes, we search the project directory
"""

from __future__ import annotations

import os
from pathlib import Path

from .graph import EdgeKind, FlowEdge, FlowGraph, NodeKind


class MatlabResolver:
    def __init__(self, root: str) -> None:
        self.root = os.path.normpath(root)
        # function_name -> file_path
        self._func_to_file: dict[str, str] = {}
        # function_name -> {inputs, outputs, file, line}
        self._func_info: dict[str, dict] = {}

    def discover_files(self) -> list[str]:
        """Find all .m files under root."""
        m_files = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(".") and not d.startswith("+")
                           and not d.startswith("@")]
            for fn in filenames:
                if fn.endswith(".m"):
                    m_files.append(os.path.normpath(os.path.join(dirpath, fn)))
        return m_files

    def build_function_map(self, files: list[str],
                            all_functions: dict[str, dict]) -> None:
        """Build mapping from function names to their files and signatures."""
        # Primary functions: filename matches function name
        for fpath in files:
            stem = Path(fpath).stem
            self._func_to_file[stem] = fpath

        # Also register all collected function definitions
        self._func_info.update(all_functions)
        for func_name, info in all_functions.items():
            if func_name not in self._func_to_file:
                self._func_to_file[func_name] = info["file"]

    def stitch_calls(self, graph: FlowGraph,
                      all_calls: list[dict]) -> None:
        """Create cross-file edges for function calls."""
        for call in all_calls:
            func_name = call["func_name"]
            arg_names = call["args"]
            call_line = call["line"]
            call_file = call["file"]

            if func_name not in self._func_info:
                continue

            func_info = self._func_info[func_name]
            target_file = func_info["file"]

            if target_file == call_file:
                # Same-file call - find input param nodes and link
                pass  # handled within the file already

            # Find the input parameter nodes in the target function
            input_params = func_info.get("inputs", [])
            for i, param_name in enumerate(input_params):
                if i >= len(arg_names):
                    break
                arg_name = arg_names[i]

                # Find the arg's binding in the caller's file
                caller_nodes = [
                    n for n in graph.nodes.values()
                    if n.loc.file == os.path.normpath(call_file)
                    and n.name == arg_name
                    and n.loc.line <= call_line
                ]
                if not caller_nodes:
                    continue
                caller_node = max(caller_nodes, key=lambda n: n.loc.line)

                # Find the param node in the target function
                param_nodes = [
                    n for n in graph.nodes.values()
                    if n.loc.file == os.path.normpath(target_file)
                    and n.name == param_name
                    and n.kind == NodeKind.INPUT_PARAM
                ]
                if not param_nodes:
                    continue
                # Pick the one in the right function scope
                param_node = None
                for pn in param_nodes:
                    if func_name in pn.scope:
                        param_node = pn
                        break
                if not param_node:
                    param_node = param_nodes[0]

                graph.add_edge(FlowEdge(
                    src=caller_node.id,
                    dst=param_node.id,
                    kind=EdgeKind.CROSS_FILE,
                ))
