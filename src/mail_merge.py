"""A local desktop mail merge for Outlook and Gmail web. Python 3.10+."""
from __future__ import annotations

import csv
import json
import os
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from zoneinfo import ZoneInfo

from merge_core import (Ledger, MergeError, campaign_key, column_key, csv_safe,
                        email_address, merge, profile_key, read_sheet, validate_url)
from owa_browser import Cancelled, browser_task
from mail_providers import GMAIL_URL, PROVIDER_NAMES, provider_for_url, validate_provider_url
from scheduling import DEFAULT_ZONE, parse_schedule, schedule_label
from browser_session import BrowserWorker
from app_icon import install_app_icon

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def state_directory():
    # Source checkouts retain their existing local state. Packaged builds keep
    # account data outside the downloadable application bundle.
    if not getattr(sys, "frozen", False):
        return ROOT.parent / ".mailmerge_state"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Web Mail Merge"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Web Mail Merge"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "web-mail-merge"


STATE = state_directory()


class MailMergeApp:
    def __init__(self, root):
        self.root = root
        root.title("Web Mail Merge • Outlook & Gmail")
        install_app_icon(root, ROOT / "assets" / "app-icon-512.png")
        root.geometry("1120x860")
        root.minsize(850, 700)
        self.events = queue.Queue()
        self.browser_worker = BrowserWorker(lambda exc: self.events.put(("error", str(exc))))
        self.stop = threading.Event()
        self.busy = False
        self.sheet = None
        self.messages = ()
        self.controls = []
        settings = self.load_settings()
        self._provider_key = settings.get("provider", provider_for_url(settings.get("url", "")))
        if self._provider_key not in PROVIDER_NAMES:
            self._provider_key = "outlook"
        self.provider = tk.StringVar(value=PROVIDER_NAMES[self._provider_key])
        self.browser = tk.StringVar(value=settings.get("browser", "Chromium"))
        self.accounts = settings.get("accounts", {})
        self.schedule_defaults = settings.get("schedule", {})
        self.url = tk.StringVar(value=settings.get("url", ""))
        self.mailbox = tk.StringVar(value=settings.get("mailbox", ""))
        self.file = tk.StringVar(value=settings.get("file", ""))
        self.sheet_name = tk.StringVar(value=settings.get("sheet", ""))
        self.email_col = tk.StringVar(value=settings.get("email_col", ""))
        self.cc_col = tk.StringVar(value=settings.get("cc_col", ""))
        self.global_cc = tk.StringVar(value=settings.get("global_cc", ""))
        self.subject = tk.StringVar(value=settings.get("subject", "Hello {{name}}"))
        self.delay = tk.StringVar(value=settings.get("delay", "5"))
        self.status = tk.StringVar(value="Choose a spreadsheet, write your template, then preview.")

        main = ttk.Frame(root, padding=14)
        main.pack(fill="both", expand=True)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(8, weight=1)
        header = ttk.Frame(main)
        header.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        ttk.Label(header, text="Personalized email • Outlook & Gmail", font=("Arial", 17, "bold")).pack(side="left")
        self.provider_combo = ttk.Combobox(header, textvariable=self.provider, values=tuple(PROVIDER_NAMES.values()), width=13, state="readonly")
        self.provider_combo.pack(side="right", padx=(8, 0))
        self.provider_combo.bind("<<ComboboxSelected>>", self.change_provider)
        ttk.Label(header, text="Mail service:").pack(side="right")
        self.controls.append(self.provider_combo)
        self.entry_row(main, 1, "Mail website (HTTPS)", self.url)
        self.entry_row(main, 2, "Sending mailbox", self.mailbox)
        ttk.Label(main, text="Spreadsheet").grid(row=3, column=0, sticky="w", padx=(0, 10))
        self.file_entry = ttk.Entry(main, textvariable=self.file)
        self.file_entry.grid(row=3, column=1, sticky="ew", pady=3)
        self.controls.append(self.file_entry)
        choose = ttk.Button(main, text="Choose file…", command=self.choose_file)
        choose.grid(row=3, column=2, padx=(8, 0))
        self.controls.append(choose)

        source = ttk.Frame(main)
        source.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(5, 10))
        ttk.Label(source, text="Worksheet (blank = first visible)").pack(side="left")
        worksheet = ttk.Entry(source, textvariable=self.sheet_name, width=18)
        worksheet.pack(side="left", padx=8)
        load = ttk.Button(source, text="Load columns", command=self.load_columns)
        load.pack(side="left", padx=(0, 15))
        ttk.Label(source, text="Email column").pack(side="left")
        self.email_combo = ttk.Combobox(source, textvariable=self.email_col, width=18, state="readonly")
        self.email_combo.pack(side="left", padx=8)
        ttk.Label(source, text="CC column (optional)").pack(side="left")
        self.cc_combo = ttk.Combobox(source, textvariable=self.cc_col, width=16, state="readonly")
        self.cc_combo.pack(side="left", padx=8)
        self.controls.extend([worksheet, load, self.email_combo, self.cc_combo])
        self.entry_row(main, 5, "CC on every email", self.global_cc)
        self.entry_row(main, 6, "Subject template", self.subject)
        self.placeholders = ttk.Label(main, text="Use {{column_name}} in the subject or body. Separate CC addresses with commas or semicolons.", wraplength=1000)
        self.placeholders.grid(row=7, column=0, columnspan=3, sticky="w", pady=(8, 6))

        panes = ttk.Panedwindow(main, orient="horizontal")
        panes.grid(row=8, column=0, columnspan=3, sticky="nsew")
        editor = ttk.Frame(panes)
        preview = ttk.Frame(panes)
        panes.add(editor, weight=1)
        panes.add(preview, weight=1)
        ttk.Label(editor, text="Message template (plain text; include your signature)").pack(anchor="w")
        self.body = scrolledtext.ScrolledText(editor, wrap="word", height=12, font=("Arial", 12), undo=True)
        self.body.pack(fill="both", expand=True, padx=(0, 10), pady=5)
        self.body.insert("1.0", settings.get("body", "Hi {{name}},\n\nI wanted to get in touch with you.\n\nBest,\n[Your name]"))
        self.controls.append(self.body)
        ttk.Label(preview, text="Preview — select a row to see its full message").pack(anchor="w")
        self.table = ttk.Treeview(preview, columns=("row", "to", "cc"), show="headings", height=5)
        for name, width, label in (("row", 45, "Row"), ("to", 205, "To"), ("cc", 200, "CC")):
            self.table.heading(name, text=label)
            self.table.column(name, width=width, minwidth=35)
        scroll = ttk.Scrollbar(preview, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.table.pack(fill="x", pady=5)
        self.table.bind("<<TreeviewSelect>>", self.show_selected)
        self.detail = scrolledtext.ScrolledText(preview, wrap="word", height=10, font=("Arial", 11), state="disabled")
        self.detail.pack(fill="both", expand=True)

        actions = ttk.Frame(main)
        actions.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(12, 8))
        for text, command in (("1. Preview", self.preview), ("2. Website setup", lambda: self.start("setup")), ("Open first draft", lambda: self.start("draft")), ("3. Send batch", lambda: self.start("send")), ("Send history", self.history), ("Export preview…", self.export_preview)):
            button = ttk.Button(actions, text=text, command=command)
            button.pack(side="left", padx=(0, 7))
            self.controls.append(button)
        self.stop_button = ttk.Button(actions, text="Stop", command=self.request_stop, state="disabled")
        self.stop_button.pack(side="right")
        options = ttk.Frame(main)
        options.grid(row=10, column=0, columnspan=3, sticky="ew")
        ttk.Label(options, text="Seconds between emails:").pack(side="left")
        delay_entry = ttk.Entry(options, textvariable=self.delay, width=6)
        delay_entry.pack(side="left", padx=8)
        self.controls.append(delay_entry)
        browser_combo = ttk.Combobox(options, textvariable=self.browser, values=("Chromium", "Google Chrome"), width=14, state="readonly")
        browser_combo.pack(side="left", padx=6)
        self.controls.append(browser_combo)
        schedule_button = ttk.Button(options, text="Schedule batch…", command=self.schedule_batch)
        schedule_button.pack(side="right")
        self.controls.append(schedule_button)
        ttk.Label(options, text="Review the first draft before sending.").pack(side="left", padx=6)
        ttk.Label(main, textvariable=self.status, wraplength=1050).grid(row=11, column=0, columnspan=3, sticky="w", pady=8)
        self.log_box = scrolledtext.ScrolledText(main, height=5, wrap="word", state="disabled", font=("Arial", 10))
        self.log_box.grid(row=12, column=0, columnspan=3, sticky="ew")
        root.after(100, self.poll)
        root.protocol("WM_DELETE_WINDOW", self.close)
        if self.file.get() and Path(self.file.get()).is_file():
            self.load_columns()
        self.show_saved_schedule()

    def entry_row(self, parent, row, label, variable):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10))
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        self.controls.append(entry)

    def load_settings(self):
        try:
            return json.loads((STATE / "settings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_settings(self):
        STATE.mkdir(parents=True, exist_ok=True)
        STATE.chmod(0o700)
        settings = {name: getattr(self, name).get() for name in ("url", "mailbox", "file", "email_col", "cc_col", "global_cc", "subject", "delay")}
        settings["sheet"] = self.sheet_name.get()
        settings["body"] = self.body.get("1.0", "end-1c")
        self.accounts[self._provider_key] = {"url": self.url.get(), "mailbox": self.mailbox.get()}
        settings.update(provider=self._provider_key, browser=self.browser.get(),
                        accounts=self.accounts, schedule=self.schedule_defaults)
        path = STATE / "settings.json"
        path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        path.chmod(0o600)

    def change_provider(self, _event=None):
        self.accounts[self._provider_key] = {"url": self.url.get(), "mailbox": self.mailbox.get()}
        self._provider_key = next(key for key, name in PROVIDER_NAMES.items() if name == self.provider.get())
        account = self.accounts.get(self._provider_key, {})
        self.url.set(account.get("url", GMAIL_URL if self._provider_key == "gmail" else ""))
        self.mailbox.set(account.get("mailbox", ""))
        self.save_settings()
        self.status.set(f"Selected {self.provider.get()}. Enter the sending mailbox and run Website setup for this account.")
        self.show_saved_schedule()

    def show_saved_schedule(self):
        try:
            _, _, directory = self.config()
            saved = json.loads((directory / "schedule.json").read_text(encoding="utf-8"))
            if saved.get("status") in ("waiting", "sending"):
                self.status.set(f"An unfinished schedule was saved for {saved['scheduled_at']}. This window will not resume it automatically. Use Schedule batch to review and reschedule pending emails.")
        except (OSError, ValueError):
            pass

    def schedule_batch(self):
        if self.busy:
            return
        window = tk.Toplevel(self.root)
        window.title("Schedule batch")
        window.resizable(False, False)
        panel = ttk.Frame(window, padding=18)
        panel.pack(fill="both", expand=True)
        tomorrow = (datetime.now(ZoneInfo(DEFAULT_ZONE)) + timedelta(days=1)).date().isoformat()
        date = tk.StringVar(value=self.schedule_defaults.get("date", tomorrow))
        clock = tk.StringVar(value=self.schedule_defaults.get("time", "09:00"))
        zone = tk.StringVar(value=self.schedule_defaults.get("timezone", DEFAULT_ZONE))
        ttk.Label(panel, text="Start this batch at a chosen date and time", font=("Arial", 14, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        for row, label, variable in ((1, "Date (YYYY-MM-DD)", date), (2, "Time (24-hour HH:MM)", clock)):
            ttk.Label(panel, text=label).grid(row=row, column=0, sticky="w", padx=(0, 14), pady=5)
            ttk.Entry(panel, textvariable=variable, width=24).grid(row=row, column=1, sticky="ew", pady=5)
        ttk.Label(panel, text="Timezone").grid(row=3, column=0, sticky="w", pady=5)
        ttk.Combobox(panel, textvariable=zone, values=("UTC", "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"), width=22).grid(row=3, column=1, sticky="ew", pady=5)
        ttk.Label(panel, text="You will sign in and review the first draft now.\nThe app starts the batch at the selected time, with your delay between messages.\nKeep the app, browser and computer open and awake. Stop cancels the timer.\nA restart requires you to review and schedule again.", wraplength=480).grid(row=4, column=0, columnspan=2, sticky="w", pady=12)
        def confirm():
            try:
                when = parse_schedule(date.get(), clock.get(), zone.get())
            except MergeError as exc:
                messagebox.showerror("Schedule needs attention", str(exc), parent=window)
                return
            self.schedule_defaults = {"date": date.get().strip(), "time": clock.get().strip(), "timezone": zone.get().strip()}
            window.destroy()
            self.start("schedule", when)
        ttk.Button(panel, text="Prepare scheduled batch", command=confirm).grid(row=5, column=1, sticky="e")
        ttk.Button(panel, text="Cancel", command=window.destroy).grid(row=5, column=0, sticky="w")
        window.transient(self.root)
        window.grab_set()

    def choose_file(self):
        path = filedialog.askopenfilename(title="Choose recipient spreadsheet", filetypes=[("Spreadsheets", "*.xlsx *.csv *.tsv"), ("All files", "*")])
        if path:
            self.file.set(path)
            self.sheet_name.set("")
            self.load_columns()

    def load_columns(self):
        try:
            self.sheet = read_sheet(self.file.get(), self.sheet_name.get().strip())
            self.email_combo["values"] = self.sheet.headers
            self.cc_combo["values"] = ("", *self.sheet.headers)
            if self.email_col.get() not in self.sheet.headers:
                self.email_col.set(next((h for h in self.sheet.headers if column_key(h) in ("email", "email_address", "e_mail", "e_mail_address")), self.sheet.headers[0]))
            if self.cc_col.get() not in self.sheet.headers:
                self.cc_col.set(next((h for h in self.sheet.headers if column_key(h) in ("cc", "cc_email", "cc_emails")), ""))
            self.placeholders.configure(text="Available placeholders: " + "  ".join("{{" + column_key(h) + "}}" for h in self.sheet.headers))
            self.messages = ()
            self.table.delete(*self.table.get_children())
            self.status.set(f"Loaded {len(self.sheet.rows)} recipient rows. Preview to validate all addresses and placeholders.")
        except Exception as exc:
            self.sheet = None
            messagebox.showerror("Cannot load spreadsheet", str(exc))

    def build(self):
        # Re-read the actual file on every action, so stale previews cannot be sent.
        self.sheet = read_sheet(self.file.get(), self.sheet_name.get().strip())
        self.messages = merge(self.sheet, self.email_col.get(), self.cc_col.get(), self.global_cc.get(), self.subject.get(), self.body.get("1.0", "end-1c"))
        self.table.delete(*self.table.get_children())
        for index, message in enumerate(self.messages):
            self.table.insert("", "end", iid=str(index), values=(message.row, message.to, "; ".join(message.cc)))
        self.table.selection_set("0")
        self.show_selected()
        self.save_settings()
        self.status.set(f"Preview ready: {len(self.messages)} personalized emails. All addresses and placeholders passed validation.")
        return self.messages

    def preview(self):
        try:
            self.build()
        except Exception as exc:
            self.messages = ()
            messagebox.showerror("Preview needs attention", str(exc))

    def show_selected(self, _event=None):
        selected = self.table.selection()
        if not selected or not self.messages:
            return
        message = self.messages[int(selected[0])]
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", f"To: {message.to}\nCC: {'; '.join(message.cc) or '(none)'}\nSubject: {message.subject}\n\n{message.body}")
        self.detail.configure(state="disabled")

    def config(self):
        url = validate_provider_url(self._provider_key, self.url.get())
        mailbox = email_address(self.mailbox.get())
        directory = STATE / profile_key(url, mailbox)
        return url, mailbox, directory

    def start(self, mode, scheduled_at=None):
        if self.busy:
            return
        try:
            url, mailbox, directory = self.config()
            if mode == "schedule" and scheduled_at is None:
                raise MergeError("Choose a scheduled date and time first.")
            delay = float(self.delay.get())
            if not 1 <= delay <= 3600:
                raise MergeError("Choose a delay between 1 and 3,600 seconds.")
            messages = () if mode == "setup" else self.build()
            if mode == "setup":
                self.save_settings()
            campaign = campaign_key(url, mailbox, messages)
            if mode in ("send", "schedule"):
                ledger = Ledger(directory / "send-history.sqlite3")
                try:
                    if any(ledger.status(campaign, m.to) in ("attempting", "uncertain") for m in messages):
                        raise MergeError("A previous send is uncertain. Open Send history and resolve it after checking Sent Items.")
                    if all(ledger.status(campaign, m.to) == "submitted" for m in messages):
                        messagebox.showinfo("Batch already submitted", "All emails in this unchanged batch were already submitted. Nothing will be resent.")
                        return
                    prior = {row[0] for row in ledger.connection.execute("SELECT DISTINCT recipient FROM messages WHERE campaign != ? AND status IN ('submitted','attempting','uncertain')", (campaign,))}
                    overlap = sum(m.to.casefold() in prior for m in messages)
                    if overlap and not messagebox.askyesno("Previously contacted recipients", f"{overlap} recipients have send history in another batch. Editing the recipient list, template, CC, website or mailbox creates a new batch.\n\nContinue preparing this new batch for review?"):
                        return
                finally:
                    ledger.close()
            self.stop.clear()
            self.set_busy(True)
            provider = self._provider_key
            browser_channel = "chrome" if self.browser.get() == "Google Chrome" else None
            def work(sessions):
                try:
                    browser_task(mode, url, mailbox, directory, messages, campaign, self.stop, self.worker_ask, lambda text: self.events.put(("log", text)), delay,
                                 provider=provider, scheduled_at=scheduled_at, browser_channel=browser_channel,
                                 sessions=sessions)
                except Cancelled as exc:
                    self.events.put(("log", str(exc) or "Cancelled."))
                except Exception as exc:
                    self.events.put(("error", str(exc)))
                finally:
                    self.events.put(("done", None))
            self.browser_worker.submit(work)
        except Exception as exc:
            messagebox.showerror("Needs attention", str(exc))

    def worker_ask(self, title, text, kind):
        response = queue.Queue()
        self.events.put(("ask", (title, text, kind, response)))
        while not self.stop.is_set():
            try:
                return response.get(timeout=0.2)
            except queue.Empty:
                pass
        raise Cancelled("Stopped by user.")

    def set_busy(self, value):
        self.busy = value
        for control in self.controls:
            if isinstance(control, ttk.Combobox):
                control.configure(state="disabled" if value else "readonly")
            else:
                control.configure(state="disabled" if value else "normal")
        self.stop_button.configure(state="normal" if value else "disabled")

    def request_stop(self):
        self.stop.set()
        self.status.set("Cancelling the timer or stopping after the current send result is recorded…")

    def poll(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "log":
                    self.status.set(data)
                    self.log_box.configure(state="normal")
                    self.log_box.insert("end", data + "\n")
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")
                elif kind == "ask":
                    title, text, style, response = data
                    if self.stop.is_set():
                        response.put(False)
                    else:
                        if style == "choice":
                            answer = self.choose_mailbox_tab(title, text)
                        else:
                            answer = messagebox.askyesno(title, text) if style == "yesno" else messagebox.askokcancel(title, text)
                        response.put(answer)
                elif kind == "error":
                    self.status.set("Paused: " + data)
                    messagebox.showerror("Task paused", data)
                elif kind == "done":
                    self.set_busy(False)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def choose_mailbox_tab(self, title, content):
        window = tk.Toplevel(self.root)
        window.title(title)
        window.geometry("720x280")
        panel = ttk.Frame(window, padding=16)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text=content["prompt"], wraplength=680).pack(anchor="w", pady=(0, 10))
        choices = tk.Listbox(panel, height=6, exportselection=False)
        for label in content["options"]:
            choices.insert("end", label)
        choices.pack(fill="both", expand=True)
        result = [None]
        def choose():
            selected = choices.curselection()
            if selected:
                result[0] = selected[0]
                window.destroy()
        ttk.Button(panel, text="Use selected tab", command=choose).pack(side="right", pady=(10, 0))
        ttk.Button(panel, text="Cancel", command=window.destroy).pack(side="left", pady=(10, 0))
        window.transient(self.root)
        window.grab_set()
        self.root.wait_window(window)
        return result[0]

    def history(self):
        try:
            messages = self.build()
            url, mailbox, directory = self.config()
            campaign = campaign_key(url, mailbox, messages)
            ledger = Ledger(directory / "send-history.sqlite3")
        except Exception as exc:
            messagebox.showerror("Cannot open history", str(exc))
            return
        window = tk.Toplevel(self.root)
        window.title("Send history — current batch")
        window.geometry("850x460")
        ttk.Label(window, text="For uncertain sends, check Gmail Sent or Outlook Sent Items before choosing an action below.", padding=12).pack(anchor="w")
        ttk.Label(window, text="Submitted = the composer closed after Send; this is not a delivery receipt.", padding=(12, 0, 12, 8)).pack(anchor="w")
        table = ttk.Treeview(window, columns=("row", "to", "status", "detail"), show="headings")
        for name, width in (("row", 50), ("to", 220), ("status", 110), ("detail", 420)):
            table.heading(name, text=name.title())
            table.column(name, width=width)
        table.pack(fill="both", expand=True, padx=12, pady=8)
        def refresh():
            table.delete(*table.get_children())
            details = {r[0]: r[4] for r in ledger.list(campaign)}
            for message in messages:
                table.insert("", "end", iid=message.to.casefold(), values=(message.row, message.to, ledger.status(campaign, message.to), details.get(message.to.casefold(), "")))
        def resolve(submitted):
            selection = table.selection()
            if not selection:
                messagebox.showinfo("Select a row", "Select an uncertain message first.", parent=window)
                return
            recipient = selection[0]
            if ledger.status(campaign, recipient) not in ("attempting", "uncertain"):
                messagebox.showinfo("No resolution needed", "Only attempting or uncertain messages need manual resolution.", parent=window)
                return
            text = f"Confirm that you checked Sent Items for {recipient}.\n\n" + ("Mark this message as submitted and skip it on reruns?" if submitted else "Confirm the message was NOT sent and permit one retry?")
            if messagebox.askyesno("Resolve send result", text, parent=window):
                ledger.resolve(campaign, recipient, submitted)
                refresh()
        buttons = ttk.Frame(window, padding=12)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Checked Sent Items: sent", command=lambda: resolve(True)).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Checked Sent Items: not sent — allow retry", command=lambda: resolve(False)).pack(side="left")
        def close_history():
            ledger.close()
            window.destroy()
        window.protocol("WM_DELETE_WINDOW", close_history)
        # Prevent history edits while a browser job is running.
        window.transient(self.root)
        window.grab_set()
        refresh()

    def export_preview(self):
        try:
            messages = self.build()
            path = filedialog.asksaveasfilename(title="Save personalized email preview", defaultextension=".csv", initialfile="email-preview.csv", filetypes=[("CSV", "*.csv")])
            if path:
                with open(path, "w", encoding="utf-8-sig", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(["Row", "To", "CC", "Subject", "Body"])
                    for message in messages:
                        writer.writerow([csv_safe(v) for v in (message.row, message.to, "; ".join(message.cc), message.subject, message.body)])
                self.status.set("Preview saved. No emails were sent.")
        except Exception as exc:
            messagebox.showerror("Cannot export preview", str(exc))

    def close(self):
        if self.busy:
            if messagebox.askyesno("Stop task", "A browser task is running. Stop it? This window will stay open until the current send result is recorded."):
                self.request_stop()
            return
        self.save_settings()
        self.browser_worker.close()
        self.root.destroy()


def main():
    root = tk.Tk()
    MailMergeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
