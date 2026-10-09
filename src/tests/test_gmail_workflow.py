"""End-to-end batch checks against a local Gmail-style compose fixture."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from mail_providers import GMAIL_URL, validate_provider_url
from merge_core import Ledger, MergeError, Message
from owa_browser import Cancelled, calibrate, ensure_recipient_fields, prepare_message, run_batch, submit_message, verify_message


def spec(selector):
    return {"selector": selector, "frames": []}


PROFILE = {"provider": "gmail", "new": spec("#compose-new"), "to": spec("input[name=to]"),
           "cc": spec("input[name=cc]"), "to_area": spec("#to-row"), "cc_area": spec("#cc-row"),
           "show_cc": spec("#show-cc"), "expand_recipients": spec("#expand-recipients"),
           "subject": spec("input[name=subjectbox]"), "body": spec("#body"), "send": spec("#send")}
MESSAGES = (Message(2, "alex@example.com", ("jamie@example.com", "manager@example.com"), "Hello Alex", "Hi Alex,\n\nThanks,\nSender"),
            Message(3, "taylor@example.com", (), "Hello Taylor", "Hi Taylor,\n\nThanks,\nSender"))
FIXTURE = '''
<button id="compose-new">Compose</button>
<section id="compose" hidden>
  <button id="expand-recipients" hidden>Recipients</button>
  <div id="addresses">
    <div id="to-row"><span class="chips"></span><input name="to" aria-label="To recipients"></div>
    <button id="show-cc">Cc</button>
    <div id="cc-row" hidden><span class="chips"></span><input name="cc" aria-label="Cc recipients"></div>
  </div>
  <input name="subjectbox" aria-label="Subject">
  <div id="body" contenteditable="true" role="textbox" aria-label="Message Body"></div>
  <div id="send" role="button" tabindex="0" data-tooltip="Send (Ctrl-Enter)">Send</div>
</section>
<script>
  const get = id => document.getElementById(id);
  window.sent = [];
  get('compose-new').onclick = () => {
    get('compose').hidden = false; get('addresses').hidden = false;
    get('expand-recipients').hidden = true; get('cc-row').hidden = true;
    document.querySelectorAll('.chips').forEach(e => e.replaceChildren());
    document.querySelectorAll('input').forEach(e => e.value = '');
    get('body').replaceChildren();
  };
  get('show-cc').onclick = () => get('cc-row').hidden = false;
  get('body').onfocus = () => { get('addresses').hidden = true; get('expand-recipients').hidden = false; };
  document.querySelector('[name=subjectbox]').onfocus = get('body').onfocus;
  get('expand-recipients').onclick = () => { get('addresses').hidden = false; get('expand-recipients').hidden = true; };
  document.querySelectorAll('#addresses input').forEach(input => {
    const commit = () => {
      if(!input.value.trim()) return;
      const chip = document.createElement('span');
      chip.setAttribute('data-hovercard-id', input.value.trim());
      chip.textContent = 'Resolved contact name';
      input.parentElement.querySelector('.chips').append(chip);
      input.value = '';
    };
    input.onkeydown = event => { if(event.key === 'Tab') commit(); };
    input.onblur = commit;
  });
  get('send').onclick = () => {
    const addresses = row => Array.from(get(row).querySelectorAll('[data-hovercard-id]')).map(e => e.getAttribute('data-hovercard-id'));
    window.sent.push({to:addresses('to-row'),cc:addresses('cc-row'),subject:document.querySelector('[name=subjectbox]').value,body:get('body').innerText});
    get('compose').hidden = true;
  };
</script>
'''


class GmailWorkflowTests(unittest.TestCase):
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
        self.context.route("**/*", lambda route: route.abort())
        self.page = self.context.new_page()
        self.page.set_content(FIXTURE)
        self.stop = threading.Event()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.ledger = Ledger(Path(self.temporary.name) / "history.sqlite3")
        self.addCleanup(self.ledger.close)

    def test_gmail_draft_resolves_chips_and_reopens_collapsed_rows(self):
        prepare_message(self.page, PROFILE, MESSAGES[0], self.stop)
        verify_message(self.page, PROFILE, MESSAGES[0])
        self.assertEqual(self.page.evaluate('window.sent'), [])
        self.assertTrue(self.page.locator('#addresses').is_visible())

    def test_setup_reopens_collapsed_rows_before_validating_mappings(self):
        selections = iter(('new', 'show_cc', 'to', 'cc', 'to_area', 'cc_area',
                           'subject', 'body', 'send', 'expand_recipients'))
        def select_control(page, title, kind, stop, **kwargs):
            key = next(selections)
            if key == 'body':
                page.locator('#body').click()
            return PROFILE[key]
        def answer(title, *_):
            return title != 'Is CC visible?'
        with patch('owa_browser.pick', side_effect=select_control):
            profile = calibrate(self.page, self.stop, answer, lambda _: None, 'gmail')
        self.assertEqual(profile['expand_recipients'], PROFILE['expand_recipients'])
        self.assertTrue(self.page.locator('#addresses').is_visible())
        self.assertEqual(self.page.evaluate('window.sent'), [])

    def test_visible_summary_reopens_rows_even_if_to_input_is_still_measurable(self):
        self.page.locator('#compose-new').click()
        self.page.evaluate('''() => {
          document.getElementById('expand-recipients').hidden = false;
        }''')
        self.assertTrue(self.page.locator('[name=to]').is_visible())
        ensure_recipient_fields(self.page, PROFILE)
        self.assertFalse(self.page.locator('#expand-recipients').is_visible())
        self.assertTrue(self.page.locator('[name=cc]').is_visible())

    def test_entire_batch_sends_exact_content_and_rerun_skips_all(self):
        logs = []
        run_batch(self.page, PROFILE, MESSAGES, "campaign", self.ledger, self.stop, lambda *_: True, logs.append, delay=0)
        sent = self.page.evaluate('window.sent')
        self.assertEqual(len(sent), 2)
        for actual, expected in zip(sent, MESSAGES):
            self.assertEqual(actual['to'], [expected.to])
            self.assertEqual(actual['cc'], list(expected.cc))
            self.assertEqual(actual['subject'], expected.subject)
            self.assertEqual(actual['body'].rstrip(), expected.body)
            self.assertEqual(self.ledger.status('campaign', expected.to), 'submitted')
        run_batch(self.page, PROFILE, MESSAGES, "campaign", self.ledger, self.stop, lambda *_: self.fail('No second approval'), logs.append, delay=0)
        self.assertEqual(len(self.page.evaluate('window.sent')), 2)

    def test_edited_body_is_rejected_before_any_send_attempt(self):
        prepare_message(self.page, PROFILE, MESSAGES[0], self.stop)
        self.page.locator('#body').fill('Changed after review')
        with self.assertRaisesRegex(MergeError, 'body'):
            submit_message(self.page, PROFILE, MESSAGES[0], 'campaign', self.ledger, self.stop)
        self.assertEqual(self.ledger.status('campaign', MESSAGES[0].to), 'pending')
        self.assertEqual(self.page.evaluate('window.sent'), [])

    def test_unresolved_typed_text_cannot_pass_recipient_verification(self):
        prepare_message(self.page, PROFILE, MESSAGES[0], self.stop)
        self.page.locator('[name=to]').fill(MESSAGES[0].to)
        with self.assertRaisesRegex(MergeError, 'unresolved'):
            verify_message(self.page, PROFILE, MESSAGES[0])

    def test_gmail_recipient_entry_activates_the_widget_and_generates_keyboard_events(self):
        self.page.evaluate('''() => {
          for (const input of document.querySelectorAll('#addresses input')) {
            const commit = input.onkeydown;
            const blur = input.onblur;
            input.onmousedown = () => input.dataset.active = 'true';
            input.onkeydown = event => {
              if (event.key.length === 1) input.dataset.typed = 'true';
              if (event.key === 'Tab' && input.value && (!input.dataset.typed || !input.dataset.active)) return;
              commit(event);
            };
            input.onblur = () => {
              if (input.value && (!input.dataset.typed || !input.dataset.active)) return;
              blur();
            };
          }
        }''')
        prepare_message(self.page, PROFILE, MESSAGES[0], self.stop)
        verify_message(self.page, PROFILE, MESSAGES[0])
        self.assertEqual(self.page.evaluate('window.sent'), [])

    def test_gmail_recipient_commits_even_when_tab_is_trapped_in_the_editor(self):
        self.page.evaluate('''() => {
          for (const input of document.querySelectorAll('#addresses input'))
            input.onkeydown = event => { if(event.key === 'Tab') event.preventDefault(); };
        }''')
        prepare_message(self.page, PROFILE, MESSAGES[0], self.stop)
        verify_message(self.page, PROFILE, MESSAGES[0])
        self.assertEqual(self.page.evaluate('window.sent'), [])

    def test_gmail_autocomplete_is_dismissed_before_subject_focus(self):
        self.page.evaluate('''() => {
          const overlay = document.createElement('div');
          overlay.id = 'autocomplete'; overlay.hidden = true;
          overlay.setAttribute('role', 'option');
          overlay.setAttribute('data-email', 'different@example.org');
          overlay.style.cssText = 'position:fixed;inset:0;background:white;z-index:10';
          document.body.append(overlay);
          for (const input of document.querySelectorAll('#addresses input')) {
            input.oninput = () => overlay.hidden = false;
            const keydown = input.onkeydown;
            input.onkeydown = event => {
              if(event.key === 'Escape') overlay.hidden = true;
              keydown(event);
            };
          }
        }''')
        prepare_message(self.page, PROFILE, MESSAGES[0], self.stop)
        verify_message(self.page, PROFILE, MESSAGES[0])
        self.assertFalse(self.page.locator('#autocomplete').is_visible())
        self.assertEqual(self.page.evaluate('window.sent'), [])

    def test_peoplekit_literal_option_commits_address_when_blur_does_not(self):
        self.page.evaluate('''() => {
          for (const input of document.querySelectorAll('#addresses input')) {
            input.setAttribute('role', 'combobox');
            const blurCommit = input.onblur;
            input.onblur = () => {};
            input.oninput = () => {
              document.querySelectorAll('[role=option]').forEach(e => e.remove());
              if(!input.value) return;
              const option = document.createElement('div');
              option.setAttribute('role', 'option');
              option.setAttribute('pkd-target', '1:'+input.value+';'+input.value);
              option.textContent = 'Literal address';
              option.onclick = () => { blurCommit(); option.remove(); };
              document.body.append(option);
            };
          }
          document.addEventListener('keydown', event => {
            if(event.key === 'Escape' && !document.querySelector('[role=option]'))
              document.getElementById('compose').hidden = true;
          });
        }''')
        prepare_message(self.page, PROFILE, MESSAGES[0], self.stop)
        verify_message(self.page, PROFILE, MESSAGES[0])
        self.assertEqual(self.page.evaluate('window.sent'), [])

    def test_scheduled_batch_waits_before_send_and_records_completion(self):
        path = Path(self.temporary.name) / 'schedule.json'
        when = datetime.now(timezone.utc) + timedelta(minutes=5)
        def wait_before_send(*_):
            self.assertEqual(self.page.evaluate('window.sent'), [])
            self.assertEqual(json.loads(path.read_text())['status'], 'waiting')
            return True
        with patch('owa_browser.wait_for_schedule', side_effect=wait_before_send) as wait:
            run_batch(self.page, PROFILE, MESSAGES[:1], 'campaign', self.ledger, self.stop,
                      lambda *_: True, lambda _: None, delay=0, scheduled_at=when, schedule_file=path)
        wait.assert_called_once()
        self.assertEqual(len(self.page.evaluate('window.sent')), 1)
        self.assertEqual(json.loads(path.read_text())['status'], 'complete')

    def test_cancelled_schedule_sends_nothing_and_records_cancellation(self):
        path = Path(self.temporary.name) / 'schedule.json'
        when = datetime.now(timezone.utc) + timedelta(minutes=5)
        with patch('owa_browser.wait_for_schedule', return_value=False), self.assertRaises(Cancelled):
            run_batch(self.page, PROFILE, MESSAGES[:1], 'campaign', self.ledger, self.stop,
                      lambda *_: True, lambda _: None, delay=0, scheduled_at=when, schedule_file=path)
        self.assertEqual(self.page.evaluate('window.sent'), [])
        self.assertEqual(self.ledger.status('campaign', MESSAGES[0].to), 'pending')
        self.assertEqual(json.loads(path.read_text())['status'], 'cancelled')

    def test_provider_mismatch_is_rejected(self):
        self.assertEqual(validate_provider_url('gmail', GMAIL_URL), GMAIL_URL)
        with self.assertRaises(MergeError):
            validate_provider_url('outlook', GMAIL_URL)


if __name__ == '__main__':
    unittest.main()
