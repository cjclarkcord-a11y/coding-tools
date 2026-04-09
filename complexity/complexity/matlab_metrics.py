"""MATLAB complexity analysis using regex and line-by-line parsing."""

import os
import re
from dataclasses import dataclass


@dataclass
class FunctionMetrics:
    name: str
    file: str
    line: int
    complexity: int = 1
    max_depth: int = 0
    length: int = 0
    score: float = 0.0

    def compute_score(self):
        self.score = self.complexity * max(1, self.max_depth) + self.length / 10


# Regex patterns
_FUNC_DEF = re.compile(
    r"^\s*function\s+"
    r"(?:"
    r"(?:\[?[^=\]]*\]?\s*=\s*)?"  # optional output: [out] = or out =
    r")"
    r"(\w+)"                       # function name
    r"\s*(?:\(|$|%)",              # opening paren, end of line, or comment
    re.MULTILINE,
)

# Block openers that require a matching 'end'
_BLOCK_OPENERS = re.compile(
    r"\b(if|for|while|switch|try|parfor)\b"
)

# Decision points for cyclomatic complexity
_DECISION_KW = re.compile(
    r"\b(if|elseif|for|while|catch|case|parfor)\b"
)

# Boolean operators
_BOOL_AND = re.compile(r"&&")
_BOOL_OR = re.compile(r"\|\|")

# Comment and blank line patterns
_COMMENT_LINE = re.compile(r"^\s*%")
_BLANK_LINE = re.compile(r"^\s*$")
_END_STMT = re.compile(r"\bend\b")

# Nesting control structures
_NESTING_OPENERS = re.compile(
    r"\b(if|for|while|switch|try|parfor)\b"
)


def _strip_strings_and_comments(line: str) -> str:
    """Remove string literals and comments from a line for safe keyword matching."""
    # Remove comments (everything after unquoted %)
    result = []
    in_single_quote = False
    in_double_quote = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double_quote:
            # MATLAB single-quote strings -- simplistic toggle
            in_single_quote = not in_single_quote
            result.append(ch)
        elif ch == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            result.append(ch)
        elif ch == '%' and not in_single_quote and not in_double_quote:
            break
        else:
            result.append(ch)
    cleaned = "".join(result)
    # Now remove string contents (keep quotes but blank inside)
    cleaned = re.sub(r"'[^']*'", "''", cleaned)
    cleaned = re.sub(r'"[^"]*"', '""', cleaned)
    return cleaned


def _find_functions(lines: list[str]) -> list[tuple[str, int, int]]:
    """Find function boundaries in a MATLAB file.

    Returns list of (name, start_line_0based, end_line_0based_exclusive).
    Handles multiple functions per file (local functions).
    """
    functions: list[tuple[str, int]] = []  # (name, start_line_0based)

    for i, line in enumerate(lines):
        cleaned = _strip_strings_and_comments(line)
        m = _FUNC_DEF.match(cleaned)
        if m:
            functions.append((m.group(1), i))

    if not functions:
        return []

    # Determine boundaries using end-matching with block depth tracking
    result: list[tuple[str, int, int]] = []

    for idx, (name, start) in enumerate(functions):
        # Track block depth to find the matching 'end' for this function
        depth = 1  # the function keyword itself opens a block
        func_end = len(lines)  # default to end of file

        for i in range(start + 1, len(lines)):
            cleaned = _strip_strings_and_comments(lines[i])

            # Count block openers
            openers = _BLOCK_OPENERS.findall(cleaned)
            # Also count nested function definitions as block openers
            if _FUNC_DEF.match(cleaned):
                # A new function at depth 1 means our function ended implicitly
                # (MATLAB files without 'end' for functions)
                if depth == 1:
                    func_end = i
                    break
                openers.append("function")

            depth += len(openers)

            # Count 'end' keywords
            ends = _END_STMT.findall(cleaned)
            depth -= len(ends)

            if depth <= 0:
                func_end = i + 1
                break
        else:
            # If no explicit end found, function goes to next function or EOF
            if idx + 1 < len(functions):
                func_end = functions[idx + 1][1]
            else:
                func_end = len(lines)

        result.append((name, start, func_end))

    return result


def _analyze_function_body(lines: list[str]) -> tuple[int, int, int]:
    """Analyze a function body for complexity, nesting depth, and length.

    Returns (complexity, max_depth, length).
    """
    complexity = 1  # base
    max_depth = 0
    current_depth = 0
    length = 0

    for line in lines:
        # Length: skip blank/comment lines
        if not _BLANK_LINE.match(line) and not _COMMENT_LINE.match(line):
            length += 1

        cleaned = _strip_strings_and_comments(line)

        # Decision points
        decisions = _DECISION_KW.findall(cleaned)
        complexity += len(decisions)

        # Boolean operators
        complexity += len(_BOOL_AND.findall(cleaned))
        complexity += len(_BOOL_OR.findall(cleaned))

        # Nesting tracking: openers increase depth, 'end' decreases
        openers = _NESTING_OPENERS.findall(cleaned)
        ends = _END_STMT.findall(cleaned)

        for _ in openers:
            current_depth += 1
            if current_depth > max_depth:
                max_depth = current_depth

        for _ in ends:
            current_depth = max(0, current_depth - 1)

    return complexity, max_depth, length


def analyze_matlab_file(filepath: str) -> list[FunctionMetrics]:
    """Analyze a single MATLAB file and return metrics for each function."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except (OSError, IOError):
        return []

    lines = content.splitlines()
    functions = _find_functions(lines)
    results: list[FunctionMetrics] = []

    for name, start, end in functions:
        # Body starts after the function definition line
        body_lines = lines[start + 1 : end]
        complexity, max_depth, length = _analyze_function_body(body_lines)

        metrics = FunctionMetrics(
            name=name,
            file=filepath,
            line=start + 1,  # 1-based
            complexity=complexity,
            max_depth=max_depth,
            length=length,
        )
        metrics.compute_score()
        results.append(metrics)

    # If no functions found, treat the whole file as a script (no metrics)
    return results


def scan_matlab_files(path: str) -> list[FunctionMetrics]:
    """Scan a path (file or directory) for MATLAB files and analyze them."""
    results: list[FunctionMetrics] = []
    if os.path.isfile(path):
        if path.endswith(".m"):
            results.extend(analyze_matlab_file(path))
    elif os.path.isdir(path):
        for root, _dirs, files in os.walk(path):
            for fname in files:
                if fname.endswith(".m"):
                    fpath = os.path.join(root, fname)
                    results.extend(analyze_matlab_file(fpath))
    return results
