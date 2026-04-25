---
name: bump-deps
description: Refresh pinned versions of GitHub Actions and pre-commit hooks. Use when CI starts emitting Node-version deprecation warnings or the user says "bump the actions" / "update pre-commit hooks".
---

# /bump-deps — refresh pinned action and hook versions

This package has two places where third-party tool versions are pinned:

1. **GitHub Actions** in
   [.github/workflows/ci.yml](../../../.github/workflows/ci.yml),
   [.github/workflows/release.yml](../../../.github/workflows/release.yml),
   and [action.yml](../../../action.yml). Pinned to major-version tags.
2. **pre-commit hooks** in
   [.pre-commit-config.yaml](../../../.pre-commit-config.yaml). Pinned
   to specific `rev:` tags (a hash or `vX.Y.Z`).

Use this skill when the user asks to "bump the actions" or when CI is
emitting Node-version deprecation warnings.

## GitHub Actions — current major versions

The actions used and their current Node-24 majors (as of the last
bump):

| Action | Current pin | Notes |
| --- | --- | --- |
| `actions/checkout` | `v6` | Node 24 |
| `actions/setup-python` | `v6` | Node 24 |
| `actions/upload-artifact` | `v7` | Node 24 |
| `actions/download-artifact` | `v8` | Node 24 |
| `peter-evans/find-comment` | `v4` | |
| `peter-evans/create-or-update-comment` | `v5` | |
| `codecov/codecov-action` | `v6` | |
| `pre-commit/action` | `v3.0.1` | Pinned to exact patch |
| `pypa/gh-action-pypi-publish` | `release/v1` | Floating tag, intentional |

`pypa/gh-action-pypi-publish@release/v1` is **deliberately** a floating
ref — that's PyPA's recommended way to consume the publish action so
that security patches land without a manual bump. Don't pin it tighter.

### How to bump

For each action, look up the latest major:

```sh
gh api repos/<owner>/<action>/releases/latest --jq '.tag_name'
```

Then update every reference in the three workflow / action files.
Bumps must be applied **everywhere** — `ci.yml`, `release.yml`, and
`action.yml` can all reference the same action.

```sh
git grep -n 'actions/checkout@'
git grep -n 'actions/setup-python@'
git grep -n 'actions/upload-artifact@'
git grep -n 'actions/download-artifact@'
git grep -n 'peter-evans/'
```

After bumping, push the change on a branch and verify CI is green —
including the `action-smoke-test` job, which exercises the composite
action end-to-end.

## pre-commit hooks

```sh
pre-commit autoupdate
```

This rewrites `.pre-commit-config.yaml` in place with the latest tags
of each repo. After running:

```sh
pre-commit run --all-files
```

If a new version of any hook surfaces lint errors, **fix the errors**;
do not pin back to the older version unless the user explicitly says
so. (Old-version pins rot quickly and accumulate.)

The `pre-commit/mirrors-mypy` hook tracks mypy releases. If it bumps
mypy and that exposes new strict-mode failures, the right move is
usually to add the missing annotations or refactor — `# type: ignore`
should be a last resort.

## Don'ts

- **Don't** bump only some occurrences of an action. Mismatched majors
  inside one repo cause confusing CI failures.
- **Don't** pin `pypa/gh-action-pypi-publish` to a tighter ref.
- **Don't** silence mypy regressions exposed by a hook bump with
  `# type: ignore` without first trying to fix them properly.
- **Don't** bump and ship in the same PR as functional changes — keep
  dep bumps isolated so a regression bisects cleanly.
