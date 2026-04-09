"""Code normalization: strip comments, strings, whitespace, and replace identifiers."""

from __future__ import annotations

import re
import keyword

# ── Language keyword sets ──────────────────────────────────────────────

PYTHON_KEYWORDS: set[str] = {
    "if", "else", "elif", "for", "while", "def", "class", "return",
    "import", "from", "try", "except", "with", "as", "yield", "lambda",
    "pass", "break", "continue", "raise", "in", "not", "and", "or", "is",
    "True", "False", "None",
}

PYTHON_BUILTINS: set[str] = set(dir(__builtins__)) if isinstance(__builtins__, dict) else set(dir(__builtins__))

MATLAB_KEYWORDS: set[str] = {
    "function", "end", "if", "else", "elseif", "for", "while", "switch",
    "case", "otherwise", "try", "catch", "return", "break", "continue",
    "classdef", "properties", "methods", "persistent", "global",
}

# Common MATLAB builtins we want to preserve so they don't become _VAR_
MATLAB_BUILTINS: set[str] = {
    "disp", "fprintf", "sprintf", "length", "size", "zeros", "ones",
    "linspace", "plot", "xlabel", "ylabel", "title", "figure", "subplot",
    "hold", "legend", "abs", "sqrt", "sin", "cos", "tan", "exp", "log",
    "log10", "max", "min", "sum", "mean", "std", "reshape", "transpose",
    "inv", "det", "eig", "fft", "ifft", "conv", "filter", "sort",
    "unique", "find", "isempty", "isnumeric", "ischar", "nargin",
    "nargout", "error", "warning", "cell", "struct", "fieldnames",
    "cellfun", "arrayfun", "strcmp", "strcmpi", "strsplit", "strcat",
    "num2str", "str2num", "str2double", "true", "false", "pi", "inf",
    "nan", "eye", "rand", "randn", "round", "floor", "ceil", "mod",
    "rem", "cross", "dot", "norm", "cat", "vertcat", "horzcat",
    "repmat", "ndims", "numel", "sub2ind", "ind2sub", "logical",
    "double", "single", "int8", "int16", "int32", "int64",
    "uint8", "uint16", "uint32", "uint64", "char", "string",
}

# ── Identifier regex ──────────────────────────────────────────────────

_IDENT_RE = re.compile(r"\b([A-Za-z_]\w*)\b")

# ── Helpers ───────────────────────────────────────────────────────────


def _detect_language(filepath: str) -> str:
    """Return 'python' or 'matlab' based on file extension."""
    if filepath.endswith(".py"):
        return "python"
    if filepath.endswith(".m"):
        return "matlab"
    return "unknown"


def _strip_comments_python(line: str) -> str:
    """Remove Python # comments while respecting strings."""
    in_str: str | None = None
    i = 0
    while i < len(line):
        ch = line[i]
        if in_str is None:
            if ch == "#":
                return line[:i]
            if ch in ('"', "'"):
                # check triple quote
                triple = line[i : i + 3]
                if triple in ('"""', "'''"):
                    end = line.find(triple, i + 3)
                    if end == -1:
                        return line  # unclosed triple, keep whole line
                    i = end + 3
                    continue
                in_str = ch
        else:
            if ch == "\\" and i + 1 < len(line):
                i += 2
                continue
            if ch == in_str:
                in_str = None
        i += 1
    return line


def _strip_comments_matlab(line: str) -> str:
    """Remove MATLAB % comments while respecting strings."""
    in_str = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_str:
            in_str = True
        elif ch == "'" and in_str:
            in_str = False
        elif ch == "%" and not in_str:
            return line[:i]
    return line


def _replace_strings(line: str, lang: str) -> str:
    """Replace string literals with _STR_ placeholder."""
    if lang == "python":
        # Triple-quoted strings first, then single-quoted
        line = re.sub(r'""".*?"""', '"_STR_"', line)
        line = re.sub(r"'''.*?'''", '"_STR_"', line)
        line = re.sub(r'"(?:[^"\\]|\\.)*"', '"_STR_"', line)
        line = re.sub(r"'(?:[^'\\]|\\.)*'", '"_STR_"', line)
    elif lang == "matlab":
        line = re.sub(r'"(?:[^"\\]|\\.)*"', '"_STR_"', line)
        line = re.sub(r"'(?:[^'\\]|\\.)*'", '"_STR_"', line)
    return line


def _replace_numbers(line: str) -> str:
    """Replace numeric literals with _VAR_ so numeric differences don't matter."""
    # Float with decimal point (must come before int pattern)
    line = re.sub(r"\b\d+\.\d+(?:[eE][+-]?\d+)?\b", "_VAR_", line)
    # Integer (including hex/oct/bin)
    line = re.sub(r"\b0[xXoObB][\da-fA-F_]+\b", "_VAR_", line)
    line = re.sub(r"\b\d+\b", "_VAR_", line)
    return line


def _replace_identifiers(line: str, keep: set[str]) -> str:
    """Replace identifiers not in *keep* with _VAR_."""

    def _sub(m: re.Match) -> str:
        name = m.group(1)
        if name in keep or name == "_STR_" or name == "_VAR_":
            return name
        return "_VAR_"

    return _IDENT_RE.sub(_sub, line)


# ── Public API ────────────────────────────────────────────────────────


def normalize_line(line: str, lang: str, keep: set[str]) -> str:
    """Normalize a single line of code."""
    # Strip comments
    if lang == "python":
        line = _strip_comments_python(line)
    elif lang == "matlab":
        line = _strip_comments_matlab(line)

    # Replace strings
    line = _replace_strings(line, lang)

    # Replace numbers
    line = _replace_numbers(line)

    # Collapse whitespace and strip
    line = " ".join(line.split())

    # Replace identifiers
    line = _replace_identifiers(line, keep)

    return line


def get_keep_set(lang: str) -> set[str]:
    """Return the set of tokens to preserve for a language."""
    if lang == "python":
        return PYTHON_KEYWORDS | PYTHON_BUILTINS
    if lang == "matlab":
        return MATLAB_KEYWORDS | MATLAB_BUILTINS
    return set()


def normalize_file(filepath: str) -> list[tuple[int, str]]:
    """Normalize a source file, returning list of (original_lineno, normalized_line).

    Blank/empty normalized lines are excluded.
    """
    lang = _detect_language(filepath)
    if lang == "unknown":
        return []

    keep = get_keep_set(lang)
    results: list[tuple[int, str]] = []

    try:
        with open(filepath, encoding="utf-8", errors="replace") as fh:
            for lineno, raw_line in enumerate(fh, start=1):
                normed = normalize_line(raw_line, lang, keep)
                if normed:
                    results.append((lineno, normed))
    except OSError:
        return []

    return results
