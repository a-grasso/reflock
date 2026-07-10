#!/usr/bin/env bash
# Install reflock onto PATH as a single command, independent of any project.
#
#   ./install.sh                          # clone (or update) and install
#   REFLOCK_SRC=~/Projects/reflock ./install.sh   # symlink an existing checkout instead of cloning
#
# Re-running is safe: with a clone, it fast-forwards; with REFLOCK_SRC, it just
# re-links. Override the clone location with REFLOCK_HOME, the bin dir with
# REFLOCK_BIN_DIR (default ~/.local/bin).
set -euo pipefail

REPO_SSH="git@github.com:a-grasso/reflock.git"
REPO_HTTPS="https://github.com/a-grasso/reflock.git"
CLONE_DIR="${REFLOCK_HOME:-$HOME/.local/share/reflock}"
BIN_DIR="${REFLOCK_BIN_DIR:-$HOME/.local/bin}"

if [ -n "${REFLOCK_SRC:-}" ]; then
  SRC="$(cd "$REFLOCK_SRC" && pwd)"
  [ -f "$SRC/reflock.py" ] || { echo "no reflock.py under $SRC" >&2; exit 1; }
elif [ -d "$CLONE_DIR/.git" ]; then
  git -C "$CLONE_DIR" pull --ff-only
  SRC="$CLONE_DIR"
else
  git clone --depth 1 "$REPO_SSH" "$CLONE_DIR" 2>/dev/null \
    || git clone --depth 1 "$REPO_HTTPS" "$CLONE_DIR"
  SRC="$CLONE_DIR"
fi

mkdir -p "$BIN_DIR"
chmod +x "$SRC/reflock.py"
ln -sf "$SRC/reflock.py" "$BIN_DIR/reflock"

echo "reflock -> $SRC/reflock.py"
case ":$PATH:" in
  *":$BIN_DIR:"*) echo "on PATH — try: reflock check" ;;
  *) echo "add to PATH: export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac
