"""Inspect the live Workday application page: dump every form field with its
Workday data-automation-id, visible label, type, and current value.

This is a READ-ONLY calibration step. It fills nothing — it just shows us the
real DOM so we can write fill logic that matches this tenant. Run it against the
open Adobe application page after launching Chrome (see README).

Usage:
    ./venv/bin/python -m src.inspect_page
"""
from __future__ import annotations

import json
from playwright.sync_api import sync_playwright

from . import browser

# JS that walks the page and describes each fillable control. Workday tags
# controls with data-automation-id; labels live in associated <label> or aria.
SCAN_JS = r"""
() => {
  const out = [];
  const seen = new Set();

  function labelFor(el) {
    // aria-label / aria-labelledby first
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
    const lbid = el.getAttribute('aria-labelledby');
    if (lbid) {
      const parts = lbid.split(/\s+/).map(id => {
        const n = document.getElementById(id); return n ? n.innerText.trim() : '';
      }).filter(Boolean);
      if (parts.length) return parts.join(' ');
    }
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) return l.innerText.trim();
    }
    // climb to a labelled group
    let p = el.closest('[role="group"],[data-automation-id]');
    let depth = 0;
    while (p && depth < 4) {
      const lab = p.querySelector('label, legend');
      if (lab && lab.innerText.trim()) return lab.innerText.trim();
      p = p.parentElement; depth++;
    }
    return '';
  }

  // native inputs/selects/textareas + Workday button-style dropdowns
  const sel = 'input, select, textarea, '
            + '[data-automation-id][role="button"], '
            + 'button[aria-haspopup="listbox"], '
            + '[data-automation-id*="DropDown"], [data-automation-id*="dropdown"]';
  document.querySelectorAll(sel).forEach(el => {
    const rect = el.getBoundingClientRect();
    const visible = rect.width > 0 && rect.height > 0;
    const aid = el.getAttribute('data-automation-id')
             || (el.closest('[data-automation-id]')?.getAttribute('data-automation-id')) || '';
    const key = aid + '|' + (el.id || '') + '|' + el.tagName + '|' + (el.type||'');
    if (seen.has(key)) return; seen.add(key);
    out.push({
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || '',
      role: el.getAttribute('role') || '',
      automation_id: aid,
      id: el.id || '',
      name: el.getAttribute('name') || '',
      label: labelFor(el),
      placeholder: el.getAttribute('placeholder') || '',
      value: (el.value !== undefined ? el.value : (el.innerText||'').trim()).slice(0,80),
      required: el.getAttribute('aria-required') === 'true' || el.required === true,
      visible,
    });
  });
  return out;
}
"""


def main():
    with sync_playwright() as pw:
        b = browser.connect(pw)
        page = browser.find_workday_tab(b)
        if not page:
            print("No Workday tab open. Navigate to the application page in Chrome first.")
            return
        print(f"Inspecting: {page.url}\n")
        fields = page.evaluate(SCAN_JS)
        visible = [f for f in fields if f["visible"]]
        print(f"{len(visible)} visible fields ({len(fields)} total):\n")
        for f in visible:
            req = " *REQUIRED" if f["required"] else ""
            kind = f["role"] or f["type"] or f["tag"]
            print(f"- [{kind}] aid={f['automation_id'] or '—'}{req}")
            print(f"    label : {f['label'] or '(none)'}")
            if f["value"]:
                print(f"    value : {f['value']}")
        # also dump raw json for programmatic mapping later
        with open("/tmp/workday_fields.json", "w") as fh:
            json.dump(fields, fh, indent=2)
        print("\nRaw dump -> /tmp/workday_fields.json")
        b.close()


if __name__ == "__main__":
    main()
