"""Operate Outlook or Gmail in a visible browser with a calibrated UI profile."""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from merge_core import EMAIL_IN_TEXT, Ledger, MergeError, Message
from mail_providers import PROVIDER_NAMES, provider_for_url, validate_provider_url
from scheduling import ScheduleRecord, schedule_label, wait_for_schedule
from browser_session import BrowserSessions


class Cancelled(Exception):
    pass


def check_stop(stop):
    if stop.is_set():
        raise Cancelled("Stopped. No further messages will be sent.")


def locate(page, spec, visible_only=False):
    scope = page
    for frame_selector in spec.get("frames", []):
        scope = scope.frame_locator(frame_selector)
    locator = scope.locator(spec["selector"])
    if "text" in spec:
        locator = locator.filter(has_text=re.compile(r"^\s*" + re.escape(spec["text"]) + r"\s*$"))
    for _ in range(spec.get("ancestor_levels", 0)):
        locator = locator.locator("xpath=..")
    if visible_only:
        # Filter in the same frame before waiting. OWA keeps hidden copies of
        # compose controls earlier in the DOM than the active editor.
        locator = locator.and_(scope.locator(":visible"))
    return locator


def visible_unique(page, spec):
    locator = locate(page, spec, visible_only=True)
    locator.first.wait_for(state="visible", timeout=12000)
    if locator.count() != 1:
        raise MergeError(f"A mapped control is ambiguous ({spec['selector']!r} matches {locator.count()} visible controls). Run website setup again.")
    # Keep the locator strict instead of binding to a positional nth match.
    return locator


FRAME_SELECTOR_JS = """element => {
  for (const attr of ['name','title','id','src']) {
    const value=element.getAttribute(attr);
    if (value) {
      const selector='iframe['+attr+'='+JSON.stringify(value)+'],frame['+attr+'='+JSON.stringify(value)+']';
      if (element.ownerDocument.querySelectorAll(selector).length===1) return selector;
    }
  }
  const elements=Array.from(element.ownerDocument.querySelectorAll('iframe,frame'));
  if(elements.length===1) return 'iframe,frame';
  throw new Error('Give this frame a stable name or configure its selector manually.');
}"""


def frame_path(frame):
    path = []
    while frame.parent_frame is not None:
        path.insert(0, frame.frame_element().evaluate(FRAME_SELECTOR_JS))
        frame = frame.parent_frame
    return path


def pick(page, title, kind, stop, anchor=None, excluded=None):
    source = Path(__file__).with_name("picker.js").read_text(encoding="utf-8")
    target_frame = visible_unique(page, anchor).element_handle().owner_frame() if anchor else None
    if excluded and visible_unique(page, excluded).element_handle().owner_frame() != target_frame:
        excluded = None
    installed = set()
    try:
        while True:
            check_stop(stop)
            if page.is_closed():
                raise Cancelled("The browser window was closed.")
            for frame in page.frames:
                if target_frame is not None and frame != target_frame:
                    continue
                if frame not in installed:
                    try:
                        frame.evaluate(source, {"title": title, "kind": kind, "anchor": anchor, "excluded": excluded})
                        installed.add(frame)
                    except Exception:
                        continue
                try:
                    state = frame.evaluate("() => window.__mailMergePicker ? {result:window.__mailMergePicker.result,cancelled:window.__mailMergePicker.cancelled} : null")
                    if state and state["cancelled"]:
                        raise Cancelled("Website setup cancelled.")
                    if state and state["result"]:
                        spec = state["result"]
                        spec["frames"] = frame_path(frame)
                        return spec
                    if state is None:
                        installed.discard(frame)
                except Cancelled:
                    raise
                except Exception:
                    installed.discard(frame)
            page.wait_for_timeout(150)
    finally:
        for frame in list(page.frames):
            try:
                frame.evaluate("() => window.__mailMergePicker && window.__mailMergePicker.cleanup()")
            except Exception:
                pass


def open_compose(inbox, profile, stop):
    check_stop(stop)
    context = inbox.context
    previous = set(context.pages)
    visible_unique(inbox, profile["new"]).click()
    # Legacy OWA can open its editor in a separate window.
    deadline = time.monotonic() + 1.5
    compose = inbox
    while time.monotonic() < deadline:
        inbox.wait_for_timeout(100)
        new_pages = [p for p in context.pages if p not in previous and not p.is_closed()]
        if new_pages:
            if len(new_pages) != 1:
                raise MergeError("More than one new window opened. Close extra windows and try again.")
            compose = new_pages[0]
            compose.wait_for_load_state("domcontentloaded", timeout=15000)
            break
    return compose


def validate_regions(page, profile):
    to_field = visible_unique(page, profile["to"])
    cc_field = visible_unique(page, profile["cc"])
    to_area = visible_unique(page, profile["to_area"])
    cc_area = visible_unique(page, profile["cc_area"])
    for container, own, other in ((to_area, to_field, cc_field), (cc_area, cc_field, to_field)):
        if not container.evaluate("(container,input) => container.contains(input)", own.element_handle()):
            raise MergeError("The mapped recipient row does not contain its typing box. Run website setup again.")
        if container.evaluate("(container,input) => container.contains(input)", other.element_handle()):
            raise MergeError("A mapped recipient row includes both To and CC. Select a smaller row during setup.")


def validate_subject(page, profile):
    subject = visible_unique(page, profile["subject"])
    if not subject.evaluate("element => element.matches('input:not([type]),input[type=text],textarea')"):
        raise MergeError("The Subject mapping is not a subject typing box. Run website setup and select the Subject input.")
    for key in ("to", "cc", "body"):
        other = visible_unique(page, profile[key])
        if subject.element_handle().owner_frame() != other.element_handle().owner_frame():
            continue
        if subject.evaluate("(element, other) => element === other", other.element_handle()):
            raise MergeError(f"Subject and {key.upper() if key != 'body' else 'message body'} are mapped to the same box. Run website setup again.")


def calibrate(inbox, stop, ask, log, provider="outlook"):
    profile = {"version": 2, "provider": provider}
    log("In the browser, select Compose / New mail. Captured clicks do not activate controls.")
    profile["new"] = pick(inbox, "Select the Compose / New mail button", "button", stop)
    compose = open_compose(inbox, profile, stop)
    if not ask("Is CC visible?", "Is the CC typing box already visible in the new message?", "yesno"):
        log("Select the control that reveals CC.")
        profile["show_cc"] = pick(compose, "Select the control that shows the CC field", "button", stop)
        visible_unique(compose, profile["show_cc"]).click()
    steps = (
        ("to", "Select the To typing box", "field"),
        ("cc", "Select the CC typing box", "field"),
        ("to_area", "Confirm the highlighted To row, then choose Use selection", "area"),
        ("cc_area", "Confirm the highlighted CC row, then choose Use selection", "area"),
        ("subject", "Select the Subject typing box", "subject"),
        ("body", "Select the editable message body", "body"),
        ("send", "Select Send. This setup click will NOT send the message", "button"),
    )
    for key, title, kind in steps:
        log(title)
        if kind == "area":
            own, other = ("to", "cc") if key == "to_area" else ("cc", "to")
            profile[key] = pick(compose, title, kind, stop, anchor=profile[own], excluded=profile[other])
        else:
            profile[key] = pick(compose, title, kind, stop)
        visible_unique(compose, profile[key])
    if provider == "gmail":
        # Gmail can collapse the address rows when the body receives focus.
        visible_unique(compose, profile["body"]).click()
        if not all(locate(compose, profile[key], visible_only=True).count() == 1 for key in ("to", "cc")):
            log("Select the recipient summary line that expands To and CC.")
            profile["expand_recipients"] = pick(compose, "Select the recipient summary line to expand To and CC", "summary", stop)
            visible_unique(compose, profile["expand_recipients"]).click()
            ensure_recipient_fields(compose, profile)
    # Selecting later controls can collapse Gmail's recipient rows. Reopen
    # those rows before validating their mappings, rather than waiting on
    # hidden inputs before the summary control has been captured.
    validate_regions(compose, profile)
    validate_subject(compose, profile)
    if not ask("Finish website setup", "Setup is complete. Close or discard the empty message in the browser, return to the inbox, then choose OK here. Nothing has been sent.", "okcancel"):
        raise Cancelled("Website setup cancelled.")
    return profile


def recipient_addresses(container) -> set[str]:
    raw = container.evaluate("""container => {
      const parts=[container.innerText || ''];
      // Legacy OWA replaces an address with a display name after resolving it.
      // Its persona photo URL retains the email even when the photo is hidden.
      // Read metadata only inside visible contact chips, not hidden suggestions.
      for(const persona of container.querySelectorAll('.PersonaPaneLauncher')) {
        const box=persona.getBoundingClientRect();
        if(!box.width || !box.height || getComputedStyle(persona).visibility==='hidden') continue;
        for(const photo of persona.querySelectorAll('img[src]')) {
          try {
            const url=new URL(photo.getAttribute('src'), photo.ownerDocument.baseURI);
            if(url.pathname.endsWith('/GetPersonaPhoto')) {
              const email=url.searchParams.get('email');
              if(email) parts.push(email);
            }
          } catch { /* An invalid photo URL provides no recipient evidence. */ }
        }
      }
      for(const element of [container,...container.querySelectorAll('*')]) {
        const box=element.getBoundingClientRect();
        if(!box.width || !box.height || getComputedStyle(element).visibility==='hidden') continue;
        for(const attr of ['title','aria-label','data-email','data-hovercard-id','data-address','pkd-target','email','address','href']) {
          const value=element.getAttribute(attr); if(value) parts.push(value);
        }
        if(element.matches('input,textarea')) parts.push(element.value || '');
      }
      return parts.join('\\n');
    }""")
    return {match.rstrip(".").casefold() for match in EMAIL_IN_TEXT.findall(raw)}


def recipient_region(page, field_spec, area_spec, other_field_spec):
    """Include resolved chips beside the mapped typing box without crossing rows."""
    area = visible_unique(page, area_spec)
    if other_field_spec is None:
        return area
    field = visible_unique(page, field_spec)
    other = visible_unique(page, other_field_spec)
    if field.element_handle().owner_frame() != other.element_handle().owner_frame():
        return area
    levels = area.evaluate("""(region, other) => {
      let levels=0;
      const editors='input:not([type=hidden]),textarea,[contenteditable=true],[contenteditable=""]';
      while(region.parentElement && region.parentElement !== document.body) {
        const parent=region.parentElement;
        if(parent.contains(other)) break;
        const extra=Array.from(parent.querySelectorAll(editors)).some(editor => {
          if(region.contains(editor)) return false;
          const box=editor.getBoundingClientRect();
          return box.width>0 && box.height>0 && getComputedStyle(editor).visibility!=='hidden';
        });
        if(extra) break;
        region=parent; levels++;
      }
      return levels;
    }""", other.element_handle())
    for _ in range(levels):
        area = area.locator("xpath=..")
    return area


def write_recipients(page, field_spec, area_spec, addresses, other_field_spec=None):
    field = visible_unique(page, field_spec)
    area = recipient_region(page, field_spec, area_spec, other_field_spec)
    if recipient_addresses(area):
        raise MergeError("The new message already contains recipients. Close existing drafts and start again.")
    field.fill("; ".join(addresses))
    # Tab commits address chips without selecting an autocomplete suggestion with Enter.
    field.press("Tab")
    expected = {a.casefold() for a in addresses}
    deadline = time.monotonic() + 8
    observed = set()
    while time.monotonic() < deadline:
        observed = recipient_addresses(area)
        if observed == expected:
            return
        page.wait_for_timeout(150)
    raise MergeError(f"Cannot verify the recipient addresses. Expected {sorted(expected)}; saw {sorted(observed)}. Inspect the draft and check the mapped recipient row.")


def ensure_recipient_fields(page, profile):
    # Gmail retains a measurable To editor even in its collapsed header.
    # The visible summary is the reliable signal that rows need expanding.
    if profile.get("expand_recipients") and locate(page, profile["expand_recipients"], visible_only=True).count():
        visible_unique(page, profile["expand_recipients"]).click()
    if profile.get("show_cc") and not locate(page, profile["cc"], visible_only=True).count():
        visible_unique(page, profile["show_cc"]).click()


def write_gmail_recipients(page, profile, key, addresses):
    """Commit each address separately and require resolved chips, not typed text."""
    other = "cc" if key == "to" else "to"
    ensure_recipient_fields(page, profile)
    area = recipient_region(page, profile[key], profile[key + "_area"], profile[other])
    if recipient_addresses(area):
        raise MergeError("The new message already contains recipients. Close existing drafts and start again.")
    expected = set()
    for address in addresses:
        field = visible_unique(page, profile[key])
        # Gmail's recipient widget tracks keyboard events as well as input.
        # Its current web UI can trap Tab in the address editor; explicitly
        # leaving it for Subject commits the literal address on blur.
        field.click()
        field.fill("")
        field.press_sequentially(address, delay=10)
        # Google's PeopleKit editor offers the literal address as an option.
        # Select only an option whose email evidence exactly matches it.
        # Never accept a highlighted contact merely by pressing Enter.
        deadline = time.monotonic() + (3 if field.get_attribute("role") == "combobox" else 0)
        while True:
            committed = False
            for option in page.get_by_role("option").all():
                if not option.is_visible():
                    continue
                target = option.element_handle()
                if target and recipient_addresses(target) == {address.casefold()}:
                    target.click()
                    committed = True
                    break
            if committed or time.monotonic() >= deadline:
                break
            page.wait_for_timeout(100)
        # Dismiss suggestions before moving focus so the dropdown cannot
        # cover Subject or substitute a different suggested contact.
        if not committed and page.get_by_role("option").and_(page.locator(":visible")).count():
            field.press("Escape")
        visible_unique(page, profile["subject"]).click()
        if profile.get("expand_recipients"):
            # Subject focus collapses Gmail's header asynchronously. Wait
            # for that transition before attempting to reopen the rows.
            visible_unique(page, profile["expand_recipients"])
        ensure_recipient_fields(page, profile)
        expected.add(address.casefold())
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            field = visible_unique(page, profile[key])
            area = recipient_region(page, profile[key], profile[key + "_area"], profile[other])
            if not field.input_value().strip() and recipient_addresses(area) == expected:
                break
            page.wait_for_timeout(150)
        else:
            raise MergeError(f"Gmail did not resolve the {key.upper()} address {address}. Inspect the draft; nothing further was sent.")


def normalize_body(text):
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ").rstrip()


def body_text(locator):
    if locator.evaluate("element => element.matches('input,textarea')"):
        return locator.input_value()
    return locator.inner_text()


def verify_message(page, profile, message):
    ensure_recipient_fields(page, profile)
    for key, other, expected in (("to", "cc", {message.to.casefold()}),
                                 ("cc", "to", {a.casefold() for a in message.cc})):
        if profile.get("provider") == "gmail" and visible_unique(page, profile[key]).input_value().strip():
            raise MergeError(f"Gmail still has unresolved {key.upper()} recipient text. The batch has stopped.")
        observed = recipient_addresses(recipient_region(page, profile[key], profile[key + "_area"], profile[other]))
        if observed != expected:
            raise MergeError(f"Cannot verify {key.upper()} recipients. Expected {sorted(expected)}; saw {sorted(observed)}. The batch has stopped.")
    if visible_unique(page, profile["subject"]).input_value() != message.subject:
        raise MergeError("The subject in the browser does not match the preview.")
    if normalize_body(body_text(visible_unique(page, profile["body"]))) != normalize_body(message.body):
        raise MergeError("The body in the browser does not match the preview.")


def prepare_message(inbox, profile, message, stop):
    compose = open_compose(inbox, profile, stop)
    check_stop(stop)
    ensure_recipient_fields(compose, profile)
    validate_regions(compose, profile)
    validate_subject(compose, profile)
    if profile.get("provider") == "gmail":
        write_gmail_recipients(compose, profile, "to", (message.to,))
        write_gmail_recipients(compose, profile, "cc", message.cc)
    else:
        write_recipients(compose, profile["to"], profile["to_area"], (message.to,), profile["cc"])
        write_recipients(compose, profile["cc"], profile["cc_area"], message.cc, profile["to"])
    visible_unique(compose, profile["subject"]).fill(message.subject)
    body = visible_unique(compose, profile["body"])
    text_box = body.evaluate("element => element.matches('input,textarea')")
    if not text_box:
        body.click()
        body.press("ControlOrMeta+A")
        body.press("Backspace")
        # Real line-break keystrokes preserve paragraphs in legacy HTML editors.
        # Inserting one multiline text node can render all paragraphs on one line.
        lines = message.body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        for index, line in enumerate(lines):
            check_stop(stop)
            if index:
                body.press("Shift+Enter")
            if line:
                compose.keyboard.insert_text(line)
    else:
        body.fill(message.body)
    verify_message(compose, profile, message)
    # Validate the action before asking the user to approve the batch, so a
    # stale mapping cannot surface only after that approval.
    if not visible_unique(compose, profile["send"]).is_enabled():
        raise MergeError("The Send button is disabled. Check the draft.")
    return compose


def submit_message(compose, profile, message, campaign, ledger, stop, acknowledgement_timeout=20):
    check_stop(stop)
    verify_message(compose, profile, message)
    send = visible_unique(compose, profile["send"])
    subject = visible_unique(compose, profile["subject"])
    if not send.is_enabled():
        raise MergeError("The Send button is disabled. Check the draft.")
    ledger.record(campaign, message, "attempting", "Send action is starting")
    try:
        send.click(timeout=12000)
        deadline = time.monotonic() + acknowledgement_timeout
        while time.monotonic() < deadline:
            # Acknowledgement is the mapped composer disappearing or its popup closing.
            # It is NOT proof of delivery to the recipient.
            if compose.is_closed() or not subject.is_visible():
                ledger.record(campaign, message, "submitted", "Composer closed after Send; check Sent Items for delivery status")
                return
            compose.wait_for_timeout(150)
        raise MergeError("The mail website did not close the message after Send. Inspect the draft and Sent / Sent Items before retrying.")
    except Exception as exc:
        ledger.record(campaign, message, "uncertain", str(exc))
        raise


def run_batch(inbox, profile, messages, campaign, ledger, stop, ask, log, delay=5,
              scheduled_at=None, schedule_file=None):
    unresolved = [m for m in messages if ledger.status(campaign, m.to) in ("attempting", "uncertain")]
    if unresolved:
        raise MergeError("An earlier send has an uncertain result. Use Send history, check Sent Items, and resolve it before continuing.")
    pending = [m for m in messages if ledger.status(campaign, m.to) != "submitted"]
    if not pending:
        log("All emails in this unchanged batch were already submitted. Nothing was resent.")
        return
    log(f"Preparing the first email. {len(pending)} remaining; {len(messages)-len(pending)} previously submitted.")
    compose = prepare_message(inbox, profile, pending[0], stop)
    action = f"Start sending all {len(pending)} remaining emails at {schedule_label(scheduled_at)}?\nKeep this app, browser and computer awake until the batch finishes." if scheduled_at else f"Send all {len(pending)} remaining personalized emails now?"
    if not ask("Review and schedule" if scheduled_at else "Review and send", f"Review the first email in the browser, including To, CC, subject, body and sending mailbox.\n\n{action}\n\nDo not click Send in the browser yourself. Choose No to keep this as an unsent draft.", "yesno"):
        raise Cancelled("Batch cancelled. The first email remains an unsent draft.")
    record = ScheduleRecord(schedule_file, scheduled_at, campaign, len(pending)) if scheduled_at and schedule_file else None
    try:
        if scheduled_at:
            if record:
                record.update("waiting")
            if not wait_for_schedule(scheduled_at, stop, log):
                raise Cancelled("Scheduled batch cancelled. No further emails will be sent.")
            if record:
                record.update("sending")
        for index, message in enumerate(pending):
            check_stop(stop)
            if index:
                compose = prepare_message(inbox, profile, message, stop)
            # This rechecks the draft after the timer, including any user edits.
            submit_message(compose, profile, message, campaign, ledger, stop)
            log(f"{index+1}/{len(pending)} submitted — row {message.row}: {message.to}")
            if index + 1 < len(pending):
                if stop.wait(delay):
                    raise Cancelled("Stopped. Submitted emails are recorded; remaining rows are pending.")
        if record:
            record.update("complete")
        log("Batch completed. The mail website accepted the Send actions; check Sent / Sent Items for delivery status.")
    except Exception as exc:
        if record:
            record.update("cancelled" if isinstance(exc, Cancelled) else "failed", str(exc))
        raise


def select_mailbox_page(context, url):
    pages = [p for p in context.pages if not p.is_closed() and urlsplit(p.url).scheme in ("http", "https")]
    candidates = [p for p in pages if urlsplit(p.url).hostname == urlsplit(url).hostname]
    # Sign-in can redirect the mailbox to another host. The user's confirmation
    # identifies the sole web tab as the inbox; blank startup tabs do not count.
    if not candidates:
        candidates = pages
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise MergeError("No mailbox tab is open. Open the mailbox inbox in the app's browser and try again.")
    raise MergeError("More than one possible mailbox tab is open. Leave only the mailbox inbox tab open and try again.")


def choose_mailbox_page(context, url, mailbox, ask):
    pages = [p for p in context.pages if not p.is_closed() and urlsplit(p.url).scheme in ("http", "https")]
    candidates = [p for p in pages if urlsplit(p.url).hostname == urlsplit(url).hostname] or pages
    if not candidates:
        raise MergeError("No mailbox tab is open. Open the mailbox in the app's browser and try again.")
    if len(candidates) == 1:
        return candidates[0]
    labels = []
    for index, page in enumerate(candidates):
        parts = urlsplit(page.url)
        labels.append(f"{index+1}. {page.title()} — {parts.hostname}{parts.path}")
    selected = ask("Choose the mailbox tab", {
        "prompt": f"Choose the tab for {mailbox}. Other tabs can stay open. Return that tab to the inbox and close its existing compose windows before continuing.",
        "options": labels,
    }, "choice")
    if selected is None:
        raise Cancelled("Mailbox tab selection cancelled. The browser remains open.")
    if not isinstance(selected, int) or not 0 <= selected < len(candidates):
        raise MergeError("No valid mailbox tab was selected.")
    return candidates[selected]


def browser_task(mode, url, mailbox, state_dir, messages, campaign, stop, ask, log, delay=5,
                 provider=None, scheduled_at=None, browser_channel=None, sessions=None):
    if mode == "schedule" and scheduled_at is None:
        raise MergeError("Choose a scheduled date and time first.")
    provider = provider or provider_for_url(url)
    validate_provider_url(provider, url)
    service = PROVIDER_NAMES[provider]
    state_dir.mkdir(parents=True, exist_ok=True)
    state_dir.chmod(0o700)
    profile_file = state_dir / "website.json"
    if mode != "setup" and not profile_file.exists():
        raise MergeError("Run Website setup for this URL and mailbox first.")
    owned_sessions = sessions is None
    sessions = sessions or BrowserSessions()
    try:
        context, created = sessions.get_context(state_dir, browser_channel)
        page = context.pages[0] if context.pages else context.new_page()
        if created or urlsplit(page.url).scheme not in ("http", "https"):
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
        instruction = "Sign in normally in the browser, including any MFA." if created else "Your browser is still open. Switch to the mailbox tab for this account."
        if not ask(f"Ready in {service}?", f"{instruction}\n\nConfirm that you are using {mailbox}. Return to the inbox and close or discard existing compose windows. Other tabs can remain open.\n\nChoose OK when ready.", "okcancel"):
            raise Cancelled("Task cancelled. The browser remains open.")
        check_stop(stop)
        page = choose_mailbox_page(context, url, mailbox, ask)
        page.bring_to_front()
        if mode == "setup":
            profile = calibrate(page, stop, ask, log, provider)
            profile["url"] = url
            profile["mailbox"] = mailbox
            temporary = profile_file.with_suffix(".tmp")
            temporary.write_text(json.dumps(profile, indent=2), encoding="utf-8")
            temporary.replace(profile_file)
            log("Website setup saved. You can now open a draft or send the batch.")
        else:
            profile = json.loads(profile_file.read_text(encoding="utf-8"))
            if profile.get("url") != url or profile.get("mailbox", "").casefold() != mailbox.casefold():
                raise MergeError("Website setup belongs to a different URL or mailbox.")
            if profile.get("provider", "outlook") != provider:
                raise MergeError("Run Website setup for the selected mail service first.")
            if mode == "draft":
                prepare_message(page, profile, messages[0], stop)
                log(f"First personalized draft is open in {service}. Nothing was sent.")
                ask("Inspect the draft", "Review To, CC, subject and body in the browser. Do not send this draft manually if you plan to run the full batch. Choose OK to return to the app. The browser and draft remain open; close or discard the draft and return to the inbox before the next batch.", "okcancel")
            elif mode in ("send", "schedule"):
                ledger = Ledger(state_dir / "send-history.sqlite3")
                try:
                    run_batch(page, profile, messages, campaign, ledger, stop, ask, log, delay,
                              scheduled_at, state_dir / "schedule.json")
                finally:
                    ledger.close()
        log("Browser kept open. You can switch tabs or return to the inbox for the next action.")
    finally:
        # Desktop actions share one owner thread/session. Only standalone
        # callers close their temporary session; app sessions close on app exit.
        if owned_sessions:
            sessions.close()
