/* Point-and-click calibration. Captured clicks never activate mail controls. */
({ title, kind, anchor = null, excluded = null }) => {
  if (window.__mailMergePicker) window.__mailMergePicker.cleanup();
  let selected = null;
  const state = { result: null, cancelled: false };
  const panel = document.createElement('div');
  panel.setAttribute('data-mail-merge-picker', '');
  Object.assign(panel.style, {
    position: 'fixed', top: '8px', right: '8px', zIndex: '2147483647',
    padding: '12px', width: '350px', background: '#14324d', color: 'white',
    font: '14px/1.45 Arial,sans-serif', borderRadius: '8px', boxShadow: '0 2px 12px #0008'
  });
  const heading = document.createElement('div');
  heading.textContent = title;
  panel.append(heading);
  const description = document.createElement('div');
  description.style.margin = '8px 0';
  description.textContent = 'Click the control. It will be outlined without activating it.';
  panel.append(description);
  const outline = document.createElement('div');
  outline.setAttribute('data-mail-merge-picker', '');
  Object.assign(outline.style, { position: 'fixed', pointerEvents: 'none',
    zIndex: '2147483646', border: '3px solid #ffae25', boxSizing: 'border-box' });
  const visible = element => {
    const box = element.getBoundingClientRect();
    const visibility = getComputedStyle(element).visibility;
    return box.width > 0 && box.height > 0 && visibility !== 'hidden' && visibility !== 'collapse';
  };
  // Hidden OWA composer templates must not force a fragile positional mapping.
  const unique = selector => { try { return Array.from(document.querySelectorAll(selector)).filter(visible).length === 1; } catch { return false; } };
  const cssSpec = element => {
    const tag = element.tagName.toLowerCase();
    // Prefer attributes that usually survive opening a fresh composer.
    for (const attr of ['aria-label', 'name', 'data-testid', 'autoid', 'data-tooltip', 'title', 'placeholder']) {
      const value = element.getAttribute(attr);
      if (value) {
        const selector = tag + '[' + attr + '=' + JSON.stringify(value) + ']';
        if (unique(selector)) return { selector };
      }
    }
    if (kind === 'summary') {
      // Gmail replaces "Recipients" with contact names and regenerates IDs
      // for each composer. Anchor its summary to a unique container class.
      const classes = Array.from(element.classList);
      // Gmail also uses aoD for Subject. Its recipient summary container
      // has tabindex; qualify that attribute before selecting the class.
      const gmailSummary = tag + '.aoD[tabindex]';
      if (classes.includes('aoD') && element.hasAttribute('tabindex') && unique(gmailSummary))
        return { selector: gmailSummary };
      for (const className of classes) {
        const selector = tag + '.' + CSS.escape(className);
        if (unique(selector)) return { selector };
      }
    }
    if (kind === 'button') {
      const text = (element.innerText || element.value || '').trim();
      const selector = tag + (element.getAttribute('role') ? '[role=' + JSON.stringify(element.getAttribute('role')) + ']' : '');
      if (text && text.length < 100 && Array.from(document.querySelectorAll(selector)).filter(e => visible(e) && (e.innerText || e.value || '').trim() === text).length === 1)
        return { selector, text };
    }
    if (element.id && unique('#' + CSS.escape(element.id))) return { selector: '#' + CSS.escape(element.id) };
    const pieces = [];
    let node = element;
    while (node && node.nodeType === 1) {
      const tagName = node.tagName.toLowerCase();
      const siblings = node.parentElement ? Array.from(node.parentElement.children).filter(e => e.tagName === node.tagName) : [node];
      pieces.unshift(tagName + (siblings.length > 1 ? ':nth-of-type(' + (siblings.indexOf(node) + 1) + ')' : ''));
      const selector = pieces.join(' > ');
      if (unique(selector)) return { selector };
      node = node.parentElement;
    }
    throw new Error('Cannot uniquely identify that control.');
  };
  const editableSelector = 'input:not([type=button]):not([type=submit]):not([type=hidden]),textarea,[contenteditable=true],[contenteditable=""]';
  const subjectSelector = 'input:not([type]),input[type=text],textarea';
  const editable = element => element.matches(editableSelector) || (element === document.body && document.designMode.toLowerCase() === 'on');
  const fromSpec = spec => {
    if (!spec) return null;
    const matches = Array.from(document.querySelectorAll(spec.selector)).filter(element =>
      visible(element) && (!('text' in spec) || (element.innerText || element.value || '').trim() === spec.text));
    return matches.length === 1 ? matches[0] : null;
  };
  const field = fromSpec(anchor);
  const otherField = fromSpec(excluded);
  const areaError = element => {
    if (!field) return editable(element) ? 'Select the recipient row around the typing box.' : '';
    if (!element.contains(field)) return 'This selection does not contain the mapped typing box.';
    if (otherField && element.contains(otherField)) return 'This area includes both To and CC. Keep the highlighted recipient row separate.';
    const otherEditors = Array.from(element.querySelectorAll(editableSelector)).filter(editor => {
      const box = editor.getBoundingClientRect();
      return editor !== field && !field.contains(editor) && !panel.contains(editor) &&
        box.width > 0 && box.height > 0 && getComputedStyle(editor).visibility !== 'hidden';
    });
    if (otherEditors.length || element === document.body || element === document.documentElement)
      return 'This area includes another typing box. Choose a smaller recipient row.';
    return '';
  };
  const recipientRow = () => {
    let row = field;
    while (row && row.parentElement && !editable(row.parentElement) && !areaError(row.parentElement))
      row = row.parentElement;
    return row;
  };
  const update = () => {
    if (!selected) return;
    const box = selected.getBoundingClientRect();
    Object.assign(outline.style, { left: box.left + 'px', top: box.top + 'px', width: box.width + 'px', height: box.height + 'px' });
    description.textContent = kind === 'area' && field
      ? 'The recipient row is highlighted. Choose Use selection to continue. Use Smaller area or Larger area if needed.'
      : 'Selected: ' + selected.tagName.toLowerCase() + '. Choose Use selection to continue.';
  };
  const makeButton = (label, action) => {
    const button = document.createElement('button');
    button.textContent = label;
    button.style.cssText = 'margin:4px 6px 0 0;padding:6px 8px;color:#14324d;background:white;border:0;border-radius:4px;cursor:pointer';
    button.addEventListener('click', action);
    panel.append(button);
  };
  makeButton('Use selection', () => {
    if (!selected) { description.textContent = 'Click a control first.'; return; }
    if (kind === 'subject' && !selected.matches(subjectSelector)) {
      description.textContent = 'Select the Subject typing box above the message body.';
      return;
    }
    if ((kind === 'field' || kind === 'body') && !editable(selected)) {
      description.textContent = 'Select the actual typing box or editable message body.';
      return;
    }
    if (kind === 'area') {
      const error = areaError(selected);
      if (error) { description.textContent = error; return; }
    }
    try {
      if (kind === 'area' && field) {
        // Anchor the row to its typing box so inserted recipient chips and
        // changing composer IDs do not shift a positional row selector.
        let levels = 0;
        for (let node = field; node !== selected; node = node.parentElement) levels++;
        state.result = { ...anchor, ancestor_levels: levels };
      } else {
        state.result = cssSpec(selected);
      }
      description.textContent = 'Selection saved. Continuing…';
    } catch (error) {
      description.textContent = 'Could not save this selection: ' + error.message + ' Try selecting the typing box again.';
    }
  });
  makeButton('Larger area', () => {
    if (selected && selected.parentElement) {
      if (kind === 'area') {
        const error = areaError(selected.parentElement);
        if (error) { description.textContent = error; return; }
      }
      selected = selected.parentElement; update();
    }
  });
  if (kind === 'area') makeButton('Smaller area', () => {
    if (!field || !selected || selected === field) return;
    let smaller = field;
    while (smaller.parentElement && smaller.parentElement !== selected) smaller = smaller.parentElement;
    selected = smaller; update();
  });
  makeButton('Cancel', () => { state.cancelled = true; });
  const capture = event => {
    if (panel.contains(event.target)) return;
    event.preventDefault(); event.stopPropagation(); event.stopImmediatePropagation();
    let element = event.target;
    if (!(element instanceof Element)) return;
    if (kind === 'button') element = element.closest('button,a,[role=button],input[type=button],input[type=submit]') || element;
    if (kind === 'summary') element = element.closest('[tabindex],button,[role=button]') || element;
    if (kind === 'field' || kind === 'body') {
      element = element.closest('input,textarea,[contenteditable=true],[contenteditable=""]') || element;
      if (kind === 'body' && document.designMode.toLowerCase() === 'on') element = document.body;
    }
    if (kind === 'subject') element = element.closest(subjectSelector) || element;
    if (kind === 'area' && field) {
      // Clicking the typing box or its label selects its row, not the editor.
      if (field.contains(element) || element.contains(field)) element = recipientRow();
      const error = areaError(element);
      if (error) { description.textContent = error; return; }
    }
    selected = element;
    update();
  };
  const keydown = event => { if (event.key === 'Escape') { event.preventDefault(); state.cancelled = true; } };
  // Webmail may focus editors or expand recipients on mouse-down, before
  // click. Capture the whole gesture so setup cannot change the target.
  const capturedEvents = ['pointerdown', 'mousedown', 'mouseup', 'click'];
  for (const name of capturedEvents) document.addEventListener(name, capture, true);
  document.addEventListener('keydown', keydown, true);
  window.addEventListener('scroll', update, true);
  state.cleanup = () => {
    for (const name of capturedEvents) document.removeEventListener(name, capture, true);
    document.removeEventListener('keydown', keydown, true);
    window.removeEventListener('scroll', update, true);
    panel.remove(); outline.remove();
    delete window.__mailMergePicker;
  };
  (document.body || document.documentElement).append(panel, outline);
  window.__mailMergePicker = state;
  if (kind === 'area' && field) { selected = recipientRow(); update(); }
}
