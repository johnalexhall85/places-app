#!/bin/bash
# Package a skill folder as a claude.ai-importable zip (skill folder at the zip root).
#   skills/build_skill_zip.sh chip-nofo-recipient-profile [dist-dir]
# Excludes tests, caches, venvs, and fixtures; the zip holds SKILL.md, scripts/, assets/, references/.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
name="$1"; dist="${2:-$here/dist}"
[ -f "$here/$name/SKILL.md" ] || { echo "no $here/$name/SKILL.md" >&2; exit 2; }
mkdir -p "$dist"; out="$dist/$name.zip"; rm -f "$out"
(cd "$here" && zip -qr "$out" "$name" -x "$name/tests/*" "*/__pycache__/*" "*.pyc" "$name/.venv/*" "*/.DS_Store")
unzip -l "$out" | tail -n +4 | head -n -2 | awk '{print $4}'
echo "wrote $out ($(du -h "$out" | cut -f1))"
