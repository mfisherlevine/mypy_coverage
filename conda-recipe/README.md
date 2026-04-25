# conda-forge recipe

This directory holds the conda-forge recipe (`meta.yaml`) used to seed and
update the package on conda-forge.

## How conda-forge publishing works

Conda-forge does **not** publish via a workflow in this repository. Once
the package has a feedstock, the conda-forge ecosystem handles new
releases automatically:

1. A new tag triggers `release.yml`, which publishes to PyPI.
2. The conda-forge bot (`regro-cf-autotick-bot`) polls PyPI, detects the
   new release, and opens a PR against
   `conda-forge/mypy-coverage-feedstock` that bumps `version` and
   `sha256` in the feedstock's `recipe/meta.yaml`.
3. A maintainer reviews the PR, waits for CI, and merges. The package
   is built on conda-forge's CI and pushed to `anaconda.org/conda-forge`.

So routine maintenance is: review and merge the bot PR. No action in
this repository is required for a normal release.

## First-time submission to conda-forge

This only needs to happen once.

1. Fork [`conda-forge/staged-recipes`](https://github.com/conda-forge/staged-recipes).
2. Copy this directory into the fork as
   `recipes/mypy-coverage/meta.yaml` (the recipe is the only file
   needed; do not copy this README).
3. Update the `sha256` in `meta.yaml` to match the current release on
   PyPI:
   ```sh
   curl -sL https://pypi.org/pypi/mypy-coverage/json \
     | python -c 'import json,sys; \
                  d=json.load(sys.stdin)["urls"]; \
                  t=[u for u in d if u["packagetype"]=="sdist"][0]; \
                  print(t["digests"]["sha256"])'
   ```
4. Open a PR titled `Add mypy-coverage`. The conda-forge maintainer
   team will review.
5. Once merged, a feedstock repo
   (`conda-forge/mypy-coverage-feedstock`) is created automatically and
   `mfisherlevine` is added as a maintainer. From this point onward,
   the autotick bot handles new releases.

## Updating this in-repo copy

This in-repo copy exists as documentation and as a reference seed for
the feedstock. It is **not** the source of truth once the feedstock
exists. Keep it loosely in sync with the feedstock when the feedstock
recipe changes in non-trivial ways (new dependency, build script
change, Python floor bump). Routine version/sha256 bumps don't need
to be mirrored here.

## Recipe quick-reference

- `noarch: python` because the package is pure Python with no
  C extensions.
- `host` dependencies are the build backend (`hatchling`), `pip`, and
  the Python interpreter. `run` only needs Python — the package has no
  third-party runtime dependencies.
- `test.commands` runs `mypy-coverage --version` and `--help` to confirm
  the entry point is wired up.
- `license: GPL-3.0-or-later` matches `pyproject.toml`. `license_family`
  is the conda-forge classifier (`GPL3`).
- `python_min` is set at the top via `{% set python_min = "3.11" %}`
  and used as `python {{ python_min }}` in `host` / `test.requires` and
  `python >={{ python_min }}` in `run`. This is conda-forge's
  recommended pattern for `noarch: python` recipes — it lets the
  central pinning machinery rebuild the package when the supported
  Python range shifts. If [pyproject.toml](../pyproject.toml) ever
  raises `requires-python`, bump `python_min` here in lockstep.
