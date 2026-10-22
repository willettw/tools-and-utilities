#!/usr/bin/env python3
"""
meeting_notes.py - Save (and optionally email) notes from your weekly meetings, built from Bee conversations

PURPOSE:
    For each meeting defined in the yml (weekday + start time), finds the Bee AI conversation
    captured at that time in the local Bee knowledgebase (populated by sync_bee_ai.py) and writes
    a notes file, <YYYYMMDD>.md, into that meeting's output_dir (e.g. a folder in your knowledgebase).
    The notes use a fixed template: who was there (as far as Bee could identify), topics and what was
    discussed, takeaways and action items. A meeting that Bee split into several back-to-back
    conversations is merged into one set of notes. Notes are emailed only when the meeting's
    send_email is true (or --email is passed). Schedule several meetings by adding entries to
    `meeting:` and running the script per meeting from cron with --meeting NAME.
    An existing notes file is never overwritten unless --force (or the meeting's overwrite) is set.
    Use --list to see every conversation for the day, and --conversation to pick exact ones
    when the automatic time-window match is wrong.

USAGE:
    python3 meeting_notes.py [OPTIONS]

EXAMPLES:
    python3 meeting_notes.py                        # every configured meeting, most recent occurrence
    python3 meeting_notes.py --meeting "Weekly Sr IT"
    python3 meeting_notes.py --date 2026-10-15
    python3 meeting_notes.py --date 2026-10-15 --list
    python3 meeting_notes.py --meeting "Weekly Sr IT" --date 2026-10-15 --conversation 11290808
    python3 meeting_notes.py --date 2026-10-15 --dry-run    # print, don't save or send
    python3 meeting_notes.py --date 2026-10-15 --email      # save, and email too
    python3 meeting_notes.py --sync --verbose
    python3 meeting_notes.py --debug
    python3 meeting_notes.py --config custom_meeting_notes.yml

EXIT CODES:
    0 = Success (including "no conversation matched", which is logged as WARN)
    1 = Configuration error
    2 = Execution error (sync/send failure, conversation not found, etc.)

REQUIREMENTS:
    - PyYAML
    - Bee conversations synced to bee.knowledgebase_dir (sync_bee_ai.py, or use --sync with the Bee CLI)
    - Reachable SMTP relay (email block in the yml), only for meetings that send email

VERSION: 1.1.0
REVISION HISTORY:
    1.0.0 - Initial implementation (2026-10-22)
    1.1.0 - Multiple meetings, per-meeting output_dir, notes saved as markdown, email only on request (2026-10-22)
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


class ConfigError(Exception):
    pass


class MeetingError(Exception):
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
    for section in ("bee", "email"):
        cfg.setdefault(section, {})
        if not isinstance(cfg[section], dict):
            raise ConfigError(f"'{section}' must be a mapping in {path}")
    if not cfg["bee"].get("knowledgebase_dir"):
        raise ConfigError("bee.knowledgebase_dir is required")
    meetings = cfg.get("meeting") or {}
    if isinstance(meetings, dict):
        meetings = [meetings]
    if not meetings or not all(isinstance(m, dict) for m in meetings):
        raise ConfigError(f"'meeting' must be a mapping or a list of mappings in {path}")
    seen = set()
    for m in meetings:
        m.setdefault("weekday", "thursday")
        m.setdefault("start", "10:00")
        m.setdefault("name", f"{m['weekday']} {m['start']}")
        label = f"meeting '{m['name']}'"
        if str(m["weekday"]).lower() not in WEEKDAYS:
            raise ConfigError(f"{label}: weekday must be one of {WEEKDAYS}")
        try:
            datetime.strptime(str(m["start"]), "%H:%M")
        except ValueError:
            raise ConfigError(f"{label}: start must look like HH:MM")
        if not m.get("output_dir"):
            raise ConfigError(f"{label}: output_dir is required")
        m["every_weeks"] = int(m.get("every_weeks") or 1)
        if m["every_weeks"] > 1:
            try:
                anchor = m.get("anchor_date")
                m["anchor_date"] = anchor if isinstance(anchor, date) else datetime.strptime(str(anchor), "%Y-%m-%d").date()
            except ValueError:
                raise ConfigError(f"{label}: anchor_date (YYYY-MM-DD) is required when every_weeks > 1")
            if m["anchor_date"].weekday() != WEEKDAYS.index(str(m["weekday"]).lower()):
                raise ConfigError(f"{label}: anchor_date {m['anchor_date']} is not a {m['weekday']}")
        if m["name"] in seen:
            raise ConfigError(f"Duplicate meeting name '{m['name']}'")
        seen.add(m["name"])
    cfg["meeting"] = meetings
    return cfg


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
    for line in text.splitlines():
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
    meta = dict(re.findall(r"^- (start_time|end_time|state): (\S+)", text, re.M))
    if "start_time" not in meta:
        return None
    secs = sections(text)
    summary = re.sub(r"^## Summary\s*", "", secs.get("Summary", "").strip()).strip()
    speakers: Dict[str, int] = {}
    for name in re.findall(r"^- ([^:\n]{1,40}): ", text.split("## Transcriptions", 1)[-1], re.M):
        speakers[name.strip()] = speakers.get(name.strip(), 0) + 1
    start = parse_iso(meta["start_time"])
    end = parse_iso(meta["end_time"]) if meta.get("end_time", "n/a").strip().lower() != "n/a" else start
    return {
        "id": path.stem,
        "path": path,
        "start": start,
        "end": end,
        "title": secs.get("Short Summary", "").strip() or f"Conversation {path.stem}",
        "summary": summary,
        "atmosphere": secs.get("Atmosphere", "").strip(),
        "takeaways": bullets(secs.get("Key Take aways", secs.get("Key Takeaways", ""))),
        "actions": bullets(secs.get("Action Items", "")),
        "speakers": speakers,
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


def meeting_window(day: date, mcfg: Dict[str, Any]) -> tuple:
    """(earliest, latest) start time, local, for a conversation to count as the start of the meeting."""
    h, m = map(int, str(mcfg.get("start", "10:00")).split(":"))
    start = datetime.combine(day, time(h, m)).astimezone()
    return (start - timedelta(minutes=int(mcfg.get("early_minutes", 15))),
            start + timedelta(minutes=int(mcfg.get("start_slack_minutes", 20))))


def select_meeting(convs: List[Dict[str, Any]], window: tuple, merge_gap_minutes: int = 3) -> List[Dict[str, Any]]:
    """Conversations starting inside `window`, plus any that follow within merge_gap_minutes (Bee splits long meetings)."""
    lo, hi = window
    chosen = [c for c in convs if lo <= c["start"] <= hi]
    if not chosen:
        return []
    end = max(c["end"] for c in chosen)
    for c in convs:
        if c in chosen or c["start"] < chosen[0]["start"]:
            continue
        if c["start"] - end <= timedelta(minutes=merge_gap_minutes):
            chosen.append(c)
            end = max(end, c["end"])
    return sorted(chosen, key=lambda c: c["start"])


# --------------------------------------------------------------------------
# Notes
# --------------------------------------------------------------------------
def attendees(convs: List[Dict[str, Any]], mcfg: Dict[str, Any]) -> Dict[str, Any]:
    """Names from transcript speaker labels and 'Name:' owners in action items; Bee often can't name others."""
    ignore = {s.lower() for s in mcfg.get("ignore_speakers", ["Unknown"])}
    me = str(mcfg.get("my_name", "")).lower()
    names: List[str] = []
    unknown = False
    for c in convs:
        found = list(c["speakers"])
        for a in c["actions"]:
            m = re.match(r"^([A-Z][\w' .-]*?):\s", a)
            if m:
                found += re.split(r"\s+and\s+|,\s*", m.group(1))
        for n in found:
            n = n.strip()
            if n.lower() == "unknown":
                unknown = True
            if not n or n.lower() in ignore or n.lower() == me or not n[0].isupper():
                continue
            if n not in names:
                names.append(n)
    return {"names": names, "unidentified": unknown or not names}


def build_notes(day: date, convs: List[Dict[str, Any]], mcfg: Dict[str, Any]) -> Dict[str, Any]:
    start, end = convs[0]["start"], max(c["end"] for c in convs)
    minutes = round((end - start).total_seconds() / 60)
    takeaways, actions = [], []
    for c in convs:
        takeaways += [t for t in c["takeaways"] if t not in takeaways]
        actions += [a for a in c["actions"] if a not in actions]
    me = str(mcfg.get("my_name", "")).lower()
    mine = [a for a in actions if me and re.match(rf"^[^:]*\b{re.escape(me)}\b[^:]*:", a, re.I)]
    return {
        "name": mcfg.get("name", "Meeting"),
        "day": day, "start": start, "end": end, "minutes": minutes, "convs": convs,
        "attendees": attendees(convs, mcfg), "takeaways": takeaways,
        "actions": actions, "my_actions": mine, "my_name": mcfg.get("my_name", "You"),
    }


def fmt_time(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def fmt_day(day: date) -> str:
    return day.strftime("%A, %B %d, %Y").replace(" 0", " ")


def render_text(n: Dict[str, Any]) -> str:
    L = [f"{n['name']} - {fmt_day(n['day'])}",
         f"Time: {fmt_time(n['start'])} - {fmt_time(n['end'])} ({n['minutes']} min)",
         f"Source: Bee conversation(s) {', '.join(c['id'] for c in n['convs'])}", "", "WHO WAS THERE"]
    a = n["attendees"]
    L.append(f"  - {n['my_name']} (you)")
    L += [f"  - {x}" for x in a["names"]]
    if a["unidentified"]:
        L.append("  - Other participants Bee could not identify")
    L += ["", "TOPICS DISCUSSED"]
    for i, c in enumerate(n["convs"], 1):
        L += [f"  {i}. {c['title']} ({fmt_time(c['start'])} - {fmt_time(c['end'])})"]
        L += [f"     {ln}" if ln else "" for ln in (c["summary"] or "(no summary available)").splitlines()]
        L.append("")
    L.append("TAKEAWAYS")
    L += [f"  - {t}" for t in n["takeaways"]] or ["  (none recorded)"]
    L += ["", "ACTION ITEMS"]
    L += [f"  - {t}" for t in n["actions"]] or ["  (none recorded)"]
    if n["my_actions"]:
        L += ["", f"ACTION ITEMS FOR YOU ({n['my_name']})"] + [f"  - {t}" for t in n["my_actions"]]
    return "\n".join(L) + "\n"


def render_html(n: Dict[str, Any]) -> str:
    e = html.escape

    def ul(items: List[str]) -> str:
        return "<ul>" + "".join(f"<li>{e(i)}</li>" for i in items) + "</ul>" if items else "<p><i>None recorded</i></p>"

    a = n["attendees"]
    people = [f"{n['my_name']} (you)"] + a["names"] + (["Other participants Bee could not identify"] if a["unidentified"] else [])
    topics = "".join(
        f"<h3>{i}. {e(c['title'])} <small>({fmt_time(c['start'])} - {fmt_time(c['end'])})</small></h3>"
        + "".join(f"<p>{e(p)}</p>" for p in re.split(r"\n\s*\n", c["summary"] or "(no summary available)") if p.strip())
        for i, c in enumerate(n["convs"], 1))
    mine = f"<h2>Action items for you ({e(str(n['my_name']))})</h2>{ul(n['my_actions'])}" if n["my_actions"] else ""
    return (
        "<html><body style=\"font-family:Arial,sans-serif;font-size:14px;max-width:760px\">"
        f"<h1>{e(n['name'])} - {e(fmt_day(n['day']))}</h1>"
        f"<p><b>Time:</b> {fmt_time(n['start'])} - {fmt_time(n['end'])} ({n['minutes']} min)<br>"
        f"<b>Source:</b> Bee conversation(s) {e(', '.join(c['id'] for c in n['convs']))}</p>"
        f"<h2>Who was there</h2>{ul(people)}<h2>Topics discussed</h2>{topics}"
        f"<h2>Takeaways</h2>{ul(n['takeaways'])}<h2>Action items</h2>{ul(n['actions'])}{mine}"
        "</body></html>")


def render_markdown(n: Dict[str, Any]) -> str:
    a = n["attendees"]
    L = [f"# {n['name']} - {fmt_day(n['day'])}", "",
         f"**Time:** {fmt_time(n['start'])} - {fmt_time(n['end'])} ({n['minutes']} min)  ",
         f"**Source:** Bee conversation(s) {', '.join(c['id'] for c in n['convs'])}", "",
         "## Who was there", "", f"- {n['my_name']} (you)"]
    L += [f"- {x}" for x in a["names"]]
    if a["unidentified"]:
        L.append("- Other participants Bee could not identify")
    L += ["", "## Topics discussed", ""]
    for i, c in enumerate(n["convs"], 1):
        L += [f"### {i}. {c['title']} ({fmt_time(c['start'])} - {fmt_time(c['end'])})", "",
              c["summary"] or "(no summary available)", ""]
    L += ["## Takeaways", ""] + ([f"- {t}" for t in n["takeaways"]] or ["_None recorded_"])
    L += ["", "## Action items", ""] + ([f"- {t}" for t in n["actions"]] or ["_None recorded_"])
    if n["my_actions"]:
        L += ["", f"## Action items for you ({n['my_name']})", ""] + [f"- {t}" for t in n["my_actions"]]
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------
def default_meeting_day(weekday: str, today: Optional[date] = None) -> date:
    today = today or date.today()
    return today - timedelta(days=(today.weekday() - WEEKDAYS.index(weekday.lower())) % 7)


def off_cycle_ok(m: Dict[str, Any], day: date) -> bool:
    """True if `day` falls on the meeting's every_weeks cycle counted from anchor_date."""
    if m["every_weeks"] <= 1:
        return True
    return (day - m["anchor_date"]).days % (7 * m["every_weeks"]) == 0


def run_sync(bcfg: Dict[str, Any]) -> None:
    cmd = [bcfg.get("binary", "bee"), "sync", "--output", str(Path(bcfg["knowledgebase_dir"]).expanduser()),
           "--only", "conversations", "--recent-days", str(int(bcfg.get("sync_recent_days", 3)))]
    logit(f"Running: {' '.join(cmd)}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=int(bcfg.get("sync_timeout_seconds", 600)))
    except (OSError, subprocess.TimeoutExpired) as ex:
        raise MeetingError(f"bee sync failed: {ex}")
    if r.returncode != 0:
        raise MeetingError(f"bee sync exited {r.returncode}: {(r.stderr or r.stdout).strip()[:300]}")


def send_email(ecfg: Dict[str, Any], subject: str, text: str, body_html: str) -> None:
    if not ecfg.get("to"):
        raise ConfigError("email.to is required (or pass --to)")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = ecfg.get("from") or f"{getpass.getuser()}@{socket.getfqdn()}"
    msg["To"] = ecfg["to"] if isinstance(ecfg["to"], str) else ", ".join(ecfg["to"])
    msg.set_content(text)
    msg.add_alternative(body_html, subtype="html")
    try:
        with smtplib.SMTP(ecfg.get("smtp_host", "smtp.iufh.local"), int(ecfg.get("smtp_port", 25)), timeout=30) as s:
            s.send_message(msg)
    except (OSError, smtplib.SMTPException) as ex:
        raise MeetingError(f"Send failed: {ex}")


def save_notes(mcfg: Dict[str, Any], day: date, text: str, force: bool = False) -> Optional[Path]:
    """Write <YYYYMMDD>.md to the meeting's output_dir; None (file untouched) if it exists and overwriting isn't allowed."""
    folder = Path(str(mcfg["output_dir"])).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day.strftime('%Y%m%d')}.md"
    if path.exists() and not (force or mcfg.get("overwrite", False)):
        return None
    path.write_text(text, encoding="utf-8")
    return path


def print_candidates(convs: List[Dict[str, Any]], window: tuple, gap: int) -> None:
    print(f"Meeting must start between {fmt_time(window[0])} and {fmt_time(window[1])}")
    if not convs:
        print("No conversations found for that date.")
    picked = {c["id"] for c in select_meeting(convs, window, gap)}
    for c in convs:
        hit = "*" if c["id"] in picked else " "
        print(f"{hit} {c['id']}  {fmt_time(c['start']):>8} - {fmt_time(c['end']):<8} {c['title']}")
    print("(* = selected as the meeting; use --conversation ID to choose explicitly)")


def run_meeting(mcfg: Dict[str, Any], day: date, args: argparse.Namespace, kb: Path, ecfg: Dict[str, Any]) -> None:
    """Find the meeting's conversations for `day`, save the notes, and email them if requested."""
    name = mcfg["name"]
    convs = load_day(kb, day)
    window = meeting_window(day, mcfg)
    gap = int(mcfg.get("merge_gap_minutes", 3))
    logit(f"[{name}] {len(convs)} conversation(s) on {day}")

    if args.list:
        print(f"== {name} ({day})")
        print_candidates(convs, window, gap)
        return

    if args.conversation:
        chosen = [c for c in convs if c["id"] in set(args.conversation)]
        missing = set(args.conversation) - {c["id"] for c in chosen}
        if missing:
            raise MeetingError(f"[{name}] Conversation(s) not found on {day}: {', '.join(sorted(missing))} (try --list)")
    else:
        chosen = select_meeting(convs, window, gap)
    if not chosen:
        hint = "" if convs else f" No synced conversations for that date in {kb} (try --sync)."
        logit(f"[{name}] No conversation matched the meeting window on {day}.{hint} Nothing written.", "WARN")
        print(f"[{name}] No conversation matched the meeting window on {day}.{hint} Use --list to review.")
        return

    notes = build_notes(day, chosen, mcfg)
    logit(f"[{name}] Using conversation(s): {', '.join(c['id'] for c in chosen)}")
    markdown = render_markdown(notes)
    if args.dry_run:
        print(markdown)
        return

    path = save_notes(mcfg, day, markdown, args.force)
    if path is None:
        existing = Path(str(mcfg["output_dir"])).expanduser() / f"{day.strftime('%Y%m%d')}.md"
        logit(f"[{name}] {existing} already exists; not overwritten (use --force)", "WARN")
        print(f"[{name}] WARNING: {existing} already exists; not overwritten (use --force)")
    else:
        logit(f"[{name}] Saved notes to {path}")
        print(f"[{name}] Saved notes to {path}")

    if (args.email or bool(mcfg.get("send_email", False))) and not args.no_email:
        mail = dict(ecfg)
        mail["to"] = args.to or mcfg.get("to") or ecfg.get("to")
        subject = str(mcfg.get("subject") or ecfg.get("subject") or "{name} Notes - {date}")
        send_email(mail, subject.format(name=name, date=day.isoformat()), render_text(notes), render_html(notes))
        logit(f"[{name}] Emailed notes to {mail['to']}")
        print(f"[{name}] Emailed notes for {day} to {mail['to']}")


def main() -> None:
    global LOGFILE, VERBOSE, DEBUG
    p = argparse.ArgumentParser(description="Save (and optionally email) notes from your weekly meetings using Bee conversations")
    p.add_argument("--meeting", action="append", help="Only run the named meeting(s) from the yml; repeatable (default: all)")
    p.add_argument("--date", help="Meeting date YYYY-MM-DD (default: most recent configured weekday)")
    p.add_argument("--conversation", action="append", help="Use this Bee conversation ID instead of the time-window match; repeatable (one meeting only)")
    p.add_argument("--list", action="store_true", help="List the day's conversations and exit (nothing is written or sent)")
    p.add_argument("--sync", action="store_true", help="Run `bee sync` for recent conversations first")
    p.add_argument("--dry-run", action="store_true", help="Print the notes instead of saving or emailing them")
    p.add_argument("--email", action="store_true", help="Email the notes even if the meeting's send_email is false")
    p.add_argument("--no-email", action="store_true", help="Save the notes but don't email them even if send_email is true")
    p.add_argument("--force", action="store_true", help="Overwrite an existing notes file for that date")
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

    bcfg, ecfg = cfg["bee"], dict(cfg["email"])
    exit_code = 0
    try:
        selected = cfg["meeting"]
        if args.meeting:
            unknown = set(args.meeting) - {m["name"] for m in selected}
            if unknown:
                raise ConfigError(f"Unknown meeting(s): {', '.join(sorted(unknown))}. "
                                  f"Configured: {', '.join(m['name'] for m in selected)}")
            selected = [m for m in selected if m["name"] in args.meeting]
        if args.conversation and len(selected) != 1:
            raise ConfigError("--conversation needs exactly one meeting; add --meeting NAME")
        fixed_day = None
        if args.date:
            try:
                fixed_day = date.fromisoformat(args.date)
            except ValueError:
                raise ConfigError(f"--date must be YYYY-MM-DD, got '{args.date}'")
        if VERBOSE or DEBUG:
            logit(f"Finalized parameters: config={cfg_path} meetings={[m['name'] for m in selected]} date={fixed_day} "
                  f"conversation={args.conversation} list={args.list} sync={args.sync} dry_run={args.dry_run} "
                  f"email={args.email} no_email={args.no_email} to={args.to} logfile={LOGFILE}")

        if args.sync:
            run_sync(bcfg)
        kb = Path(bcfg["knowledgebase_dir"]).expanduser()
        for m in selected:
            day = fixed_day or default_meeting_day(str(m["weekday"]))
            if not fixed_day:
                while not off_cycle_ok(m, day):
                    day -= timedelta(days=7)
            if fixed_day and not args.meeting and len(cfg["meeting"]) > 1 and day.weekday() != WEEKDAYS.index(str(m["weekday"]).lower()):
                logit(f"[{m['name']}] skipped: {day} is not a {m['weekday']} (use --meeting to force)")
                continue
            if not args.meeting and not off_cycle_ok(m, day):
                logit(f"[{m['name']}] skipped: {day} is not in its every-{m['every_weeks']}-week cycle (use --meeting to force)")
                continue
            try:
                run_meeting(m, day, args, kb, ecfg)
            except MeetingError as ex:
                logit(str(ex), "ERROR")
                print(f"ERROR: {ex}", file=sys.stderr)
                exit_code = 2
    except ConfigError as ex:
        logit(str(ex), "ERROR")
        print(f"ERROR: {ex}", file=sys.stderr)
        exit_script(1)
    except MeetingError as ex:
        logit(str(ex), "ERROR")
        print(f"ERROR: {ex}", file=sys.stderr)
        exit_script(2)
    exit_script(exit_code)


if __name__ == "__main__":
    main()
