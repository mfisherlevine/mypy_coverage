# mypy-coverage

A fast, stdlib-only CLI that reports how much of a Python codebase is
actually type-checked by mypy.

The catch with mypy's default `check_untyped_defs = False` is that **fully
unannotated functions are silently skipped** — their bodies are not analysed
and any real type errors inside them are invisible. `mypy-coverage`
enumerates exactly these, plus files covered by the `exclude` pattern, and
computes aggregate coverage percentages.

## Install

No dependencies. Copy `mypy_coverage.py` anywhere on your PATH (and rename
to `mypy-coverage` if you like):

```sh
cp mypy_coverage.py ~/bin/mypy-coverage
chmod +x ~/bin/mypy-coverage
```

Requires Python 3.11+ (for `tomllib`). Python 3.10 works if you `pip
install tomli`.

## Usage

```sh
# Scan current project (auto-detect config)
mypy-coverage

# Scan specific paths
mypy-coverage src/ tests/

# Fail CI if body-checked coverage is below 85%
mypy-coverage --threshold 85

# Full list of every unannotated definition
mypy-coverage --list

# List partially annotated ones too
mypy-coverage --list --list-partial

# Machine-readable output
mypy-coverage --format json

# GitHub Actions annotations
mypy-coverage --format github

# Flag imports that decay to Any
mypy-coverage --silent-any
```

## What counts as "covered"?

Each function, method, or class is placed in one bucket:

| Status        | Meaning                                                                              |
| ------------- | ------------------------------------------------------------------------------------ |
| `annotated`   | Every param (excluding `self`/`cls`) and the return type are annotated.              |
| `partial`     | At least one annotation. Mypy **does** check the body; missing types become `Any`.   |
| `unannotated` | Zero annotations. Mypy **skips** the body when `check_untyped_defs = False`.         |
| `excluded`    | File matches the mypy `exclude` regex; mypy never sees it.                           |

Two coverage metrics are reported:

- **body-checked by mypy** = `(annotated + partial) / (total - excluded)` —
  the fraction of definitions whose bodies mypy analyses.
- **fully annotated** = `annotated / (total - excluded)` — stricter; what
  you'd get under `disallow_untyped_defs`.

## Config discovery

Walks up from the current directory looking for, in order:

1. `mypy.ini` / `.mypy.ini`
2. `setup.cfg` (with a `[mypy]` section)
3. `pyproject.toml` (with a `[tool.mypy]` table)

The tool reads:

- `check_untyped_defs` — affects how unannotated bodies are treated
- `exclude` — regex of paths mypy skips
- `files` and `mypy_path` — default set of paths to scan
- `ignore_missing_imports` per-module — powers `--silent-any`

If no config is found, the current directory is scanned with mypy defaults.

## Silent-Any detection (`--silent-any`)

A best-effort scan for syntactic patterns that usually decay to `Any` even
when the surrounding code *looks* annotated:

- **`ignored-import`** — a symbol imported from a module configured with
  `ignore_missing_imports = True`. Everything that symbol names is `Any`.
- **`untyped-decorator`** — a function decorated with a name imported from
  an ignored module. The decorator can silently erase the wrapped
  function's return type.
- **`type-ignore`** — any `# type: ignore` comment.

True "silent Any" detection (types that collapse to Any during mypy's
semantic analysis) requires actually running mypy; see the `--deep`
roadmap note below.

## Output formats

- `text` (default) — human-readable summary, per-file table, optional
  listings
- `json` — complete machine-readable dump including per-definition records
- `markdown` — suitable for pasting in PRs and issues
- `github` — `::warning` / `::notice` annotations for GitHub Actions

## CI use

```yaml
- name: mypy coverage
  run: |
    python3 mypy_coverage.py \
      --threshold 85 \
      --format github
```

Exit codes:

- `0` — scan succeeded and, if `--threshold` was given, coverage met it
- `1` — coverage below threshold
- `2` — invalid arguments or missing config/paths

## Limitations and roadmap

- The scan is syntactic. It does **not** resolve imports, so a function
  with an annotation that references an unresolvable name is still counted
  as annotated. Running mypy itself is the only way to catch that.
- `--silent-any` is heuristic. It won't catch every path to `Any` — in
  particular, `Any` introduced by calling an untyped function returning
  `Any` is invisible without running mypy.
- Possible future flag `--deep`: shell out to `mypy --disallow-any-unimported
  --disallow-any-decorated` and merge the diagnostics for a more thorough
  silent-Any check.

## License

TBD (add a `LICENSE` file before the first tagged release).
