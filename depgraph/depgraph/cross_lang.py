"""Cross-language dependency detection (MATLAB -> Python)."""

from __future__ import annotations

import re
from pathlib import Path


# py.module_name.func() or py.module_name.submodule.func()
_RE_PY_DOT = re.compile(
    r"""\bpy\.([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)""",
)

# pyrunfile('script.py', ...) or pyrunfile("script.py", ...)
_RE_PYRUNFILE = re.compile(
    r"""\bpyrunfile\s*\(\s*['"]([^'"]+\.py)['"]\s*""",
)

# pyrun("import foo", ...) or pyrun('import foo', ...)
_RE_PYRUN_IMPORT = re.compile(
    r"""\bpyrun\s*\(\s*['"]import\s+([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)['"]""",
)

# pyrun("from foo import bar", ...)
_RE_PYRUN_FROM_IMPORT = re.compile(
    r"""\bpyrun\s*\(\s*['"]from\s+([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)\s+import""",
)


def extract_cross_lang_deps(file_path: Path, project_root: Path) -> list[dict]:
    """Extract cross-language dependencies from a MATLAB file calling Python.

    Returns a list of dicts with keys:
        - source: str (absolute path of the MATLAB file)
        - target: str (absolute path of the Python file, or module name if unresolved)
        - type: str ("py_dot" | "pyrunfile" | "pyrun_import")
        - raw: str (the raw reference as written)
        - cross_language: True
    """
    if file_path.suffix != ".m":
        return []

    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    deps: list[dict] = []
    source = str(file_path)
    seen: set[str] = set()

    # py.module_name.func()
    for match in _RE_PY_DOT.finditer(text):
        dotted = match.group(1)
        # The first part is the module name (or could be multi-level)
        # e.g., py.numpy -> module = "numpy"
        # e.g., py.scipy.signal -> could be scipy/signal.py or scipy.py
        module_parts = dotted.split(".")
        raw = f"py.{dotted}"
        # Try resolving progressively shorter prefixes
        resolved = _resolve_python_module(module_parts, project_root)
        target = str(resolved) if resolved else dotted
        if target not in seen:
            seen.add(target)
            deps.append({
                "source": source,
                "target": target,
                "type": "py_dot",
                "raw": raw,
                "cross_language": True,
            })

    # pyrunfile('script.py')
    for match in _RE_PYRUNFILE.finditer(text):
        script = match.group(1)
        resolved = _resolve_script(script, file_path.parent, project_root)
        target = str(resolved) if resolved else script
        raw = f"pyrunfile('{script}')"
        if target not in seen:
            seen.add(target)
            deps.append({
                "source": source,
                "target": target,
                "type": "pyrunfile",
                "raw": raw,
                "cross_language": True,
            })

    # pyrun("import foo")
    for match in _RE_PYRUN_IMPORT.finditer(text):
        module = match.group(1)
        parts = module.split(".")
        resolved = _resolve_python_module(parts, project_root)
        target = str(resolved) if resolved else module
        raw = f"pyrun('import {module}')"
        if target not in seen:
            seen.add(target)
            deps.append({
                "source": source,
                "target": target,
                "type": "pyrun_import",
                "raw": raw,
                "cross_language": True,
            })

    # pyrun("from foo import bar")
    for match in _RE_PYRUN_FROM_IMPORT.finditer(text):
        module = match.group(1)
        parts = module.split(".")
        resolved = _resolve_python_module(parts, project_root)
        target = str(resolved) if resolved else module
        raw = f"pyrun('from {module} import ...')"
        if target not in seen:
            seen.add(target)
            deps.append({
                "source": source,
                "target": target,
                "type": "pyrun_import",
                "raw": raw,
                "cross_language": True,
            })

    return deps


def _resolve_python_module(parts: list[str], project_root: Path) -> Path | None:
    """Try to resolve a Python module name to a file in the project."""
    # Try the full path first, then progressively shorter
    for length in range(len(parts), 0, -1):
        sub = parts[:length]
        # As a .py file
        candidate = project_root.joinpath(*sub[:-1], sub[-1] + ".py")
        if candidate.is_file():
            return candidate
        # As a package
        candidate = project_root.joinpath(*sub, "__init__.py")
        if candidate.is_file():
            return candidate
    return None


def _resolve_script(script: str, current_dir: Path, project_root: Path) -> Path | None:
    """Resolve a Python script path."""
    # Relative to the MATLAB file
    candidate = current_dir / script
    if candidate.is_file():
        return candidate
    # Relative to project root
    candidate = project_root / script
    if candidate.is_file():
        return candidate
    return None
