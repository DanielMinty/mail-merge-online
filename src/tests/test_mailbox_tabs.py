"""Regression checks for mailbox tab selection using local browser fixtures."""
import unittest

from playwright.sync_api import sync_playwright

from merge_core import MergeError
from owa_browser import select_mailbox_page


START_URL = "https://mail.example.test/owa/"
INBOX_URL = "https://owa.example.test/owa/"


class MailboxTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        # All pages are simulated: no sign-in or external network is involved.
        self.context.route("**/*", lambda route: route.fulfill(
            status=200, content_type="text/html", body="<h1>Mailbox fixture</h1>"))

    def open_page(self, url):
        page = self.context.new_page()
        page.goto(url)
        return page

    def test_mailbox_redirects_to_a_different_host(self):
        self.context.route(START_URL, lambda route: route.fulfill(
            content_type="text/html", body=f'<script>location.replace("{INBOX_URL}")</script>'))
        page = self.context.new_page()
        page.goto(START_URL, wait_until="commit")
        page.wait_for_url(INBOX_URL)
        self.assertEqual(page.url, INBOX_URL)
        self.assertIs(select_mailbox_page(self.context, START_URL), page)

    def test_blank_startup_tab_does_not_count_as_an_extra_mailbox(self):
        self.context.new_page()
        inbox = self.open_page(INBOX_URL)
        self.assertIs(select_mailbox_page(self.context, START_URL), inbox)

    def test_same_host_mailbox_is_selected_among_sign_in_tabs(self):
        self.open_page("https://login.example.test/sign-in")
        inbox = self.open_page(START_URL)
        self.assertIs(select_mailbox_page(self.context, START_URL), inbox)

    def test_closed_tab_does_not_count(self):
        self.open_page(START_URL).close()
        inbox = self.open_page(INBOX_URL)
        self.assertIs(select_mailbox_page(self.context, START_URL), inbox)

    def test_two_mailbox_tabs_still_require_closing_one(self):
        self.open_page(START_URL)
        self.open_page(START_URL)
        with self.assertRaisesRegex(MergeError, "More than one"):
            select_mailbox_page(self.context, START_URL)

    def test_two_redirected_tabs_are_not_guessed(self):
        self.open_page(INBOX_URL)
        self.open_page("https://login.example.test/sign-in")
        with self.assertRaisesRegex(MergeError, "More than one"):
            select_mailbox_page(self.context, START_URL)

    def test_no_mailbox_has_a_distinct_error(self):
        self.context.new_page()
        with self.assertRaisesRegex(MergeError, "No mailbox tab"):
            select_mailbox_page(self.context, START_URL)


if __name__ == "__main__":
    unittest.main()
