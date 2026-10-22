#!/usr/bin/env python3
"""
dnd_recap.py - Email yourself a recap of last week's D&D session, built from Bee conversations

PURPOSE:
    Finds the Bee AI conversations captured during your weekly D&D night (default: the
    previous Thursday evening) in the local Bee knowledgebase (populated by sync_bee_ai.py),
    keeps the ones that look like the game (campaign keywords in the transcript),
    and has Claude (the `claude` CLI in print mode) write an in-game recap from the transcripts:
    what happened, your character's moments, decisions, NPCs and open threads for next session.
    Bee's own summaries are not used unless recap.use_bee_summaries is true.
    Household chatter that Bee mixed into the same recording is left out.
    The recap is saved as markdown (<YYYYMMDD>.md) in output.dir -- your Curse of Strahd Sessions
    folder in the knowledgebase -- and emailed. An existing note is never overwritten unless
    --force (or output.overwrite) is set. If Claude can't be run, the
    recap falls back to Bee's own summaries (with a note saying so).
    Designed to run from cron on Thursday morning for the previous week's session.

USAGE:
    python3 dnd_recap.py [OPTIONS]

EXAMPLES:
    python3 dnd_recap.py                          # previous Thursday
    python3 dnd_recap.py --date 2026-10-15
    python3 dnd_recap.py --date 2026-10-15 --list
    python3 dnd_recap.py --date 2026-10-15 --conversation 11313276
    python3 dnd_recap.py --dry-run                # print, don't save or send
    python3 dnd_recap.py --no-llm --dry-run       # Bee summaries only, no Claude call (or recap.use_llm: false)
    python3 dnd_recap.py --sync --verbose
    python3 dnd_recap.py --debug
    python3 dnd_recap.py --config custom_dnd_recap.yml

CRON (Thursday 07:00, after sync_bee_ai.py at 05:00):
    0 7 * * 4 /usr/local/bin/dnd_recap.py >/dev/null 2>&1

EXIT CODES:
    0 = Success (including "no session found that week", which is logged as WARN)
    1 = Configuration error
    2 = Execution error (sync/send failure, etc.)

REQUIREMENTS:
    - PyYAML
    - credvault (only if the yml uses vault: references, e.g. the Gmail app password)
    - Bee conversations synced to bee.knowledgebase_dir (sync_bee_ai.py, or use --sync with the Bee CLI)
    - claude CLI logged in (recap.claude_binary); otherwise Bee summaries are used
    - Reachable SMTP server (email block in the yml)

VERSION: 1.0.0
REVISION HISTORY:
    1.0.0 - Initial implementation (2026-10-22)
"""

import argparse
import getpass
import html
import re
import smtplib
import socket
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

SCRIPT_NAME = Path(__file__).stem
CONFIG_FILENAME = f"{SCRIPT_NAME}.yml"
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

LOGFILE: Optional[str] = None
VERBOSE = False
DEBUG = False

RECAP_SYSTEM_PROMPT = """You write session recaps for a tabletop D&D group.
You are given Bee wearable recordings (rough speech-to-text transcripts with no reliable
speaker labels) from one evening. Write a recap of the GAME ONLY:
ignore work talk, household conversation, TV, health and anything else outside the game.
Transcripts are noisy: names may be misspelled or misheard; prefer the most plausible
in-world spelling and don't invent events that aren't supported by the material.

Output GitHub-flavored markdown only, no preamble, in this shape:
# <Campaign> recap: <Weekday, Month D>
One or two sentences on where the session started and ended.
## <one heading per major scene/location, in order>
Bullets of what happened, who was met, what was learned or gained.
## <Player>'s moments
Bullets about the player's own character (decisions, items, arguments they made). Omit if none.
## Key decisions
## NPCs
Bullets: **Name** - who they are / what they want (only ones that mattered this session).
## Loot & rewards
Omit if none.
## Open threads / next session
Bullets of unresolved leads, plans and anything the party agreed to do next."""


class ConfigError(Exception):
    pass


class RecapError(Exception):
    pass


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
def logit(msg: str, status: str = "INFO", logFile: Optional[str] = None,
          debug: Optional[bool] = None, verbose: Optional[bool] = None,
          clearlog: bool = False) -> None:
    """Timestamped file logger; debug/verbose also echo to stdout."""
    logFile = logFile or LOGFILE or str(Path.home() / "logs" / f"{SCRIPT_NAME}.log")
    debug = DEBUG if debug is None else debug
    verbose = VERBOSE if verbose is None else verbose
    status = (status or "INFO").upper()
    if debug:
        status = "DEBUG"
    elif verbose and status == "DEBUG":
        status = "INFO"
    line = f"{datetime.now().strftime('%Y%m%d:%H%M%S')} {status} {msg}"
    path = Path(logFile).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w" if clearlog else "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    if debug or verbose:
        print(line)


def exit_script(code: int) -> None:
    if code == 0:
        logit(f"{SCRIPT_NAME} Completed")
    else:
        logit(f"{SCRIPT_NAME} Exiting with errors (exit code {code})", "ERROR")
    path = Path(LOGFILE or str(Path.home() / "logs" / f"{SCRIPT_NAME}.log")).expanduser()
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n\n")
    sys.exit(code)


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
def find_config_path(cli_path: Optional[str]) -> Path:
    if cli_path:
        p = Path(cli_path).expanduser()
        if not p.is_file():
            raise ConfigError(f"Config file not found: {p}")
        return p
    candidates = [Path.cwd() / CONFIG_FILENAME, Path("/usr/local/etc") / CONFIG_FILENAME]
    for p in candidates:
        if p.is_file():
            return p
    raise ConfigError("Config file not found. Searched: " + ", ".join(str(c) for c in candidates))


def load_config(path: Path) -> Dict[str, Any]:
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as ex:
        raise ConfigError(f"Cannot parse {path}: {ex}")
    for section in ("bee", "session", "recap", "output", "email"):
        cfg.setdefault(section, {})
        if not isinstance(cfg[section], dict):
            raise ConfigError(f"'{section}' must be a mapping in {path}")
    if not cfg["bee"].get("knowledgebase_dir"):
        raise ConfigError("bee.knowledgebase_dir is required")
    if str(cfg["session"].get("weekday", "thursday")).lower() not in WEEKDAYS:
        raise ConfigError(f"session.weekday must be one of {WEEKDAYS}")
    for key, default in (("evening_start", "17:00"), ("evening_end", "23:59")):
        try:
            datetime.strptime(str(cfg["session"].get(key, default)), "%H:%M")
        except ValueError:
            raise ConfigError(f"session.{key} must look like HH:MM")
    if not cfg["session"].get("keywords"):
        raise ConfigError("session.keywords must list at least one campaign keyword")
    return cfg


def resolve_vault_refs(section: Dict[str, Any]) -> Dict[str, Any]:
    """Replace vault:NAME strings via credvault; only imported when a reference is present."""
    if not any(isinstance(v, str) and v.startswith("vault:") for v in section.values()):
        return section
    sys.path.insert(0, "/usr/local/bin")
    try:
        from credvault import resolve_secrets
        return resolve_secrets(section)
    except Exception as ex:  # ImportError or CredVaultError
        raise ConfigError(f"Cannot resolve vault reference: {ex}")


# --------------------------------------------------------------------------
# Bee conversation parsing
# --------------------------------------------------------------------------
def parse_iso(value: str) -> datetime:
    """Bee timestamps are UTC (...Z); return an aware datetime in local time."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()


def sections(text: str) -> Dict[str, str]:
    """Split a conversation markdown file into {'## heading': body} (Transcriptions excluded)."""
    out: Dict[str, str] = {}
    current = None
    for line in text.split("## Transcriptions", 1)[0].splitlines():
        m = re.match(r"^## (.+?)\s*$", line)
        if m:
            current = m.group(1)
            out[current] = ""
        elif current:
            out[current] += line + "\n"
    return out


def bullets(body: str) -> List[str]:
    items = [re.sub(r"^\s*[-*]\s+", "", ln).strip() for ln in body.splitlines() if re.match(r"^\s*[-*]\s+", ln)]
    return [i for i in items if i and i != "(none)"]


def parse_conversation(path: Path) -> Optional[Dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    meta = dict(re.findall(r"^- (start_time|end_time): (\S+)", text, re.M))
    if "start_time" not in meta:
        return None
    secs = sections(text)
    transcript = text.split("## Transcriptions", 1)[1] if "## Transcriptions" in text else ""
    transcript = "\n".join(ln for ln in transcript.splitlines()
                           if ln.strip() and not re.match(r"^(### Transcription|- realtime:)", ln))
    start = parse_iso(meta["start_time"])
    return {
        "id": path.stem,
        "start": start,
        "end": parse_iso(meta["end_time"]) if "end_time" in meta else start,
        "title": secs.get("Short Summary", "").strip() or f"Conversation {path.stem}",
        "summary": re.sub(r"^## Summary\s*", "", secs.get("Summary", "").strip()).strip(),
        "takeaways": bullets(secs.get("Key Take aways", secs.get("Key Takeaways", ""))),
        "actions": bullets(secs.get("Action Items", "")) + bullets(secs.get("Next Session", "")),
        "transcript": transcript,
    }


def load_day(kb_dir: Path, day: date) -> List[Dict[str, Any]]:
    """Conversations that start on `day` in local time (Bee's folders are by UTC date, so check neighbours)."""
    convs: Dict[str, Dict[str, Any]] = {}
    for offset in (-1, 0, 1):
        folder = kb_dir / "conversations" / (day + timedelta(days=offset)).isoformat()
        if not folder.is_dir():
            continue
        for f in folder.glob("*.md"):
            c = parse_conversation(f)
            if c and c["start"].date() == day:
                convs[c["id"]] = c
    return sorted(convs.values(), key=lambda c: c["start"])


def keyword_hits(conv: Dict[str, Any], keywords: List[str], use_summaries: bool = False) -> int:
    """Total occurrences of the campaign keywords (whole words, case-insensitive); Bee's title/summary count only if use_summaries."""
    blob = " ".join([conv["title"], conv["summary"], conv["transcript"]] if use_summaries else [conv["transcript"]])
    return sum(len(re.findall(rf"(?<!\w){re.escape(k)}(?!\w)", blob, re.I)) for k in keywords)


def evening_window(day: date, scfg: Dict[str, Any]) -> tuple:
    def at(hhmm: str) -> datetime:
        h, m = map(int, hhmm.split(":"))
        return datetime.combine(day, time(h, m)).astimezone()
    return at(str(scfg.get("evening_start", "17:00"))), at(str(scfg.get("evening_end", "23:59")))


def select_session(convs: List[Dict[str, Any]], window: tuple, scfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Conversations overlapping the evening window that mention the campaign often enough."""
    lo, hi = window
    need = int(scfg.get("min_keyword_hits", 3))
    return [c for c in convs if c["end"] >= lo and c["start"] <= hi and c["hits"] >= need]


# --------------------------------------------------------------------------
# Recap
# --------------------------------------------------------------------------
def fmt_time(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def fmt_day(day: date) -> str:
    return day.strftime("%A, %B %d, %Y").replace(" 0", " ")


def build_source(convs: List[Dict[str, Any]], max_chars: int, use_summaries: bool = False) -> str:
    """Transcripts (plus Bee summaries if use_summaries), transcripts trimmed evenly if the total is over max_chars."""
    heads = [f"=== Bee conversation {c['id']} ({fmt_time(c['start'])} - {fmt_time(c['end'])})\n"
             + (f"--- Bee summary ({c['title']}) ---\n{c['summary']}\n"
                + "".join(f"- {t}\n" for t in c["takeaways"] + c["actions"]) if use_summaries else "")
             for c in convs]
    budget = max(0, max_chars - sum(len(h) for h in heads))
    total = sum(len(c["transcript"]) for c in convs) or 1
    parts = []
    for h, c in zip(heads, convs):
        t = c["transcript"]
        keep = int(budget * len(t) / total)
        if len(t) > keep:
            t = t[:keep] + "\n[...transcript truncated...]"
        parts.append(f"{h}--- Transcript ---\n{t}\n")
    return "\n".join(parts)


def run_claude(source: str, day: date, rcfg: Dict[str, Any]) -> str:
    system_prompt = RECAP_SYSTEM_PROMPT
    if rcfg.get("use_bee_summaries"):
        system_prompt += "\n\nBee's auto-generated summaries are included as hints; the transcripts are authoritative."
    instructions = (f"Campaign: {rcfg.get('campaign') or 'unknown'}. "
                    f"The player who wants this recap is {rcfg.get('my_name', 'the player')}"
                    + (f", who plays {rcfg['my_character']}" if rcfg.get("my_character") else "")
                    + f". Session date: {fmt_day(day)}. Write the recap from the material on stdin.")
    cmd = [str(Path(str(rcfg.get("claude_binary", "claude"))).expanduser()), "-p", instructions,
           "--system-prompt", system_prompt, "--tools", "", "--no-session-persistence",
           "--output-format", "text"]
    if rcfg.get("model"):
        cmd += ["--model", str(rcfg["model"])]
    logit(f"Running claude ({len(source)} chars of source)")
    try:
        r = subprocess.run(cmd, input=source, capture_output=True, text=True,
                           timeout=int(rcfg.get("timeout_seconds", 600)))
    except (OSError, subprocess.TimeoutExpired) as ex:
        raise RecapError(f"claude failed: {ex}")
    if r.returncode != 0 or not r.stdout.strip():
        raise RecapError(f"claude exited {r.returncode}: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout.strip() + "\n"


def transcript_note(day: date, convs: List[Dict[str, Any]], rcfg: Dict[str, Any], reason: str) -> str:
    """No-Claude note built only from the raw transcripts (no Bee summaries)."""
    L = [f"# {rcfg.get('campaign') or 'D&D'} session transcript: {fmt_day(day)}", "",
         f"_Raw Bee transcript ({reason}); not summarized and may include non-game talk._", ""]
    for c in convs:
        L += [f"## Conversation {c['id']} ({fmt_time(c['start'])} - {fmt_time(c['end'])})", "", c["transcript"], ""]
    return "\n".join(L)


def bee_fallback(day: date, convs: List[Dict[str, Any]], rcfg: Dict[str, Any], reason: str) -> str:
    L = [f"# {rcfg.get('campaign') or 'D&D'} recap: {fmt_day(day)}", "",
         f"_Claude recap unavailable ({reason}); these are Bee's own summaries and may include non-game talk._", ""]
    for c in convs:
        L += [f"## {c['title']} ({fmt_time(c['start'])} - {fmt_time(c['end'])})", "", c["summary"] or "(no summary)", ""]
        if c["takeaways"]:
            L += ["**Takeaways**", ""] + [f"- {t}" for t in c["takeaways"]] + [""]
        if c["actions"]:
            L += ["**Open threads / next session**", ""] + [f"- {t}" for t in c["actions"]] + [""]
    return "\n".join(L)


def md_to_html(md: str) -> str:
    """Just enough markdown (headings, bullets, bold/italic, paragraphs) for the recap email."""
    def inline(s: str) -> str:
        s = html.escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        return re.sub(r"(?<!\w)[_*](.+?)[_*](?!\w)", r"<i>\1</i>", s)

    out, in_list = [], False
    for ln in md.splitlines():
        m_h = re.match(r"^(#{1,4})\s+(.*)", ln)
        m_li = re.match(r"^\s*[-*]\s+(.*)", ln)
        if in_list and not m_li:
            out.append("</ul>")
            in_list = False
        if m_h:
            n = len(m_h.group(1))
            out.append(f"<h{n}>{inline(m_h.group(2))}</h{n}>")
        elif m_li:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(m_li.group(1))}</li>")
        elif ln.strip():
            out.append(f"<p>{inline(ln)}</p>")
    if in_list:
        out.append("</ul>")
    return ("<html><body style=\"font-family:Arial,sans-serif;font-size:14px;max-width:760px\">"
            + "\n".join(out) + "</body></html>")


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------
def default_session_day(weekday: str, today: Optional[date] = None) -> date:
    """Most recent `weekday` strictly before today (so a Thursday run recaps the previous Thursday)."""
    today = today or date.today()
    return today - timedelta(days=((today.weekday() - WEEKDAYS.index(weekday.lower())) % 7) or 7)


def run_sync(bcfg: Dict[str, Any]) -> None:
    cmd = [bcfg.get("binary", "bee"), "sync", "--output", str(Path(bcfg["knowledgebase_dir"]).expanduser()),
           "--only", "conversations", "--recent-days", str(int(bcfg.get("sync_recent_days", 8)))]
    logit(f"Running: {' '.join(cmd)}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=int(bcfg.get("sync_timeout_seconds", 600)))
    except (OSError, subprocess.TimeoutExpired) as ex:
        raise RecapError(f"bee sync failed: {ex}")
    if r.returncode != 0:
        raise RecapError(f"bee sync exited {r.returncode}: {(r.stderr or r.stdout).strip()[:300]}")


def save_recap(ocfg: Dict[str, Any], day: date, text: str, force: bool = False) -> Optional[Path]:
    """Write <YYYYMMDD>.md; returns None (file untouched) if it exists and overwriting isn't allowed."""
    folder = Path(str(ocfg.get("dir") or "~/Documents/dnd_recaps")).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day.strftime('%Y%m%d')}.md"
    if path.exists() and not (force or ocfg.get("overwrite", False)):
        return None
    path.write_text(text, encoding="utf-8")
    return path


def send_email(ecfg: Dict[str, Any], subject: str, text: str, body_html: str) -> None:
    if not ecfg.get("to"):
        raise ConfigError("email.to is required (or pass --to)")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = ecfg.get("from") or ecfg.get("username") or f"{getpass.getuser()}@{socket.getfqdn()}"
    msg["To"] = ecfg["to"] if isinstance(ecfg["to"], str) else ", ".join(ecfg["to"])
    msg.set_content(text)
    msg.add_alternative(body_html, subtype="html")
    try:
        with smtplib.SMTP(ecfg.get("smtp_host", "smtp.iufh.local"), int(ecfg.get("smtp_port", 25)), timeout=30) as s:
            if ecfg.get("starttls"):
                s.starttls()
            if ecfg.get("username"):
                s.login(ecfg["username"], ecfg.get("password") or "")
            s.send_message(msg)
    except (OSError, smtplib.SMTPException) as ex:
        raise RecapError(f"Send failed: {ex}")


def print_candidates(convs: List[Dict[str, Any]], window: tuple, scfg: Dict[str, Any]) -> None:
    print(f"Evening window {fmt_time(window[0])} - {fmt_time(window[1])}, "
          f"needs >= {int(scfg.get('min_keyword_hits', 3))} keyword hits")
    if not convs:
        print("No conversations found for that date.")
    picked = {c["id"] for c in select_session(convs, window, scfg)}
    for c in convs:
        hit = "*" if c["id"] in picked else " "
        print(f"{hit} {c['id']}  {fmt_time(c['start']):>8} - {fmt_time(c['end']):<8} hits={c['hits']:<4} {c['title']}")
    print("(* = selected as the session; use --conversation ID to choose explicitly)")


def main() -> None:
    global LOGFILE, VERBOSE, DEBUG
    p = argparse.ArgumentParser(description="Recap last week's D&D session from Bee conversations")
    p.add_argument("--date", help="Session date YYYY-MM-DD (default: previous configured weekday)")
    p.add_argument("--conversation", action="append", help="Use this Bee conversation ID instead of auto-selection; repeatable")
    p.add_argument("--list", action="store_true", help="List the day's conversations and exit (nothing is sent)")
    p.add_argument("--sync", action="store_true", help="Run `bee sync` for recent conversations first")
    p.add_argument("--no-llm", action="store_true", help="Skip Claude; build the recap from Bee summaries")
    p.add_argument("--dry-run", action="store_true", help="Print the recap instead of saving and emailing it")
    p.add_argument("--no-email", action="store_true", help="Save the recap file but don't email it")
    p.add_argument("--force", action="store_true", help="Overwrite an existing recap file for that date")
    p.add_argument("--to", help="Override the email recipient(s)")
    p.add_argument("--config", help="Path to yml config")
    p.add_argument("--logfile", help="Log file path")
    p.add_argument("--verbose", action="store_true", help="Enable verbose output")
    p.add_argument("--debug", action="store_true", help="Enable debug output")
    args = p.parse_args()

    try:
        cfg_path = find_config_path(args.config)
        cfg = load_config(cfg_path)
    except ConfigError as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        sys.exit(1)

    lc = cfg.get("logging") or {}
    VERBOSE = args.verbose or bool(lc.get("verbose", False))
    DEBUG = args.debug or bool(lc.get("debug", False))
    LOGFILE = args.logfile or lc.get("logfile") or str(Path.home() / "logs" / f"{SCRIPT_NAME}.log")
    logit(f"Starting {SCRIPT_NAME}", clearlog=bool(lc.get("clearlog", False)))

    bcfg, scfg, rcfg, ocfg, ecfg = cfg["bee"], cfg["session"], cfg["recap"], cfg["output"], dict(cfg["email"])
    if args.to:
        ecfg["to"] = args.to
    try:
        if args.date:
            try:
                day = date.fromisoformat(args.date)
            except ValueError:
                raise ConfigError(f"--date must be YYYY-MM-DD, got '{args.date}'")
        else:
            day = default_session_day(str(scfg.get("weekday", "thursday")))
        if VERBOSE or DEBUG:
            logit(f"Finalized parameters: config={cfg_path} date={day} conversation={args.conversation} "
                  f"list={args.list} sync={args.sync} no_llm={args.no_llm} dry_run={args.dry_run} "
                  f"no_email={args.no_email} to={ecfg.get('to')} output_dir={ocfg.get('dir')} logfile={LOGFILE}")

        if args.sync:
            run_sync(bcfg)
        kb = Path(bcfg["knowledgebase_dir"]).expanduser()
        use_summaries = bool(rcfg.get("use_bee_summaries", False))
        convs = load_day(kb, day)
        for c in convs:
            c["hits"] = keyword_hits(c, [str(k) for k in scfg["keywords"]], use_summaries)
        window = evening_window(day, scfg)
        logit(f"{len(convs)} conversation(s) on {day}")

        if args.list:
            print_candidates(convs, window, scfg)
            exit_script(0)

        if args.conversation:
            chosen = [c for c in convs if c["id"] in set(args.conversation)]
            missing = set(args.conversation) - {c["id"] for c in chosen}
            if missing:
                raise RecapError(f"Conversation(s) not found on {day}: {', '.join(sorted(missing))} (try --list)")
        else:
            chosen = select_session(convs, window, scfg)
        if not chosen:
            hint = "" if convs else f" No synced conversations for that date in {kb} (try --sync)."
            logit(f"No D&D session found on {day}.{hint} Nothing sent.", "WARN")
            print(f"No D&D session found on {day}.{hint} Use --list to review.")
            exit_script(0)
        logit(f"Using conversation(s): {', '.join(c['id'] for c in chosen)}")

        if args.no_llm or not rcfg.get("use_llm", True):
            why = "--no-llm" if args.no_llm else "recap.use_llm is false"
            recap = bee_fallback(day, chosen, rcfg, why) if use_summaries else transcript_note(day, chosen, rcfg, why)
        else:
            try:
                recap = run_claude(build_source(chosen, int(rcfg.get("max_source_chars", 400000)), use_summaries),
                                   day, rcfg)
            except RecapError as ex:
                if not use_summaries:
                    raise
                logit(f"{ex}; falling back to Bee summaries", "WARN")
                recap = bee_fallback(day, chosen, rcfg, str(ex)[:120])
        recap += f"\n_Source: Bee conversation(s) {', '.join(c['id'] for c in chosen)}_\n"

        if args.dry_run:
            print(recap)
            exit_script(0)
        path = save_recap(ocfg, day, recap, args.force)
        if path is None:
            existing = Path(str(ocfg.get("dir"))).expanduser() / f"{day.strftime('%Y%m%d')}.md"
            logit(f"{existing} already exists; not overwritten (use --force)", "WARN")
            print(f"WARNING: {existing} already exists; not overwritten (use --force)")
        else:
            logit(f"Saved recap to {path}")
            print(f"Saved recap to {path}")
        if not args.no_email and ecfg.get("enabled", True):
            ecfg = resolve_vault_refs(ecfg)
            subject = str(ecfg.get("subject", "D&D Recap - {date}")).format(date=day.isoformat())
            send_email(ecfg, subject, recap, md_to_html(recap))
            logit(f"Emailed recap to {ecfg['to']}")
            print(f"Emailed recap for {day} to {ecfg['to']}")
    except ConfigError as ex:
        logit(str(ex), "ERROR")
        print(f"ERROR: {ex}", file=sys.stderr)
        exit_script(1)
    except RecapError as ex:
        logit(str(ex), "ERROR")
        print(f"ERROR: {ex}", file=sys.stderr)
        exit_script(2)
    exit_script(0)


if __name__ == "__main__":
    main()
