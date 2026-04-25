---
name: release
description: Cut a new mypy-coverage release. Bumps the version in pyproject.toml and __init__.py, updates README examples, opens a PR, and (after merge) tags and pushes. PyPI publish runs automatically from the tag; conda-forge follows via the autotick bot.
---

# /release — cut a new mypy-coverage release

Use this skill when the user asks to "cut a release", "ship X.Y.Z",
"bump the version", or similar. Do **not** start tagging or pushing
without confirming the version number with the user first.

## Inputs you need

Ask the user for, if not supplied:

1. The new version (`X.Y.Z`). Use semver:
   - **patch** — bug fixes, internal cleanup, no behavior changes
   - **minor** — new flags, new outputs, new public API surface
   - **major** — only after `1.0`; right now everything is `0.x`
2. Whether they want you to push the tag yourself or stop after the
   PR merges so they can tag manually. Default: stop after merge.

## Steps

### 1. Verify clean state

```sh
git status
git fetch origin
git log --oneline origin/main..HEAD   # should be empty if on main
```

If on a feature branch, that's fine — the bump itself goes via PR.

### 2. Read current version

The version lives in two files that must stay in lockstep:

- [pyproject.toml](../../../pyproject.toml) → `[project] version`
- [src/mypy_coverage/\_\_init\_\_.py](../../../src/mypy_coverage/__init__.py) → `__version__`

Confirm both currently show the same version. If they diverge, fix
that first as a separate concern before continuing.

### 3. Bump the version

Update **all** of these to the new version:

- `pyproject.toml` → `version = "X.Y.Z"`
- `src/mypy_coverage/__init__.py` → `__version__ = "X.Y.Z"`
- `README.md` — search for the previous version string. There are
  references in the install snippets (`@v0.2.3` git tag, `mfisherlevine/mypy_coverage@v0.2.3`
  action example, and possibly inside `version` doc).
- `conda-recipe/meta.yaml` → `{% set version = "X.Y.Z" %}`. Set the
  `sha256` placeholder back to all zeros — it'll be filled in once the
  PyPI release exists. (This in-repo recipe is informational; the
  authoritative recipe lives in the conda-forge feedstock.)

Run a sanity grep for any remaining occurrences of the old version:

```sh
git grep -nF "0.2.3"   # replace with the actually-old version
```

Hits in `tests/`, `CHANGELOG.md`, or historical docs are fine; hits in
live install instructions or pyproject metadata are not.

### 4. Run the local checks

```sh
pre-commit run --all-files
pytest -ra
mypy
mypy-coverage --threshold 100
```

All four must pass before you push.

### 5. Open a PR

```sh
git checkout -b release/vX.Y.Z
git add -A
git commit -m "release: vX.Y.Z"
git push -u origin release/vX.Y.Z
gh pr create --title "release: vX.Y.Z" --body "..."
```

PR body should be a short bulleted list of what changed since the last
release (look at `git log vPREVIOUS..HEAD --oneline` for the raw
material; rewrite into user-facing language).

### 6. After merge — tag and push

This step is **destructive on rollback** (you can't recall a tag once
it's pushed; if a release goes bad, ship a new patch). Confirm with the
user before pushing the tag.

```sh
git checkout main
git pull
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin vX.Y.Z
```

Pushing the tag triggers
[.github/workflows/release.yml](../../../.github/workflows/release.yml),
which:

1. Builds the wheel with `python -m build`.
2. Verifies the wheel filename embeds the tag's version.
3. Uploads to PyPI via Trusted Publishing (no API token).

Watch it:

```sh
gh run watch
```

### 7. Conda-forge follow-up

Within ~24h, `regro-cf-autotick-bot` will open a PR against
`conda-forge/mypy-coverage-feedstock` bumping the version and sha256.
Tell the user to expect this; usually it just needs reviewing and
merging once CI on the feedstock passes.

If the package isn't yet on conda-forge, point them at
[conda-recipe/README.md](../../../conda-recipe/README.md) for the
one-time staged-recipes submission process.

## Don'ts

- **Don't** push a tag before the bump PR is merged — the tag would
  point at a commit that's not on `main`.
- **Don't** amend or force-push a published tag. Ship a new patch
  version instead.
- **Don't** publish to PyPI manually. The Trusted Publishing flow in
  `release.yml` is the only sanctioned path; manual uploads bypass the
  tag-vs-wheel-version check.
- **Don't** skip the dogfood check (`mypy-coverage --threshold 100`).
  Releases that fail self-coverage are the worst possible advertising.
