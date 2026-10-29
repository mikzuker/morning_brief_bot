---
name: morning-brief
description: Morning catch-up for one research project, built from the user's Claude Code chats of the last working day. Sorts the chats by purpose (theoretical, explaining, planning, fixing), checks code, slides, papers and other project folders to see what each chat led to and what is new, and proposes the top 3 things to work on today. Use when the user asks for their morning brief, "what did I do yesterday" or "where did I leave off", or when the morning-brief launcher runs it.
---

# Morning brief

The researcher's Claude Code chats are the main record of their work. Your job: read
yesterday's chats for this project, understand what each one was for, check in the project's
folders what came of it and what is new, and write a brief that gets them back into their work
in two minutes, ending with three ranked suggestions for today.

**Chats first, everything else second.** Git, tests, the optional progress log and the other
folders explain and verify what was discussed in the chats, and add what happened outside them.

## Hard rules

- **Read-only.** Never edit, create, move or delete files. Never run code, tests, training or
  state-changing git. The only command you may run is the collector (see Input).
- **Grounded.** Every claim comes from the context bundle or a file you read. Name the source
  (chat number and time, commit hash, file name). Mark guesses with "probably".
- **Never re-read an unchanged file.** A file not edited during the covered period was already
  covered by an earlier brief. The bundle gives what that brief said about it (sections marked
  "not re-read"); use that. If you want to open a file the bundle does not cover (e.g. one named in
  a chat), first run the collector with `--file-info <path>`: if it was not edited during the covered
  period, use the earlier brief's summary it prints and don't open the file. Open an unchanged file
  only if a thread cannot be understood without it and no brief covers it (at most one, briefly).
- **Cheap.** Use the bundle. Beyond it: expand at most 3 chats in full, read at most 3 PDFs
  (first page only, and only those whose text could not be extracted) and look at at most 3 images, and only when they matter for the brief.
- **Short.** About 500 words in total. No preamble, no closing remarks.
- **Not every project has everything.** A progress log, git, tests, slides or papers may all be
  missing. Work with what is there and never suggest adding what is not.

## Input

1. **Context bundle (preferred).** The launcher pipes it into the prompt. It starts with
   `=== MORNING-BRIEF CONTEXT ===` and names the project and its folders with their roles.
2. **No bundle (interactive use).** Run
   `python3 <this skill's folder>/scripts/collect.py --project "<name>"` for a configured project,
   or with no arguments to cover every repo that yesterday's chats were in.
3. **Drill-down.** `python3 <this skill's folder>/scripts/collect.py --session <chat id>` prints one
   chat in full. Use it when a chat's purpose or outcome is unclear from its summary.
4. **File check.** `python3 <this skill's folder>/scripts/collect.py --project "<name>" --file-info <path>`
   prints when a file was last edited and what an earlier brief said about it. Run it before opening
   any file yourself.

The bundle, in order:

| Part | Contents |
|---|---|
| Header | Project name, its folders and their roles, the chat day covered, the period for files |
| `PREVIOUS BRIEF` | The last brief for this project: was its top suggestion done? |
| `CHATS ON <day>` | Every chat of the working day (it ends at 04:00): time span, title, every user prompt with its time (`[+image]` = the user pasted a picture, usually a plot), files Claude edited or read, commands run, Claude's last reply |
| `OTHER DAYS WITH CHATS` | Other active days since the last brief |
| `CODE FOLDER` | Head of `CLAUDE.md`/`README.md`, git log and status, the progress log *if one exists*, failing tests, files changed since the start of the chat day (tagged `[edited in chat]` / `[outside chats]`) |
| `SLIDES FOLDER` | Deck dates (meeting cadence), the latest deck (from the brief that covered it, or its text the first time), new decks' text |
| `FILES MENTIONED IN THE CHATS BUT UNCHANGED` | Documents named in the chats that were not edited in the covered period, with what earlier briefs said about them. Use these to understand the chats; don't report them as new |
| `PAPERS` / `NOTES` / `RESULTS` / `OTHER FOLDER` | Each new or changed file with its extracted content. Articles (PDFs in a papers folder) come as opening lines (title, authors), abstract and conclusions; other PDFs as their first pages' text. Images, and PDFs with no text layer, are listed with their path for you to open |

## Step 1 — Split the chats into threads

A chat often covers more than one piece of work. Read the prompts in order and cut each chat
into **threads**: a run of prompts about one object and one purpose. Start a new thread when the
object changes (another script, model or result) or the purpose changes (from looking at a plot
to fixing the code that made it). Several chats about the same thing form one thread.

## Step 2 — Classify each thread

Each thread gets exactly one type:

| Type | The user is… | Typical prompts |
|---|---|---|
| **Theoretical** | understanding existing code or a method | "what does this function do", "explain how the prior is built", "why is it done this way" |
| **Explaining** | evaluating results | pasted plots (`[+image]`), "is this metric good", "interpret these numbers", raw-data or metric checks, comparing runs |
| **Planning** | creating something new: a new class or object | a new model, method, algorithm, pipeline, script or module; design discussion before building it |
| **Fixing** | changing something that already exists | bug fixes, errors and tracebacks, refactoring, adding a function or option to an existing model or script |

Tie-breakers:
- New file, model, method or algorithm → **Planning**, even if it was implemented in the same chat.
  A new function, option or behaviour inside an existing object → **Fixing**.
- Asking *why a result looks wrong* → **Explaining**. Once the user asks to change the code → a new
  **Fixing** thread.
- Asking *how code works* with no result involved → **Theoretical**.
- `[ran /command]` lines: classify by what the command was used for.

## Step 3 — Name sub-groups

Within each type, group the threads by the object they are about. Name each group after that
object, taken from the chats: the model, method, script or result (e.g. "Segmentation model",
"Data loader"). Never use generic names like "Code changes" or "Misc".

## Step 4 — Check what each thread led to

Use the code-folder context, thread by thread:

- **Planning / Fixing:** committed (which commit)? Still uncommitted? Tests for it, and do they pass?
  Result files produced (`[outside chats]` files in results or figure folders)? A progress-log entry,
  if the project keeps a log?
- **Explaining:** the conclusion reached, with the key number (from Claude's last reply, the log or
  the slides). Is a question left open?
- **Theoretical:** what was understood, in one line.

Give each thread a status: **done** (committed or concluded), **in progress** (uncommitted, or code
without results), or **open** (question unanswered, error unresolved, chat ended mid-task).
Mention commits or result files that no chat explains under "Outside chats".

## Step 5 — What is new in the other folders

For each non-code folder with new or changed files:

- **Slides:** what the newest deck says, in one or two lines, and what of yesterday's work is not on
  it yet. From the deck dates, work out the meeting cadence and when the next one is due.
- **Papers:** for each new article, use the extracted title, abstract and conclusions: one line on what
  it does and finds, and one line on how it relates to this project's current work (only if there is a
  clear link to yesterday's chats or the code, e.g. a method that could replace or test something). Open
  the PDF with the Read tool only if no text could be extracted (scanned), first page only. If an
  article clearly bears on an open thread, it is a good candidate for a "new idea" in the Top 3.
- **Notes / results / other:** one line per file or group of similar files on what it contains and
  why it matters. Look at a new figure only if it is central to yesterday's work.

Skip folders with nothing new. If more than ~5 files are new in one folder, summarize them as a group.

## Step 6 — Top 3 for today

Propose three things to work on today, ranked by priority. Each must be grounded in something in
this brief. Rank with these rules, in order:

1. **Unblock:** broken or half-finished work other things depend on: failing tests, an error left
   unresolved in a chat, uncommitted code that was mid-change.
2. **Deadline:** the next meeting is within ~2 days and yesterday's results are not on the slides yet.
3. **Validate fresh work:** code written yesterday that has no tests, no real-data run or no check
   against a baseline.
4. **Next natural step:** stated in the chats, the log or the slides ("next: …", "pending").
5. **New idea:** from a new paper, an open question in an Explaining thread, or a pattern you see
   across the chats (e.g. the same problem coming up repeatedly).

Make the three different in kind where possible (e.g. one finish, one test, one new idea), and
include at least one **testing/validation** or **new idea** item. For each: what, why now (with
the source), rough effort (≤1 h, half day, day), and the first concrete step (file, script or command).

## Output format

Return exactly this Markdown, nothing before or after it. Leave out sections and types that are
empty. Keep the four types in this order.

```
# Morning brief: {project} · {Weekday, D Month}

Covering {Weekday D Month}: {n} chats, {first time}–{last time}.

## Yesterday's work

### Planning (new objects)
**{Sub-group}** — {what was created, 1–2 sentences}. *{status}*: {evidence, e.g. "committed 7983356, tests pass"}.

### Fixing (changes to existing objects)
**{Sub-group}** — {what was changed and why}. *{status}*: {evidence}.

### Explaining (evaluating results)
**{Sub-group}** — {what was evaluated} → {conclusion with the key number}. {open question, if any}.

### Theoretical (understanding the code)
**{Sub-group}** — {what was clarified, one line}.

**Outside chats:** {commits or result files no chat explains, one line}.

## New in your folders
- **Slides:** {…} Next meeting: {day, if a cadence is visible}.
- **Papers:** *{title}* — {what it does}; {link to the project}.
- **{Other role}:** {…}

## Where you left off
{2–3 sentences: the last thread of the day, how far it got, what is missing.}

## Top 3 for today
1. **{Title}** · {finish / test / validate / prepare meeting / new idea} · {effort}
   {Why now, with source.} First step: {concrete action}.
2. …
3. …

## Flags
{Only real ones: failing tests, uncommitted work older than 2 days, unpushed commits, the previous
brief's top item still not done. Leave the section out if there are none.}
```

If `OTHER DAYS WITH CHATS` lists more days, add a last line: `Also active: {day} ({n} prompts), …`.

## Edge cases

- **No chats for this project:** say so in one line under the title, then build the brief from the
  code and other folders: last step, new in your folders, top 3.
- **Chat reading switched off:** the same, without mentioning chats.
- **A chat with only vague prompts** ("hi", "continue"): fold it into the thread it continues, or drop it.
- **A folder not found:** one line under Flags, e.g. `Slides folder ~/Talks not found.`
- **Keynote text looks garbled or empty:** use the deck's name and date only; don't guess its content.
- **Empty or broken bundle:** output one line saying what was missing.
