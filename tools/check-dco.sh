#!/usr/bin/env bash
# DCO check: every commit in the range must carry a Signed-off-by trailer that
# matches the commit author. Run locally as: ./tools/check-dco.sh origin/main..HEAD
set -euo pipefail

range="${1:-origin/main..HEAD}"
fail=0

while IFS= read -r sha; do
  [ -z "$sha" ] && continue
  author_email="$(git log -1 --format='%ae' "$sha")"
  body="$(git log -1 --format='%B' "$sha")"

  if ! printf '%s' "$body" | grep -qiE '^Signed-off-by: .+ <.+@.+>'; then
    echo "MISSING sign-off: $sha $(git log -1 --format='%s' "$sha")"
    fail=1
    continue
  fi

  if ! printf '%s' "$body" | grep -qiE "^Signed-off-by: .+ <${author_email}>"; then
    echo "MISMATCHED sign-off: $sha expected <$author_email>"
    fail=1
  fi
done < <(git rev-list "$range")

if [ "$fail" -ne 0 ]; then
  echo
  echo "Fix with: git commit -s --amend   (or git rebase --signoff $range)"
  exit 1
fi
echo "DCO: all commits signed off"
