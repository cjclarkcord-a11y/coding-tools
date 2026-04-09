"""Python error handling auditor using the ast module."""

import ast
import os
from dataclasses import dataclass


@dataclass
class Issue:
    file: str
    line: int
    severity: str  # HIGH, MEDIUM, LOW
    title: str
    description: str
    code_lines: list[str]


# I/O calls that should be guarded with try/except
_IO_FUNCS = {"open"}
_IO_MODULES = {"requests", "urllib", "socket", "sqlite3", "psycopg2", "pymysql"}


def _is_test_file(filepath: str) -> bool:
    """Check if the file is a test file."""
    base = os.path.basename(filepath)
    return (
        base.startswith("test_")
        or base.endswith("_test.py")
        or base == "conftest.py"
        or "/tests/" in filepath.replace("\\", "/")
        or "/test/" in filepath.replace("\\", "/")
    )


def _get_source_lines(source: str) -> list[str]:
    return source.splitlines()


def _extract_code(lines: list[str], lineno: int, count: int = 2) -> list[str]:
    """Extract lines around the given 1-based line number."""
    start = max(0, lineno - 1)
    end = min(len(lines), start + count)
    return [l for l in lines[start:end]]


def _is_inside_try(node: ast.AST, ancestors: dict[int, ast.AST]) -> bool:
    """Walk up the ancestor chain to see if this node is inside a Try body."""
    current_id = id(node)
    while current_id in ancestors:
        parent = ancestors[current_id]
        if isinstance(parent, ast.Try):
            return True
        current_id = id(parent)
    return False


def _build_ancestor_map(tree: ast.AST) -> dict[int, ast.AST]:
    """Build a mapping from child node id to parent node."""
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _body_is_empty(body: list[ast.stmt]) -> bool:
    """Check if an except body is effectively empty (only pass, ..., or string expr)."""
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            # Ellipsis or docstring
            if stmt.value.value is ... or isinstance(stmt.value.value, str):
                continue
        return False
    return True


def _body_has_raise(body: list[ast.stmt]) -> bool:
    """Check if a body contains a raise statement at any depth."""
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Raise):
            return True
    return False


def _handler_is_swallowed(handler: ast.ExceptHandler) -> bool:
    """Check if the except handler catches and does nothing (pass only)."""
    if len(handler.body) == 1:
        stmt = handler.body[0]
        if isinstance(stmt, ast.Pass):
            return True
    return False


def _check_bare_except(handler: ast.ExceptHandler, lines: list[str], filepath: str) -> Issue | None:
    if handler.type is None:
        return Issue(
            file=filepath,
            line=handler.lineno,
            severity="HIGH",
            title="Bare except",
            description="Catches all exceptions including KeyboardInterrupt and SystemExit",
            code_lines=_extract_code(lines, handler.lineno),
        )
    return None


def _check_broad_except(handler: ast.ExceptHandler, lines: list[str], filepath: str) -> Issue | None:
    if handler.type is None:
        return None
    if isinstance(handler.type, ast.Name) and handler.type.id in ("Exception", "BaseException"):
        return Issue(
            file=filepath,
            line=handler.lineno,
            severity="MEDIUM",
            title="Broad except",
            description=f"Catching {handler.type.id} is too broad in most cases",
            code_lines=_extract_code(lines, handler.lineno),
        )
    return None


def _check_swallowed(handler: ast.ExceptHandler, lines: list[str], filepath: str) -> Issue | None:
    if _handler_is_swallowed(handler):
        return Issue(
            file=filepath,
            line=handler.lineno,
            severity="HIGH",
            title="Swallowed exception",
            description="Exception is caught and silently ignored with pass",
            code_lines=_extract_code(lines, handler.lineno),
        )
    return None


def _check_empty_body(handler: ast.ExceptHandler, lines: list[str], filepath: str) -> Issue | None:
    if _body_is_empty(handler.body) and not _handler_is_swallowed(handler):
        return Issue(
            file=filepath,
            line=handler.lineno,
            severity="HIGH",
            title="Empty except body",
            description="Except block body is effectively empty (only pass or ...)",
            code_lines=_extract_code(lines, handler.lineno),
        )
    return None


def _check_generic_raise(tree: ast.AST, lines: list[str], filepath: str) -> list[Issue]:
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and node.exc is not None:
            exc = node.exc
            # raise Exception(...) or raise Exception
            if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name) and exc.func.id == "Exception":
                issues.append(Issue(
                    file=filepath,
                    line=node.lineno,
                    severity="LOW",
                    title="Generic raise",
                    description="Raising bare Exception instead of a specific exception type",
                    code_lines=_extract_code(lines, node.lineno),
                ))
            elif isinstance(exc, ast.Name) and exc.id == "Exception":
                issues.append(Issue(
                    file=filepath,
                    line=node.lineno,
                    severity="LOW",
                    title="Generic raise",
                    description="Raising bare Exception instead of a specific exception type",
                    code_lines=_extract_code(lines, node.lineno),
                ))
    return issues


def _check_unguarded_io(tree: ast.AST, lines: list[str], filepath: str) -> list[Issue]:
    """Find I/O calls not inside try/except."""
    ancestors = _build_ancestor_map(tree)
    issues = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        is_io = False
        call_desc = ""

        # open(...)
        if isinstance(node.func, ast.Name) and node.func.id in _IO_FUNCS:
            is_io = True
            call_desc = f"{node.func.id}()"

        # requests.get(...), urllib.request.urlopen(...), socket.socket(...), etc.
        elif isinstance(node.func, ast.Attribute):
            # Get the root module name from chained attribute access
            root = node.func
            parts = [node.func.attr]
            while isinstance(root, ast.Attribute):
                root = root.value
                if isinstance(root, ast.Attribute):
                    parts.append(root.attr)
            if isinstance(root, ast.Name):
                parts.append(root.id)
                root_name = root.id
                if root_name in _IO_MODULES:
                    is_io = True
                    parts.reverse()
                    call_desc = ".".join(parts) + "()"

        if is_io and not _is_inside_try(node, ancestors):
            issues.append(Issue(
                file=filepath,
                line=node.lineno,
                severity="MEDIUM",
                title="Unguarded I/O",
                description=f"{call_desc} call not inside try/except",
                code_lines=_extract_code(lines, node.lineno),
            ))

    return issues


def _check_inconsistent_return(tree: ast.AST, lines: list[str], filepath: str) -> list[Issue]:
    """Find functions that sometimes return a value and sometimes return None implicitly."""
    issues = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        # Skip test functions
        if node.name.startswith("test_") or node.name.startswith("_test"):
            continue

        # Skip __init__, __del__, setters, etc. that don't return values
        if node.name in ("__init__", "__del__", "__setattr__", "__delattr__",
                         "setUp", "tearDown", "setUpClass", "tearDownClass"):
            continue

        returns: list[ast.Return] = []
        # Only look at returns directly in this function (not nested)
        for child in ast.walk(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child is not node:
                continue
            if isinstance(child, ast.Return):
                returns.append(child)

        if not returns:
            continue

        has_value_return = any(r.value is not None for r in returns)
        has_bare_return = any(r.value is None for r in returns)

        # Check for implicit None return (function body doesn't always end with return)
        # Simple heuristic: last statement is not a return or raise
        last_stmt = node.body[-1] if node.body else None
        implicit_none = (
            last_stmt is not None
            and not isinstance(last_stmt, (ast.Return, ast.Raise))
            and not (isinstance(last_stmt, ast.If) or isinstance(last_stmt, ast.Try))
        )

        if has_value_return and (has_bare_return or implicit_none):
            issues.append(Issue(
                file=filepath,
                line=node.lineno,
                severity="LOW",
                title="Inconsistent return",
                description=f"Function '{node.name}' sometimes returns a value and sometimes returns None",
                code_lines=_extract_code(lines, node.lineno, 1),
            ))

    return issues


def audit_python_file(filepath: str) -> list[Issue]:
    """Audit a single Python file for error handling issues."""
    if _is_test_file(filepath):
        return []

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
    except OSError:
        return []

    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        return []

    lines = _get_source_lines(source)
    issues: list[Issue] = []

    # Walk the AST looking for try/except blocks
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            for check in (_check_bare_except, _check_broad_except, _check_swallowed, _check_empty_body):
                issue = check(handler, lines, filepath)
                if issue is not None:
                    issues.append(issue)

    # Generic raise
    issues.extend(_check_generic_raise(tree, lines, filepath))

    # Unguarded I/O
    issues.extend(_check_unguarded_io(tree, lines, filepath))

    # Inconsistent return
    issues.extend(_check_inconsistent_return(tree, lines, filepath))

    # Sort by line number
    issues.sort(key=lambda i: i.line)
    return issues
