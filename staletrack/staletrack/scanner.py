"""Core scanning logic for detecting TODOs, FIXMEs, HACKs, and commented-out code."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from staletrack.git_age import BlameCache, BlameInfo

# Directories to skip
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".tox", ".mypy_cache", ".pytest_cache"}

# Marker keywords (case-insensitive)
MARKER_KEYWORDS = ["TODO", "FIXME", "HACK", "XXX", "TEMP", "WORKAROUND"]
_MARKER_PATTERN = re.compile(
    r"\b(" + "|".join(MARKER_KEYWORDS) + r")\b[\s:]*(.*)$",
    re.IGNORECASE,
)

# Code-like patterns for Python commented-out code (after stripping # prefix)
_PY_CODE_PATTERNS = [
    re.compile(r"^\s*\w+\s*="),              # assignment: x = ...
    re.compile(r"^\s*\w+\s*\("),             # function call: foo(...)
    re.compile(r"^\s*(if|elif|else)\b"),      # control flow
    re.compile(r"^\s*(for|while)\b"),         # loops
    re.compile(r"^\s*(return|yield|raise)\b"),# return/yield/raise
    re.compile(r"^\s*(import|from)\b"),       # imports
    re.compile(r"^\s*(def|class)\b"),         # definitions
    re.compile(r"^\s*(try|except|finally)\b"),# exception handling
    re.compile(r"^\s*(with|as)\b"),           # context managers
    re.compile(r"^\s*(assert)\b"),            # assertions
    re.compile(r"^\s*(print|self\.)\b"),      # common patterns
    re.compile(r"^\s*\w+\.\w+\s*\("),        # method calls: obj.method(...)
    re.compile(r"^\s*(break|continue|pass)\b"),
]

# Code-like patterns for MATLAB commented-out code (after stripping % prefix)
_M_CODE_PATTERNS = [
    re.compile(r"^\s*\w+\s*="),              # assignment
    re.compile(r"^\s*\w+\s*\("),             # function call
    re.compile(r"^\s*(if|elseif|else)\b"),    # control flow
    re.compile(r"^\s*(for|while)\b"),         # loops
    re.compile(r"^\s*(return)\b"),            # return
    re.compile(r"^\s*(function)\b"),          # function def
    re.compile(r"^\s*(end)\b"),              # end blocks
    re.compile(r"^\s*(switch|case|otherwise)\b"),
    re.compile(r"^\s*(try|catch)\b"),
    re.compile(r"^\s*(error|warning|disp|fprintf)\s*\("),
    re.compile(r"^\s*\w+\.\w+"),             # property/method access
    re.compile(r"^\s*(break|continue)\b"),
    re.compile(r"^\s*(global|persistent)\b"),
]


@dataclass
class MarkerItem:
    """A TODO/FIXME/HACK marker found in source."""
    filepath: Path
    line_number: int
    keyword: str       # TODO, FIXME, HACK, etc.
    text: str          # the message after the keyword
    blame: BlameInfo | None = None
    item_type: str = "marker"


@dataclass
class CommentedCodeBlock:
    """A block of commented-out code."""
    filepath: Path
    start_line: int
    end_line: int
    lines: list[str]   # the raw commented lines
    blame: BlameInfo | None = None
    item_type: str = "commented_code"

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


@dataclass
class ScanResult:
    """Results from scanning a directory."""
    files_scanned: int = 0
    markers: list[MarkerItem] = field(default_factory=list)
    commented_blocks: list[CommentedCodeBlock] = field(default_factory=list)

    @property
    def todos(self) -> list[MarkerItem]:
        return [m for m in self.markers if m.keyword.upper() == "TODO"]

    @property
    def fixmes(self) -> list[MarkerItem]:
        return [m for m in self.markers if m.keyword.upper() == "FIXME"]

    @property
    def hacks(self) -> list[MarkerItem]:
        return [m for m in self.markers if m.keyword.upper() == "HACK"]

    @property
    def commented_line_count(self) -> int:
        return sum(b.line_count for b in self.commented_blocks)

    @property
    def all_items(self) -> list[MarkerItem | CommentedCodeBlock]:
        items: list[MarkerItem | CommentedCodeBlock] = []
        items.extend(self.markers)
        items.extend(self.commented_blocks)
        return items


def _collect_files(root: Path, py_only: bool = False, m_only: bool = False) -> list[Path]:
    """Recursively collect .py and .m files, skipping ignored directories."""
    files: list[Path] = []
    if root.is_file():
        if root.suffix in (".py", ".m"):
            files.append(root)
        return files

    for item in sorted(root.rglob("*")):
        # Skip ignored directories
        if any(part in SKIP_DIRS for part in item.parts):
            continue
        if not item.is_file():
            continue
        if py_only and item.suffix != ".py":
            continue
        if m_only and item.suffix != ".m":
            continue
        if item.suffix in (".py", ".m"):
            files.append(item)
    return files


def _get_comment_prefix(filepath: Path) -> str:
    """Return the comment prefix for the file type."""
    if filepath.suffix == ".m":
        return "%"
    return "#"


def _get_code_patterns(filepath: Path) -> list[re.Pattern]:
    """Return code-like patterns for the file type."""
    if filepath.suffix == ".m":
        return _M_CODE_PATTERNS
    return _PY_CODE_PATTERNS


def _is_comment_line(line: str, prefix: str) -> bool:
    """Check if a line is a single-line comment (ignoring leading whitespace)."""
    stripped = line.strip()
    return stripped.startswith(prefix) and not stripped.startswith(prefix * 2 + "!")


def _strip_comment_prefix(line: str, prefix: str) -> str:
    """Remove the comment prefix from a line."""
    stripped = line.strip()
    if stripped.startswith(prefix):
        return stripped[len(prefix):]
    return stripped


def _looks_like_code(content: str, patterns: list[re.Pattern]) -> bool:
    """Check if a comment's content looks like code."""
    for pattern in patterns:
        if pattern.search(content):
            return True
    return False


def _scan_markers(lines: list[str], filepath: Path, blame_cache: BlameCache) -> list[MarkerItem]:
    """Scan lines for marker keywords in comments and multi-line strings."""
    results: list[MarkerItem] = []
    prefix = _get_comment_prefix(filepath)
    in_multiline: str | None = None  # tracks triple-quote delimiter

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Track Python multi-line string state
        if filepath.suffix == ".py":
            if in_multiline is not None:
                # We are inside a multi-line string
                if in_multiline in line:
                    in_multiline = None  # closing delimiter on this line
                # Check for markers inside the multi-line string
                match = _MARKER_PATTERN.search(stripped)
                if match:
                    keyword = match.group(1).upper()
                    text = match.group(2).strip()
                    blame = blame_cache.get_blame(filepath, i)
                    results.append(MarkerItem(
                        filepath=filepath,
                        line_number=i,
                        keyword=keyword,
                        text=text,
                        blame=blame,
                    ))
                continue
            else:
                # Check if a multi-line string opens on this line
                for delim in ('"""', "'''"):
                    count = stripped.count(delim)
                    if count == 1:
                        # Opens but does not close on same line
                        in_multiline = delim
                        break
                    # count >= 2 means opens and closes on same line (single-line docstring)

        # Check single-line comments
        if stripped.startswith(prefix):
            match = _MARKER_PATTERN.search(stripped)
            if match:
                keyword = match.group(1).upper()
                text = match.group(2).strip()
                blame = blame_cache.get_blame(filepath, i)
                results.append(MarkerItem(
                    filepath=filepath,
                    line_number=i,
                    keyword=keyword,
                    text=text,
                    blame=blame,
                ))

    return results


def _scan_commented_code(lines: list[str], filepath: Path, blame_cache: BlameCache) -> list[CommentedCodeBlock]:
    """Scan for blocks of 3+ consecutive commented lines that look like code."""
    results: list[CommentedCodeBlock] = []
    prefix = _get_comment_prefix(filepath)
    code_patterns = _get_code_patterns(filepath)

    i = 0
    while i < len(lines):
        # Find start of a consecutive comment block
        if not _is_comment_line(lines[i], prefix):
            i += 1
            continue

        # Collect consecutive comment lines
        block_start = i
        block_lines: list[str] = []
        while i < len(lines) and _is_comment_line(lines[i], prefix):
            block_lines.append(lines[i])
            i += 1

        # Need at least 3 consecutive comment lines
        if len(block_lines) < 3:
            continue

        # Check if >50% of lines look like code
        code_line_count = 0
        for bline in block_lines:
            content = _strip_comment_prefix(bline, prefix)
            # Skip empty comment lines in the ratio calculation
            if not content.strip():
                continue
            # Skip lines that contain marker keywords (those are TODOs, not code)
            if _MARKER_PATTERN.search(content):
                continue
            if _looks_like_code(content, code_patterns):
                code_line_count += 1

        # Count non-empty, non-marker lines for the ratio
        non_empty = sum(
            1 for bl in block_lines
            if _strip_comment_prefix(bl, prefix).strip()
            and not _MARKER_PATTERN.search(_strip_comment_prefix(bl, prefix))
        )

        if non_empty > 0 and code_line_count / non_empty > 0.5:
            start_line = block_start + 1  # 1-indexed
            end_line = block_start + len(block_lines)
            blame = blame_cache.get_blame_for_range(filepath, start_line, end_line)
            results.append(CommentedCodeBlock(
                filepath=filepath,
                start_line=start_line,
                end_line=end_line,
                lines=block_lines,
                blame=blame,
            ))

    return results


def scan(
    root: Path,
    py_only: bool = False,
    m_only: bool = False,
    todos_only: bool = False,
    commented_code_only: bool = False,
) -> ScanResult:
    """Scan a directory tree for stale markers and commented-out code.

    Args:
        root: Directory or file to scan.
        py_only: Only scan .py files.
        m_only: Only scan .m files.
        todos_only: Only report marker items (TODO/FIXME/HACK/etc).
        commented_code_only: Only report commented-out code blocks.

    Returns:
        ScanResult with all findings.
    """
    root = root.resolve()
    files = _collect_files(root, py_only=py_only, m_only=m_only)
    blame_cache = BlameCache(root if root.is_dir() else root.parent)

    result = ScanResult(files_scanned=len(files))

    for filepath in files:
        try:
            text = filepath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        file_lines = text.splitlines()

        if not commented_code_only:
            result.markers.extend(_scan_markers(file_lines, filepath, blame_cache))

        if not todos_only:
            result.commented_blocks.extend(
                _scan_commented_code(file_lines, filepath, blame_cache)
            )

    return result
