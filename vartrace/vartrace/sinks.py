"""Classification data for sinks and transforms.

Name-based heuristic matching. Covers ~90% of real-world cases without
needing type inference.
"""

# method/function name -> human-readable category
TRANSFORMS: dict[str, str] = {
    # encoding
    "encode": "encoding",
    "decode": "encoding",
    "b64encode": "encoding",
    "b64decode": "encoding",
    "urlsafe_b64encode": "encoding",
    "urlsafe_b64decode": "encoding",
    "quote": "encoding",
    "unquote": "encoding",
    # hashing
    "hexdigest": "hashing",
    "digest": "hashing",
    "sha256": "hashing",
    "sha1": "hashing",
    "sha512": "hashing",
    "md5": "hashing",
    "pbkdf2_hmac": "hashing",
    # encryption
    "encrypt": "encryption",
    "decrypt": "encryption",
    "fernet": "encryption",
    # serialization
    "dumps": "serialization",
    "loads": "deserialization",
    "dump": "serialization",
    "load": "deserialization",
    # string ops that change data shape
    "strip": "sanitization",
    "lstrip": "sanitization",
    "rstrip": "sanitization",
    "replace": "sanitization",
    "lower": "case_transform",
    "upper": "case_transform",
    "title": "case_transform",
    "capitalize": "case_transform",
    "split": "splitting",
    "join": "joining",
    "format": "formatting",
    "format_map": "formatting",
    # type conversions
    "int": "type_cast",
    "float": "type_cast",
    "str": "type_cast",
    "bool": "type_cast",
    "bytes": "type_cast",
    "list": "type_cast",
    "dict": "type_cast",
    "tuple": "type_cast",
    "set": "type_cast",
}

# method/function name -> sink category
SINKS: dict[str, str] = {
    # console
    "print": "console",
    "pprint": "console",
    # file I/O
    "write": "file",
    "writelines": "file",
    "writerow": "file",
    "writerows": "file",
    # network / HTTP
    "send": "network",
    "sendall": "network",
    "sendto": "network",
    "post": "http",
    "get": "http",
    "put": "http",
    "patch": "http",
    "delete": "http",
    "request": "http",
    # database
    "execute": "database",
    "executemany": "database",
    "executescript": "database",
    "insert": "database",
    "update": "database",
    "bulk_create": "database",
    "bulk_update": "database",
    # logging
    "log": "logging",
    "warning": "logging",
    "error": "logging",
    "info": "logging",
    "debug": "logging",
    "critical": "logging",
    "exception": "logging",
    # environment / config
    "setenv": "environment",
    "putenv": "environment",
    # subprocess
    "run": "subprocess",
    "call": "subprocess",
    "check_call": "subprocess",
    "check_output": "subprocess",
    "Popen": "subprocess",
}
