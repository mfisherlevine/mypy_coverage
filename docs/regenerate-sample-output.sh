#!/usr/bin/env bash
#
# Recipe to regenerate docs/sample-output.png — the screenshot embedded
# in the README's "Sample report" section.
#
# Re-run this if the text-format renderer changes shape (column widths,
# section headers, color thresholds, etc.) and the screenshot drifts.
#
# What this script does:
#   1. Builds a small demo project under /tmp/mc_demo by copying a
#      curated subset of tests/fixtures/, plus a hand-written mypy.ini
#      that excludes legacy/. The mix is chosen to exercise every
#      visual element of the report:
#        - main coverage in green  (>=90%)        : src/core.py + src/api.py
#        - per-file gaps row       (yellow row)   : src/utils.py at 77.8%
#        - excluded section in red (<70%)         : legacy/*
#        - parse-error footer      (yellow)       : src/parser.py
#        - config-discovery line                  : /tmp/mc_demo/mypy.ini
#   2. Runs `mypy-coverage --list .` (the trailing `.` is required —
#      without it, the tool only walks the `files = src` paths from
#      mypy.ini and the excluded section silently disappears).
#   3. Prints next-step instructions for taking the screenshot.
#
# Usage:
#   docs/regenerate-sample-output.sh
#   # ...take the screenshot, save as docs/sample-output.jpg...
#
# Save as JPG (not PNG) — Retina screenshots of a terminal land around
# 800 KB as PNG, over the pre-commit large-files limit (500 KB). A
# normal-quality JPG of the same image is ~300 KB and the colour
# differences are imperceptible. Avoid PNG palette quantisation (e.g.
# Pillow's `quantize(colors=N)`) — at low colour counts the green/red
# coverage percentages drift to muddy off-shades.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FX="$REPO_ROOT/tests/fixtures"
DEMO=/tmp/mc_demo

rm -rf "$DEMO"
mkdir -p "$DEMO/src" "$DEMO/legacy"

cp "$FX/fully_annotated.py"   "$DEMO/src/core.py"
cp "$FX/fully_annotated.py"   "$DEMO/src/api.py"
cp "$FX/nested.py"            "$DEMO/src/utils.py"
cp "$FX/syntax_broken.py"     "$DEMO/src/parser.py"
cp "$FX/fully_unannotated.py" "$DEMO/legacy/old_loader.py"
cp "$FX/exact_50pct.py"       "$DEMO/legacy/old_text.py"

cat > "$DEMO/mypy.ini" <<'EOF'
[mypy]
files = src
exclude = ^legacy/
strict = True
EOF

cd "$DEMO"

cat <<MSG
Demo project built at $DEMO.
Now in a clean terminal window (dark theme, ~90 cols wide):

  PS1='\$ '              # bash, or
  PROMPT='\$ '           # zsh
  cd $DEMO
  clear
  mypy-coverage --list .

Then screenshot just the terminal contents and save as
$REPO_ROOT/docs/sample-output.jpg (JPG keeps the file size under the
pre-commit 500 KB limit without crushing the green/red colours).

Previewing the output now:
----------------------------------------------------------------------
MSG

mypy-coverage --color always --list .
