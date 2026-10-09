"""A mailbox browser survives actions and stays on its owning thread."""
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import patch

from browser_session import BrowserSessions, BrowserWorker
from merge_core import MergeError
from owa_browser import Cancelled, browser_task, choose_mailbox_page


URL = "https://mail.example.test/owa/"
MAILBOX = "sender@example.test"


class BrowserSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.sessions = BrowserSessions(headless=True)
        self.addCleanup(self.sessions.close)

    def test_reuses_the_context_without_navigating_or_closing_after_actions(self):
        context, created = self.sessions.get_context(self.directory)
        self.assertTrue(created)
        context.route("**/*", lambda route: route.fulfill(content_type="text/html", body="<title>Test mailbox</title>Inbox"))
        page = context.pages[0]
        page.goto(URL)
        profile = {"provider": "outlook"}
        with patch("owa_browser.calibrate", return_value=profile):
            browser_task("setup", URL, MAILBOX, self.directory, (), "campaign", threading.Event(),
                         lambda *_: True, lambda _: None, sessions=self.sessions)
        self.assertFalse(page.is_closed())
        page.goto(URL + "sent")
        with patch("owa_browser.prepare_message") as prepare:
            browser_task("draft", URL, MAILBOX, self.directory, (object(),), "campaign", threading.Event(),
                         lambda *_: True, lambda _: None, sessions=self.sessions)
        self.assertIs(prepare.call_args.args[0], page)
        self.assertEqual(page.url, URL + "sent")
        self.assertFalse(page.is_closed())
        again, created = self.sessions.get_context(self.directory)
        self.assertIs(again, context)
        self.assertFalse(created)

    def test_cancelled_action_leaves_the_browser_open(self):
        context, _ = self.sessions.get_context(self.directory)
        context.route("**/*", lambda route: route.fulfill(body="Inbox"))
        context.pages[0].goto(URL)
        with self.assertRaises(Cancelled):
            browser_task("setup", URL, MAILBOX, self.directory, (), "campaign", threading.Event(),
                         lambda *_: False, lambda _: None, sessions=self.sessions)
        self.assertFalse(context.pages[0].is_closed())
        self.assertTrue(context.browser.is_connected())

    def test_reused_blank_tab_is_loaded_before_readiness_prompt(self):
        context, _ = self.sessions.get_context(self.directory)
        context.route("**/*", lambda route: route.fulfill(body="Inbox"))
        with patch("owa_browser.calibrate", return_value={"provider": "outlook"}):
            browser_task("setup", URL, MAILBOX, self.directory, (), "campaign", threading.Event(),
                         lambda *_: True, lambda _: None, sessions=self.sessions)
        self.assertEqual(context.pages[0].url, URL)

    def test_multiple_mailbox_tabs_can_be_selected_without_closing_others(self):
        context, _ = self.sessions.get_context(self.directory)
        context.route("**/*", lambda route: route.fulfill(content_type="text/html", body="<title>Mailbox</title>Inbox"))
        first = context.pages[0]
        first.goto(URL)
        second = context.new_page()
        second.goto(URL + "second")
        requests = []
        def choose(title, content, kind):
            requests.append((content, kind))
            return 1
        self.assertIs(choose_mailbox_page(context, URL, MAILBOX, choose), second)
        self.assertEqual(len(requests[0][0]["options"]), 2)
        self.assertEqual(requests[0][1], "choice")
        self.assertFalse(first.is_closed())

    def test_changing_browser_type_requires_closing_existing_window(self):
        context, _ = self.sessions.get_context(self.directory)
        with self.assertRaisesRegex(MergeError, "already open"):
            self.sessions.get_context(self.directory, channel="chrome")
        self.assertTrue(context.browser.is_connected())


class WorkerThreadTests(unittest.TestCase):
    def test_actions_and_shutdown_share_one_owner_thread(self):
        results = queue.Queue()
        errors = []
        class FakeSessions:
            def poll(self):
                pass
            def close(self):
                results.put(("closed", threading.get_ident(), self))
        worker = BrowserWorker(errors.append, FakeSessions)
        self.addCleanup(worker.close)
        for index in range(2):
            worker.submit(lambda sessions, index=index: results.put((index, threading.get_ident(), sessions)))
        first = results.get(timeout=2)
        second = results.get(timeout=2)
        self.assertEqual(first[1], second[1])
        self.assertIs(first[2], second[2])
        self.assertNotEqual(first[1], threading.get_ident())
        self.assertTrue(worker.close())
        closed = results.get(timeout=2)
        self.assertEqual(closed[1], first[1])
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
