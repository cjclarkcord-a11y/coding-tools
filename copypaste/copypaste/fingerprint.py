"""Block fingerprinting: split normalized code into overlapping blocks and hash them."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Block:
    """A contiguous block of normalized code from a single file."""
    filepath: str
    start_line: int   # original source line number (1-based)
    end_line: int      # inclusive
    normalized_lines: tuple[str, ...]
    digest: str        # MD5 hex digest of the joined normalized text


def _hash_lines(lines: tuple[str, ...]) -> str:
    """Return MD5 hex digest of normalized lines joined by newline."""
    payload = "\n".join(lines).encode("utf-8")
    return hashlib.md5(payload).hexdigest()


def fingerprint_file(
    normalized: list[tuple[int, str]],
    filepath: str,
    min_lines: int = 5,
) -> list[Block]:
    """Create overlapping blocks of *min_lines* lines and hash each one.

    *normalized* is a list of (original_lineno, normalized_text) pairs as
    returned by ``normalizer.normalize_file``.
    """
    if len(normalized) < min_lines:
        return []

    blocks: list[Block] = []
    for i in range(len(normalized) - min_lines + 1):
        window = normalized[i : i + min_lines]
        lines_tuple = tuple(t for _, t in window)
        start = window[0][0]
        end = window[-1][0]
        digest = _hash_lines(lines_tuple)
        blocks.append(Block(
            filepath=filepath,
            start_line=start,
            end_line=end,
            normalized_lines=lines_tuple,
            digest=digest,
        ))
    return blocks


@dataclass
class MergedRegion:
    """A merged contiguous region of duplicate code in one file."""
    filepath: str
    start_line: int
    end_line: int
    normalized_lines: list[str] = field(default_factory=list)

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


def merge_adjacent_blocks(blocks: list[Block]) -> MergedRegion:
    """Merge a list of overlapping blocks from the same file into one region.

    Assumes *blocks* are from the same file and sorted by start_line.
    """
    if not blocks:
        raise ValueError("Cannot merge empty block list")

    # Collect all unique normalized lines in order
    seen_lines: dict[int, str] = {}
    for b in blocks:
        # Map original line numbers to normalized text
        # We know block start/end and the normalized_lines tuple length
        # But original line numbers may not be consecutive (blank lines skipped)
        # So we reconstruct from the block's data
        pass

    # Simpler approach: track the full span and gather normalized lines
    filepath = blocks[0].filepath
    start = min(b.start_line for b in blocks)
    end = max(b.end_line for b in blocks)

    # Gather normalized lines from the blocks in order, deduplicating by position
    line_map: dict[int, str] = {}
    for b in blocks:
        # Each block has min_lines normalized lines starting from its index
        # We need to map back to original line numbers
        # The block knows start_line and end_line from original source
        # and has normalized_lines as a tuple
        # We can approximate by distributing evenly, but better to use
        # the fact that blocks are overlapping windows of the normalized list
        pass

    # Since we don't have per-line mapping inside the block, collect all
    # unique normalized lines from all blocks in order
    all_lines: list[str] = []
    seen: set[str] = set()
    for b in blocks:
        for nl in b.normalized_lines:
            # Use a positional approach: just collect unique lines in order
            pass

    # Best approach: use first block's lines, then append only new lines from subsequent blocks
    all_lines = list(blocks[0].normalized_lines)
    for b in blocks[1:]:
        # Each subsequent block overlaps by (min_lines - 1) lines with the previous window
        # So only the last line of each new block is truly new
        all_lines.append(b.normalized_lines[-1])

    return MergedRegion(
        filepath=filepath,
        start_line=start,
        end_line=end,
        normalized_lines=all_lines,
    )
