#!/usr/bin/env bash
set -euo pipefail
COMMIT="9beeb721c2af551bacaab827a76bddaecaa0ca5e"
ROOT="${1:-upstream}"
if [ ! -d "$ROOT/.git" ]; then
  git clone https://github.com/ashishpatel26/500-AI-Agents-Projects.git "$ROOT"
fi
git -C "$ROOT" fetch origin "$COMMIT"
git -C "$ROOT" checkout "$COMMIT"
ACTUAL="$(git -C "$ROOT" rev-parse HEAD)"
if [ "$ACTUAL" != "$COMMIT" ]; then
  echo "Commit verification failed: $ACTUAL" >&2
  exit 1
fi
echo "Pinned actual upstream agents at $ACTUAL"
