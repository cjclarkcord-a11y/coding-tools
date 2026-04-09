"""Regex patterns for detecting hardcoded secrets and credentials."""

import re

# Each pattern is a tuple of (compiled_regex, label, severity).
# Severity: CRITICAL, HIGH, MEDIUM, LOW

PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # ── CRITICAL ──────────────────────────────────────────────────────────
    # Private keys
    (re.compile(r"-----BEGIN\s[\w\s]*PRIVATE KEY-----"), "Private key", "CRITICAL"),

    # AWS Secret Access Key (40-char base64 following known assignment)
    (re.compile(
        r"""(?:aws_secret_access_key|AWS_SECRET_ACCESS_KEY)\s*[=:]\s*['"]([A-Za-z0-9/+=]{40})['"]"""
    ), "AWS Secret Key", "CRITICAL"),

    # Connection strings with embedded credentials
    (re.compile(
        r"(?:mongodb|postgresql|postgres|mysql|redis|amqp|mssql)"
        r"://[^\s'\"]+:[^\s'\"]+@[^\s'\"]+",
        re.IGNORECASE,
    ), "Connection string with credentials", "CRITICAL"),

    # ── HIGH ──────────────────────────────────────────────────────────────
    # AWS Access Key ID
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key ID", "HIGH"),

    # Azure storage / account key
    (re.compile(
        r"""(?:AccountKey|azure[_-]?storage[_-]?key)\s*[=:]\s*['"][A-Za-z0-9+/=]{20,}['"]""",
        re.IGNORECASE,
    ), "Azure key", "HIGH"),

    # GCP API key
    (re.compile(r"AIza[0-9A-Za-z_-]{35}"), "GCP API key", "HIGH"),

    # GitHub tokens
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "GitHub personal access token", "HIGH"),
    (re.compile(r"gho_[A-Za-z0-9]{36}"), "GitHub OAuth token", "HIGH"),
    (re.compile(r"ghs_[A-Za-z0-9]{36}"), "GitHub server token", "HIGH"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{22,}"), "GitHub fine-grained PAT", "HIGH"),

    # Slack tokens
    (re.compile(r"xox[bporas]-[A-Za-z0-9-]+"), "Slack token", "HIGH"),

    # Stripe keys
    (re.compile(r"sk_live_[A-Za-z0-9]{24,}"), "Stripe secret key", "HIGH"),
    (re.compile(r"pk_live_[A-Za-z0-9]{24,}"), "Stripe publishable key", "HIGH"),

    # SendGrid API key
    (re.compile(r"SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}"), "SendGrid API key", "HIGH"),

    # JWT tokens
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
     "JWT token", "HIGH"),

    # Bearer tokens
    (re.compile(r"[Bb]earer\s+[A-Za-z0-9_\-.~+/]{20,}=*"), "Bearer token", "HIGH"),

    # Generic API key assignment
    (re.compile(
        r"""api[_-]?key\s*[=:]\s*['"][^'"]{8,}['"]""", re.IGNORECASE
    ), "API key assignment", "HIGH"),

    # Password assignments
    (re.compile(
        r"""(?:password|passwd|pwd)\s*[=:]\s*['"][^'"]+['"]""", re.IGNORECASE
    ), "Hardcoded password", "HIGH"),

    # Secret assignments
    (re.compile(
        r"""(?:secret|secret[_-]?key)\s*[=:]\s*['"][^'"]{8,}['"]""", re.IGNORECASE
    ), "Hardcoded secret", "HIGH"),

    # ── LOW ───────────────────────────────────────────────────────────────
    # Generic sensitive variable names assigned to non-literal expressions
    # (these are informational only)
    (re.compile(
        r"""(?:secret|token|credential|auth[_-]?key|api[_-]?key|password|passwd)\s*[=:]\s*[^'"\s]""",
        re.IGNORECASE,
    ), "Sensitive variable name", "LOW"),
]

# ── MATLAB-specific patterns ──────────────────────────────────────────────
MATLAB_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # webread / webwrite with inline key params
    (re.compile(
        r"""(?:webread|webwrite|weboptions)\s*\(.*['"][^'"]*(?:key|token|api|auth)[^'"]*['"]""",
        re.IGNORECASE,
    ), "MATLAB web call with potential key", "HIGH"),

    # py.requests with hardcoded auth
    (re.compile(
        r"""py\.requests\.\w+\s*\(.*(?:auth|header|token|key)\s*=""",
        re.IGNORECASE,
    ), "MATLAB py.requests with auth", "HIGH"),

    # database() with connection credentials
    (re.compile(
        r"""database\s*\([^)]*['"][^'"]+['"][^)]*['"][^'"]+['"][^)]*['"][^'"]+['"]""",
    ), "MATLAB database() with credentials", "CRITICAL"),
]

# Variable-name keywords that hint a nearby high-entropy string is a secret.
SENSITIVE_VAR_KEYWORDS: set[str] = {
    "secret", "token", "credential", "auth", "key", "password", "passwd",
    "pwd", "api_key", "apikey", "access_key", "private", "signing",
}
