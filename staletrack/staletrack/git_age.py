"""Git blame integration for dating flagged items."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BlameInfo:
    """Blame information for a single line."""
    author: str
    timestamp: int  # unix epoch
    age_seconds: int
    age_text: str
    staleness: str  # FRESH, AGING, STALE, ANCIENT


# Staleness thresholds in seconds
_30_DAYS = 30 * 86400
_180_DAYS = 180 * 86400
_1_YEAR = 365 * 86400


def classify_staleness(age_seconds: int) -> str:
    """Classify age into a staleness category."""
    if age_seconds < _30_DAYS:
        return "FRESH"
    elif age_seconds < _180_DAYS:
        return "AGING"
    elif age_seconds < _1_YEAR:
        return "STALE"
    else:
        return "ANCIENT"


def format_age(age_seconds: int) -> str:
    """Convert seconds to human-readable age string."""
    if age_seconds < 0:
        return "just now"

    minutes = age_seconds // 60
    hours = age_seconds // 3600
    days = age_seconds // 86400
    months = age_seconds // (30 * 86400)
    years = age_seconds // (365 * 86400)

    if days == 0:
        if hours == 0:
            if minutes <= 1:
                return "just now"
            return f"{minutes} minutes ago"
        if hours == 1:
            return "1 hour ago"
        return f"{hours} hours ago"
    if days == 1:
        return "1 day ago"
    if days < 30:
        return f"{days} days ago"
    if months == 1:
        return "1 month ago"
    if months < 12:
        return f"{months} months ago"
    if years == 1:
        return "1 year ago"
    return f"{years} years ago"


def _is_git_repo(path: Path) -> bool:
    """Check whether path is inside a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _get_git_root(path: Path) -> Path | None:
    """Get the root of the git repository containing path."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


class BlameCache:
    """Cache git blame results per file. Runs blame once per file."""

    def __init__(self, scan_root: Path):
        self.scan_root = scan_root
        self._cache: dict[Path, dict[int, BlameInfo] | None] = {}
        self._is_git = _is_git_repo(scan_root)
        self._git_root = _get_git_root(scan_root) if self._is_git else None
        self._now = int(time.time())

    @property
    def is_git_repo(self) -> bool:
        return self._is_git

    def get_blame(self, filepath: Path, line_number: int) -> BlameInfo | None:
        """Get blame info for a specific line in a file.

        Returns None if not a git repo or blame fails.
        """
        if not self._is_git:
            return None

        if filepath not in self._cache:
            self._cache[filepath] = self._run_blame(filepath)

        file_blame = self._cache[filepath]
        if file_blame is None:
            return None

        return file_blame.get(line_number)

    def get_blame_for_range(self, filepath: Path, start: int, end: int) -> BlameInfo | None:
        """Get blame info for a range of lines (uses the oldest line)."""
        if not self._is_git:
            return None

        if filepath not in self._cache:
            self._cache[filepath] = self._run_blame(filepath)

        file_blame = self._cache[filepath]
        if file_blame is None:
            return None

        oldest: BlameInfo | None = None
        for line_no in range(start, end + 1):
            info = file_blame.get(line_no)
            if info is not None:
                if oldest is None or info.age_seconds > oldest.age_seconds:
                    oldest = info

        return oldest

    def _run_blame(self, filepath: Path) -> dict[int, BlameInfo] | None:
        """Run git blame -p on a file and parse porcelain output."""
        cwd = self._git_root or self.scan_root
        try:
            result = subprocess.run(
                ["git", "blame", "-p", str(filepath)],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return None
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None

        return self._parse_porcelain(result.stdout)

    def _parse_porcelain(self, output: str) -> dict[int, BlameInfo]:
        """Parse git blame porcelain output into per-line BlameInfo."""
        result: dict[int, BlameInfo] = {}
        lines = output.split("\n")
        i = 0
        current_author = "unknown"
        current_timestamp = 0
        current_line_no = 0

        while i < len(lines):
            line = lines[i]

            # Header line: <sha> <orig_line> <final_line> [<num_lines>]
            parts = line.split()
            if len(parts) >= 3 and len(parts[0]) == 40:
                try:
                    current_line_no = int(parts[2])
                except ValueError:
                    pass
                i += 1
                continue

            if line.startswith("author "):
                current_author = line[7:].strip()
            elif line.startswith("author-time "):
                try:
                    current_timestamp = int(line[12:].strip())
                except ValueError:
                    current_timestamp = 0
            elif line.startswith("\t"):
                # This is the actual source line -- record the blame entry
                age_seconds = max(0, self._now - current_timestamp)
                result[current_line_no] = BlameInfo(
                    author=current_author,
                    timestamp=current_timestamp,
                    age_seconds=age_seconds,
                    age_text=format_age(age_seconds),
                    staleness=classify_staleness(age_seconds),
                )

            i += 1

        return result
