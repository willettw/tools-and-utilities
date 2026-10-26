#!/usr/bin/env python3
"""
bee_todo_manager.py - GUI to view Bee AI suggested todos and their status

PURPOSE:
    Uses the same `bee` CLI as the morning report tooling (`bee todos suggestions`)
    to list Bee's suggested todos in a sortable table (ID, text, status, alarm,
    created); selecting a row shows its details. Double-click the Due, Priority or
    Project cell to set them (due via calendar popup; priority P1-P4 as in Todoist,
    blank = P4; project from a dropdown of your Todoist projects, prefilled with
    default_project). "New project..." in that dropdown, or the New Project button,
    creates a Todoist project (optionally under a parent). Accept adds each checked
    suggestion to Todoist in its project with that due date and priority, then accepts
    it in Bee. Dismiss dismisses it in Bee.

USAGE:
    python3 bee_todo_manager.py [OPTIONS]

EXAMPLES:
    python3 bee_todo_manager.py
    python3 bee_todo_manager.py --verbose
    python3 bee_todo_manager.py --debug
    python3 bee_todo_manager.py --config custom_bee_todo_manager.yml
    python3 bee_todo_manager.py --logfolder ~/logs

EXIT CODES:
    0 = Success
    1 = Configuration error
    2 = Execution error

REQUIREMENTS:
    - PyYAML, tkinter (python3-tk), todoist-api-python
    - credvault (secret todoist/api_token)
    - bee CLI (logged in; see `bee status`)

VERSION: 1.1.0
REVISION HISTORY:
    1.0.0 - Initial implementation (2026-10-12)
    1.1.0 - Project column (dropdown of Todoist projects, default_project prefill),
            create projects from the app; --logfolder, logs named <script>_YYMMDD.log
            (2026-10-26)
"""
import argparse
import calendar
import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from datetime import date, datetime
from tkinter import font as tkfont, messagebox, ttk

import yaml

SCRIPT = os.path.basename(sys.argv[0])
SCRIPT_NAME = os.path.splitext(SCRIPT)[0]

DEFAULT_LOG_FOLDER = "/usr/local/logs"
FALLBACK_LOG_FOLDER = "~/logs"
_log_cfg = {"logfolder": None, "verbose": False, "debug": False}


def log_path(folder):
    """Today's logfile in folder; falls back to ~/logs if the folder can't be created."""
    folder = os.path.expanduser(folder or DEFAULT_LOG_FOLDER)
    try:
        os.makedirs(folder, exist_ok=True)
        if not os.access(folder, os.W_OK):
            raise PermissionError(f"{folder} is not writable")
    except OSError as exc:
        fallback = os.path.expanduser(FALLBACK_LOG_FOLDER)
        print(f"WARNING: cannot use log folder {folder} ({exc}); logging to {fallback}", file=sys.stderr)
        os.makedirs(fallback, exist_ok=True)
        folder = fallback
    _log_cfg["logfolder"] = folder
    return os.path.join(folder, f"{SCRIPT_NAME}_{datetime.now().strftime('%y%m%d')}.log")


def logit(msg, status="INFO", logFolder=None, debug=None, verbose=None, clearlog=False):
    """Write a timestamped line to <logfolder>/<script>_YYMMDD.log; echo to stdout if verbose/debug."""
    debug = _log_cfg["debug"] if debug is None else debug
    verbose = _log_cfg["verbose"] if verbose is None else verbose
    if debug:
        status = "DEBUG"
    elif verbose:
        status = "INFO"
    line = f"{datetime.now().strftime('%Y%m%d:%H%M%S')} {status} {msg}\n"
    with open(log_path(logFolder or _log_cfg["logfolder"]), "w" if clearlog else "a") as fh:
        fh.write(line)
    if debug or verbose:
        print(line, end="")


def find_config(cli_path):
    candidates = [cli_path] if cli_path else [f"./{SCRIPT_NAME}.yml", f"/usr/local/etc/{SCRIPT_NAME}.yml"]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    print(f"ERROR: config not found. Searched: {', '.join(c for c in candidates if c)}", file=sys.stderr)
    sys.exit(1)


def fmt_date(value):
    if not value:
        return ""
    return datetime.fromtimestamp(int(value) / 1000).strftime("%Y-%m-%d")


def fetch_suggestions(bee_binary, limit):
    cmd = [bee_binary, "todos", "suggestions", "--limit", str(limit), "--json"]
    logit(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"bee exited {result.returncode}: {result.stderr.strip() or result.stdout.strip()}")
    return json.loads(result.stdout).get("todoSuggestions", [])


def run_suggestion_action(bee_binary, action, todo_id):
    """Run accept-suggestion or dismiss-suggestion; return an error string or None."""
    cmd = [bee_binary, "todos", f"{action}-suggestion", str(todo_id), "--json"]
    logit(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    if result.returncode != 0:
        return result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
    return None


PRIORITIES = {"": 1, "P1": 4, "P2": 3, "P3": 2, "P4": 1}  # label -> Todoist API value


def parse_due(text):
    """Return a date for YYYY-MM-DD or YYYYMMDD, None if blank; ValueError if invalid."""
    text = text.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"invalid due date '{text}' (use YYYY-MM-DD)")


_api = None


def todoist_api(cfg):
    """One TodoistAPI client per run, token from credvault."""
    global _api
    if _api is None:
        sys.path.insert(0, "/usr/local/bin")
        from credvault import get_secret
        from todoist_api_python.api import TodoistAPI
        _api = TodoistAPI(get_secret(cfg.get("todoist_secret", "todoist/api_token")))
    return _api


def fetch_projects(cfg):
    """Active Todoist projects as [(id, label, depth)]: Inbox first, then each project
    followed by its sub-projects in Todoist's order. label is 'Parent / Child'."""
    projects = [p for page in todoist_api(cfg).get_projects() for p in page if not p.is_archived]
    children = {}
    for p in projects:
        children.setdefault(p.parent_id, []).append(p)
    out = []

    def walk(parent_id, prefix, depth):
        for p in sorted(children.get(parent_id, []), key=lambda x: (not x.is_inbox_project, x.order)):
            label = f"{prefix}{p.name}"
            out.append((p.id, label, depth))
            walk(p.id, f"{label} / ", depth + 1)
    walk(None, "", 0)
    return out


def create_project(cfg, name, parent_id=None):
    return todoist_api(cfg).add_project(name=name[:120], parent_id=parent_id)


def add_to_todoist(cfg, content, description, due, priority, project_id=None):
    """Create a Todoist task in project_id (None = Inbox)."""
    return todoist_api(cfg).add_task(content=content[:500], description=(description or "")[:16000] or None,
                                     due_date=due, priority=PRIORITIES[priority], project_id=project_id)


STATE_FILE = os.path.expanduser(f"~/.config/{SCRIPT_NAME}/state.json")


def load_state():
    try:
        with open(STATE_FILE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


class DatePicker(tk.Toplevel):
    """Modal month calendar; calls on_pick('YYYY-MM-DD' or '') when a day/Clear is chosen."""

    def __init__(self, parent, start, on_pick):
        super().__init__(parent)
        self.title("Choose due date")
        self.resizable(False, False)
        self.on_pick = on_pick
        today = date.today()
        self.year, self.month = (start or today).year, (start or today).month
        self.selected = start
        head = ttk.Frame(self, padding=4)
        head.pack(fill="x")
        ttk.Button(head, text="<", width=3, command=lambda: self.shift(-1)).pack(side="left")
        self.title_var = tk.StringVar()
        ttk.Label(head, textvariable=self.title_var, anchor="center").pack(side="left", expand=True, fill="x")
        ttk.Button(head, text=">", width=3, command=lambda: self.shift(1)).pack(side="right")
        self.grid_frame = ttk.Frame(self, padding=4)
        self.grid_frame.pack()
        foot = ttk.Frame(self, padding=4)
        foot.pack(fill="x")
        ttk.Button(foot, text="Today", command=lambda: self.pick(today)).pack(side="left")
        ttk.Button(foot, text="Clear", command=lambda: self.pick(None)).pack(side="left", padx=4)
        ttk.Button(foot, text="Cancel", command=self.destroy).pack(side="right")
        self.draw()
        self.transient(parent)
        self.wait_visibility()
        self.grab_set()

    def shift(self, delta):
        m = self.month - 1 + delta
        self.year, self.month = self.year + m // 12, m % 12 + 1
        self.draw()

    def draw(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.title_var.set(f"{calendar.month_name[self.month]} {self.year}")
        for c, name in enumerate(calendar.day_abbr):
            ttk.Label(self.grid_frame, text=name[:2], anchor="center").grid(row=0, column=c)
        for r, week in enumerate(calendar.Calendar(firstweekday=0).monthdayscalendar(self.year, self.month), 1):
            for c, day in enumerate(week):
                if day:
                    d = date(self.year, self.month, day)
                    tk.Button(self.grid_frame, text=str(day), width=3, relief="flat",
                              font=("TkDefaultFont", 9, "bold") if d == date.today() else "TkDefaultFont",
                              bg="#bcd" if d == self.selected else self.cget("bg"),
                              command=lambda d=d: self.pick(d)).grid(row=r, column=c)

    def pick(self, d):
        self.on_pick(d.strftime("%Y-%m-%d") if d else "")
        self.destroy()


class NewProjectDialog(tk.Toplevel):
    """Modal dialog: project name and optional parent; calls on_ok(name, parent_id)."""

    def __init__(self, parent, projects, on_ok):
        super().__init__(parent)
        self.title("New Todoist project")
        self.resizable(False, False)
        self.on_ok = on_ok
        self.parents = {"(none - top level)": None}
        self.parents.update({label: pid for pid, label, _ in projects})
        body = ttk.Frame(self, padding=10)
        body.pack(fill="both")
        ttk.Label(body, text="Name:").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar()
        entry = ttk.Entry(body, textvariable=self.name_var, width=40)
        entry.grid(row=0, column=1, sticky="we", pady=2)
        ttk.Label(body, text="Parent:").grid(row=1, column=0, sticky="w")
        self.parent_var = tk.StringVar(value="(none - top level)")
        ttk.Combobox(body, textvariable=self.parent_var, values=list(self.parents), state="readonly",
                     width=38).grid(row=1, column=1, sticky="we", pady=2)
        foot = ttk.Frame(body)
        foot.grid(row=2, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(foot, text="Create", command=self.ok).pack(side="left")
        ttk.Button(foot, text="Cancel", command=self.destroy).pack(side="left", padx=(4, 0))
        self.bind("<Return>", lambda _e: self.ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.transient(parent)
        self.wait_visibility()
        self.grab_set()
        entry.focus_set()

    def ok(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("New project", "Enter a project name.", parent=self)
            return
        self.on_ok(name, self.parents.get(self.parent_var.get()))
        self.destroy()


class TodoApp(tk.Tk):
    COLUMNS = (("check", "\u2611", 40), ("text", "Suggested Todo", 520), ("status", "Status", 80),
               ("due", "Due", 110), ("priority", "Priority", 70), ("project", "Project", 160),
               ("alarm", "Alarm", 80), ("created", "Created", 80))
    COLUMN_CHARS = {"project": 22}   # fixed-column widths in characters (default 12)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        state = load_state()
        self.edits = {}  # todo id -> {"due": str, "priority": str, "project": (id, label)}
        self.projects = []  # [(id, label, depth)] from Todoist
        self.default_project = cfg.get("default_project", "Inbox")
        self.checked = set()  # ids ticked in the checkbox column
        self.title("Bee Suggested Todos")
        self.geometry(state.get("geometry") or cfg.get("window_size", "1000x700"))
        self.bee_binary = cfg.get("bee_binary", "bee")
        self.limit = int(cfg.get("limit", 200))
        self.todos = []
        self.sort_col, self.sort_rev = "created", True

        bar = ttk.Frame(self, padding=6)
        bar.pack(fill="x")
        ttk.Button(bar, text="Refresh", command=self.refresh).pack(side="left")
        self.action_btns = [
            ttk.Button(bar, text="Accept", command=lambda: self.act("accept")),
            ttk.Button(bar, text="Dismiss", command=lambda: self.act("dismiss")),
        ]
        self.action_btns[0].pack(side="left", padx=(12, 0))
        self.action_btns[1].pack(side="left", padx=4)
        ttk.Button(bar, text="New Project...", command=self.new_project).pack(side="left", padx=(12, 0))

        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        size = int(cfg.get("font_size", 12))
        style = ttk.Style(self)
        style.configure("Treeview", font=("TkDefaultFont", size), rowheight=int(size * 2.1))
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in self.COLUMNS], show="headings")
        for key, label, width in self.COLUMNS:
            fixed = key not in ("check", "text")
            self.tree.heading(key, text=label, anchor="w" if key == "text" else "center",
                              command=self.toggle_all if key == "check"
                              else lambda k=key: self.sort_by(k))
            if fixed:
                width = self.COLUMN_CHARS.get(key, 12) * tkfont.Font(font=("TkDefaultFont", size)).measure("0")
            self.tree.column(key, width=width, minwidth=width if key != "text" else 200,
                             stretch=(key == "text"), anchor="w" if key == "text" else "center")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Configure>", self.fit_text_column)
        self.tree.bind("<<TreeviewSelect>>", self.show_details)
        self.tree.bind("<Double-1>", self.edit_cell)
        self.tree.bind("<Button-1>", self.click_check)

        self.details = tk.Text(self, height=8, wrap="word", state="disabled")
        self.details.pack(fill="x")
        self.status_var = tk.StringVar()
        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x")
        ttk.Label(self, textvariable=self.status_var, anchor="w", padding=4).pack(fill="x")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.refresh()
        self.load_projects()

    def on_close(self):
        state = {"geometry": self.geometry()}
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE, "w") as fh:
                json.dump(state, fh)
        except OSError as exc:
            logit(f"Could not save window state: {exc}", "WARN")
        self.destroy()

    def refresh(self):
        self.status_var.set("Loading suggestions...")
        threading.Thread(target=self._load, daemon=True).start()

    def load_projects(self, then=None):
        """Fetch Todoist projects in the background; then(projects) runs afterwards."""
        def work():
            try:
                projects = fetch_projects(self.cfg)
                logit(f"Fetched {len(projects)} Todoist projects")
                self.after(0, self._projects_loaded, projects, then)
            except Exception as exc:
                logit(f"Todoist project fetch failed: {exc}", "ERROR")
                self.after(0, lambda: messagebox.showerror("Todoist", f"Could not load projects: {exc}"))
        threading.Thread(target=work, daemon=True).start()

    def _projects_loaded(self, projects, then):
        self.projects = projects
        if self.todos:
            self.populate()
        if then:
            then(projects)

    def project_default(self):
        """(id, label) for default_project; id None = Inbox."""
        for pid, label, _ in self.projects:
            if label.lower() == str(self.default_project).lower():
                return (pid, label)
        return (None, "Inbox")

    def row_project(self, todo_id):
        return self.edits.get(todo_id, {}).get("project") or self.project_default()

    def new_project(self, row=None):
        """Ask for a name/parent, create it in Todoist, reload the list; set it on row if given."""
        def created(name, parent_id):
            self.status_var.set(f"Creating project {name}...")

            def work():
                try:
                    p = create_project(self.cfg, name, parent_id)
                    logit(f"Created Todoist project {p.name} ({p.id})")
                    self.after(0, lambda: self.load_projects(then=lambda projects: self._project_created(p.id, row)))
                except Exception as exc:
                    logit(f"Create project {name} failed: {exc}", "ERROR")
                    self.after(0, lambda: messagebox.showerror("Todoist", f"Could not create project: {exc}"))
            threading.Thread(target=work, daemon=True).start()
        NewProjectDialog(self, self.projects, created)

    def _project_created(self, project_id, row):
        label = next((lbl for pid, lbl, _ in self.projects if pid == project_id), None)
        self.status_var.set(f"Created project {label}")
        if row and label:
            self._set_project(row, (project_id, label))

    def _set_project(self, row, project):
        self.edits.setdefault(int(row), {})["project"] = project
        self.tree.set(row, "project", project[1])

    def _load(self):
        try:
            todos = fetch_suggestions(self.bee_binary, self.limit)
            self.after(0, self._loaded, todos)
        except Exception as exc:
            logit(f"Fetch failed: {exc}", "ERROR")
            self.after(0, self._failed, exc)

    def act(self, action):
        ids = sorted(self.checked & set(self.todos))
        if not ids:
            return
        if action == "accept":
            try:
                for i in ids:
                    parse_due(self.edits.get(i, {}).get("due", ""))
            except ValueError as exc:
                messagebox.showerror("Due date", str(exc))
                return
        label = "Add to Todoist and accept" if action == "accept" else "Dismiss"
        if not messagebox.askyesno(action.title(), f"{label} {len(ids)} suggestion(s)?"):
            return
        self.progress.configure(maximum=len(ids), value=0)
        for b in self.action_btns:
            b.state(["disabled"])
        self.status_var.set(f"{action.title()}: 0 of {len(ids)}")
        threading.Thread(target=self._act, args=(action, ids), daemon=True).start()

    def _act(self, action, ids):
        errors = []
        for n, todo_id in enumerate(ids, 1):
            try:
                err = None
                if action == "accept":
                    t, e = self.todos[todo_id], self.edits.get(todo_id, {})
                    try:
                        project_id, project_label = self.row_project(todo_id)
                        add_to_todoist(self.cfg, t.get("text") or "", t.get("details"),
                                       parse_due(e.get("due", "")), e.get("priority", ""), project_id)
                        logit(f"Todoist task added for {todo_id} in {project_label}")
                    except Exception as exc:
                        err = f"Todoist: {exc}"
                if not err:
                    err = run_suggestion_action(self.bee_binary, action, todo_id)
            except Exception as exc:
                err = str(exc)
            if err:
                logit(f"{action} {todo_id} failed: {err}", "ERROR")
                errors.append(f"{todo_id}: {err}")
            else:
                logit(f"{action} {todo_id} ok")
            self.after(0, self._progress, action, n, len(ids))
        self.after(0, self._acted, errors)

    def _progress(self, action, n, total):
        self.progress.configure(value=n)
        self.status_var.set(f"{action.title()}: {n} of {total}")

    def _acted(self, errors):
        for b in self.action_btns:
            b.state(["!disabled"])
        self.progress.configure(value=0)
        if errors:
            messagebox.showerror("Bee CLI error", "\n".join(errors[:5]))
        self.refresh()

    def _loaded(self, todos):
        self.todos = {t["id"]: t for t in todos}
        self.checked &= set(self.todos)
        logit(f"Fetched {len(todos)} suggestions")
        self.populate()

    def _failed(self, exc):
        self.status_var.set("Load failed")
        messagebox.showerror("Bee CLI error", str(exc))

    def populate(self):
        rows = [{"id": t["id"], "check": "\u2611" if t["id"] in self.checked else "\u2610",
                 "text": (t.get("text") or "").strip(),
                 "status": "Pending", "alarm": fmt_date(t.get("alarm_at")),
                 "due": self.edits.get(t["id"], {}).get("due", ""),
                 "priority": self.edits.get(t["id"], {}).get("priority", ""),
                 "project": self.row_project(t["id"])[1],
                 "created": fmt_date(t.get("created_at"))} for t in self.todos.values()]
        rows.sort(key=lambda r: (r[self.sort_col] is None, r[self.sort_col]), reverse=self.sort_rev)
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            self.tree.insert("", "end", iid=str(r["id"]), values=[r[c[0]] for c in self.COLUMNS])
        self.status_var.set(f"{len(rows)} suggested todos")

    def fit_text_column(self, event):
        # Treeview only grows stretch columns, never shrinks them, so size it explicitly.
        others = sum(self.tree.column(c[0], "width") for c in self.COLUMNS if c[0] != "text")
        self.tree.column("text", width=max(200, event.width - others - 2))

    def click_check(self, event):
        if (self.tree.identify_region(event.x, event.y) != "cell"
                or self.tree.identify_column(event.x) != "#1"):
            return
        row = self.tree.identify_row(event.y)
        todo_id = int(row)
        self.checked.symmetric_difference_update({todo_id})
        self.tree.set(row, "check", "\u2611" if todo_id in self.checked else "\u2610")
        return "break"

    def toggle_all(self):
        self.checked = set() if self.checked >= set(self.todos) else set(self.todos)
        self.populate()

    def _set_edit(self, row, key, value):
        self.edits.setdefault(int(row), {})[key] = value
        self.tree.set(row, key, value)

    def edit_cell(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        row = self.tree.identify_row(event.y)
        key = self.COLUMNS[int(self.tree.identify_column(event.x)[1:]) - 1][0]
        if key == "text":
            self.checked.symmetric_difference_update({int(row)})
            self.tree.set(row, "check", "\u2611" if int(row) in self.checked else "\u2610")
        elif key == "priority":
            menu = tk.Menu(self, tearoff=0)
            for label, text in (("P1", "P1 - Urgent"), ("P2", "P2 - High"), ("P3", "P3 - Medium"),
                                ("P4", "P4 - Normal"), ("", "(none)")):
                menu.add_command(label=text, command=lambda v=label: self._set_edit(row, "priority", v))
            menu.tk_popup(event.x_root, event.y_root)
        elif key == "project":
            menu = tk.Menu(self, tearoff=0)
            if not self.projects:
                menu.add_command(label="(loading Todoist projects...)", state="disabled")
            for pid, label, depth in self.projects:
                name = label.rsplit(" / ", 1)[-1]
                menu.add_command(label=("    " * depth) + name,
                                 command=lambda p=(pid, label): self._set_project(row, p))
            menu.add_separator()
            menu.add_command(label="New project...", command=lambda: self.new_project(row))
            menu.tk_popup(event.x_root, event.y_root)
        elif key == "due":
            try:
                start = parse_due(self.tree.set(row, "due"))
            except ValueError:
                start = None
            DatePicker(self, start, lambda v: self._set_edit(row, "due", v))

    def show_details(self, _event):
        sel = self.tree.selection()
        t = self.todos.get(int(sel[0])) if sel else None
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        if t:
            self.details.insert("1.0", t.get("details") or "")
        self.details.configure(state="disabled")

    def sort_by(self, col):
        self.sort_rev = not self.sort_rev if col == self.sort_col else False
        self.sort_col = col
        self.populate()


def main():
    parser = argparse.ArgumentParser(description="GUI to view Bee AI suggested todos")
    parser.add_argument("--config", help="Path to config yml")
    parser.add_argument("--logfolder", help=f"Folder for logs; file is {SCRIPT_NAME}_YYMMDD.log "
                                            f"(default: {DEFAULT_LOG_FOLDER})")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    args = parser.parse_args()

    cfg_path = find_config(args.config)
    with open(cfg_path) as fh:
        cfg = yaml.safe_load(fh) or {}
    log = cfg.get("logging", {})
    _log_cfg["logfolder"] = args.logfolder or log.get("logfolder") or DEFAULT_LOG_FOLDER
    _log_cfg["verbose"] = args.verbose or bool(log.get("verbose", False))
    _log_cfg["debug"] = args.debug or bool(log.get("debug", False))

    logit(f"Starting {SCRIPT}")
    logit(f"config={cfg_path} logfolder={_log_cfg['logfolder']} verbose={_log_cfg['verbose']} "
          f"debug={_log_cfg['debug']}", "DEBUG") if (_log_cfg["verbose"] or _log_cfg["debug"]) else None
    try:
        TodoApp(cfg).mainloop()
    except Exception as exc:
        logit(f"Fatal: {exc}", "ERROR")
        sys.exit(2)
    finally:
        logit(f"{SCRIPT} Completed\n\n")


if __name__ == "__main__":
    main()
