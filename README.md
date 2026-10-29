# Morning brief

Each morning, Claude reads your Claude Code chats from the previous working day, checks what
came of them in your project folders (code, slides, papers, notes…), and writes a short brief:
what you worked on, sorted by type, what's new in your folders, where you left off, and the
top 3 things to do today. Everything runs on your Mac with your own Claude account. Nothing in
your folders is changed.

## Requirements

- macOS with the command line tools (`xcode-select --install`)
- [Claude Code](https://docs.claude.com/en/docs/claude-code), installed and logged in (run `claude` once).
The Claude desktop app is not needed.

## Install

```bash
git clone https://github.com/mikzuker/morning-brief.git ~/.morning-brief
~/.morning-brief/install.sh
```

The installer links the skills into Claude Code, adds the `morning-brief` command, and starts
a short setup chat where Claude asks:

1. whether it may read your Claude Code chats,
2. your projects, and for each one its folders (code, slides, papers, notes, results),
3. whether the brief should start **automatically** (the first time you open your Mac after e.g.

   07:00, once a day) or **manually** (`morning-brief` in Terminal),
4. whether to open the brief as a file or in Terminal with a follow-up chat.

## Use

| Command                             | What it does                                               |
| ----------------------------------- | ---------------------------------------------------------- |
| `morning-brief`                     | Briefs for all projects (shows today's if already written) |
| `morning-brief "<My_Project_Name>"` | One project                                                |
| `morning-brief --print`             | Print the brief in Terminal instead of opening it          |
| `morning-brief --yesterday`         | Yesterday's brief, from the cache                          |
| `morning-brief --refresh`           | Write today's brief again (re-explores everything)         |
| `morning-brief --setup`             | Change projects, folders or the start method               |
| `morning-brief --list`              | Show configured projects                                   |

Briefs are cached in `~/MorningBrief/<project>/YYYY-MM-DD.md` for two days: calling `morning-brief`  
again during the day shows the cached brief instantly, without exploring project folders and chats again. On the third day the brief is deleted  
(change with `keep_days` in the config). Two small files outlive the cache: `.seen.json` (what
earlier briefs said about each file, so unchanged files are never read again) and `.carryover.md`
(the last brief's top 3 and open threads, so the next brief can check what got done, e.g. after a
weekend).

## Update / uninstall

```bash
cd ~/.morning-brief && git pull      # update
~/.morning-brief/uninstall.sh        # remove (keeps config and briefs; add --all to delete them)
```

## Good to know

- **Cost:** each brief is one Claude Code run on your plan (default model: Sonnet; change `model`
in `~/.config/morning-brief/config.json`).
- **Folders in Documents, Desktop or iCloud:** the first automatic run may trigger a macOS prompt
("python3 would like to access…"). Allow it once, or the brief will skip those folders.
- **Brief place:** Briefs stay in `~/MorningBrief`.
- **Each file is read once:** a file's content goes into the brief only when it is new or was edited.
Later, if a chat mentions it again, the brief reuses what an earlier brief said about it
(kept in `~/MorningBrief/<project>/.seen.json`, which outlives the two-day brief cache).
- **Articles (PDF):** text is read with macOS's built-in PDF engine (no install needed); for each new
paper the brief gets the title, abstract and conclusions. Scanned PDFs without a text layer are
listed by name only.
- **Keynote decks:** text is extracted on a best-effort basis; if a deck shows up empty, the brief
uses its name and date only.

## Files

```
bin/morning-brief                         the command (also what the login job runs)
skills/morning-brief/SKILL.md             how Claude writes the brief
skills/morning-brief/scripts/collect.py   gathers chats, git and new files (read-only)
skills/morning-brief-setup/SKILL.md       the first-run interview
install.sh / uninstall.sh
config.example.json
```
