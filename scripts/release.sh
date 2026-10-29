#!/usr/bin/env bash

set -euo pipefail

fail() {
  printf 'Release aborted: %s\n' "$*" >&2
  exit 1
}

valid_version() {
  [[ "$1" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]
}

version_greater() {
  local -a left right
  local i
  IFS=. read -r -a left <<< "$1"
  IFS=. read -r -a right <<< "$2"
  for i in 0 1 2; do
    if (( left[i] > right[i] )); then return 0; fi
    if (( left[i] < right[i] )); then return 1; fi
  done
  return 1
}

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
for command in git gh make; do
  command -v "$command" >/dev/null || fail "$command is required."
done

phase="preflight checks"
trap 'printf "Release stopped during %s. Completed commits, tags and pushes have been kept; inspect their state before retrying.\n" "$phase" >&2' ERR

[[ -z "$(git status --porcelain)" ]] || fail "Commit or stash all changes, including untracked files, first."
branch=$(git symbolic-ref --quiet --short HEAD) || fail "Check out a branch before releasing."
remote=${RELEASE_REMOTE:-origin}
remote_url=$(git remote get-url --push "$remote")
git var GIT_AUTHOR_IDENT >/dev/null
git var GIT_COMMITTER_IDENT >/dev/null
gh auth status
repository=$(gh repo view "$remote_url" --json nameWithOwner --jq .nameWithOwner)

current_version=$(cat VERSION)
current_base=${current_version%-dev}
valid_version "$current_base" || fail "VERSION must contain X.Y.Z or X.Y.Z-dev."
release_version=${RELEASE_VERSION:-}
if [[ -z "$release_version" ]]; then
  printf 'Release version [%s]: ' "$current_base" >&2
  IFS= read -r release_version || fail "Unable to read a release version from stdin; specify RELEASE_VERSION."
  release_version=${release_version:-$current_base}
fi
valid_version "$release_version" || fail "RELEASE_VERSION must be a stable X.Y.Z version."
if version_greater "$current_base" "$release_version"; then
  fail "RELEASE_VERSION cannot be lower than $current_base."
fi
IFS=. read -r major minor patch <<< "$release_version"
next_version=${NEXT_VERSION:-$major.$minor.$((patch + 1))-dev}
next_base=${next_version%-dev}
[[ "$next_version" == *-dev ]] && valid_version "$next_base" || fail "NEXT_VERSION must contain X.Y.Z-dev."
version_greater "$next_base" "$release_version" || fail "NEXT_VERSION must be greater than $release_version."

for tag in "$release_version" "v$release_version"; do
  if git show-ref --verify --quiet "refs/tags/$tag"; then
    fail "Tag $tag already exists locally."
  fi
done
remote_tags=$(git ls-remote --tags "$remote_url" "refs/tags/$release_version" "refs/tags/v$release_version")
[[ -z "$remote_tags" ]] || fail "A tag for $release_version already exists on $remote."
if gh release view "$release_version" --repo "$repository" >/dev/null 2>&1; then
  fail "A GitHub Release for $release_version already exists."
fi
git fetch --no-tags "$remote_url" "refs/heads/$branch"
git merge-base --is-ancestor FETCH_HEAD HEAD || fail "The current branch is behind or diverged from $remote/$branch. Pull its changes first."

printf 'Releasing %s from %s to %s; next development version: %s\n' "$release_version" "$branch" "$remote" "$next_version"
phase="tests"
PYTHONDONTWRITEBYTECODE=1 make test
[[ -z "$(git status --porcelain)" ]] || fail "Tests changed the working tree; inspect the changes before releasing."

phase="the release commit and tag"
printf '%s\n' "$release_version" > VERSION
for script in bin/php-compat-check docker/bin/php-compat-check; do
  [[ "$(bash "$script" --version)" == "php-compat-check $release_version" ]] || fail "Version check failed for $script."
done
if ! git diff --quiet -- VERSION; then
  git add -- VERSION
  git commit -m "Release $release_version"
fi
git tag -a "$release_version" -m "Release $release_version"

phase="pushing the release commit and tag"
git push --atomic --no-follow-tags "$remote" "HEAD:refs/heads/$branch" "refs/tags/$release_version"

phase="creating the GitHub Release"
# The tag workflow may already have created this release while the push completed.
if ! gh release create "$release_version" --repo "$repository" --verify-tag --draft --generate-notes --title "$release_version"; then
  gh release view "$release_version" --repo "$repository" >/dev/null
fi

phase="the next development commit"
printf '%s\n' "$next_version" > VERSION
git add -- VERSION
git commit -m "Start $next_version development"
git push --no-follow-tags "$remote" "HEAD:refs/heads/$branch"

printf 'Release %s pushed; VERSION is now %s. GitHub Actions publishes the release after building and verifying its assets.\n' "$release_version" "$next_version"
