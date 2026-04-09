"""Shannon entropy calculation for high-entropy string detection."""

from __future__ import annotations

import math
import re
from collections import Counter

# Threshold above which a string is considered high-entropy.
ENTROPY_THRESHOLD = 4.5

# Regex to pull quoted string literals out of a line.
_STRING_LITERAL_RE = re.compile(r"""(['"])((?:(?!\1).){12,})\1""")

# Patterns that are common false positives for high-entropy strings.
_FALSE_POSITIVE_PATTERNS: list[re.Pattern] = [
    # File paths (Unix / Windows)
    re.compile(r"^[/\\.]"),
    re.compile(r"^[A-Za-z]:[/\\]"),
    # URLs to documentation / non-credential hosts
    re.compile(r"^https?://(?:docs\.|www\.|en\.wikipedia|stackoverflow|github\.com/\w+/\w+(?:#|$))"),
    # Format strings with braces / percent placeholders
    re.compile(r"\{[^}]*\}"),
    re.compile(r"%[sdifx%]", re.IGNORECASE),
    # Hash algorithm names / references in comments
    re.compile(r"^(?:sha-?(?:1|256|384|512)|md5|blake2|ripemd|hmac)", re.IGNORECASE),
    # Common placeholder / example values
    re.compile(r"^(?:example|placeholder|changeme|your[_-])", re.IGNORECASE),
    # Lorem ipsum
    re.compile(r"^lorem\s", re.IGNORECASE),
    # UUIDs (low risk on their own)
    re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE),
]

# Keywords on the same line that suggest the string might be a secret.
_CONTEXT_KEYWORDS = re.compile(
    r"(?:secret|token|credential|auth|key|password|passwd|pwd|signing|private|api)",
    re.IGNORECASE,
)


def shannon_entropy(s: str) -> float:
    """Return the Shannon entropy (bits per character) of *s*."""
    if not s:
        return 0.0
    length = len(s)
    counts = Counter(s)
    return -sum(
        (count / length) * math.log2(count / length) for count in counts.values()
    )


def _is_false_positive(value: str) -> bool:
    """Return True if *value* looks like a benign high-entropy string."""
    for pat in _FALSE_POSITIVE_PATTERNS:
        if pat.search(value):
            return True
    return False


def find_high_entropy_strings(
    line: str,
    line_number: int,
    filepath: str,
) -> list[tuple[str, str, float, int]]:
    """Scan *line* for high-entropy string literals near sensitive context.

    Returns a list of ``(matched_text, context_keyword, entropy, line_number)``
    tuples for every flagged string.
    """
    results: list[tuple[str, str, float, int]] = []

    for m in _STRING_LITERAL_RE.finditer(line):
        value = m.group(2)

        # Quick length gate -- very short strings are rarely secrets.
        if len(value) < 12:
            continue

        ent = shannon_entropy(value)
        if ent <= ENTROPY_THRESHOLD:
            continue

        if _is_false_positive(value):
            continue

        # Only flag if the surrounding line contains a security-related keyword.
        ctx = _CONTEXT_KEYWORDS.search(line)
        if ctx is None:
            continue

        results.append((value, ctx.group(0), ent, line_number))

    return results
