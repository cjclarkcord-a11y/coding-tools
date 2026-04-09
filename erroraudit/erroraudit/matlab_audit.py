"""MATLAB error handling auditor using regex."""

import os
import re
from dataclasses import dataclass


@dataclass
class Issue:
    file: str
    line: int
    severity: str
    title: str
    description: str
    code_lines: list[str]


def _is_test_file(filepath: str) -> bool:
    base = os.path.basename(filepath)
    return (
        base.startswith("test_")
        or base.startswith("Test")
        or "/tests/" in filepath.replace("\\", "/")
        or "/test/" in filepath.replace("\\", "/")
    )


def _read_file(filepath: str) -> str | None:
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _get_lines(source: str) -> list[str]:
    return source.splitlines()


def _extract_code(lines: list[str], lineno: int, count: int = 1) -> list[str]:
    start = max(0, lineno - 1)
    end = min(len(lines), start + count)
    return lines[start:end]


def _find_try_catch_blocks(source: str) -> list[dict]:
    """Find all try/catch/end blocks and return their line ranges and catch info."""
    lines = source.splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        # Match 'try' as standalone keyword
        if re.match(r"^\s*try\s*(%.*)?$", lines[i]):
            try_line = i + 1  # 1-based
            catch_line = None
            catch_ident = None
            catch_body_lines: list[int] = []
            end_line = None
            depth = 1
            j = i + 1
            in_catch = False
            while j < len(lines):
                line_s = lines[j].strip()
                # Track nesting: other block openers
                if re.match(r"^\s*(try|for|while|if|switch|parfor)\b", lines[j]) and not re.match(r"^\s*%", lines[j]):
                    depth += 1
                elif re.match(r"^\s*end\b", lines[j]) and not re.match(r"^\s*%", lines[j]):
                    depth -= 1
                    if depth == 0:
                        end_line = j + 1
                        break
                elif depth == 1 and re.match(r"^\s*catch\b", lines[j]):
                    in_catch = True
                    catch_line = j + 1  # 1-based
                    # Check for catch identifier: catch ME, catch e, etc.
                    m = re.match(r"^\s*catch\s+(\w+)", lines[j])
                    catch_ident = m.group(1) if m else None
                elif in_catch and depth == 1:
                    catch_body_lines.append(j)
                j += 1

            if catch_line is not None:
                blocks.append({
                    "try_line": try_line,
                    "catch_line": catch_line,
                    "catch_ident": catch_ident,
                    "catch_body_indices": catch_body_lines,
                    "end_line": end_line,
                })
        i += 1
    return blocks


def _is_inside_try_catch(lineno: int, blocks: list[dict]) -> bool:
    """Check if a 1-based line number falls inside any try/catch block."""
    for b in blocks:
        end = b["end_line"] or 999999
        if b["try_line"] <= lineno <= end:
            return True
    return False


def _check_empty_catch(blocks: list[dict], lines: list[str], filepath: str) -> list[Issue]:
    issues = []
    for block in blocks:
        body_indices = block["catch_body_indices"]
        # Filter out blank lines and comment-only lines
        non_trivial = [
            idx for idx in body_indices
            if lines[idx].strip() and not re.match(r"^\s*%", lines[idx])
        ]
        if not non_trivial:
            issues.append(Issue(
                file=filepath,
                line=block["catch_line"],
                severity="MEDIUM",
                title="Empty catch block",
                description="Catch block is empty or contains only comments",
                code_lines=_extract_code(lines, block["catch_line"]),
            ))
    return issues


def _check_catch_no_identifier(blocks: list[dict], lines: list[str], filepath: str) -> list[Issue]:
    issues = []
    for block in blocks:
        if block["catch_ident"] is None:
            issues.append(Issue(
                file=filepath,
                line=block["catch_line"],
                severity="LOW",
                title="Catch without identifier",
                description="catch without variable (e.g. catch ME) - cannot inspect the error",
                code_lines=_extract_code(lines, block["catch_line"]),
            ))
    return issues


def _check_catch_ignores_variable(blocks: list[dict], lines: list[str], filepath: str) -> list[Issue]:
    issues = []
    for block in blocks:
        ident = block["catch_ident"]
        if ident is None:
            continue
        # Check if the identifier is used anywhere in the catch body
        body_text = "\n".join(lines[idx] for idx in block["catch_body_indices"])
        # Remove comments
        body_no_comments = re.sub(r"%.*$", "", body_text, flags=re.MULTILINE)
        if ident not in body_no_comments:
            issues.append(Issue(
                file=filepath,
                line=block["catch_line"],
                severity="MEDIUM",
                title="Catch-and-ignore",
                description=f"Catch block has variable '{ident}' but never uses it",
                code_lines=_extract_code(lines, block["catch_line"]),
            ))
    return issues


def _check_unchecked_fopen(lines: list[str], blocks: list[dict], filepath: str) -> list[Issue]:
    """Find fopen calls where the return value is not checked for -1."""
    issues = []
    fopen_re = re.compile(r"(\w+)\s*=\s*fopen\s*\(")
    check_re_template = r"(if\s+.*{var}\s*==\s*-1|if\s+.*{var}\s*<\s*0|if\s+.*{var}\s*~=\s*-1|assert\s*\(\s*{var})"

    for i, line in enumerate(lines):
        lineno = i + 1
        if re.match(r"^\s*%", line):
            continue
        m = fopen_re.search(line)
        if not m:
            continue
        var = m.group(1)
        # Check the next few lines for a check on the variable
        check_re = re.compile(check_re_template.format(var=re.escape(var)))
        found_check = False
        # Also OK if inside try/catch
        if _is_inside_try_catch(lineno, blocks):
            continue
        for j in range(i + 1, min(i + 5, len(lines))):
            if check_re.search(lines[j]):
                found_check = True
                break
        if not found_check:
            issues.append(Issue(
                file=filepath,
                line=lineno,
                severity="HIGH",
                title="Unchecked fopen",
                description="Return value not tested for -1",
                code_lines=_extract_code(lines, lineno),
            ))
    return issues


def _check_unguarded_file_io(lines: list[str], blocks: list[dict], filepath: str) -> list[Issue]:
    """Find file I/O calls (fread, fwrite, load, etc.) not inside try/catch and not preceded by fopen check."""
    issues = []
    io_re = re.compile(r"\b(fread|fwrite|fclose|fscanf|fprintf|textscan|load|save)\s*\(")

    for i, line in enumerate(lines):
        lineno = i + 1
        if re.match(r"^\s*%", line):
            continue
        m = io_re.search(line)
        if not m:
            continue
        if _is_inside_try_catch(lineno, blocks):
            continue
        func_name = m.group(1)
        issues.append(Issue(
            file=filepath,
            line=lineno,
            severity="MEDIUM",
            title="Unguarded file I/O",
            description=f"{func_name}() call not inside try/catch",
            code_lines=_extract_code(lines, lineno),
        ))
    return issues


def _check_py_calls(lines: list[str], blocks: list[dict], filepath: str) -> list[Issue]:
    """Find py.* calls not inside try/catch."""
    issues = []
    py_re = re.compile(r"\bpy\.\w+")

    for i, line in enumerate(lines):
        lineno = i + 1
        if re.match(r"^\s*%", line):
            continue
        if not py_re.search(line):
            continue
        if _is_inside_try_catch(lineno, blocks):
            continue
        issues.append(Issue(
            file=filepath,
            line=lineno,
            severity="MEDIUM",
            title="No error handling on Python call",
            description="py.* call not inside try/catch - cross-language calls can throw unexpected errors",
            code_lines=_extract_code(lines, lineno),
        ))
    return issues


def _check_eval_without_try(lines: list[str], blocks: list[dict], filepath: str) -> list[Issue]:
    """Find eval/evalc/feval calls not inside try/catch."""
    issues = []
    eval_re = re.compile(r"\b(eval|evalc|feval)\s*\(")

    for i, line in enumerate(lines):
        lineno = i + 1
        if re.match(r"^\s*%", line):
            continue
        m = eval_re.search(line)
        if not m:
            continue
        if _is_inside_try_catch(lineno, blocks):
            continue
        func_name = m.group(1)
        issues.append(Issue(
            file=filepath,
            line=lineno,
            severity="HIGH",
            title=f"{func_name} without try/catch",
            description=f"{func_name}() is dangerous without error handling",
            code_lines=_extract_code(lines, lineno),
        ))
    return issues


def audit_matlab_file(filepath: str) -> list[Issue]:
    """Audit a single MATLAB file for error handling issues."""
    if _is_test_file(filepath):
        return []

    source = _read_file(filepath)
    if source is None:
        return []

    lines = _get_lines(source)
    blocks = _find_try_catch_blocks(source)
    issues: list[Issue] = []

    issues.extend(_check_empty_catch(blocks, lines, filepath))
    issues.extend(_check_catch_no_identifier(blocks, lines, filepath))
    issues.extend(_check_catch_ignores_variable(blocks, lines, filepath))
    issues.extend(_check_unchecked_fopen(lines, blocks, filepath))
    issues.extend(_check_unguarded_file_io(lines, blocks, filepath))
    issues.extend(_check_py_calls(lines, blocks, filepath))
    issues.extend(_check_eval_without_try(lines, blocks, filepath))

    issues.sort(key=lambda i: i.line)
    return issues
