"""Reuse signed-in browser sessions on a single Playwright-owning thread."""
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

from merge_core import MergeError


def configure_browser_cache():
    # Playwright defaults frozen apps to a browser inside the package, but our
    # downloads intentionally exclude browser binaries. Choose its normal user
    # cache before starting the driver so launching and installing agree.
    if not getattr(sys, "frozen", False) or os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    if sys.platform == "darwin":
        cache = Path.home() / "Library" / "Caches"
    elif sys.platform == "win32":
        cache = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(cache / "ms-playwright")


class BrowserSessions:
    def __init__(self, headless=False):
        self.headless = headless
        self.playwright = None
        self.contexts = {}

    def get_context(self, state_dir, channel=None):
        key = str(Path(state_dir).resolve())
        existing = self.contexts.get(key)
        if existing:
            context, previous_channel = existing
            if context.browser and context.browser.is_connected():
                if channel != previous_channel:
                    raise MergeError("A browser for this mailbox is already open. Use its current browser setting, or close that browser window before changing the browser type.")
                return context, False
            self.contexts.pop(key, None)
        if self.playwright is None:
            configure_browser_cache()
            from playwright.sync_api import sync_playwright
            self.playwright = sync_playwright().start()
        try:
            context = self.playwright.chromium.launch_persistent_context(
                str(Path(state_dir) / "browser"), channel=channel, headless=self.headless,
                viewport={"width": 1280, "height": 850})
        except Exception as exc:
            if channel == "chrome":
                raise MergeError("Google Chrome could not open. Install Chrome or choose Chromium in the app.") from exc
            if "Executable doesn't exist" not in str(exc):
                raise
            # A packaged app installs its browser to Playwright's per-user cache
            # on first use. The binary and account profile never enter the app.
            from playwright._impl._driver import compute_driver_executable, get_driver_env
            node, cli = compute_driver_executable()
            try:
                subprocess.run([node, cli, "install", "chromium"], check=True,
                               env=get_driver_env(), capture_output=True, text=True, timeout=600)
                context = self.playwright.chromium.launch_persistent_context(
                    str(Path(state_dir) / "browser"), channel=None, headless=self.headless,
                    viewport={"width": 1280, "height": 850})
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as install_error:
                raise MergeError("Chromium download could not finish. Check your internet connection and try again.") from install_error
        self.contexts[key] = (context, channel)
        context.on("close", lambda: self.contexts.pop(key, None))
        return context, True

    def poll(self):
        # Dispatch browser-close events while the worker is waiting for a task.
        for context, _ in list(self.contexts.values()):
            pages = [page for page in context.pages if not page.is_closed()]
            if pages:
                try:
                    pages[0].wait_for_timeout(50)
                    return
                except Exception:
                    continue

    def close(self):
        for context, _ in list(self.contexts.values()):
            try:
                context.close()
            except Exception:
                pass
        self.contexts.clear()
        if self.playwright:
            self.playwright.stop()
            self.playwright = None


class BrowserWorker:
    def __init__(self, on_error, session_factory=BrowserSessions):
        self.tasks = queue.Queue()
        self.on_error = on_error
        self.session_factory = session_factory
        self.thread = threading.Thread(target=self.run, daemon=True, name="mail-browser")
        self.thread.start()

    def submit(self, task):
        self.tasks.put(task)

    def run(self):
        sessions = self.session_factory()
        try:
            while True:
                try:
                    task = self.tasks.get(timeout=0.2)
                except queue.Empty:
                    sessions.poll()
                    continue
                if task is None:
                    break
                try:
                    task(sessions)
                except Exception as exc:
                    self.on_error(exc)
        finally:
            sessions.close()

    def close(self):
        self.tasks.put(None)
        self.thread.join(timeout=5)
        return not self.thread.is_alive()
