"""Core scanning logic -- walks the file tree and applies detection rules."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path

from secretscan.entropy import find_high_entropy_strings
from secretscan.patterns import MATLAB_PATTERNS, PATTERNS, SENSITIVE_VAR_KEYWORDS

# Extensions we care about.
SCANNABLE_EXTENSIONS: set[str] = {
    ".py", ".m",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env",
}

# Directories that are always skipped.
SKIP_DIRS: set[str] = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tox", ".mypy_cache"}

SEVERITY_ORDER = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}


@dataclass
class Finding:
    filepath: str
    line_number: int
    severity: str
    label: str
    matched_text: str

    @property
    def severity_rank(self) -> int:
        return SEVERITY_ORDER.get(self.severity, 0)

    def truncated_match(self, max_chars: int = 8) -> str:
        """Return the matched text truncated for safe display."""
        text = self.matched_text.strip()
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "..."


@dataclass
class ScanResult:
    files_scanned: int = 0
    findings: list[Finding] = field(default_factory=list)

    def count_by_severity(self, severity: str) -> int:
        return sum(1 for f in self.findings if f.severity == severity)


# ── Gitignore handling ────────────────────────────────────────────────────

def _load_gitignore_patterns(root: str) -> list[str]:
    """Load .gitignore patterns from *root*, returning raw glob strings."""
    gitignore = os.path.join(root, ".gitignore")
    if not os.path.isfile(gitignore):
        return []
    patterns: list[str] = []
    try:
        with open(gitignore, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                patterns.append(line)
    except OSError:
        pass
    return patterns


def _is_gitignored(rel_path: str, patterns: list[str]) -> bool:
    """Simple glob-based check against gitignore patterns."""
    # Normalise to forward slashes for matching.
    rel = rel_path.replace("\\", "/")
    parts = rel.split("/")
    for pat in patterns:
        pat_clean = pat.strip("/")
        # Match against full relative path.
        if fnmatch.fnmatch(rel, pat_clean):
            return True
        if fnmatch.fnmatch(rel, pat_clean + "/**"):
            return True
        # Match against any path component (directory name).
        for part in parts:
            if fnmatch.fnmatch(part, pat_clean):
                return True
    return False


# ── File-level scanning ──────────────────────────────────────────────────

def _is_binary(filepath: str, chunk_size: int = 8192) -> bool:
    """Heuristic: file is binary if the first chunk contains null bytes."""
    try:
        with open(filepath, "rb") as fh:
            chunk = fh.read(chunk_size)
            return b"\x00" in chunk
    except OSError:
        return True


def _scan_file(filepath: str) -> list[Finding]:
    """Apply pattern + entropy checks to a single file."""
    findings: list[Finding] = []
    ext = os.path.splitext(filepath)[1].lower()
    is_matlab = ext == ".m"

    try:
        with open(filepath, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return findings

    for line_idx, line in enumerate(lines, start=1):
        # --- Regex patterns ---
        for pattern, label, severity in PATTERNS:
            match = pattern.search(line)
            if match:
                findings.append(Finding(
                    filepath=filepath,
                    line_number=line_idx,
                    severity=severity,
                    label=label,
                    matched_text=match.group(0),
                ))

        # --- MATLAB-specific ---
        if is_matlab:
            for pattern, label, severity in MATLAB_PATTERNS:
                match = pattern.search(line)
                if match:
                    findings.append(Finding(
                        filepath=filepath,
                        line_number=line_idx,
                        severity=severity,
                        label=label,
                        matched_text=match.group(0),
                    ))

        # --- High-entropy string detection ---
        for value, ctx_keyword, _entropy, _ln in find_high_entropy_strings(line, line_idx, filepath):
            findings.append(Finding(
                filepath=filepath,
                line_number=line_idx,
                severity="MEDIUM",
                label=f"High-entropy string near '{ctx_keyword}'",
                matched_text=value,
            ))

    return findings


# ── Public API ────────────────────────────────────────────────────────────

def scan(path: str, min_severity: str = "LOW") -> ScanResult:
    """Scan *path* (file or directory) and return a `ScanResult`.

    Only findings at or above *min_severity* are included.
    """
    min_rank = SEVERITY_ORDER.get(min_severity.upper(), 1)
    result = ScanResult()
    target = Path(path).resolve()

    if target.is_file():
        files = [str(target)]
        gitignore_patterns: list[str] = []
        root = str(target.parent)
    elif target.is_dir():
        root = str(target)
        gitignore_patterns = _load_gitignore_patterns(root)
        files = _collect_files(root, gitignore_patterns)
    else:
        return result

    for fp in files:
        if _is_binary(fp):
            continue
        result.files_scanned += 1
        for finding in _scan_file(fp):
            if finding.severity_rank >= min_rank:
                result.findings.append(finding)

    # Sort: CRITICAL first, then by file + line.
    result.findings.sort(key=lambda f: (-f.severity_rank, f.filepath, f.line_number))
    return result


def _collect_files(root: str, gitignore_patterns: list[str]) -> list[str]:
    """Walk *root* and yield scannable file paths."""
    collected: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skipped directories in-place.
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS
            and not _is_gitignored(os.path.relpath(os.path.join(dirpath, d), root), gitignore_patterns)
        ]

        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in SCANNABLE_EXTENSIONS:
                continue
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, root)
            if _is_gitignored(rel, gitignore_patterns):
                continue
            collected.append(full)
    return collected
