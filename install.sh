#!/bin/bash
# Install the morning brief for this user (macOS). Safe to run again.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

say "1/4  Checking requirements"
command -v git >/dev/null || { echo "git missing: run 'xcode-select --install' first."; exit 1; }
command -v python3 >/dev/null || { echo "python3 missing: run 'xcode-select --install' first."; exit 1; }
CLAUDE="$(command -v claude || true)"
for c in "$HOME/.local/bin/claude" "$HOME/.claude/local/claude" /opt/homebrew/bin/claude /usr/local/bin/claude; do
  [ -z "$CLAUDE" ] && [ -x "$c" ] && CLAUDE="$c"
done
if [ -z "$CLAUDE" ]; then
  echo "Claude Code is not installed. Install it (see https://docs.claude.com/en/docs/claude-code),"
  echo "run 'claude' once to log in, then run this script again."
  exit 1
fi
echo "Claude Code: $CLAUDE"

say "2/4  Linking the skills into Claude Code"
mkdir -p "$HOME/.claude/skills"
ln -sfn "$REPO/skills/morning-brief"       "$HOME/.claude/skills/morning-brief"
ln -sfn "$REPO/skills/morning-brief-setup" "$HOME/.claude/skills/morning-brief-setup"
echo "Linked (a later 'git pull' in $REPO updates them)."

say "3/4  Adding the 'morning-brief' command"
chmod +x "$REPO/bin/morning-brief"
mkdir -p "$HOME/.local/bin"
ln -sfn "$REPO/bin/morning-brief" "$HOME/.local/bin/morning-brief"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.zshrc"
     export PATH="$HOME/.local/bin:$PATH"
     echo "Added ~/.local/bin to your PATH in ~/.zshrc (open a new Terminal window to use it)." ;;
esac

say "4/4  Setup: Claude will now ask which projects and folders to cover"
exec "$HOME/.local/bin/morning-brief" --setup
