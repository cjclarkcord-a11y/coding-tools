"""MATLAB dependency extraction using regex."""

from __future__ import annotations

import re
from pathlib import Path

# Comprehensive set of MATLAB builtins to ignore
MATLAB_BUILTINS: set[str] = {
    # Array creation and manipulation
    "zeros", "ones", "eye", "rand", "randn", "randi", "linspace", "logspace",
    "true", "false", "inf", "nan", "eps", "pi", "i", "j",
    "reshape", "permute", "ipermute", "squeeze", "repmat", "repelem",
    "cat", "horzcat", "vertcat", "transpose", "ctranspose",
    "fliplr", "flipud", "flip", "rot90", "circshift", "shiftdim",
    "colon", "sub2ind", "ind2sub", "ndgrid", "meshgrid",
    # Size and shape
    "size", "length", "numel", "ndims", "height", "width", "isscalar",
    "isvector", "ismatrix", "isrow", "iscolumn",
    # Searching and sorting
    "find", "sort", "sortrows", "unique", "union", "intersect",
    "setdiff", "setxor", "ismember", "issorted",
    # Math - basic
    "max", "min", "sum", "prod", "cumsum", "cumprod", "cummax", "cummin",
    "mean", "median", "std", "var", "mode", "movmean", "movmedian",
    "movstd", "movvar", "movsum", "movprod", "movmax", "movmin",
    "abs", "sign", "sqrt", "cbrt", "nthroot", "hypot",
    "log", "log2", "log10", "log1p", "exp", "expm1", "pow2",
    "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
    "sind", "cosd", "tand", "asind", "acosd", "atand",
    "sinh", "cosh", "tanh", "asinh", "acosh", "atanh",
    "ceil", "floor", "round", "fix", "mod", "rem",
    "real", "imag", "conj", "angle", "complex",
    "gcd", "lcm", "factorial", "nchoosek", "perms",
    # Linear algebra
    "inv", "pinv", "det", "trace", "eig", "eigs", "svd", "svds",
    "norm", "rank", "null", "orth", "rref", "qr", "lu", "chol",
    "ldl", "schur", "hess", "balance", "cond", "rcond",
    "cross", "dot", "kron", "tril", "triu", "diag", "blkdiag",
    "linsolve", "mldivide", "mrdivide", "lsqminnorm",
    "expm", "logm", "sqrtm", "funm",
    # FFT and signal
    "fft", "fft2", "fftn", "ifft", "ifft2", "ifftn",
    "fftshift", "ifftshift", "fftw",
    "conv", "conv2", "convn", "deconv", "filter", "filter2",
    "xcorr", "xcov",
    # Interpolation and fitting
    "interp1", "interp2", "interp3", "interpn", "griddedInterpolant",
    "scatteredInterpolant", "spline", "pchip", "makima",
    "polyfit", "polyval", "polyder", "polyint", "roots", "poly",
    "ppval", "mkpp", "unmkpp",
    # ODE and optimization
    "ode45", "ode23", "ode113", "ode15s", "ode23s", "ode23t", "ode23tb",
    "ode15i", "odeset", "odeget", "deval",
    "fzero", "fminbnd", "fminsearch", "fminunc", "fmincon",
    "lsqcurvefit", "lsqnonlin", "lsqnonneg",
    "optimset", "optimoptions", "optimget",
    "integral", "integral2", "integral3", "trapz", "cumtrapz", "quad",
    # Display and output
    "disp", "display", "fprintf", "sprintf", "printf",
    "error", "warning", "message", "lastwarn", "lasterr",
    "assert", "validateattributes", "validatestring",
    "num2str", "str2num", "str2double", "int2str", "mat2str",
    "char", "string", "cellstr", "strtrim", "strip",
    "lower", "upper", "strsplit", "strjoin", "strfind",
    "strrep", "replace", "contains", "startsWith", "endsWith",
    "regexp", "regexpi", "regexprep", "regexptranslate",
    "compose", "extractBefore", "extractAfter", "extractBetween",
    "insertBefore", "insertAfter", "eraseBetween", "erase", "pad",
    # Plotting
    "plot", "plot3", "semilogx", "semilogy", "loglog",
    "scatter", "scatter3", "bar", "barh", "bar3", "bar3h",
    "histogram", "histogram2", "histcounts",
    "pie", "pie3", "area", "stem", "stairs",
    "errorbar", "polarplot", "fplot", "fimplicit",
    "surf", "surfc", "surfl", "surface", "mesh", "meshc", "meshz",
    "contour", "contourf", "contour3", "contourslice",
    "quiver", "quiver3", "streamline", "streamslice",
    "image", "imagesc", "imshow", "pcolor",
    "patch", "fill", "fill3", "line", "rectangle", "text", "annotation",
    "figure", "axes", "subplot", "tiledlayout", "nexttile",
    "hold", "title", "xlabel", "ylabel", "zlabel",
    "legend", "colorbar", "colormap",
    "grid", "axis", "xlim", "ylim", "zlim", "clim",
    "view", "rotate3d", "pan", "zoom", "datacursormode",
    "close", "clf", "cla", "gcf", "gca", "gco",
    "set", "get", "drawnow", "refresh", "shg",
    "print", "savefig", "saveas", "exportgraphics",
    "uifigure", "uiaxes", "uicontrol", "uimenu",
    # Data types
    "struct", "cell", "table", "timetable", "categorical", "containers",
    "fieldnames", "rmfield", "orderfields", "isfield",
    "cell2mat", "cell2struct", "mat2cell", "num2cell", "struct2cell",
    "cell2table", "struct2table", "table2cell", "table2struct",
    "array2table", "table2array",
    "readtable", "writetable", "readmatrix", "writematrix",
    "readcell", "writecell", "readtimetable", "writetimetable",
    # Type checking
    "isempty", "isnan", "isinf", "isfinite",
    "isnumeric", "ischar", "isstring", "iscell", "isstruct",
    "islogical", "isfloat", "isinteger", "isreal",
    "isa", "class", "typecast", "cast",
    # Type conversion
    "double", "single", "int8", "int16", "int32", "int64",
    "uint8", "uint16", "uint32", "uint64", "logical",
    # Workspace and environment
    "exist", "which", "who", "whos", "clear", "clearvars", "clc",
    "cd", "pwd", "dir", "ls", "what",
    "mkdir", "rmdir", "copyfile", "movefile", "delete",
    "fullfile", "fileparts", "filesep", "pathsep",
    "tempdir", "tempname", "matlabroot", "userpath",
    "path", "addpath", "rmpath", "genpath", "savepath", "restoredefaultpath",
    # File I/O
    "fopen", "fclose", "fread", "fwrite",
    "fscanf", "fgets", "fgetl", "feof", "ftell", "fseek", "frewind",
    "load", "save", "matfile",
    "imread", "imwrite", "imfinfo",
    "audioread", "audiowrite", "audioinfo",
    "csvread", "csvwrite", "dlmread", "dlmwrite",
    "textscan", "textread",
    "jsonencode", "jsondecode",
    "xmlread", "xmlwrite", "xslt",
    # Control flow (keywords treated as builtins for safety)
    "deal", "cellfun", "arrayfun", "structfun", "rowfun", "varfun",
    "accumarray", "bsxfun", "pagefun",
    "try", "catch", "switch", "case", "otherwise",
    "for", "while", "if", "else", "elseif", "end",
    "return", "break", "continue", "pause",
    "nargin", "nargout", "varargin", "varargout",
    "nargchk", "narginchk", "nargoutchk",
    "inputParser", "addRequired", "addOptional", "addParameter", "parse",
    # Debug and profiling
    "mfilename", "dbstop", "dbclear", "dbcont", "dbdown", "dbup",
    "dbstack", "dbstatus", "dbtype", "dbquit",
    "keyboard", "input",
    "tic", "toc", "timeit", "cputime",
    "profile", "profsave",
    # Date and time
    "clock", "now", "date", "datestr", "datenum", "datevec",
    "datetime", "duration", "calendarDuration",
    "seconds", "minutes", "hours", "days", "years",
    "dateshift", "between", "isbetween",
    "etime", "addtodate",
    # Random and statistics extras
    "rng", "randperm", "datasample",
    "histc", "hist", "ksdensity", "normpdf", "normcdf", "norminv",
    # Misc
    "eval", "feval", "evalc", "evalin", "assignin",
    "global", "persistent",
    "run", "source",
    "nargout", "nargin",
    "methods", "properties", "events", "enumeration",
    "superclasses", "metaclass",
    "isequal", "isequaln", "eq", "ne", "lt", "gt", "le", "ge",
    "and", "or", "not", "xor", "any", "all",
    "bitand", "bitor", "bitxor", "bitcmp", "bitshift", "bitget", "bitset",
    "sparse", "issparse", "full", "spalloc", "speye", "spones",
    "sprand", "sprandn", "nnz", "nonzeros", "nzmax",
    "spy", "spconvert", "spfun",
    "map", "keys", "values", "isKey", "remove",
    "timer", "start", "stop", "wait",
    "parfor", "parfeval", "parpool", "gcp", "spmd",
}

# Regex patterns for MATLAB dependency extraction
# Match function calls: result = funcname(...) or funcname(...)
# But not keywords, not string contents, not comments
_RE_FUNC_CALL = re.compile(
    r"""
    (?:^|(?<=[\s;,=({\[]))   # preceded by start/whitespace/operator
    ([a-zA-Z]\w*)             # function name (capture group 1)
    \s*\(                     # opening paren (with optional space)
    """,
    re.VERBOSE | re.MULTILINE,
)

# Match: run('script.m') or run("script.m")
_RE_RUN_STRING = re.compile(
    r"""\brun\s*\(\s*['"]([^'"]+)['"]\s*\)""",
)

# Match: run script  (without parens)
_RE_RUN_BARE = re.compile(
    r"""^\s*run\s+(\S+)""",
    re.MULTILINE,
)

# Match: addpath('dir') or addpath("dir")
_RE_ADDPATH = re.compile(
    r"""\baddpath\s*\(\s*['"]([^'"]+)['"]\s*\)""",
)

# Match class instantiation: obj = ClassName(...)
# Classes start with uppercase by convention
_RE_CLASS_USAGE = re.compile(
    r"""
    (?:^|(?<=[\s;,=({\[]))
    ([A-Z]\w*)                # class name starting with uppercase
    \s*\(
    """,
    re.VERBOSE | re.MULTILINE,
)


def extract_matlab_deps(file_path: Path, project_root: Path) -> list[dict]:
    """Extract dependencies from a MATLAB file.

    Returns a list of dicts with keys:
        - source: str
        - target: str (absolute path of dependency, or raw name if unresolved)
        - type: str ("function_call" | "run" | "addpath" | "class_usage")
        - raw: str
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    # Strip comments (% to end of line) and block comments (%{ ... %})
    cleaned = _strip_comments(text)

    deps: list[dict] = []
    source = str(file_path)
    seen_targets: set[str] = set()

    # Collect all .m files in the project for resolution
    m_files = _index_m_files(project_root)

    # Function calls
    for match in _RE_FUNC_CALL.finditer(cleaned):
        name = match.group(1)
        if name.lower() in MATLAB_BUILTINS or name.lower() == name[:1] and name in ("end",):
            continue
        if name in MATLAB_BUILTINS:
            continue
        resolved = _resolve_matlab_name(name, m_files, project_root)
        if resolved and str(resolved) != source and str(resolved) not in seen_targets:
            seen_targets.add(str(resolved))
            deps.append({
                "source": source,
                "target": str(resolved),
                "type": "function_call",
                "raw": name,
            })

    # run('script.m') calls
    for match in _RE_RUN_STRING.finditer(cleaned):
        script = match.group(1)
        resolved = _resolve_script_path(script, file_path.parent, project_root)
        if resolved and str(resolved) != source and str(resolved) not in seen_targets:
            seen_targets.add(str(resolved))
            deps.append({
                "source": source,
                "target": str(resolved),
                "type": "run",
                "raw": script,
            })

    # run script (bare)
    for match in _RE_RUN_BARE.finditer(cleaned):
        script = match.group(1).strip().rstrip(";")
        if script in MATLAB_BUILTINS:
            continue
        resolved = _resolve_script_path(script, file_path.parent, project_root)
        if resolved and str(resolved) != source and str(resolved) not in seen_targets:
            seen_targets.add(str(resolved))
            deps.append({
                "source": source,
                "target": str(resolved),
                "type": "run",
                "raw": script,
            })

    # addpath
    for match in _RE_ADDPATH.finditer(cleaned):
        dir_path = match.group(1)
        resolved = (project_root / dir_path)
        deps.append({
            "source": source,
            "target": str(resolved),
            "type": "addpath",
            "raw": dir_path,
        })

    # Class usage
    for match in _RE_CLASS_USAGE.finditer(cleaned):
        name = match.group(1)
        if name in MATLAB_BUILTINS:
            continue
        resolved = _resolve_matlab_name(name, m_files, project_root)
        if resolved and str(resolved) != source and str(resolved) not in seen_targets:
            seen_targets.add(str(resolved))
            deps.append({
                "source": source,
                "target": str(resolved),
                "type": "class_usage",
                "raw": name,
            })

    return deps


def _strip_comments(text: str) -> str:
    """Remove MATLAB comments from source text."""
    # Remove block comments %{ ... %}
    text = re.sub(r"%\{.*?%\}", "", text, flags=re.DOTALL)
    # Remove line comments (% to end of line), but not inside strings
    lines = []
    for line in text.splitlines():
        # Simple approach: remove everything after first % not inside quotes
        cleaned = _remove_line_comment(line)
        lines.append(cleaned)
    return "\n".join(lines)


def _remove_line_comment(line: str) -> str:
    """Remove line comment, respecting string literals."""
    in_single = False
    in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "%" and not in_single and not in_double:
            return line[:i]
    return line


_m_file_cache: dict[str, dict[str, Path]] = {}


def _index_m_files(project_root: Path) -> dict[str, Path]:
    """Build an index of name -> path for all .m files in the project."""
    key = str(project_root)
    if key in _m_file_cache:
        return _m_file_cache[key]
    index: dict[str, Path] = {}
    skip = {".git", "__pycache__", ".venv", "node_modules"}
    for m_file in _walk_files(project_root, ".m", skip):
        name = m_file.stem
        # First one found wins (could be improved with path priority)
        if name not in index:
            index[name] = m_file
    _m_file_cache[key] = index
    return index


def _walk_files(root: Path, suffix: str, skip: set[str]):
    """Walk directory tree yielding files with given suffix, skipping dirs."""
    try:
        for entry in root.iterdir():
            if entry.name in skip:
                continue
            if entry.is_dir():
                yield from _walk_files(entry, suffix, skip)
            elif entry.is_file() and entry.suffix == suffix:
                yield entry
    except PermissionError:
        pass


def _resolve_matlab_name(name: str, m_files: dict[str, Path], project_root: Path) -> Path | None:
    """Resolve a MATLAB function/class name to a .m file."""
    if name in m_files:
        return m_files[name]
    # Check for +pkg/@ClassName/ pattern
    for m_path in m_files.values():
        parts = m_path.parts
        for i, part in enumerate(parts):
            if part.startswith("@") and part[1:] == name:
                return m_path
    return None


def _resolve_script_path(script: str, current_dir: Path, project_root: Path) -> Path | None:
    """Resolve a script path from a run() call."""
    # Add .m if no extension
    if not script.endswith(".m"):
        script = script + ".m"
    # Try relative to current file
    candidate = current_dir / script
    if candidate.is_file():
        return candidate
    # Try relative to project root
    candidate = project_root / script
    if candidate.is_file():
        return candidate
    return None


def clear_cache() -> None:
    """Clear the .m file index cache."""
    _m_file_cache.clear()
