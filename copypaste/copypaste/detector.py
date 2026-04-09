"""Core duplicate detection: gather fingerprints, group, merge, and report."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from collections import defaultdict

from copypaste.normalizer import normalize_file
from copypaste.fingerprint import (
    Block,
    MergedRegion,
    fingerprint_file,
    merge_adjacent_blocks,
)

# Directories to skip while walking
SKIP_DIRS: set[str] = {
    "__pycache__", ".git", ".venv", "venv", "node_modules", ".tox",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs", "env",
}


@dataclass
class DuplicateGroup:
    """A group of code regions that are duplicates of each other."""
    regions: list[MergedRegion]
    normalized_preview: list[str] = field(default_factory=list)

    @property
    def line_count(self) -> int:
        """Representative line count (from longest region)."""
        if not self.regions:
            return 0
        return max(r.line_count for r in self.regions)

    @property
    def copy_count(self) -> int:
        return len(self.regions)

    @property
    def total_duplicate_lines(self) -> int:
        """Total duplicate lines (all copies minus the 'original')."""
        if len(self.regions) <= 1:
            return 0
        return self.line_count * (len(self.regions) - 1)


@dataclass
class ScanResult:
    """Result of scanning a path for duplicates."""
    files_scanned: int = 0
    groups: list[DuplicateGroup] = field(default_factory=list)

    @property
    def total_duplicate_lines(self) -> int:
        return sum(g.total_duplicate_lines for g in self.groups)


def _collect_files(
    path: str,
    py_only: bool = False,
    m_only: bool = False,
) -> list[str]:
    """Walk *path* and collect Python/MATLAB source files."""
    extensions: set[str] = set()
    if py_only:
        extensions.add(".py")
    elif m_only:
        extensions.add(".m")
    else:
        extensions.update((".py", ".m"))

    if os.path.isfile(path):
        ext = os.path.splitext(path)[1]
        return [path] if ext in extensions else []

    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(path):
        # Prune skipped directories in-place
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for fname in filenames:
            ext = os.path.splitext(fname)[1]
            if ext in extensions:
                full = os.path.join(dirpath, fname)
                # Quick binary check: read a small chunk
                try:
                    with open(full, "rb") as fh:
                        chunk = fh.read(1024)
                    if b"\x00" in chunk:
                        continue  # binary file
                except OSError:
                    continue
                files.append(full)
    return files


def _group_blocks_by_hash(all_blocks: list[Block]) -> dict[str, list[Block]]:
    """Group blocks by their digest, keeping only hashes with 2+ blocks from different files."""
    by_hash: dict[str, list[Block]] = defaultdict(list)
    for block in all_blocks:
        by_hash[block.digest].append(block)

    # Filter: must appear in at least 2 different files
    return {
        h: blocks
        for h, blocks in by_hash.items()
        if len(set(b.filepath for b in blocks)) >= 2
    }


def _merge_groups(
    hash_groups: dict[str, list[Block]],
    min_lines: int,
) -> list[DuplicateGroup]:
    """Merge overlapping hash-matched blocks into maximal duplicate regions.

    Strategy:
    1. Build per-file ordered block lists for forward-extension.
    2. For each hash that appears in 2+ locations, extend matches forward
       to find the longest contiguous duplicate span.
    3. Keep only maximal (non-dominated) match pairs.
    4. Group match pairs into DuplicateGroups by transitive overlap.
    """
    # ── Step 1: build per-file block sequences ──────────────────────

    # Collect ALL blocks (not just those in hash_groups) per file
    file_blocks: dict[str, list[Block]] = defaultdict(list)
    for blocks in hash_groups.values():
        for b in blocks:
            file_blocks[b.filepath].append(b)

    # Deduplicate and sort by start_line
    for fp in file_blocks:
        seen: set[int] = set()
        deduped: list[Block] = []
        for b in sorted(file_blocks[fp], key=lambda b: b.start_line):
            if b.start_line not in seen:
                seen.add(b.start_line)
                deduped.append(b)
        file_blocks[fp] = deduped

    # Map start_line -> index for each file
    file_idx: dict[str, dict[int, int]] = {}
    for fp, blocks in file_blocks.items():
        file_idx[fp] = {b.start_line: i for i, b in enumerate(blocks)}

    # ── Step 2: extend each hash-match pair to maximal runs ─────────

    # For each pair we find, store as (region1, region2) keyed on canonical pair
    # We track "already covered" pairs to avoid redundant extension
    covered_pairs: set[tuple[str, int, str, int]] = set()
    match_pairs: list[tuple[MergedRegion, MergedRegion]] = []

    for digest, blocks in hash_groups.items():
        locations = [(b.filepath, b.start_line) for b in blocks]

        for i in range(len(locations)):
            for j in range(i + 1, len(locations)):
                fp1, sl1 = locations[i]
                fp2, sl2 = locations[j]
                if fp1 == fp2 and sl1 == sl2:
                    continue
                # Canonical order
                if (fp1, sl1) > (fp2, sl2):
                    fp1, sl1, fp2, sl2 = fp2, sl2, fp1, sl1

                if (fp1, sl1, fp2, sl2) in covered_pairs:
                    continue

                idx_map1 = file_idx.get(fp1, {})
                idx_map2 = file_idx.get(fp2, {})
                if sl1 not in idx_map1 or sl2 not in idx_map2:
                    continue

                i1 = idx_map1[sl1]
                i2 = idx_map2[sl2]
                blocks1 = file_blocks[fp1]
                blocks2 = file_blocks[fp2]

                # Extend forward while digests match
                fwd = 0
                while (i1 + fwd < len(blocks1)
                       and i2 + fwd < len(blocks2)
                       and blocks1[i1 + fwd].digest == blocks2[i2 + fwd].digest):
                    if fp1 == fp2:
                        b1 = blocks1[i1 + fwd]
                        b2 = blocks2[i2 + fwd]
                        if b1.start_line <= b2.end_line and b2.start_line <= b1.end_line:
                            break
                    fwd += 1

                if fwd == 0:
                    continue

                # Mark all sub-pairs as covered so we don't re-extend them
                for off in range(fwd):
                    s1 = blocks1[i1 + off].start_line
                    s2 = blocks2[i2 + off].start_line
                    a, b_ = (fp1, s1), (fp2, s2)
                    if a > b_:
                        a, b_ = b_, a
                    covered_pairs.add((a[0], a[1], b_[0], b_[1]))

                run1 = blocks1[i1 : i1 + fwd]
                run2 = blocks2[i2 : i2 + fwd]
                region1 = merge_adjacent_blocks(run1)
                region2 = merge_adjacent_blocks(run2)
                match_pairs.append((region1, region2))

    if not match_pairs:
        return []

    # ── Step 3: remove dominated pairs ──────────────────────────────
    # A pair (A1,A2) dominates (B1,B2) if B1 is inside A1 and B2 is inside A2
    # (or any permutation matching the same files).

    def _contains(outer: MergedRegion, inner: MergedRegion) -> bool:
        return (outer.filepath == inner.filepath
                and outer.start_line <= inner.start_line
                and outer.end_line >= inner.end_line)

    # Sort largest first for efficient domination check
    match_pairs.sort(key=lambda p: -(p[0].line_count + p[1].line_count))

    maximal: list[tuple[MergedRegion, MergedRegion]] = []
    for pair in match_pairs:
        r1, r2 = pair
        dominated = False
        for m1, m2 in maximal:
            if (_contains(m1, r1) and _contains(m2, r2)):
                dominated = True
                break
            if (_contains(m1, r2) and _contains(m2, r1)):
                dominated = True
                break
        if not dominated:
            maximal.append(pair)

    # ── Step 4: group into DuplicateGroups by transitive region overlap ─

    # Each maximal pair gives us a set of region-keys that are duplicates.
    # Group pairs where the same region-key appears.
    RegionKey = tuple[str, int, int]

    region_map: dict[RegionKey, MergedRegion] = {}
    # edges: region -> set of duplicate regions
    edges: dict[RegionKey, set[RegionKey]] = defaultdict(set)

    for r1, r2 in maximal:
        k1 = (r1.filepath, r1.start_line, r1.end_line)
        k2 = (r2.filepath, r2.start_line, r2.end_line)
        region_map[k1] = r1
        region_map[k2] = r2
        edges[k1].add(k2)
        edges[k2].add(k1)

    # Connected components via BFS
    visited: set[RegionKey] = set()
    components: list[list[RegionKey]] = []

    for key in region_map:
        if key in visited:
            continue
        comp: list[RegionKey] = []
        queue = [key]
        while queue:
            curr = queue.pop()
            if curr in visited:
                continue
            visited.add(curr)
            comp.append(curr)
            for nb in edges.get(curr, set()):
                if nb not in visited:
                    queue.append(nb)
        components.append(comp)

    # Build DuplicateGroups
    consolidated: list[DuplicateGroup] = []

    for comp in components:
        regions = [region_map[k] for k in comp]
        if len(regions) < 2:
            continue
        longest = max(regions, key=lambda r: r.line_count)
        preview = longest.normalized_lines[:6]
        consolidated.append(DuplicateGroup(
            regions=sorted(regions, key=lambda r: (r.filepath, r.start_line)),
            normalized_preview=preview,
        ))

    # Sort groups by size descending (best refactoring targets first)
    consolidated.sort(key=lambda g: -(g.line_count * g.copy_count))

    return consolidated


def scan(
    path: str,
    min_lines: int = 5,
    py_only: bool = False,
    m_only: bool = False,
) -> ScanResult:
    """Scan *path* for duplicate code blocks.

    Returns a ``ScanResult`` with all duplicate groups found.
    """
    files = _collect_files(path, py_only=py_only, m_only=m_only)
    result = ScanResult(files_scanned=len(files))

    if not files:
        return result

    # Fingerprint every file
    all_blocks: list[Block] = []
    for fpath in files:
        normalized = normalize_file(fpath)
        blocks = fingerprint_file(normalized, fpath, min_lines=min_lines)
        all_blocks.extend(blocks)

    if not all_blocks:
        return result

    # Group by hash
    hash_groups = _group_blocks_by_hash(all_blocks)
    if not hash_groups:
        return result

    # Merge and consolidate
    result.groups = _merge_groups(hash_groups, min_lines)

    return result
