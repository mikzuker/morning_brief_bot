#!/usr/bin/env python3
"""Collect read-only context for one morning brief.

Chats first: reads the user's Claude Code conversations of the last working day for the
project, then gives the context needed to understand them: git, tests and an optional
progress log for code folders, and the content of new files in the other folders
(slides, papers, notes, results).

Usage:
    python3 collect.py --project NAME            # a project from ~/.config/morning-brief/config.json
    python3 collect.py --folder DIR[:role] ...   # ad hoc, without a config
    python3 collect.py                           # no config: every project yesterday's chats touched
    python3 collect.py --session <chat id>       # one chat in full (drill-down)
    Options: --day YYYY-MM-DD, --config PATH

Read-only: it only reads files and runs read-only git commands.
Standard library only (Python 3.9+, as shipped with the macOS command line tools).
"""

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "morning-brief" / "config.json"
DEFAULT_BRIEF_DIR = Path.home() / "MorningBrief"
CLAUDE_DIR = Path(os.environ.get("MORNING_BRIEF_CLAUDE_DIR", Path.home() / ".claude" / "projects"))

DAY_CUTOFF_HOUR = 4          # chats before 04:00 belong to the previous working day
MAX_LOOKBACK_DAYS = 14
LOG_NAMES = ["PROGRESS.md", "NOTES.md", "LOG.md", "JOURNAL.md", "LABBOOK.md"]
CONTEXT_NAMES = ["CLAUDE.md", "README.md"]
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv",
             ".mypy_cache", ".ipynb_checkpoints", ".idea", ".vscode", ".claude"}
SKIP_FILES = {".DS_Store", "Icon\r"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

TEXT_EXT = {".md", ".txt", ".tex", ".bib", ".rst", ".py", ".r", ".jl", ".m", ".sh", ".json",
            ".yaml", ".yml", ".toml", ".cfg", ".ini", ".html", ".org"}
TABLE_EXT = {".csv", ".tsv"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
SLIDE_EXT = {".key", ".pptx", ".pdf"}

MAX_COMMITS = 25
MAX_RECENT_FILES = 40
MAX_COMMANDS = 15
MAX_REPLY_CHARS = 700
MAX_FILES_PER_FOLDER = 12
SNIPPET_CHARS = 1500
ARTICLE_CHARS = 4500
DECK_CHARS = 3500
MAX_LOG_ENTRIES = 4
MAX_LOG_CHARS = 5000


# ============================================================================================
# helpers
# ============================================================================================
def section(title, body):
    body = (body or "").strip()
    print(f"\n--- {title} ---")
    print(body if body else "(none)")


def fmt_time(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def clip(text, n):
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n] + " […]"


def parse_ts(s):
    """ISO timestamp from a transcript (UTC, 'Z') -> naive local datetime."""
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except (AttributeError, ValueError):
        return None


def workday(t):
    return (t - dt.timedelta(hours=DAY_CUTOFF_HOUR)).date()


def day_start(day):
    return dt.datetime.combine(day, dt.time(DAY_CUTOFF_HOUR))


def slug(name):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-").lower() or "project"


def inside(path, folder):
    try:
        return Path(path).resolve().is_relative_to(Path(folder).resolve())
    except (OSError, ValueError):
        return False


def git(folder, *args):
    try:
        out = subprocess.run(["git", "-C", str(folder), *args], capture_output=True,
                             text=True, timeout=20)
        return out.stdout if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def touched(st):
    """Last time a file was edited or added to this disk (macOS creation time)."""
    return max(st.st_mtime, getattr(st, "st_birthtime", 0))


# ============================================================================================
# config
# ============================================================================================
def load_config(path):
    try:
        return json.loads(Path(path).expanduser().read_text())
    except (OSError, ValueError):
        return None


def project_from_config(cfg, name):
    for p in cfg.get("projects", []):
        if p.get("name", "").lower() == name.lower():
            folders = [{"path": Path(f["path"]).expanduser(), "role": f.get("role", "other"),
                        "pattern": f.get("pattern"), "recursive": f.get("recursive", True)}
                       for f in p.get("folders", [])]
            return {"name": p["name"], "folders": folders, "log_file": p.get("log_file")}
    names = ", ".join(p.get("name", "?") for p in cfg.get("projects", []))
    sys.exit(f"No project called '{name}' in the config. Projects: {names}")


def all_config_folders(cfg):
    return [Path(f["path"]).expanduser() for p in (cfg or {}).get("projects", [])
            for f in p.get("folders", [])]


# ============================================================================================
# Claude Code chats
# ============================================================================================
def read_session(path):
    session = {"id": path.stem, "cwd": None, "branch": None, "title": None, "events": []}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return session
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("type") == "summary" and rec.get("summary"):
            session["title"] = rec["summary"]
            continue
        if rec.get("isSidechain") or rec.get("isMeta"):
            continue
        t = parse_ts(rec.get("timestamp", ""))
        if t is None:
            continue
        session["cwd"] = rec.get("cwd") or session["cwd"]
        session["branch"] = rec.get("gitBranch") or session["branch"]
        content = (rec.get("message") or {}).get("content")

        if rec.get("type") == "user":
            text, has_image = "", False
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                if any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
                    continue
                text = " ".join(c.get("text", "") for c in content
                                if isinstance(c, dict) and c.get("type") == "text")
                has_image = any(isinstance(c, dict) and c.get("type") == "image" for c in content)
            text = text.strip()
            cmd = re.search(r"<command-name>(.*?)</command-name>", text)
            if cmd:
                args = re.search(r"<command-args>(.*?)</command-args>", text, re.S)
                text = f"[ran {cmd.group(1)}] {args.group(1).strip() if args else ''}".strip()
            elif text.startswith(("<", "[Request interrupted", "Caveat:")):
                continue
            if text or has_image:
                session["events"].append((t, "prompt", (text, has_image)))

        elif rec.get("type") == "assistant" and isinstance(content, list):
            for c in content:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "text" and c.get("text", "").strip():
                    session["events"].append((t, "reply", c["text"].strip()))
                elif c.get("type") == "tool_use":
                    name, inp = c.get("name", ""), c.get("input") or {}
                    if name in EDIT_TOOLS and (inp.get("file_path") or inp.get("notebook_path")):
                        session["events"].append((t, "edit", inp.get("file_path") or inp["notebook_path"]))
                    elif name == "Read" and inp.get("file_path"):
                        session["events"].append((t, "read", inp["file_path"]))
                    elif name == "Bash" and inp.get("command"):
                        session["events"].append((t, "bash", inp["command"]))
    session["events"].sort(key=lambda e: e[0])
    return session


def load_sessions(not_before, brief_dir):
    sessions = []
    if not CLAUDE_DIR.is_dir():
        return sessions
    for f in CLAUDE_DIR.glob("*/*.jsonl"):
        try:
            if dt.datetime.fromtimestamp(f.stat().st_mtime) < not_before:
                continue
        except OSError:
            continue
        s = read_session(f)
        if not any(k == "prompt" for _, k, _ in s["events"]):
            continue
        if s["cwd"] and inside(s["cwd"], brief_dir):
            continue  # the brief's own runs are not work
        sessions.append(s)
    return sessions


def rel(path, folders):
    for f in folders:
        if inside(path, f):
            return str(Path(path).resolve().relative_to(Path(f).resolve()))
    return str(path)


def print_session(n, s, start, end, folders, prompt_cap):
    ev = [e for e in s["events"] if start <= e[0] < end]
    prompts = [e for e in ev if e[1] == "prompt"]
    first_all = next(e for e in s["events"] if e[1] == "prompt")
    where = Path(s["cwd"]).name if s["cwd"] else "?"
    print(f"\n### Chat {n} · in {where} · {prompts[0][0]:%H:%M}–{ev[-1][0]:%H:%M} · "
          f"{len(prompts)} prompts{' · branch ' + s['branch'] if s['branch'] else ''} · id {s['id']}")
    if s["title"]:
        print(f"Title: {s['title']}")
    if first_all[0] < start:
        print(f"Continues a chat started {first_all[0]:%Y-%m-%d %H:%M} with: {clip(first_all[2][0], 300)}")
    print("User prompts:")
    for t, _, (text, img) in prompts:
        print(f"  {t:%H:%M}  {clip(text, prompt_cap)}{'  [+image]' if img else ''}")
    edited = sorted({rel(p, folders) for _, k, p in ev if k == "edit"})
    read = sorted({rel(p, folders) for _, k, p in ev if k == "read"} - set(edited))
    cmds = list(dict.fromkeys(clip(c, 160) for _, k, c in ev if k == "bash"))
    replies = [r for _, k, r in ev if k == "reply"]
    if edited:
        print("Files edited/created: " + ", ".join(edited))
    if read:
        print("Files read: " + ", ".join(read[:15]) + (f" … +{len(read) - 15}" if len(read) > 15 else ""))
    if cmds:
        print("Commands run (last): " + " | ".join(cmds[-MAX_COMMANDS:]))
    if replies:
        print(f"Claude's last reply: {clip(replies[-1], MAX_REPLY_CHARS)}")


def dump_one_session(session_id):
    for f in CLAUDE_DIR.glob(f"*/{session_id}*.jsonl"):
        s = read_session(f)
        print(f"=== FULL CHAT {s['id']} · {s['cwd']} · {s['title'] or ''} ===")
        for t, kind, p in s["events"]:
            if kind == "prompt":
                print(f"\n[{t:%m-%d %H:%M}] USER: {clip(p[0], 3000)}{' [+image]' if p[1] else ''}")
            elif kind == "reply":
                print(f"[{t:%H:%M}] CLAUDE: {clip(p, 1500)}")
            else:
                print(f"[{t:%H:%M}] ({kind}) {clip(p, 200)}")
        return
    print(f"No chat with id {session_id} found.")


# ============================================================================================
# reading file contents (best effort, never fails)
# ============================================================================================
def snappy_decompress(data):
    """Minimal raw-Snappy decoder (used by Keynote's .iwa files)."""
    i = 0
    while data[i] & 0x80:   # skip the uncompressed-length varint
        i += 1
    i += 1
    out = bytearray()
    while i < len(data):
        tag = data[i]
        i += 1
        kind = tag & 3
        if kind == 0:
            ln = tag >> 2
            if ln >= 60:
                nb = ln - 59
                ln = int.from_bytes(data[i:i + nb], "little")
                i += nb
            ln += 1
            out += data[i:i + ln]
            i += ln
            continue
        if kind == 1:
            ln, off = ((tag >> 2) & 7) + 4, ((tag >> 5) << 8) | data[i]
            i += 1
        elif kind == 2:
            ln, off = (tag >> 2) + 1, int.from_bytes(data[i:i + 2], "little")
            i += 2
        else:
            ln, off = (tag >> 2) + 1, int.from_bytes(data[i:i + 4], "little")
            i += 4
        if off == 0 or off > len(out):
            raise ValueError("bad snappy offset")
        start = len(out) - off
        if off >= ln:
            out += out[start:start + ln]
        else:
            for k in range(ln):
                out.append(out[start + k])
    return bytes(out)


def iwa_payload(raw):
    """Concatenate the decompressed chunks of one .iwa file."""
    out, i = bytearray(), 0
    while i + 4 <= len(raw):
        length = int.from_bytes(raw[i + 1:i + 4], "little")
        chunk = raw[i + 4:i + 4 + length]
        i += 4 + length
        try:
            out += snappy_decompress(chunk)
        except (IndexError, ValueError):
            break
    return bytes(out)


TEXT_RUN = re.compile(rb"(?:[\x20-\x7e]|[\xc2-\xf4][\x80-\xbf]{1,3}){12,}")
NOISE = re.compile(r"(Helvetica|Arial|Times|\.png|\.jpg|\.pdf|com\.apple|_Style|\bStyle\b|^[\w.\-/]+$)")


def keynote_text(path):
    """Best-effort text of a Keynote deck (slide order may be mixed)."""
    blobs = []
    if path.is_dir():  # package format
        idx = path / "Index.zip"
        if idx.is_file():
            with zipfile.ZipFile(idx) as z:
                blobs = [z.read(n) for n in z.namelist() if n.endswith(".iwa")]
        else:
            blobs = [p.read_bytes() for p in (path / "Index").glob("*.iwa")]
    else:
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.startswith("Index/") and n.endswith(".iwa")]
            slides = [n for n in names if "Slide" in n] or names
            blobs = [z.read(n) for n in slides]
    seen, lines = set(), []
    for raw in blobs:
        for m in TEXT_RUN.finditer(iwa_payload(raw)):
            r = m.group()
            if 12 <= r[0] <= len(r) - 1:  # protobuf length prefix that happens to be printable
                r = r[1:1 + r[0]]
            s = r.decode("utf-8", "ignore").strip()
            if s.count(" ") < 2 or NOISE.search(s) or s in seen:
                continue
            seen.add(s)
            lines.append(s)
    return "\n".join(lines) or "(no text found in the Keynote file)"


def office_text(path, kind):
    with zipfile.ZipFile(path) as z:
        if kind == "docx":
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
            return re.sub(r"<[^>]+>", "", xml.replace("</w:p>", "\n")).strip()
        slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                        key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
        parts = []
        for k, n in enumerate(slides, 1):
            xml = z.read(n).decode("utf-8", "ignore")
            words = " ".join(re.findall(r"<a:t>([^<]*)</a:t>", xml))
            parts.append(f"[slide {k}] {words}")
        return "\n".join(parts)


# ---- PDF text ---------------------------------------------------------------------------
# Tried in order: macOS PDFKit (built in, no install) -> pypdf (if installed)
# -> pdftotext (poppler, if installed) -> a small built-in parser for simple PDFs -> title/page count only.
PDF_FIRST_PAGES = 3      # title, authors, abstract, introduction
PDF_LAST_PAGES = 3       # conclusions (before the references)

JXA_PDFKIT = r"""
try { ObjC.import('PDFKit'); } catch (e) { ObjC.import('Quartz'); }
function run(argv) {
  var d = $.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath(argv[0]));
  if (!d || d.isNil()) return '';
  var n = d.pageCount, first = parseInt(argv[1]), last = parseInt(argv[2]), out = [n];
  for (var i = 0; i < n; i++) {
    if (i >= first && i < n - last) continue;
    var s = d.pageAtIndex(i).string;
    out.push(i + '\u0001' + ((s && !s.isNil()) ? s.js : ''));
  }
  return out.join('\u0002');
}
"""


def _pages_pdfkit(path):
    if sys.platform != "darwin":
        return None
    r = subprocess.run(["osascript", "-l", "JavaScript", "-e", JXA_PDFKIT, str(path),
                        str(PDF_FIRST_PAGES), str(PDF_LAST_PAGES)],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    parts = r.stdout.rstrip("\n").split("\u0002")
    pages = {}
    for chunk in parts[1:]:
        idx, _, text = chunk.partition("\u0001")
        pages[int(idx)] = text
    return int(parts[0]), pages


def _pages_pdftotext(path):
    exe = shutil.which("pdftotext") or next((e for e in ["/opt/homebrew/bin/pdftotext", "/usr/local/bin/pdftotext"]
                                                if Path(e).is_file()), None)
    if not exe:
        return None
    r = subprocess.run([exe, "-enc", "UTF-8", str(path), "-"], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return None
    all_pages = r.stdout.split("\f")
    if all_pages and not all_pages[-1].strip():
        all_pages = all_pages[:-1]
    n = len(all_pages)
    keep = set(range(min(PDF_FIRST_PAGES, n))) | set(range(max(0, n - PDF_LAST_PAGES), n))
    return n, {i: all_pages[i] for i in keep}


def _pages_pypdf(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    reader = PdfReader(str(path))
    n = len(reader.pages)
    keep = set(range(min(PDF_FIRST_PAGES, n))) | set(range(max(0, n - PDF_LAST_PAGES), n))
    return n, {i: (reader.pages[i].extract_text() or "") for i in sorted(keep)}


PDF_STRING = re.compile(rb"\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f\s]+>")


def _pdf_literal(b):
    out, i = bytearray(), 1
    esc = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}
    while i < len(b) - 1:
        c = b[i]
        if c == 0x5C:  # backslash
            i += 1
            d = b[i]
            if 0x30 <= d <= 0x37:
                j = i
                while j < min(i + 3, len(b) - 1) and 0x30 <= b[j] <= 0x37:
                    j += 1
                out.append(int(b[i:j], 8) & 0xFF)
                i = j
                continue
            out.append(esc.get(d, d))
        else:
            out.append(c)
        i += 1
    return out.decode("latin-1").translate(TEX_LIGATURES)


TEX_LIGATURES = {11: "ff", 12: "fi", 13: "fl", 14: "ffi", 15: "ffl"}  # LaTeX OT1 font slots


def _pages_builtin(path):
    """Very small text extractor for simple (e.g. LaTeX) PDFs: Flate streams, Tj/TJ operators.
    Page boundaries are not tracked, so everything counts as 'first pages'."""
    import base64
    import zlib
    data = path.read_bytes()
    texts = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\n?endstream", data, re.S):
        raw = m.group(1)
        header = data[max(0, m.start() - 300):m.start()]
        try:
            if b"ASCII85Decode" in header:
                raw = base64.a85decode(raw.strip(), adobe=raw.strip().endswith(b"~>"))
            if b"FlateDecode" in header:
                raw = zlib.decompress(raw)
        except (zlib.error, ValueError):
            continue
        if b"BT" not in raw:
            continue
        for block in re.findall(rb"BT(.*?)ET", raw, re.S):
            line = []
            for tok in re.finditer(rb"\[(.*?)\]\s*TJ|(\((?:\\.|[^\\)])*\))\s*(?:Tj|'|\")|(T\*|-?\d+\.?\d*\s+-?\d+\.?\d*\s+T[dD])", block, re.S):
                if tok.group(1) is not None:
                    for part in re.finditer(rb"\((?:\\.|[^\\)])*\)|(-?\d+\.?\d*)", tok.group(1)):
                        if part.group(1):
                            if float(part.group(1)) < -200:
                                line.append(" ")
                        else:
                            line.append(_pdf_literal(part.group()))
                elif tok.group(2) is not None:
                    line.append(_pdf_literal(tok.group(2)))
                else:
                    line.append("\n")
            texts.append("".join(line))
        if sum(len(t) for t in texts) > 40000:
            break
    text = "\n".join(texts)
    letters = sum(ch.isalpha() for ch in text)
    if len(text) < 200 or letters < 0.5 * len(text.replace(" ", "").replace("\n", "")):
        return None  # nothing readable (custom font encodings, scanned pages…)
    pages = len(re.findall(rb"/Type\s*/Page\b", data))
    return pages, {0: text}


def pdf_pages(path):
    """(page_count, {page_index: text}, method) using the first extractor that works."""
    for name, fn in [("PDFKit", _pages_pdfkit), ("pypdf", _pages_pypdf),
                     ("pdftotext", _pages_pdftotext), ("built-in parser", _pages_builtin)]:
        try:
            res = fn(path)
        except Exception:
            res = None
        if res and sum(len(t.strip()) for t in res[1].values()) > 100:
            return res[0], res[1], name
    return None


def _clean(text):
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)          # join hyphenated line breaks
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def pdf_meta_title(path):
    head = path.read_bytes()[:3_000_000]
    m = re.search(rb"/Title\s*\(([^)]{3,300})\)", head)
    if not m:
        return None
    raw = m.group(1)
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", "ignore").strip() or None
    return raw.decode("latin-1", "ignore").strip() or None


def pdf_content(path, cap, role):
    title = pdf_meta_title(path)
    res = pdf_pages(path)
    if not res:
        return (f"PDF" + (f", title: {title}" if title else "") +
                ". No text layer could be extracted (probably scanned). "
                "View the first page with the Read tool if it matters.")
    n, pages, method = res
    first = _clean("\n".join(pages[i] for i in sorted(pages) if i < PDF_FIRST_PAGES))
    last = _clean("\n".join(pages[i] for i in sorted(pages) if i >= max(PDF_FIRST_PAGES, n - PDF_LAST_PAGES)))
    head = f"PDF, {n or '?'} pages (text via {method})" + (f". Metadata title: {title}" if title else "")

    if role != "papers":  # slides, notes, results: just the text from the start
        return head + "\n" + clip_block(first, cap)

    # article: title/authors block, abstract, conclusions
    out = [head]
    out.append("Opening lines: " + clip(first[:400], 400))
    abstract = re.search(r"(?is)\babstract\b[\s.:—–-]*(.{150,2500}?)"
                         r"(?=\n\s*\n|\n\s*(?:\d+\.?|I\.?)?\s*introduction\b|\bkeywords\b|\bindex terms\b)", first)
    if abstract:
        out.append("Abstract: " + clip(abstract.group(1), 1800))
    else:
        out.append("Start of text: " + clip(first[400:2000], 1600))
    concl = re.search(r"(?im)^\s*(?:[\dIVX]+\.?\s*)?(conclusions?|concluding remarks|summary( and outlook)?|"
                      r"discussion( and conclusions?)?|outlook)\s*$\n(.{30,}?)"
                      r"(?=^\s*(?:references|bibliography|acknowledge?ments?|appendix)\b|\Z)", last or first, re.S | re.M)
    if concl:
        out.append(f"{concl.group(1).title()}: " + clip(concl.group(4), 1500))
    return clip_block("\n".join(out), cap)


def file_content(path, cap, role=None):
    ext = path.suffix.lower()
    try:
        size = path.stat().st_size if path.is_file() else 0
        if size > 300_000_000:
            return "(very large file, not opened)"
        if ext in TEXT_EXT:
            return clip_block(path.read_text(encoding="utf-8", errors="replace"), cap)
        if ext == ".ipynb":
            nb = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            cells = nb.get("cells", [])
            body = "\n".join(f"[{c.get('cell_type')}] " + "".join(c.get("source", [])) for c in cells)
            return f"Notebook, {len(cells)} cells.\n" + clip_block(body, cap)
        if ext in TABLE_EXT:
            with open(path, encoding="utf-8", errors="replace") as f:
                head = [next(f, "") for _ in range(6)]
            rows = sum(1 for _ in open(path, "rb")) if size < 100_000_000 else "many"
            return f"Table, {rows} rows. First lines:\n" + "".join(head)
        if ext == ".docx":
            return clip_block(office_text(path, "docx"), cap)
        if ext == ".pptx":
            return clip_block(office_text(path, "pptx"), cap)
        if ext == ".key":
            return clip_block(keynote_text(path), cap)
        if ext == ".pdf":
            return pdf_content(path, cap, role)
        if ext in IMAGE_EXT:
            return "Image. Can be viewed with the Read tool."
        return f"({ext or 'no extension'} file, {size // 1024} KB, content not extracted)"
    except Exception as e:  # never let one odd file break the brief
        return f"(could not read: {type(e).__name__})"


def clip_block(text, cap):
    text = text.strip()
    return text if len(text) <= cap else text[:cap] + "\n[…cut…]"


# ============================================================================================
# memory: never read an unchanged file twice, use the brief that already summarized it
# ============================================================================================
DOC_EXT = {".pdf", ".key", ".pptx", ".docx", ".ipynb", ".md", ".txt", ".tex", ".csv", ".tsv"}


class Memory:
    """Which files earlier briefs already covered.

    `.seen.json` in the project's brief folder maps a file path to the mtime/size it had when its
    content went into a brief, and that brief's name. The launcher updates it after each successful
    brief from the manifest this script writes (only files whose content was actually included)."""

    def __init__(self, pdir, today_iso):
        self.pdir, self.today = pdir, today_iso
        self.briefs = sorted(p for p in pdir.glob("????-??-??.md") if p.stem != today_iso) if pdir.is_dir() else []
        try:
            self.seen = json.loads((pdir / ".seen.json").read_text())
        except (OSError, ValueError):
            self.seen = {}
        self.included = []

    def summarized_in(self, p):
        """The brief that summarized this exact version of the file, if any."""
        e = self.seen.get(str(p.resolve()))
        if not e or e.get("brief", "").startswith(self.today):
            return None
        try:
            st = p.stat()
        except OSError:
            return None
        b = self.pdir / e["brief"]
        if abs(e["mtime"] - st.st_mtime) < 2 and e["size"] == st.st_size and b.exists():
            return b
        return None

    def brief_after_edit(self, p):
        """The first brief after the file's last edit that mentions it (covers files from before
        the index existed)."""
        edited = workday(dt.datetime.fromtimestamp(p.stat().st_mtime)).isoformat()
        for b in [b for b in self.briefs if b.stem > edited][:5]:
            if self.excerpt(b, p):
                return b
        return None

    @staticmethod
    def excerpt(brief, p, cap=700):
        keys = {p.name.lower()} | ({p.stem.lower()} if len(p.stem) >= 6 else set())
        lines = brief.read_text(errors="replace").splitlines()
        hits = []
        for i, line in enumerate(lines):
            if any(k in line.lower() for k in keys):
                hits.append(line.strip())
                if i + 1 < len(lines) and lines[i + 1].startswith((" ", "\t")):
                    hits.append(lines[i + 1].strip())
        return clip_block("\n".join(dict.fromkeys(hits)), cap)

    def recall(self, p):
        """(brief, excerpt) from earlier briefs for an unchanged file, or (None, '')."""
        b = self.summarized_in(p) or self.brief_after_edit(p)
        return (b, self.excerpt(b, p)) if b else (None, "")

    def include(self, p, cap, role):
        """Read the file's content for this bundle and remember it for the manifest."""
        try:
            st = p.stat()
            self.included.append({"path": str(p.resolve()), "mtime": st.st_mtime, "size": st.st_size})
        except OSError:
            pass
        return file_content(p, cap, role)

    def write_manifest(self, path):
        Path(path).write_text(json.dumps(self.included, indent=1))


def recalled_text(mem, p, why):
    b, ex = mem.recall(p)
    edited = fmt_time(p.stat().st_mtime)
    if b:
        return (f"Unchanged since {edited}; not re-read. From brief {b.name}:\n{ex}" if ex else
                f"Unchanged since {edited}; not re-read. Brief {b.name} had its content but did not mention it "
                f"(judged unimportant then).")
    return (f"Unchanged since {edited}; not re-read, and no earlier brief covers it. {why}")


# ============================================================================================
# folders
# ============================================================================================
def walk_files(folder, pattern, recursive, exclude):
    folder = Path(folder)
    if not folder.is_dir():
        return
    for root, dirs, files in os.walk(folder):
        root_p = Path(root)
        depth = len(root_p.relative_to(folder).parts)
        keep = []
        for d in dirs:
            p = root_p / d
            if d in SKIP_DIRS or d.startswith(".") or any(p.resolve() == e for e in exclude):
                continue
            if p.suffix.lower() == ".key":  # Keynote package folder = one file
                if not pattern or p.match(pattern):
                    yield p
                continue
            keep.append(d)
        dirs[:] = keep if (recursive and depth < 5) else []
        for name in files:
            if name in SKIP_FILES or name.endswith(".pyc") or name.startswith("~$"):
                continue
            p = root_p / name
            if pattern and not p.match(pattern):
                continue
            yield p


def stat_touched(p):
    try:
        return touched(p.stat())
    except OSError:
        return 0


def code_folder_block(folder, since, chat_edited, log_file):
    print(f"\n=== CODE FOLDER: {folder} ===")
    if not folder.is_dir():
        print("(folder not found)")
        return
    ctx = next((folder / n for n in CONTEXT_NAMES if (folder / n).is_file()), None)
    if ctx:
        section(f"PROJECT CONTEXT ({ctx.name}, first lines)", clip_block(ctx.read_text(errors="replace"), 2500))

    if git(folder, "rev-parse", "--is-inside-work-tree"):
        log = git(folder, "log", f"--since={since:%Y-%m-%d %H:%M}", f"-n{MAX_COMMITS}",
                  "--date=format:%Y-%m-%d %H:%M", "--pretty=%h  %ad  %s", "--stat=100,60")
        if not (log or "").strip():
            log = "No commits in this period. Last 3 commits:\n" + (git(
                folder, "log", "-n3", "--date=format:%Y-%m-%d %H:%M", "--pretty=%h  %ad  %s") or "")
        section(f"GIT LOG (since {since:%Y-%m-%d %H:%M})", log)
        status_lines = (git(folder, "status", "-sb") or "").splitlines()
        body = "\n".join(status_lines[:40]) + (f"\n… and {len(status_lines) - 40} more" if len(status_lines) > 40 else "")
        changed = [l[3:].split(" -> ")[-1] for l in status_lines[1:] if not l.startswith("??")]
        mtimes = [(folder / c).stat().st_mtime for c in changed if (folder / c).exists()]
        if mtimes:
            age = (dt.datetime.now() - dt.datetime.fromtimestamp(min(mtimes))).days
            body += f"\nOldest uncommitted change to a tracked file: {fmt_time(min(mtimes))} ({age} days ago)"
        ahead = git(folder, "rev-list", "--count", "@{u}..HEAD")
        if ahead and ahead.strip() != "0":
            body += f"\nCommits not pushed: {ahead.strip()}"
        section("GIT STATUS", body)

    # optional progress log: configured name, else a common name if present; silent if none
    log_path = folder / log_file if log_file else next((folder / n for n in LOG_NAMES if (folder / n).is_file()), None)
    if log_path and log_path.is_file():
        text = log_path.read_text(encoding="utf-8", errors="replace")
        starts = [m.start() for m in re.finditer(r"(?m)^##\s", text)]
        chunk = text[starts[max(0, len(starts) - MAX_LOG_ENTRIES)]:] if starts else text
        chunk = chunk if len(chunk) <= MAX_LOG_CHARS else "[…]\n" + chunk[-MAX_LOG_CHARS:]
        section(f"PROGRESS LOG ({log_path.name}, last entries)", chunk)

    lastfailed = folder / ".pytest_cache" / "v" / "cache" / "lastfailed"
    if lastfailed.is_file():
        try:
            failed = json.loads(lastfailed.read_text())
            section("TESTS", f"Last pytest run: {fmt_time(lastfailed.stat().st_mtime)}\n" +
                    ("\n".join(list(failed)[:20]) if failed else "No failing tests."))
        except ValueError:
            pass

    found = sorted(((stat_touched(p), p) for p in walk_files(folder, None, True, set())
                    if stat_touched(p) >= since.timestamp()), reverse=True)
    lines = []
    for t, p in found[:MAX_RECENT_FILES]:
        tag = "[edited in chat]" if str(p.resolve()) in chat_edited else "[outside chats]"
        lines.append(f"{fmt_time(t)}  {p.relative_to(folder)}  {tag}")
    if len(found) > MAX_RECENT_FILES:
        lines.append(f"… and {len(found) - MAX_RECENT_FILES} more")
    section(f"FILES CHANGED OR ADDED SINCE {since:%Y-%m-%d %H:%M}", "\n".join(lines))


def other_folder_block(f, since, exclude, mem):
    folder, role = f["path"], f["role"]
    pat = f" (only {f['pattern']})" if f.get("pattern") else ""
    print(f"\n=== {role.upper()} FOLDER: {folder}{pat} ===")
    if not folder.is_dir():
        print("(folder not found)")
        return
    files = sorted(((stat_touched(p), p) for p in walk_files(folder, f.get("pattern"), f.get("recursive", True), exclude)),
                   reverse=True)
    new = [(t, p) for t, p in files if t >= since.timestamp()]
    if role == "slides":
        decks = sorted(((p.stat().st_mtime, p) for _, p in files if p.suffix.lower() in SLIDE_EXT), reverse=True)
        section("DECKS (newest first, for meeting cadence)",
                "\n".join(f"{fmt_time(t)}  {p.name}" for t, p in decks[:8]))
        if decks and decks[0][1] not in {p for _, p in new}:  # the last thing presented
            t, p = decks[0]
            b, ex = mem.recall(p)
            section(f"LATEST DECK (not new): {p.name}",
                    recalled_text(mem, p, "") if b else mem.include(p, DECK_CHARS, role))
    if not new:
        section(f"NEW OR CHANGED SINCE {since:%Y-%m-%d %H:%M}", "Nothing new.")
        return
    print(f"\n--- NEW OR CHANGED SINCE {since:%Y-%m-%d %H:%M}: {len(new)} file(s) ---")
    for t, p in new[:MAX_FILES_PER_FOLDER]:
        ext = p.suffix.lower()
        cap = (ARTICLE_CHARS if ext == ".pdf" and role == "papers" else
               DECK_CHARS if ext in {".key", ".pptx"} or (ext == ".pdf" and role == "slides") else SNIPPET_CHARS)
        print(f"\n> {p.relative_to(folder)}  ({fmt_time(t)}, path: {p})")
        b = mem.summarized_in(p)  # e.g. copied or re-saved without changes
        print(f"Already summarized in brief {b.name}; unchanged, not re-read." if b else mem.include(p, cap, role))
    if len(new) > MAX_FILES_PER_FOLDER:
        print(f"\n… and {len(new) - MAX_FILES_PER_FOLDER} more: " +
              ", ".join(p.name for _, p in new[MAX_FILES_PER_FOLDER:MAX_FILES_PER_FOLDER + 20]))


# ============================================================================================
# main
# ============================================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", help="project name from the config")
    ap.add_argument("--folder", action="append", default=[], help="DIR[:role], ad hoc (repeatable)")
    ap.add_argument("--day", help="working day to cover, YYYY-MM-DD")
    ap.add_argument("--config", default=str(CONFIG_PATH))
    ap.add_argument("--session", help="print one chat in full and exit")
    ap.add_argument("--file-info", help="with --project: is this file new, or what did an earlier brief say about it?")
    ap.add_argument("--manifest", help="write the list of files whose content was included here (used by the launcher)")
    args = ap.parse_args()

    if args.session:
        return dump_one_session(args.session)

    cfg = load_config(args.config)
    brief_dir = Path((cfg or {}).get("brief_dir", DEFAULT_BRIEF_DIR)).expanduser()
    read_chats = (cfg or {}).get("read_chats", True)

    if args.project:
        if not cfg:
            sys.exit(f"No config at {args.config}. Run `morning-brief --setup` first.")
        project = project_from_config(cfg, args.project)
    elif args.folder:
        folders = []
        for spec in args.folder:
            path, _, role = spec.partition(":")
            folders.append({"path": Path(path).expanduser(), "role": role or "code", "pattern": None, "recursive": True})
        project = {"name": folders[0]["path"].name, "folders": folders, "log_file": None}
    else:
        project = None  # discover projects from the chats

    now = dt.datetime.now()
    today = workday(now)
    sessions = load_sessions(now - dt.timedelta(days=MAX_LOOKBACK_DAYS + 1), brief_dir) if read_chats else []

    if project is None:  # ad hoc: every repo yesterday's chats were in
        roots = {}
        for s in sessions:
            if s["cwd"] and Path(s["cwd"]).is_dir():
                top = git(s["cwd"], "rev-parse", "--show-toplevel")
                roots[str(Path(top.strip()) if top else Path(s["cwd"]))] = True
        project = {"name": "all chats", "folders": [{"path": Path(r), "role": "code", "pattern": None,
                                                     "recursive": True} for r in roots], "log_file": None}
        mine = sessions
    else:
        mine = [s for s in sessions if s["cwd"] and any(inside(s["cwd"], f["path"]) for f in project["folders"])]

    folder_paths = [f["path"] for f in project["folders"]]
    pdir = brief_dir / slug(project["name"])
    previous = sorted(p for p in pdir.glob("????-??-??.md") if p.stem != now.date().isoformat()) if pdir.is_dir() else []
    mem = Memory(pdir, now.date().isoformat())

    if args.file_info:
        p = Path(args.file_info).expanduser()
        if not p.exists():
            sys.exit(f"{p}: not found")
        st = p.stat()
        print(f"{p}\nLast edited: {fmt_time(st.st_mtime)}; added: {fmt_time(getattr(st, 'st_birthtime', st.st_mtime))}")
        print(recalled_text(mem, p, "Open it only if the brief cannot be written without it."))
        return

    per_day = defaultdict(int)
    for s in mine:
        for t, k, _ in s["events"]:
            if k == "prompt":
                per_day[workday(t)] += 1
    if args.day:
        chat_day = dt.date.fromisoformat(args.day)
    else:
        past = sorted(d for d in per_day if d < today)
        chat_day = past[-1] if past else None

    # window for files/git: the chat day, or since the previous brief, or since yesterday morning
    if chat_day:
        since = day_start(chat_day)
    elif previous:
        since = dt.datetime.fromtimestamp(previous[-1].stat().st_mtime)
    else:
        since = day_start(today - dt.timedelta(days=1))
    since = max(since, now - dt.timedelta(days=MAX_LOOKBACK_DAYS))

    print("=== MORNING-BRIEF CONTEXT ===")
    print(f"Project: {project['name']}")
    for f in project["folders"]:
        print(f"  folder ({f['role']}): {f['path']}" + (f"  [only {f['pattern']}]" if f.get("pattern") else ""))
    print(f"Now: {now:%A %Y-%m-%d %H:%M}")
    print(f"Chat day covered: {chat_day:%A %Y-%m-%d}" if chat_day else
          "Chat day covered: none (no Claude Code chats found for this project in the last 14 days)"
          if read_chats else "Chat reading is switched off in the config.")
    print(f"Files and git covered since: {since:%A %Y-%m-%d %H:%M}")

    if previous:
        section(f"PREVIOUS BRIEF ({previous[-1].name})", previous[-1].read_text(errors="replace")[:3000])
    else:
        section("PREVIOUS BRIEF", "First run: no previous brief.")

    # ---- 1. chats ------------------------------------------------------------------------
    chat_edited, mentioned = set(), []  # mentioned: chat text, to spot file names
    if chat_day:
        start, end = day_start(chat_day), day_start(chat_day) + dt.timedelta(days=1)
        day_sessions = [s for s in mine if any(k == "prompt" and start <= t < end for t, k, _ in s["events"])]
        day_sessions.sort(key=lambda s: next(t for t, k, _ in s["events"] if k == "prompt" and t >= start))
        n_prompts = sum(1 for s in day_sessions for t, k, _ in s["events"] if k == "prompt" and start <= t < end)
        cap = 600 if n_prompts <= 80 else 300 if n_prompts <= 200 else 150
        print(f"\n=== CHATS ON {chat_day:%A %Y-%m-%d}: {len(day_sessions)} chats, {n_prompts} prompts ===")
        for i, s in enumerate(day_sessions, 1):
            print_session(i, s, start, end, folder_paths, cap)
        chat_edited = {str(Path(p).resolve()) for s in day_sessions for t, k, p in s["events"]
                       if k == "edit" and t >= start}
        for s in day_sessions:
            for t, k, x in s["events"]:
                if not (start <= t < end):
                    continue
                if k in ("prompt", "bash", "edit", "read"):
                    mentioned.append((x[0] if k == "prompt" else x).lower())
        since_prev = workday(dt.datetime.fromtimestamp(previous[-1].stat().st_mtime)) if previous else None
        others = [d for d in sorted(per_day) if d != chat_day and d < today and (since_prev is None or d >= since_prev)]
        if others:
            section("OTHER DAYS WITH CHATS SINCE THE LAST BRIEF",
                    "\n".join(f"{d:%a %Y-%m-%d}: {per_day[d]} prompts" for d in others[-7:]))

    # ---- 2. context: code folders first, then the other folders ----------------------------
    exclude = {p.resolve() for p in all_config_folders(cfg) + folder_paths + [brief_dir]}
    for f in project["folders"]:
        if f["role"] == "code":
            code_folder_block(f["path"], since, chat_edited, project.get("log_file"))
    for f in project["folders"]:
        if f["role"] != "code":
            other_folder_block(f, since, exclude - {f["path"].resolve()}, mem)

    # ---- 3. documents yesterday's chats talked about but that did not change ---------------
    if mentioned:
        chat_text, lines, done = "\n".join(mentioned), [], set()
        for f in project["folders"]:
            for p in walk_files(f["path"], None, f.get("recursive", True),
                                exclude - {f["path"].resolve()}):
                if (p.suffix.lower() not in DOC_EXT or p.name in CONTEXT_NAMES + LOG_NAMES
                        or p.name.lower() not in chat_text or p.resolve() in done):
                    continue
                if stat_touched(p) < since.timestamp():
                    done.add(p.resolve())
                    lines.append(f"> {p.name} ({p})\n" + recalled_text(
                        mem, p, "Open it only if a thread cannot be understood without it."))
        if lines:
            section("FILES MENTIONED IN THE CHATS BUT UNCHANGED (summaries from earlier briefs)", "\n\n".join(lines[:15]))

    if args.manifest:
        mem.write_manifest(args.manifest)


if __name__ == "__main__":
    sys.exit(main())
