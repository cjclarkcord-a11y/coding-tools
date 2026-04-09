"""Extract references from Python source files using the ast module."""

from __future__ import annotations

import ast
import re
from pathlib import Path


def extract_python_refs(file_path: Path, all_py_files: dict[str, Path]) -> set[Path]:
    """Parse a Python file and return the set of project files it references.

    Args:
        file_path: The Python file to analyse.
        all_py_files: Mapping of module-style names (dot-separated, no .py)
                      to their resolved Path objects for every Python file in
                      the project.  For example:
                          "utils.helpers" -> Path(".../utils/helpers.py")
                          "utils"         -> Path(".../utils/__init__.py")

    Returns:
        A set of Path objects that *file_path* imports / references.
    """
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()

    refs: set[Path] = set()

    # --- AST-based import extraction ---
    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        # Fall back to regex if the file has syntax errors
        return _regex_fallback(source, all_py_files)

    for node in ast.walk(tree):
        # import foo, import foo.bar
        if isinstance(node, ast.Import):
            for alias in node.names:
                _resolve_module(alias.name, all_py_files, refs)

        # from foo import bar, from foo.bar import baz
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                _resolve_module(node.module, all_py_files, refs)
                # "from pkg import submod" -- submod might be a file
                for alias in node.names:
                    _resolve_module(f"{node.module}.{alias.name}", all_py_files, refs)

        # importlib.import_module("foo.bar") / __import__("foo")
        elif isinstance(node, ast.Call):
            func_name = _call_name(node)
            if func_name in ("importlib.import_module", "__import__", "import_module"):
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    _resolve_module(node.args[0].value, all_py_files, refs)

    # --- String-literal dynamic references (exec/eval patterns) ---
    refs |= _string_refs(source, all_py_files)

    return refs


def _resolve_module(module_name: str, all_py_files: dict[str, Path], refs: set[Path]) -> None:
    """Try to resolve a dotted module name to one or more project files."""
    # Exact match: "utils.helpers" -> utils/helpers.py
    if module_name in all_py_files:
        refs.add(all_py_files[module_name])
        return

    # Package match: "utils" might mean utils/__init__.py
    init_key = f"{module_name}.__init__"
    if init_key in all_py_files:
        refs.add(all_py_files[init_key])

    # Prefix match: "import pkg" should also mark pkg/__init__.py
    # and "import pkg.sub" should mark pkg/sub.py or pkg/sub/__init__.py
    parts = module_name.split(".")
    for i in range(len(parts), 0, -1):
        candidate = ".".join(parts[:i])
        if candidate in all_py_files:
            refs.add(all_py_files[candidate])
            break
        init_candidate = f"{candidate}.__init__"
        if init_candidate in all_py_files:
            refs.add(all_py_files[init_candidate])
            break


def _call_name(node: ast.Call) -> str:
    """Return dotted name for a Call node's function, e.g. 'importlib.import_module'."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        parts: list[str] = [node.func.attr]
        val = node.func.value
        while isinstance(val, ast.Attribute):
            parts.append(val.attr)
            val = val.value
        if isinstance(val, ast.Name):
            parts.append(val.id)
        return ".".join(reversed(parts))
    return ""


def _string_refs(source: str, all_py_files: dict[str, Path]) -> set[Path]:
    """Find references to project files in string literals (loose heuristic)."""
    refs: set[Path] = set()
    # Match quoted strings that look like module paths or file names
    for match in re.finditer(r"""['"]([a-zA-Z_][\w./]*)['"]""", source):
        token = match.group(1)
        # Could be a dotted module path
        if "." in token and not token.endswith(".py"):
            mod = token.replace("/", ".")
            if mod in all_py_files:
                refs.add(all_py_files[mod])
        # Could be a file path ending in .py
        if token.endswith(".py"):
            stem = token.replace("/", ".").replace("\\", ".").removesuffix(".py")
            if stem in all_py_files:
                refs.add(all_py_files[stem])
            # Also try just the filename stem
            basename = Path(token).stem
            if basename in all_py_files:
                refs.add(all_py_files[basename])
    return refs


def _regex_fallback(source: str, all_py_files: dict[str, Path]) -> set[Path]:
    """Regex fallback for files that fail to parse with ast."""
    refs: set[Path] = set()

    # import x / import x.y
    for m in re.finditer(r"^\s*import\s+([\w.]+)", source, re.MULTILINE):
        _resolve_module(m.group(1), all_py_files, refs)

    # from x import y
    for m in re.finditer(r"^\s*from\s+([\w.]+)\s+import", source, re.MULTILINE):
        _resolve_module(m.group(1), all_py_files, refs)

    return refs


def build_python_file_index(py_files: list[Path], root: Path) -> dict[str, Path]:
    """Build a mapping from dotted-module-name to file path for all Python files.

    For ``root/pkg/sub/mod.py`` we generate keys like:
        - "pkg.sub.mod"
        - "mod"  (basename shortcut)
    """
    index: dict[str, Path] = {}
    for fp in py_files:
        try:
            rel = fp.relative_to(root)
        except ValueError:
            continue

        parts = list(rel.parts)
        # Remove .py extension from the last part
        parts[-1] = parts[-1].removesuffix(".py")

        dotted = ".".join(parts)
        index[dotted] = fp

        # Also register the bare file stem for short imports
        stem = fp.stem
        if stem not in index:
            index[stem] = fp

    return index
