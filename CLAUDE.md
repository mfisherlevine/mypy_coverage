# mypy-coverage — repo guide for Claude Code

This file orients you (Claude) when working in this repository. The
human-facing documentation lives in [README.md](README.md); this file
is for in-repo automation conventions, gotchas, and pointers to skills.

## What this package is

A stdlib-only Python CLI + composite GitHub Action that reports mypy
annotation coverage. It is intentionally dependency-free at runtime —
**do not add any runtime dependencies** without an explicit conversation
with the maintainer. The `dev` extra carries `pytest`, `pytest-cov`,
`mypy`, `ruff`, and `pre-commit`.

Targets: Python **3.11+** (3.11, 3.12, 3.13 in CI).

## Layout

```
src/mypy_coverage/
  models.py        Dataclasses and status constants
  config.py        mypy.ini / setup.cfg / pyproject.toml parsing
  discovery.py     File walking, exclude-regex matching
  scanner.py       AST walk, function/method/class classification
  silent_any.py    --silent-any detection
  report.py        build_report + per-file aggregation
  render.py        text / json / markdown / github renderers
  cli.py           argparse and main entry point
tests/             pytest suite + tests/fixtures (deliberately broken,
                   excluded from lint/format/mypy)
conda-recipe/      conda-forge meta.yaml (see conda-recipe/README.md)
action.yml         GitHub composite action wrapping the CLI
.github/workflows/ ci.yml + release.yml
```

`tests/fixtures/` contains intentionally unannotated and one
syntactically broken Python file. Pre-commit, ruff, and mypy all
exclude it. **Do not lint or format anything under `tests/fixtures/`.**

## Dev commands

```sh
pip install -e '.[dev]'
pre-commit install
pre-commit run --all-files
pytest -ra --cov=mypy_coverage --cov-report=term --cov-branch
mypy                      # strict; src/mypy_coverage and tests must pass
mypy-coverage             # dogfood: must report 100% self-coverage
```

The package is dogfooded: `mypy-coverage` run against itself **must**
report 100% (`--threshold 100`). CI enforces this in the `self-coverage`
job. Any new code you add must be fully annotated, otherwise the gate
trips on the next push.

## CI gates (required for merge to `main`)

All jobs in [.github/workflows/ci.yml](.github/workflows/ci.yml) must pass:

| Job | What it checks |
| --- | --- |
| `pre-commit` | `ruff` lint+format, `mypy --strict`, hygiene hooks. |
| `test` | `pytest` on Python 3.11 / 3.12 / 3.13, uploads to Codecov. |
| `self-coverage` | `mypy-coverage --threshold 100` on its own source. Posts a sticky markdown comment to PRs. |
| `action-smoke-test` | Runs the composite action end-to-end against `src/mypy_coverage` and asserts `percent-fully-typed = 100.0`. |

The smoke test asserting 100% is **load-bearing**: if you regress the
package's self-coverage you both fail the gate and fail the smoke test.

## Style conventions

- Code style is enforced by `ruff` (lint + format, line-length 100,
  double-quoted strings). Configuration is in
  [pyproject.toml](pyproject.toml) under `[tool.ruff]`. Don't fight it.
- Type checking is `mypy --strict` (`pyproject.toml` → `[tool.mypy]`).
  Everything in `src/` and `tests/` must type-check cleanly.
- The project follows the user's broader preferences: no needless
  comments, no docstrings explaining the obvious, no `# type: ignore`
  unless genuinely necessary, no premature abstractions.
- Imports use `from __future__ import annotations` at module top.
- Public API is re-exported from
  [src/mypy_coverage/__init__.py](src/mypy_coverage/__init__.py); keep
  `__all__` and the imports in sync with what's actually public.

## Versioning and release

The version lives in **two** places that must stay in lockstep:

- [pyproject.toml](pyproject.toml) → `[project] version`
- [src/mypy_coverage/__init__.py](src/mypy_coverage/__init__.py) → `__version__`

The README also references the current version in `pip install
"git+...@vX.Y.Z"` examples and the `uses: mfisherlevine/mypy_coverage@vX.Y.Z`
example; bump those when shipping a release.

The release flow is:

1. Bump the version in both files (and README examples).
2. Land the bump on `main`.
3. Tag `vX.Y.Z` and push the tag.
4. [.github/workflows/release.yml](.github/workflows/release.yml)
   builds the wheel, verifies its filename matches the tag, and
   publishes to PyPI via Trusted Publishing (no API token needed).
5. Conda-forge's `regro-cf-autotick-bot` opens a feedstock PR within
   ~24h. Review and merge it.

See [.claude/skills/release/SKILL.md](.claude/skills/release/SKILL.md)
for the full release walkthrough.

## conda-forge

The conda-forge recipe is checked in at
[conda-recipe/meta.yaml](conda-recipe/meta.yaml). See
[conda-recipe/README.md](conda-recipe/README.md) for the first-time
submission process and how the autotick bot handles ongoing releases.

## GitHub Actions versions

The workflows pin only major versions (e.g. `actions/checkout@v6`,
`actions/setup-python@v6`, `actions/upload-artifact@v7`,
`actions/download-artifact@v8`, `peter-evans/find-comment@v4`,
`peter-evans/create-or-update-comment@v5`). These are the Node-24
generation; using older majors triggers Node 20 deprecation warnings.
When the next Node bump happens, update the four `actions/*` ones and
the two `peter-evans/*` ones together.

## Things to avoid

- **Don't** add runtime dependencies. Stdlib-only is a feature.
- **Don't** edit anything under `tests/fixtures/` to "fix" it — the
  brokenness is the point.
- **Don't** lower the `--threshold 100` self-coverage gate to paper
  over a missed annotation; just annotate.
- **Don't** amend an existing tag. If a release is bad, ship a new
  patch version.
- **Don't** lint/format generated artifacts: `.coverage`, `.mypy_cache`,
  `.pytest_cache`, `.ruff_cache`, `dist/`. Discovery already skips these.

## Available skills

- [/release](.claude/skills/release/SKILL.md) — cut a new PyPI release.
- [/bump-deps](.claude/skills/bump-deps/SKILL.md) — refresh pinned
  GitHub Actions and pre-commit hook versions.
