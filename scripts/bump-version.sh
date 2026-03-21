#!/usr/bin/env bash
set -euo pipefail

# Bump the version in pyproject.toml and create a git tag.
#
# Usage:
#   ./scripts/bump-version.sh 1.2.0        # set exact version
#   ./scripts/bump-version.sh patch         # 1.0.0 → 1.0.1
#   ./scripts/bump-version.sh minor         # 1.0.0 → 1.1.0
#   ./scripts/bump-version.sh major         # 1.0.0 → 2.0.0

PYPROJECT="pyproject.toml"

current=$(grep -m1 '^version' "$PYPROJECT" | sed 's/version = "\(.*\)"/\1/')
if [ -z "$current" ]; then
    echo "error: could not read current version from $PYPROJECT" >&2
    exit 1
fi

bump_part() {
    local IFS=.
    read -r major minor patch <<< "$current"
    case "$1" in
        major) echo "$((major + 1)).0.0" ;;
        minor) echo "${major}.$((minor + 1)).0" ;;
        patch) echo "${major}.${minor}.$((patch + 1))" ;;
    esac
}

arg="${1:?Usage: bump-version.sh <major|minor|patch|X.Y.Z>}"

case "$arg" in
    major|minor|patch) new=$(bump_part "$arg") ;;
    [0-9]*.[0-9]*.[0-9]*) new="$arg" ;;
    *) echo "error: argument must be major, minor, patch, or a semver string" >&2; exit 1 ;;
esac

# Update pyproject.toml
sed -i.bak "s/^version = \".*\"/version = \"${new}\"/" "$PYPROJECT"
rm -f "${PYPROJECT}.bak"

echo "bumped ${current} → ${new}"
echo ""
echo "next steps:"
echo "  git add pyproject.toml"
echo "  git commit -m \"release: v${new}\""
echo "  git tag v${new}"
echo "  git push origin main --tags"
