"""Hidden legacy OWA composer copies must not hide the active controls."""
from pathlib import Path
import unittest

from playwright.sync_api import sync_playwright

from merge_core import MergeError
from owa_browser import visible_unique


SEND = {"selector": 'button[aria-label="Send"]', "frames": []}
PICKER = Path(__file__).resolve().parents[1].joinpath("picker.js").read_text()
BUTTONS = '''
<div hidden><button aria-label="Send">Send</button></div>
<section id="active"><button id="send" aria-label="Send">Send</button></section>
'''


class VisibleControlTests(unittest.TestCase):
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
        self.page = self.context.new_page()

    def test_hidden_first_match_does_not_block_visible_send(self):
        self.page.set_content(BUTTONS)
        self.assertEqual(visible_unique(self.page, SEND).get_attribute("id"), "send")

    def test_waits_for_active_control_while_hidden_copy_remains(self):
        self.page.set_content(BUTTONS.replace('id="active"', 'id="active" hidden'))
        self.page.evaluate("setTimeout(() => document.querySelector('#active').hidden = false, 100)")
        self.assertEqual(visible_unique(self.page, SEND).get_attribute("id"), "send")

    def test_two_visible_buttons_are_rejected(self):
        self.page.set_content(BUTTONS.replace('<div hidden>', '<div>'))
        with self.assertRaisesRegex(MergeError, "ambiguous"):
            visible_unique(self.page, SEND)

    def test_frame_and_ancestor_mapping_filter_in_the_correct_frame(self):
        self.page.set_content('<button aria-label="Send">Send</button><iframe name="compose"></iframe>')
        self.page.frame(name="compose").set_content(BUTTONS)
        spec = {**SEND, "frames": ['iframe[name="compose"]'], "ancestor_levels": 1}
        self.assertEqual(visible_unique(self.page, spec).get_attribute("id"), "active")

    def test_picker_keeps_stable_label_despite_hidden_duplicates(self):
        self.page.set_content(BUTTONS)
        self.page.evaluate(PICKER, {"title": "Select Send", "kind": "button"})
        self.page.locator('#send').click()
        self.page.get_by_role('button', name='Use selection', exact=True).click()
        spec = self.page.evaluate('window.__mailMergePicker.result')
        self.assertEqual(spec['selector'], SEND['selector'])
        self.page.evaluate('window.__mailMergePicker.cleanup()')
        self.page.set_content('<header>New layout</header>' + BUTTONS.replace('<section', '<article').replace('</section>', '</article>'))
        self.assertEqual(visible_unique(self.page, spec).get_attribute("id"), "send")

    def test_picker_distinguishes_toolbar_and_footer_send_buttons(self):
        self.page.set_content('''
          <header><button aria-label="Send" autoid="_fce_0">Send</button></header>
          <footer><button aria-label="Send" autoid="_mcp_g">Send</button></footer>
          <div hidden><button aria-label="Send" autoid="_mcp_g">Send</button></div>
        ''')
        self.page.evaluate(PICKER, {"title": "Select Send", "kind": "button"})
        self.page.locator('header button').click()
        self.page.get_by_role('button', name='Use selection', exact=True).click()
        spec = self.page.evaluate('window.__mailMergePicker.result')
        self.assertEqual(spec['selector'], 'button[autoid="_fce_0"]')
        self.page.evaluate('window.__mailMergePicker.cleanup()')
        self.assertEqual(visible_unique(self.page, spec).get_attribute('autoid'), '_fce_0')


if __name__ == "__main__":
    unittest.main()
