"""Load and discover mypy configuration."""

from __future__ import annotations

import re
from configparser import ConfigParser
from pathlib import Path

from .models import MypyConfig

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore[import-not-found,no-redef,unused-ignore]
    except ImportError:
        tomllib = None  # type: ignore[assignment,unused-ignore]


_CONFIG_CANDIDATES = ("mypy.ini", ".mypy.ini", "setup.cfg", "pyproject.toml")


def discover_config(start: Path) -> Path | None:
    """Walk up from ``start`` looking for a file containing a mypy section."""
    for directory in (start, *start.parents):
        for name in _CONFIG_CANDIDATES:
            candidate = directory / name
            if candidate.is_file() and _has_mypy_section(candidate):
                return candidate
    return None


def _has_mypy_section(path: Path) -> bool:
    suffix = path.suffix.lower()
    try:
        if suffix in {".ini", ".cfg"} or path.name == ".mypy.ini":
            parser = ConfigParser()
            parser.read(path)
            return parser.has_section("mypy")
        if suffix == ".toml":
            if tomllib is None:
                return False
            with path.open("rb") as fh:
                data = tomllib.load(fh)
            return "mypy" in data.get("tool", {})
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    return False


def load_config(path: Path) -> MypyConfig:
    """Parse a mypy config file into the fields we care about."""
    cfg = MypyConfig(source=path)
    suffix = path.suffix.lower()
    if suffix in {".ini", ".cfg"} or path.name == ".mypy.ini":
        _load_ini_config(path, cfg)
    elif suffix == ".toml":
        _load_toml_config(path, cfg)
    else:
        raise ValueError(f"Unrecognised config file type: {path}")
    return cfg


def _load_ini_config(path: Path, cfg: MypyConfig) -> None:
    parser = ConfigParser()
    parser.read(path)

    try:
        main = parser["mypy"]
    except KeyError:
        return

    cfg.check_untyped_defs = _parse_bool(main.get("check_untyped_defs", "false"))
    exclude_raw = main.get("exclude")
    if exclude_raw:
        cfg.exclude_regex = _compile_exclude(exclude_raw)
    files_raw = main.get("files")
    if files_raw:
        cfg.files = _split_files(files_raw)
    mypy_path_raw = main.get("mypy_path")
    if mypy_path_raw:
        cfg.mypy_path = _split_files(mypy_path_raw)

    for section_name in parser.sections():
        if not section_name.startswith("mypy-"):
            continue
        section = parser[section_name]
        if _parse_bool(section.get("ignore_missing_imports", "false")):
            module = section_name[len("mypy-") :]
            cfg.ignored_modules.add(module)


def _load_toml_config(path: Path, cfg: MypyConfig) -> None:
    if tomllib is None:  # pragma: no cover
        raise RuntimeError(
            "Reading pyproject.toml requires tomllib (Python 3.11+) or tomli."
        )
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    mypy_tbl = data.get("tool", {}).get("mypy", {})
    if not mypy_tbl:
        return

    cfg.check_untyped_defs = bool(mypy_tbl.get("check_untyped_defs", False))

    exclude = mypy_tbl.get("exclude")
    if isinstance(exclude, list):
        cfg.exclude_regex = _compile_exclude("|".join(exclude))
    elif isinstance(exclude, str):
        cfg.exclude_regex = _compile_exclude(exclude)

    files = mypy_tbl.get("files")
    if isinstance(files, list):
        cfg.files = list(files)
    elif isinstance(files, str):
        cfg.files = _split_files(files)

    mypy_path = mypy_tbl.get("mypy_path")
    if isinstance(mypy_path, list):
        cfg.mypy_path = list(mypy_path)
    elif isinstance(mypy_path, str):
        cfg.mypy_path = _split_files(mypy_path)

    overrides = mypy_tbl.get("overrides", [])
    if isinstance(overrides, list):
        for override in overrides:
            if not isinstance(override, dict):
                continue
            if not override.get("ignore_missing_imports"):
                continue
            module = override.get("module")
            if isinstance(module, str):
                cfg.ignored_modules.add(module)
            elif isinstance(module, list):
                cfg.ignored_modules.update(m for m in module if isinstance(m, str))


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"true", "yes", "1", "on"}


def _split_files(value: str) -> list[str]:
    parts: list[str] = []
    for chunk in value.replace("\n", ",").split(","):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk.rstrip("/"))
    return parts


def _compile_exclude(pattern: str) -> re.Pattern[str]:
    """Compile a mypy-style exclude regex.

    Mypy accepts a single regex (often with ``(?x)`` verbose mode and ``|``
    alternation) or a list of regexes. The caller joins list form with ``|``.
    """
    return re.compile(pattern)
