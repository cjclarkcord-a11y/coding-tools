"""Python complexity analysis using the ast module."""

import ast
import os
from dataclasses import dataclass, field


@dataclass
class FunctionMetrics:
    name: str
    file: str
    line: int
    complexity: int = 1
    max_depth: int = 0
    length: int = 0
    score: float = 0.0

    def compute_score(self):
        self.score = self.complexity * max(1, self.max_depth) + self.length / 10


class _NestingCounter(ast.NodeVisitor):
    """Walk a function body to find maximum nesting depth of control structures."""

    NESTING_NODES = (
        ast.If, ast.For, ast.While, ast.Try, ast.With,
        ast.AsyncFor, ast.AsyncWith,
    )
    # Python 3.11+ has TryStar
    try:
        NESTING_NODES = NESTING_NODES + (ast.TryStar,)
    except AttributeError:
        pass

    def __init__(self):
        self.max_depth = 0
        self._current_depth = 0

    def _visit_nesting(self, node):
        self._current_depth += 1
        if self._current_depth > self.max_depth:
            self.max_depth = self._current_depth
        self.generic_visit(node)
        self._current_depth -= 1

    def visit_If(self, node):
        self._visit_nesting(node)

    def visit_For(self, node):
        self._visit_nesting(node)

    def visit_AsyncFor(self, node):
        self._visit_nesting(node)

    def visit_While(self, node):
        self._visit_nesting(node)

    def visit_Try(self, node):
        self._visit_nesting(node)

    def visit_TryStar(self, node):
        self._visit_nesting(node)

    def visit_With(self, node):
        self._visit_nesting(node)

    def visit_AsyncWith(self, node):
        self._visit_nesting(node)


class _ComplexityCounter(ast.NodeVisitor):
    """Count decision points in a function body for cyclomatic complexity."""

    def __init__(self):
        self.complexity = 1  # base complexity

    def visit_If(self, node):
        self.complexity += 1
        self.generic_visit(node)

    def visit_For(self, node):
        self.complexity += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node):
        self.complexity += 1
        self.generic_visit(node)

    def visit_While(self, node):
        self.complexity += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node):
        self.complexity += 1
        self.generic_visit(node)

    def visit_With(self, node):
        self.complexity += 1
        self.generic_visit(node)

    def visit_AsyncWith(self, node):
        self.complexity += 1
        self.generic_visit(node)

    def visit_Assert(self, node):
        self.complexity += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        # each 'and'/'or' adds (num_values - 1) decision points
        self.complexity += len(node.values) - 1
        self.generic_visit(node)

    def visit_IfExp(self, node):
        # ternary expression: x if c else y
        self.complexity += 1
        self.generic_visit(node)

    def visit_comprehension(self, node):
        # each 'if' filter in a comprehension
        self.complexity += len(node.ifs)
        self.generic_visit(node)


def _count_function_length(source_lines: list[str], start_line: int, end_line: int) -> int:
    """Count non-blank, non-comment lines in a function body."""
    count = 0
    for i in range(start_line, min(end_line, len(source_lines))):
        line = source_lines[i].strip()
        if line == "" or line.startswith("#"):
            continue
        count += 1
    return count


def _get_end_line(node) -> int:
    """Get the end line of a node, handling different Python versions."""
    if hasattr(node, "end_lineno") and node.end_lineno is not None:
        return node.end_lineno
    # Fallback: estimate from child nodes
    max_line = node.lineno
    for child in ast.walk(node):
        if hasattr(child, "lineno") and child.lineno is not None:
            max_line = max(max_line, child.lineno)
        if hasattr(child, "end_lineno") and child.end_lineno is not None:
            max_line = max(max_line, child.end_lineno)
    return max_line


class _FunctionCollector(ast.NodeVisitor):
    """Collect all function/method definitions from a module."""

    def __init__(self, filepath: str, source_lines: list[str]):
        self.filepath = filepath
        self.source_lines = source_lines
        self.functions: list[FunctionMetrics] = []
        self._class_stack: list[str] = []

    def visit_ClassDef(self, node):
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node):
        self._process_function(node)

    def visit_AsyncFunctionDef(self, node):
        self._process_function(node)

    def _process_function(self, node):
        if self._class_stack:
            name = ".".join(self._class_stack) + "." + node.name
        else:
            name = node.name

        # Cyclomatic complexity
        cc = _ComplexityCounter()
        cc.visit(node)

        # Nesting depth
        nc = _NestingCounter()
        for child in node.body:
            nc.visit(child)

        # Function length
        end_line = _get_end_line(node)
        # node.lineno is 1-based; body starts after the def line
        body_start = node.body[0].lineno - 1 if node.body else node.lineno
        length = _count_function_length(self.source_lines, body_start, end_line)

        metrics = FunctionMetrics(
            name=name,
            file=self.filepath,
            line=node.lineno,
            complexity=cc.complexity,
            max_depth=nc.max_depth,
            length=length,
        )
        metrics.compute_score()
        self.functions.append(metrics)

        # Visit nested functions/classes
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.visit(child)


def analyze_python_file(filepath: str) -> list[FunctionMetrics]:
    """Analyze a single Python file and return metrics for each function."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
    except (OSError, IOError):
        return []

    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        return []

    source_lines = source.splitlines()
    collector = _FunctionCollector(filepath, source_lines)
    collector.visit(tree)
    return collector.functions


def scan_python_files(path: str) -> list[FunctionMetrics]:
    """Scan a path (file or directory) for Python files and analyze them."""
    results: list[FunctionMetrics] = []
    if os.path.isfile(path):
        if path.endswith(".py"):
            results.extend(analyze_python_file(path))
    elif os.path.isdir(path):
        for root, _dirs, files in os.walk(path):
            for fname in files:
                if fname.endswith(".py"):
                    fpath = os.path.join(root, fname)
                    results.extend(analyze_python_file(fpath))
    return results
