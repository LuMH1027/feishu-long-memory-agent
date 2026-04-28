import shlex
from pathlib import PurePosixPath
from typing import Any


def _split_command(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def _looks_like_path(value: str) -> bool:
    if not value:
        return False
    normalized = value.replace("\\", "/")
    return normalized.startswith(("/", "./", "../", "~/")) or "/" in normalized


def parse_command(command: str) -> dict[str, Any]:
    """Extract a lightweight command pattern for CLI memory ranking."""
    tokens = _split_command(command)
    if not tokens:
        return {
            "program": "",
            "subcommand": "",
            "command_family": "",
            "flags": {},
            "positionals": [],
            "paths": [],
        }

    program = tokens[0]
    subcommand = tokens[1] if len(tokens) > 1 and not tokens[1].startswith("-") else ""
    command_family = " ".join(token for token in [program, subcommand] if token)

    flags: dict[str, Any] = {}
    positionals: list[str] = []
    paths: list[str] = []
    index = 2 if subcommand else 1
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("--") and "=" in token:
            key, value = token.split("=", 1)
            flags[key] = value
            if _looks_like_path(value):
                paths.append(value)
        elif token.startswith("-"):
            next_value = None
            if index + 1 < len(tokens) and not tokens[index + 1].startswith("-"):
                next_value = tokens[index + 1]
                index += 1
            flags[token] = next_value if next_value is not None else True
            if next_value and _looks_like_path(next_value):
                paths.append(next_value)
        else:
            positionals.append(token)
            if _looks_like_path(token):
                paths.append(token)
        index += 1

    return {
        "program": program,
        "subcommand": subcommand,
        "command_family": command_family,
        "flags": flags,
        "positionals": positionals,
        "paths": list(dict.fromkeys(str(PurePosixPath(path.replace("\\", "/"))) for path in paths)),
    }


def pattern_text(pattern: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("program", "subcommand", "command_family"):
        value = pattern.get(key)
        if value:
            values.append(str(value))

    flags = pattern.get("flags")
    if isinstance(flags, dict):
        for key, value in flags.items():
            values.append(str(key))
            if value is not True and value is not None:
                values.append(str(value))

    for key in ("positionals", "paths"):
        items = pattern.get(key)
        if isinstance(items, list):
            values.extend(str(item) for item in items)

    return " ".join(values).lower()
