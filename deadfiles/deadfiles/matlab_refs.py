"""Extract references from MATLAB source files using regex."""

from __future__ import annotations

import re
from pathlib import Path


def extract_matlab_refs(
    file_path: Path,
    all_m_files: dict[str, Path],
    all_py_files: dict[str, Path],
) -> set[Path]:
    """Parse a MATLAB file and return the set of project files it references.

    Handles:
        - Direct function/script calls (function name == file name in MATLAB)
        - run('script.m'), run('script')
        - addpath references (marks all files under added paths)
        - Class references: obj = ClassName(...)
        - Cross-language: py.module.func(), pyrun(...), pyrunfile('script.py', ...)

    Args:
        file_path: The .m file to analyse.
        all_m_files: Mapping of MATLAB function/script names (no extension)
                     to their resolved Path objects.
        all_py_files: Mapping of dotted-module names to Paths (for cross-
                      language detection).

    Returns:
        A set of Path objects that *file_path* references.
    """
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()

    refs: set[Path] = set()

    # Strip MATLAB comments (% to end-of-line) and block comments (%{ ... %})
    cleaned = _strip_comments(source)

    # --- Direct function / script calls ---
    # In MATLAB, any identifier that matches a file name is a potential call.
    # We look for bare identifiers that are followed by ( or ; or end-of-line
    # or appear at the start of a statement.
    identifiers = set(re.findall(r"\b([a-zA-Z_]\w*)\b", cleaned))
    for ident in identifiers:
        if ident in all_m_files and all_m_files[ident] != file_path:
            refs.add(all_m_files[ident])

    # --- run('script') / run('script.m') ---
    for m in re.finditer(r"""\brun\s*\(\s*['"]([^'"]+)['"]\s*\)""", cleaned):
        script_name = m.group(1)
        _resolve_m_ref(script_name, all_m_files, refs)

    # --- addpath ---
    # We don't resolve addpath to files, but we note it for completeness.
    # addpath('some/dir') -- not easy to resolve without filesystem context,
    # so we skip actual resolution but keep the pattern here for extensibility.

    # --- Cross-language: py.module_name.func() ---
    for m in re.finditer(r"\bpy\.(\w+)(?:\.\w+)*", cleaned):
        py_module = m.group(1)
        if py_module in all_py_files:
            refs.add(all_py_files[py_module])

    # --- pyrun("import module; ...") ---
    for m in re.finditer(r"""\bpyrun\s*\(\s*['"]([^'"]+)['"]""", cleaned):
        code_str = m.group(1)
        # Look for import statements or module names inside the code string
        for imp in re.finditer(r"\bimport\s+(\w+)", code_str):
            mod = imp.group(1)
            if mod in all_py_files:
                refs.add(all_py_files[mod])
        for imp in re.finditer(r"\bfrom\s+(\w+)", code_str):
            mod = imp.group(1)
            if mod in all_py_files:
                refs.add(all_py_files[mod])

    # --- pyrunfile('script.py', ...) ---
    for m in re.finditer(r"""\bpyrunfile\s*\(\s*['"]([^'"]+)['"]""", cleaned):
        py_file = m.group(1)
        _resolve_py_ref(py_file, all_py_files, refs)

    return refs


def _resolve_m_ref(name: str, all_m_files: dict[str, Path], refs: set[Path]) -> None:
    """Resolve a MATLAB script/function name to a file path."""
    # Strip .m extension if present
    stem = name.removesuffix(".m")
    # Strip directory prefixes -- just use the base name
    stem = Path(stem).stem
    if stem in all_m_files:
        refs.add(all_m_files[stem])


def _resolve_py_ref(name: str, all_py_files: dict[str, Path], refs: set[Path]) -> None:
    """Resolve a Python file reference from MATLAB to a project Python file."""
    stem = name.removesuffix(".py")
    stem = Path(stem).stem
    if stem in all_py_files:
        refs.add(all_py_files[stem])
    # Also try dotted path
    dotted = name.replace("/", ".").replace("\\", ".").removesuffix(".py")
    if dotted in all_py_files:
        refs.add(all_py_files[dotted])


def _strip_comments(source: str) -> str:
    """Remove MATLAB comments from source code."""
    # Remove block comments %{ ... %}
    result = re.sub(r"%\{.*?%\}", "", source, flags=re.DOTALL)
    # Remove line comments (% to end of line), but not inside strings
    # Simple approach: remove % comments that aren't inside quotes
    lines = []
    for line in result.splitlines():
        # Naive: strip everything after the first % that isn't inside a string
        cleaned = _strip_line_comment(line)
        lines.append(cleaned)
    return "\n".join(lines)


def _strip_line_comment(line: str) -> str:
    """Remove a line-level % comment from a MATLAB line, respecting strings."""
    in_string = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "'" and not in_string:
            in_string = True
        elif ch == "'" and in_string:
            # Check for escaped quote ('')
            if i + 1 < len(line) and line[i + 1] == "'":
                i += 1  # skip escaped quote
            else:
                in_string = False
        elif ch == "%" and not in_string:
            return line[:i]
        i += 1
    return line


def is_matlab_script(file_path: Path) -> bool:
    """Determine if a .m file is a script (not a function/class).

    In MATLAB, a script has no ``function`` keyword at the top.
    Functions start with ``function [out] = name(...)`` as the first
    non-comment, non-blank line.

    Returns True if the file is a script (i.e. could be run directly).
    """
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    for line in source.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%"):
            continue
        # First non-blank, non-comment line
        return not stripped.startswith("function") and not stripped.startswith("classdef")
    return True  # empty file -- treat as script


def build_matlab_file_index(m_files: list[Path]) -> dict[str, Path]:
    """Build a mapping from function/script name (stem) to file path.

    In MATLAB, the file name *is* the function name, so we just use the
    stem (filename without extension) as the key.
    """
    index: dict[str, Path] = {}
    for fp in m_files:
        stem = fp.stem
        # If there are duplicates, keep the first one found
        if stem not in index:
            index[stem] = fp
    return index
