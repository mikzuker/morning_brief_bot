#!/bin/bash
# Remove the morning brief. Keeps your briefs (~/MorningBrief) and config unless you pass --all.
set -uo pipefail
"$HOME/.local/bin/morning-brief" --remove-trigger 2>/dev/null || true
rm -f "$HOME/.local/bin/morning-brief" \
      "$HOME/.claude/skills/morning-brief" "$HOME/.claude/skills/morning-brief-setup"
if [ "${1:-}" = "--all" ]; then
  rm -rf "$HOME/.config/morning-brief" "$HOME/MorningBrief"
  echo "Removed everything, including your config and past briefs."
else
  echo "Removed. Your config (~/.config/morning-brief) and briefs (~/MorningBrief) are kept."
fi
