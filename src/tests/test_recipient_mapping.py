"""Exercise the recipient picker and address verification in simulated OWA."""
from pathlib import Path
import threading
import unittest

from playwright.sync_api import sync_playwright

from owa_browser import pick, recipient_addresses, validate_regions, visible_unique, write_recipients


PICKER = Path(__file__).resolve().parents[1].joinpath("picker.js").read_text()
TO = {"selector": 'input[aria-label="To"]', "frames": []}
CC = {"selector": 'input[aria-label="Cc"]', "frames": []}
FIXTURE = """
<main id="composer">
  <section id="to-row"><button>To</button><div><form id="changing-to-id">
    <span class="chips"></span><div><input aria-label="To"></div>
  </form></div></section>
  <section id="cc-row"><button>Cc</button><div><form id="changing-cc-id">
    <span class="chips"></span><div><input aria-label="Cc"></div>
  </form></div></section>
  <input aria-label="Subject"><textarea aria-label="Body"></textarea>
</main>
<script>
  for (const input of document.querySelectorAll('form input')) {
    input.addEventListener('keydown', event => {
      if (event.key !== 'Tab' || !input.value) return;
      const chips = input.closest('form').querySelector('.chips');
      for (const address of input.value.split(';').map(value => value.trim())) {
        const chip = document.createElement('span');
        chip.title = address;
        chip.textContent = 'Resolved recipient';
        chips.append(chip);
      }
      input.value = '';
    });
  }
</script>
"""


class RecipientMappingTests(unittest.TestCase):
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
        self.page.set_content(FIXTURE)

    def install(self, own=TO, other=CC, frame=None):
        target = frame or self.page
        target.evaluate(PICKER, {"title": "Confirm recipient row", "kind": "area",
                                 "anchor": own, "excluded": other})
        return target

    def confirm(self, target=None):
        target = target or self.page
        target.get_by_role("button", name="Use selection", exact=True).click()
        return target.evaluate("window.__mailMergePicker.result")

    def test_use_selection_advances_without_manual_parent_selection(self):
        self.install()
        spec = self.confirm()
        self.assertIsNotNone(spec)
        row = visible_unique(self.page, spec)
        self.assertEqual(row.get_attribute("id"), "to-row")
        self.assertEqual(row.locator(".chips").count(), 1)
        self.assertEqual(row.locator(CC["selector"]).count(), 0)

    def test_clicking_the_typing_box_selects_its_whole_row(self):
        self.install()
        self.page.locator(TO["selector"]).click()
        self.assertEqual(visible_unique(self.page, self.confirm()).get_attribute("id"), "to-row")

    def test_larger_area_cannot_include_cc(self):
        self.install()
        self.page.get_by_role("button", name="Larger area", exact=True).click()
        self.assertIn("both To and CC", self.page.locator("[data-mail-merge-picker]").first.inner_text())
        self.assertEqual(visible_unique(self.page, self.confirm()).get_attribute("id"), "to-row")

    def test_accidental_cc_click_keeps_the_to_row_selected(self):
        self.install()
        self.page.locator(CC["selector"]).click()
        self.assertIn("does not contain", self.page.locator("[data-mail-merge-picker]").first.inner_text())
        self.assertEqual(visible_unique(self.page, self.confirm()).get_attribute("id"), "to-row")

    def test_smaller_selection_can_be_expanded_again(self):
        self.install()
        self.page.get_by_role("button", name="Smaller area", exact=True).click()
        self.page.get_by_role("button", name="Larger area", exact=True).click()
        self.assertEqual(visible_unique(self.page, self.confirm()).get_attribute("id"), "to-row")

    def test_plain_input_without_separate_row_is_supported(self):
        self.page.set_content('<main><input aria-label="To"><input aria-label="Cc"></main>')
        self.install()
        spec = self.confirm()
        self.assertIsNotNone(spec)
        write_recipients(self.page, TO, spec, ("alex@example.invalid",))
        self.assertEqual(recipient_addresses(visible_unique(self.page, spec)), {"alex@example.invalid"})

    def test_row_mapping_survives_changed_ids_and_inserted_chips(self):
        self.install()
        to_area = self.confirm()
        self.install(CC, TO)
        cc_area = self.confirm()
        self.page.evaluate("window.__mailMergePicker.cleanup()")
        self.page.set_content(FIXTURE.replace("changing-to-id", "new-to-id")
                              .replace("changing-cc-id", "new-cc-id")
                              .replace('<span class="chips"></span>',
                                       '<span class="chips"><span title="alex@example.invalid">Alex</span></span>', 1))
        profile = {"to": TO, "cc": CC, "to_area": to_area, "cc_area": cc_area}
        validate_regions(self.page, profile)
        self.assertEqual(recipient_addresses(visible_unique(self.page, to_area)), {"alex@example.invalid"})
        self.assertEqual(recipient_addresses(visible_unique(self.page, cc_area)), set())

    def test_verified_addresses_include_resolved_chips_outside_the_input(self):
        self.install()
        spec = self.confirm()
        self.page.evaluate("window.__mailMergePicker.cleanup()")
        addresses = ("alex@example.invalid", "jamie@example.invalid")
        write_recipients(self.page, TO, spec, addresses)
        self.assertEqual(self.page.locator(TO["selector"]).input_value(), "")
        self.assertEqual(recipient_addresses(visible_unique(self.page, spec)), set(addresses))

    def test_picker_function_maps_the_right_iframe_and_cleans_up(self):
        self.page.set_content('<input aria-label="To"><iframe name="composer"></iframe>')
        frame = self.page.frame(name="composer")
        frame.set_content(FIXTURE)
        own = {**TO, "frames": ['iframe[name="composer"]']}
        other = {**CC, "frames": ['iframe[name="composer"]']}
        # Simulate confirming the highlighted row while pick polls its result.
        frame.evaluate("""() => {
          const timer = setInterval(() => {
            if (!window.__mailMergePicker) return;
            for (const button of document.querySelectorAll('[data-mail-merge-picker] button'))
              if (button.textContent === 'Use selection') button.click();
            clearInterval(timer);
          }, 50);
        }""")
        spec = pick(self.page, "Confirm To row", "area", threading.Event(), own, other)
        self.assertEqual(len(spec["frames"]), 1)
        self.assertEqual(self.page.locator(spec["frames"][0]).get_attribute("name"), "composer")
        self.assertEqual(visible_unique(self.page, spec).get_attribute("id"), "to-row")
        self.assertFalse(frame.evaluate("Boolean(window.__mailMergePicker)"))
        self.assertFalse(self.page.evaluate("Boolean(window.__mailMergePicker)"))

    def test_gmail_summary_capture_blocks_mouse_down_and_survives_new_recipients(self):
        self.page.set_content('''<form><div id=":generated" class="hl aoD" tabindex="1">
          <div class="oL">Recipients</div></div><div class="aoD az6"><input aria-label="Subject"></div></form>
          <script>window.expanded=false;
          document.querySelector('.aoD').onmousedown=()=>window.expanded=true;</script>''')
        self.page.evaluate(PICKER, {"title": "Select recipient summary", "kind": "summary"})
        self.page.get_by_text('Recipients', exact=True).click()
        mapping = self.confirm()
        self.assertFalse(self.page.evaluate('window.expanded'))
        self.assertEqual(mapping, {'selector': 'div.aoD[tabindex]'})
        self.page.evaluate('window.__mailMergePicker.cleanup()')
        self.page.set_content('<div id=":new-id" class="aoD hl" tabindex="1">Alex, Jamie</div><div class="aoD az6"><input aria-label="Subject"></div>')
        self.assertEqual(visible_unique(self.page, mapping).inner_text(), 'Alex, Jamie')


if __name__ == "__main__":
    unittest.main()
