"""Python dependency extraction using the ast module."""

from __future__ import annotations

import ast
from pathlib import Path


def extract_python_deps(file_path: Path, project_root: Path) -> list[dict]:
    """Extract dependencies from a Python file.

    Returns a list of dicts with keys:
        - source: str (absolute path of the importing file)
        - target: str (absolute path of the imported file)
        - type: str ("import" | "from_import" | "dynamic_import" | "relative_import")
        - raw: str (the raw import string as written)
    """
    try:
        source_text = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source_text, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return []

    deps: list[dict] = []
    source = str(file_path)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolved = _resolve_module(alias.name, project_root)
                if resolved:
                    deps.append({
                        "source": source,
                        "target": str(resolved),
                        "type": "import",
                        "raw": alias.name,
                    })

        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # Relative import
                resolved = _resolve_relative_import(
                    file_path, node.module, node.level, node.names, project_root
                )
                for r in resolved:
                    deps.append({
                        "source": source,
                        "target": str(r["path"]),
                        "type": "relative_import",
                        "raw": r["raw"],
                    })
            elif node.module:
                resolved = _resolve_module(node.module, project_root)
                if resolved:
                    deps.append({
                        "source": source,
                        "target": str(resolved),
                        "type": "from_import",
                        "raw": node.module,
                    })
                # Also check if any imported name is a submodule
                for alias in node.names:
                    sub = _resolve_module(f"{node.module}.{alias.name}", project_root)
                    if sub:
                        deps.append({
                            "source": source,
                            "target": str(sub),
                            "type": "from_import",
                            "raw": f"{node.module}.{alias.name}",
                        })

        elif isinstance(node, ast.Call):
            # Detect importlib.import_module('x')
            raw = _extract_dynamic_import(node)
            if raw:
                resolved = _resolve_module(raw, project_root)
                if resolved:
                    deps.append({
                        "source": source,
                        "target": str(resolved),
                        "type": "dynamic_import",
                        "raw": raw,
                    })

    return deps


def _resolve_module(module_name: str, project_root: Path) -> Path | None:
    """Resolve a dotted module name to a file path within the project."""
    parts = module_name.split(".")
    # Try as a package (directory with __init__.py)
    pkg_path = project_root.joinpath(*parts, "__init__.py")
    if pkg_path.is_file():
        return pkg_path
    # Try as a module file
    mod_path = project_root.joinpath(*parts[:-1], parts[-1] + ".py") if parts else None
    if mod_path and mod_path.is_file():
        return mod_path
    # Try with all parts as path
    mod_path2 = project_root.joinpath(*parts).with_suffix(".py")
    if mod_path2.is_file():
        return mod_path2
    return None


def _resolve_relative_import(
    file_path: Path,
    module: str | None,
    level: int,
    names: list[ast.alias],
    project_root: Path,
) -> list[dict]:
    """Resolve a relative import to file paths."""
    results: list[dict] = []
    # Go up `level` directories from the current file's directory
    base = file_path.parent
    for _ in range(level - 1):
        base = base.parent

    if module:
        parts = module.split(".")
        target_dir = base.joinpath(*parts)
        # Could be a package
        init = target_dir / "__init__.py"
        if init.is_file():
            raw_str = "." * level + module
            results.append({"path": init, "raw": raw_str})
        # Could be a module
        target_file = base.joinpath(*parts[:-1], parts[-1] + ".py")
        if target_file.is_file():
            raw_str = "." * level + module
            results.append({"path": target_file, "raw": raw_str})
    else:
        # from . import name1, name2
        for alias in names:
            target_file = base / (alias.name + ".py")
            if target_file.is_file():
                raw_str = "." * level + alias.name
                results.append({"path": target_file, "raw": raw_str})
            # Could be a package
            init = base / alias.name / "__init__.py"
            if init.is_file():
                raw_str = "." * level + alias.name
                results.append({"path": init, "raw": raw_str})

    return results


def _extract_dynamic_import(node: ast.Call) -> str | None:
    """Extract module name from importlib.import_module('x') calls."""
    func = node.func
    # importlib.import_module('x')
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "import_module"
        and isinstance(func.value, ast.Name)
        and func.value.id == "importlib"
    ):
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            return node.args[0].value
    # Could also be: from importlib import import_module; import_module('x')
    if isinstance(func, ast.Name) and func.id == "import_module":
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            return node.args[0].value
    return None
