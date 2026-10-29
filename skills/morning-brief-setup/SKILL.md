---
name: morning-brief-setup
description: First-run setup and later changes for the morning brief. Interviews the user about their projects (each project can span several folders, e.g. code, slides, papers), how the brief should start (automatically on the first wake each morning, or by a command), and writes ~/.config/morning-brief/config.json. Use when the user runs `morning-brief --setup`, asks to set up or change their morning brief, or when no config exists yet.
---

# Morning brief setup

You are setting up the user's morning brief. Keep it friendly and quick: one question at a time,
always propose a sensible default, and do the looking-around yourself instead of asking the user
to type things you can find. Use the AskUserQuestion tool for choices when it is available.

Files involved:
- Config: `~/.config/morning-brief/config.json` (the only file you write).
- Launcher: `morning-brief` on the PATH (in this repo: `bin/morning-brief`).

If a config already exists, read it, show a short summary of it, and ask what to change. Then
change only that and skip to step 6.

## 1. Explain in two lines

"Each morning I'll read your Claude Code chats from the previous working day, check what came of
them in your project folders, and write a short brief with the top 3 things to work on. Everything
stays on this Mac; nothing is changed in your folders."

## 2. Chats

Ask: "Can I read your Claude Code chats for this? They're the main source of the brief." Default
yes. If no, set `"read_chats": false` and say the brief will be built from the folders only.

## 3. Projects and their folders

Ask: "Which project should the brief cover? A project can be several folders: for example the code,
a folder with slides for weekly meetings, a folder with papers." Let the user name a project and
give folders (paths, or names you can find under their home folder).

For each folder:
1. Check it exists, and look inside (top level, plus file types and counts). Never read file contents here.
2. Propose a role:

   | Role | What it means for the brief | Typical signs |
   |---|---|---|
   | `code` | git, tests, progress log, chats mapped to it | `.git`, `src/`, `*.py`, `pyproject.toml` |
   | `slides` | deck dates and cadence, newest deck's text | `.key`, `.pptx`, deck PDFs with dates in the names |
   | `papers` | new articles parsed: title, abstract, conclusions, link to the project | many `.pdf`, `.bib` |
   | `notes` | new or changed notes, summarized | `.md`, `.txt`, `.docx`, `.ipynb` |
   | `results` | new data, tables, figures | `.csv`, `.png`, `.npy`, `.h5` |
   | `other` | new files listed and read when readable | anything else |

3. If the folder mixes things (e.g. slides sitting next to the code folder), propose a `pattern`
   that picks only the relevant files, based on what you see (e.g. `Meeting*.key`). Folders that
   belong to another configured folder are skipped automatically, so overlap is fine.
4. Only for `code` folders: if you see a progress log (`PROGRESS.md`, `NOTES.md`, `LOG.md`, …),
   note it as `log_file`. If there is none, set nothing and say nothing about it.

Then ask: "Another project?" Repeat until done. Each project gets its own brief.

If there is more than one project, ask which should be in the automatic morning run (`"auto": true`)
and which only on demand. Default: all automatic.

## 4. How the brief should start

Ask, with these two options:

- **Automatic (recommended):** "The first time you open your Mac after {time} each day, the brief is
  written in the background (1–2 minutes) and opens when ready. At most once a day." Then ask the
  earliest time (default 07:00) and the latest (default 14:00; after that the brief is skipped for the day).
- **Manual:** "Only when you type `morning-brief` in Terminal."

Both: `morning-brief` always works by hand too, and `morning-brief <project>` makes one project's brief.

## 5. How to show it

Ask with two options:
- **Open the file (default):** the brief opens as a Markdown file in the user's default app for `.md`.
- **Terminal:** a Terminal window shows the brief and keeps a Claude session open so the user can ask
  follow-up questions ("show me that commit", "open the plot").

## 6. Write the config and confirm

Show the final config as a short readable summary (not raw JSON), ask "Save this?", then write
`~/.config/morning-brief/config.json` in this format:

```json
{
  "version": 1,
  "read_chats": true,
  "trigger": "auto",
  "auto_after": "07:00",
  "auto_until": "14:00",
  "show": "file",
  "model": "sonnet",
  "brief_dir": "~/MorningBrief",
  "projects": [
    {
      "name": "My research project",
      "auto": true,
      "log_file": "PROGRESS.md",
      "folders": [
        {"path": "~/Research/my_project", "role": "code"},
        {"path": "~/Research", "role": "slides", "pattern": "Meeting*.key", "recursive": false},
        {"path": "~/Research/papers", "role": "papers"}
      ]
    }
  ]
}
```

Notes: `trigger` is `"auto"` or `"manual"`. Use `~` paths. Omit `log_file`, `pattern` and
`recursive` when not needed (`recursive` defaults to true).

## 7. Apply the start method

- Automatic: run `morning-brief --install-trigger` (it sets up the macOS login/wake job from the config).
- Manual: run `morning-brief --remove-trigger` (safe to run when nothing is installed).

Tell the user in one line what was set up.

## 8. Offer a first run

Ask: "Make today's brief now?" If yes, tell the user to run `morning-brief` in a new Terminal
window (so it runs outside this setup chat), or run it yourself if they prefer.
