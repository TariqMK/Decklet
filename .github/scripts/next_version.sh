#!/usr/bin/env bash
# Prints the next release tag. Existing tags (git tags and GitHub release tags) are read from stdin, one per line.
# Usage: next_version.sh <major|minor|patch>            -> vX.Y.Z (main)
#        next_version.sh <major|minor|patch> <branch>   -> vX.Y.Z-label.N (branch build)
set -euo pipefail

bump="${1:-}"
branch="${2:-}"
tags=$(cat)

# Main's next version counts plain vX.Y.Z tags only, so pre-release tags never move it.
latest=$(grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' <<< "$tags" | sort -V | tail -n 1 || true)
IFS=. read -r major minor patch <<< "${latest#v}"
major=${major:-0} minor=${minor:-0} patch=${patch:-0}

case "$bump" in
  major) base="$((major + 1)).0.0" ;;
  minor) base="$major.$((minor + 1)).0" ;;
  patch) base="$major.$minor.$((patch + 1))" ;;
  *) echo "Usage: next_version.sh <major|minor|patch> [branch]" >&2; exit 1 ;;
esac

if [ -z "$branch" ]; then
  echo "v$base"
  exit 0
fi

# Branch label: lowercase, anything but letters and digits becomes a hyphen, no repeats or end hyphens, 30 characters.
label=$(printf '%s' "$branch" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' | cut -c1-30 | sed -E 's/-+$//')
if [ -z "$label" ]; then
  echo "Branch name \"$branch\" has no letters or digits to make a label from." >&2
  exit 1
fi

# N is one more than the highest existing build number for this base version and label.
base_re=${base//./\\.}
n=$(grep -E "^v${base_re}-${label}\.[0-9]+$" <<< "$tags" | sed -E 's/.*\.([0-9]+)$/\1/' | sort -n | tail -n 1 || true)
echo "v$base-$label.$(( ${n:-0} + 1 ))"
