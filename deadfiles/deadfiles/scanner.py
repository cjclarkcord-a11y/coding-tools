"""Core scanning logic -- discover files, build reference graph, find dead files."""

from __future__ import annotations

from pathlib import Path

from deadfiles.python_refs import build_python_file_index, extract_python_refs
from deadfiles.matlab_refs import (
    build_matlab_file_index,
    extract_matlab_refs,
    is_matlab_script,
)

# Directories to always skip
SKIP_DIRS: set[str] = {
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    ".env",
    "node_modules",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    "*.egg-info",
}

# Python files that are considered entry points (never reported as dead)
PY_ENTRY_POINTS: set[str] = {
    "__init__",
    "__main__",
    "setup",
    "conftest",
    "manage",
    "wsgi",
    "asgi",
    "fabfile",
    "tasks",
    "noxfile",
    "SConstruct",
    "SConscript",
}

# Filename prefixes that mark test files
TEST_PREFIXES = ("test_", "tests_")
TEST_SUFFIXES = ("_test",)


def discover_files(
    root: Path,
    *,
    py_only: bool = False,
    m_only: bool = False,
) -> tuple[list[Path], list[Path]]:
    """Walk *root* and return (python_files, matlab_files).

    Skips directories in SKIP_DIRS.
    """
    py_files: list[Path] = []
    m_files: list[Path] = []

    for item in _walk(root):
        if not py_only and item.suffix == ".m":
            m_files.append(item)
        if not m_only and item.suffix == ".py":
            py_files.append(item)

    return py_files, m_files


def _walk(root: Path):
    """Recursively yield files, skipping ignored directories."""
    try:
        entries = sorted(root.iterdir())
    except PermissionError:
        return

    for entry in entries:
        if entry.is_dir():
            name = entry.name
            if name in SKIP_DIRS or any(
                name.endswith(s) for s in (".egg-info",)
            ):
                continue
            yield from _walk(entry)
        elif entry.is_file():
            yield entry


def is_entry_point(file_path: Path, *, include_tests: bool = False) -> bool:
    """Return True if *file_path* should never be reported as dead."""
    name = file_path.stem

    if file_path.suffix == ".py":
        # Well-known entry points
        if name in PY_ENTRY_POINTS:
            return True
        # Test files
        if not include_tests:
            if any(name.startswith(p) for p in TEST_PREFIXES):
                return True
            if any(name.endswith(s) for s in TEST_SUFFIXES):
                return True
        # setup.cfg companion
        if name == "setup" and file_path.suffix == ".py":
            return True

    if file_path.suffix == ".m":
        # MATLAB scripts (no function declaration) can be run directly
        if is_matlab_script(file_path):
            return True

    return False


def scan(
    root: Path,
    *,
    py_only: bool = False,
    m_only: bool = False,
    include_tests: bool = False,
) -> ScanResult:
    """Run the full scan and return results."""
    root = root.resolve()
    py_files, m_files = discover_files(root, py_only=py_only, m_only=m_only)

    # Build indexes
    py_index = build_python_file_index(py_files, root)
    m_index = build_matlab_file_index(m_files)

    # Build reference graph: file -> set of files it references
    ref_graph: dict[Path, set[Path]] = {}

    for fp in py_files:
        ref_graph[fp] = extract_python_refs(fp, py_index)

    for fp in m_files:
        ref_graph[fp] = extract_matlab_refs(fp, m_index, py_index)

    # Compute the set of files that are referenced by at least one other file
    referenced: set[Path] = set()
    for src, targets in ref_graph.items():
        for t in targets:
            if t != src:  # self-references don't count
                referenced.add(t)

    # Determine dead files
    all_files = py_files + m_files
    entry_points: set[Path] = set()
    dead_files: list[Path] = []

    for fp in all_files:
        if is_entry_point(fp, include_tests=include_tests):
            entry_points.add(fp)
        elif fp not in referenced:
            dead_files.append(fp)

    # Sort dead files by relative path for stable output
    dead_files.sort(key=lambda p: p.relative_to(root))

    return ScanResult(
        root=root,
        all_files=all_files,
        py_files=py_files,
        m_files=m_files,
        ref_graph=ref_graph,
        referenced=referenced,
        entry_points=entry_points,
        dead_files=dead_files,
    )


class ScanResult:
    """Container for scan results."""

    __slots__ = (
        "root",
        "all_files",
        "py_files",
        "m_files",
        "ref_graph",
        "referenced",
        "entry_points",
        "dead_files",
    )

    def __init__(
        self,
        *,
        root: Path,
        all_files: list[Path],
        py_files: list[Path],
        m_files: list[Path],
        ref_graph: dict[Path, set[Path]],
        referenced: set[Path],
        entry_points: set[Path],
        dead_files: list[Path],
    ):
        self.root = root
        self.all_files = all_files
        self.py_files = py_files
        self.m_files = m_files
        self.ref_graph = ref_graph
        self.referenced = referenced
        self.entry_points = entry_points
        self.dead_files = dead_files

    @property
    def total_scanned(self) -> int:
        return len(self.all_files)

    @property
    def total_referenced(self) -> int:
        return len(self.referenced)

    @property
    def total_dead(self) -> int:
        return len(self.dead_files)

    def reference_count(self, file_path: Path) -> int:
        """How many other files reference *file_path*."""
        count = 0
        for src, targets in self.ref_graph.items():
            if src != file_path and file_path in targets:
                count += 1
        return count

    def to_dict(self) -> dict:
        """Serialisable dictionary for JSON output."""
        return {
            "root": str(self.root),
            "files_scanned": self.total_scanned,
            "referenced": self.total_referenced,
            "dead_count": self.total_dead,
            "dead_files": [
                {
                    "path": str(fp.relative_to(self.root)),
                    "references": self.reference_count(fp),
                }
                for fp in self.dead_files
            ],
            "entry_points": [
                str(fp.relative_to(self.root)) for fp in sorted(self.entry_points)
            ],
        }
