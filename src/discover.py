"""Discover the structure of a Workday application page.

Instead of hardcoding expected fields per page, this module scans the live DOM
and returns what's actually there: sections, fields, widget types, labels,
and current values. Every other module can then fill based on what exists
rather than what it assumes.

    from src.discover import discover_page
    tree = discover_page(page)
    # tree = {
    #   "page_type": "my_information",
    #   "sections": [
    #     { "heading": "Contact Information",
    #       "fields": [
    #         { "aid": "formField-legalName--firstName",
    #           "label": "First Name",
    #           "widget": "text",
    #           "value": "Sambhav",
    #           "required": True },
    #         ...
    #       ] },
    #     ...
    #   ]
    # }
"""
from __future__ import annotations

from playwright.sync_api import Page


# ── JS that runs inside the browser to scan the entire page ─────────────────
# Returns a flat list of every formField container with its metadata.
# We do this in one evaluate() call to avoid hundreds of round-trips.

_SCAN_FIELDS_JS = r"""
() => {
  const results = [];

  // Find all elements with data-automation-id starting with "formField-"
  const fields = document.querySelectorAll('[data-automation-id^="formField-"]');

  for (const field of fields) {
    const aid = field.getAttribute('data-automation-id');

    // ── detect widget type ──
    let widget = 'unknown';
    let value = '';
    let options = [];

    const textInput = field.querySelector('input[type="text"], input[type="email"], input[type="tel"], input:not([type]), textarea');
    const radioInputs = field.querySelectorAll('input[type="radio"]');
    const checkbox = field.querySelector('input[type="checkbox"]');
    const fileInput = field.querySelector('input[type="file"]');
    const dropdownBtn = field.querySelector('button[aria-haspopup="listbox"]');
    const multiselectContainer = field.querySelector('[data-automation-id="multiselectInputContainer"]');
    const searchBox = field.querySelector('[data-automation-id="searchBox"]');
    const dateYear = field.querySelector('[data-automation-id="dateSectionYear-input"]');

    if (fileInput) {
      widget = 'file';
    } else if (dateYear) {
      widget = 'date';
      const monthEl = field.querySelector('[data-automation-id="dateSectionMonth-input"]');
      const dayEl = field.querySelector('[data-automation-id="dateSectionDay-input"]');
      const m = monthEl ? monthEl.value || '' : '';
      const d = dayEl ? dayEl.value || '' : '';
      const y = dateYear.value || '';
      value = [m, d, y].filter(Boolean).join('/');
    } else if (multiselectContainer || searchBox) {
      widget = 'multiselect';
      const chips = field.querySelectorAll('[data-automation-id="selectedItem"]');
      value = [...chips].map(c => c.innerText.trim()).join(', ');
    } else if (radioInputs.length > 0) {
      widget = 'radio';
      const checked = field.querySelector('input[type="radio"]:checked');
      if (checked) {
        const lbl = document.querySelector(`label[for="${checked.id}"]`);
        value = lbl ? lbl.innerText.trim() : checked.value;
      }
      // collect option labels
      for (const r of radioInputs) {
        const lbl = document.querySelector(`label[for="${r.id}"]`);
        if (lbl) options.push(lbl.innerText.trim());
      }
    } else if (checkbox) {
      widget = 'checkbox';
      value = checkbox.checked ? 'checked' : '';
    } else if (dropdownBtn) {
      widget = 'dropdown';
      value = dropdownBtn.innerText.trim();
      if (value === '—' || value === '--' || value === '') value = '';
    } else if (textInput) {
      widget = 'text';
      value = textInput.value || '';
    }

    // ── find label ──
    let label = '';
    // method 1: aria-label on the field or its input
    label = field.getAttribute('aria-label') || '';
    if (!label && textInput) label = textInput.getAttribute('aria-label') || '';
    if (!label && dropdownBtn) label = dropdownBtn.getAttribute('aria-label') || '';

    // method 2: walk up to find a <label> or <legend>
    if (!label) {
      let p = field;
      for (let d = 0; d < 6 && p; d++) {
        const l = p.querySelector('label, legend');
        if (l && l.innerText.trim() && !l.querySelector('input')) {
          label = l.innerText.trim();
          break;
        }
        p = p.parentElement;
      }
    }

    // method 3: preceding sibling or parent's label
    if (!label) {
      const prev = field.previousElementSibling;
      if (prev && (prev.tagName === 'LABEL' || prev.tagName === 'LEGEND')) {
        label = prev.innerText.trim();
      }
    }

    // ── required? ──
    const required = !!(
      field.querySelector('[aria-required="true"]') ||
      field.querySelector('abbr[title="required"], .required') ||
      field.querySelector('label .requiredAsterisk') ||
      field.closest('[data-automation-id]')?.querySelector('[aria-required="true"]')
    );

    // ── section context: find nearest heading above ──
    let section = '';
    let el = field;
    for (let d = 0; d < 15 && el; d++) {
      const heading = el.querySelector('h1, h2, h3, h4, [data-automation-id="sectionLabel"]');
      if (heading && heading !== field && !field.contains(heading)) {
        section = heading.innerText.trim();
        break;
      }
      // check previous siblings for headings
      let sib = el.previousElementSibling;
      while (sib) {
        if (['H1','H2','H3','H4'].includes(sib.tagName) ||
            sib.getAttribute('data-automation-id') === 'sectionLabel') {
          section = sib.innerText.trim();
          break;
        }
        const inner = sib.querySelector('h1, h2, h3, h4, [data-automation-id="sectionLabel"]');
        if (inner) { section = inner.innerText.trim(); break; }
        sib = sib.previousElementSibling;
      }
      if (section) break;
      el = el.parentElement;
    }

    // ── visibility ──
    const rect = field.getBoundingClientRect();
    const visible = rect.width > 0 && rect.height > 0;

    results.push({
      aid,
      label: label.replace(/\n/g, ' ').substring(0, 120),
      widget,
      value: value.substring(0, 200),
      options,
      required,
      section: section.replace(/\n/g, ' ').substring(0, 80),
      visible,
    });
  }

  return results;
}
"""

# ── JS to find all section headings on the page ────────────────────────────

_SCAN_SECTIONS_JS = r"""
() => {
  const sections = [];
  const seen = new Set();

  // Workday uses sectionLabel, plus standard headings inside form areas
  const candidates = document.querySelectorAll(
    '[data-automation-id="sectionLabel"], ' +
    'h2, h3, h4'
  );

  for (const h of candidates) {
    const text = h.innerText.trim().replace(/\n/g, ' ').substring(0, 80);
    if (!text || seen.has(text)) continue;
    // skip headings outside the main form area
    if (!h.closest('[data-automation-id="workArea"], [data-automation-id="wd-popup-content"], main, [role="main"]')) {
      // still include if it's near formFields
      const parent = h.closest('section, div, fieldset');
      if (!parent || !parent.querySelector('[data-automation-id^="formField-"]')) continue;
    }
    seen.add(text);
    const rect = h.getBoundingClientRect();
    sections.push({
      text,
      tag: h.tagName,
      y: rect.top,
      visible: rect.width > 0 && rect.height > 0,
    });
  }

  sections.sort((a, b) => a.y - b.y);
  return sections;
}
"""

# ── JS to detect page-level info ───────────────────────────────────────────

_PAGE_INFO_JS = r"""
() => {
  const info = {};

  // page title / job heading
  const header = document.querySelector('[data-automation-id="jobPostingHeader"]');
  info.jobTitle = header ? header.innerText.trim() : '';

  // progress steps (Workday shows them as a step indicator)
  const steps = document.querySelectorAll('[data-automation-id="progressItem"], [data-automation-id="stepItem"]');
  info.steps = [...steps].map(s => ({
    label: s.innerText.trim(),
    active: s.classList.contains('active') ||
            s.getAttribute('aria-current') === 'step' ||
            s.getAttribute('aria-current') === 'true',
  }));

  // current step label from the active progress item
  const activeStep = [...steps].find(s =>
    s.classList.contains('active') ||
    s.getAttribute('aria-current') === 'step' ||
    s.getAttribute('aria-current') === 'true'
  );
  info.currentStep = activeStep ? activeStep.innerText.trim() : '';

  // page footer buttons
  info.hasNext = !!document.querySelector('[data-automation-id="pageFooterNextButton"]');
  info.hasSubmit = !!document.querySelector('button[data-automation-id="bottom-navigation-next-button"]');
  info.hasPrev = !!document.querySelector('[data-automation-id="pageFooterPreviousButton"]');

  // error count
  info.errorCount = document.querySelectorAll('[data-automation-id="errorMessage"]').length;

  // question sets (for Application Questions pages)
  info.hasQuestionSet = !!document.querySelector('[data-automation-id="questionSet"]');

  // file input (resume upload)
  info.hasFileUpload = !!document.querySelector('input[type="file"]');

  // add buttons count
  info.addButtonCount = document.querySelectorAll('[data-automation-id="add-button"]').length;

  // popup/dialog overlay (blocks all interaction when present)
  const popupGlass = document.querySelector('[data-automation-id="wd-popup-glass"]');
  info.hasPopup = !!popupGlass;
  if (popupGlass) {
    const popupContent = popupGlass.querySelector('[data-automation-id="wd-popup-content"]') || popupGlass;
    const popupBtns = popupContent.querySelectorAll('button');
    info.popup = {
      text: popupContent.innerText.trim().substring(0, 300),
      buttons: [...popupBtns].map(b => ({
        text: b.innerText.trim(),
        aid: b.getAttribute('data-automation-id') || '',
      })),
    };
  } else {
    info.popup = null;
  }

  return info;
}
"""


# ── JS to scan add buttons and their section context ───────────────────────

_SCAN_ADD_BUTTONS_JS = r"""
() => {
  const results = [];
  const adds = document.querySelectorAll('[data-automation-id="add-button"]');

  for (const btn of adds) {
    const rect = btn.getBoundingClientRect();
    let section = "";
    let p = btn;
    for (let d = 0; d < 10 && p; d++) {
      const h = p.querySelector('h2, h3, h4, [data-automation-id="sectionLabel"]');
      if (h && h.innerText.trim()) { section = h.innerText.trim(); break; }
      const prev = p.previousElementSibling;
      if (prev) {
        const ph = prev.querySelector('h2, h3, h4') || (prev.matches('h2, h3, h4') ? prev : null);
        if (ph) { section = ph.innerText.trim(); break; }
      }
      p = p.parentElement;
    }
    results.push({
      section: section.substring(0, 80),
      y: rect.top,
      visible: rect.width > 0 && rect.height > 0,
    });
  }
  return results;
}
"""


def _group_by_section(fields: list[dict], sections: list[dict]) -> list[dict]:
    """Group flat field list into sections based on the section text each field
    reported. Fields with no section go under "(ungrouped)"."""
    section_map: dict[str, list[dict]] = {}
    order = []
    for f in fields:
        key = f.get("section") or "(ungrouped)"
        if key not in section_map:
            section_map[key] = []
            order.append(key)
        section_map[key].append(f)

    result = []
    for key in order:
        result.append({
            "heading": key,
            "fields": section_map[key],
        })
    return result


def discover_fields(page: Page) -> list[dict]:
    """Return a flat list of every form field on the current page.

    Each entry: {aid, label, widget, value, options, required, section, visible}
    """
    return page.evaluate(_SCAN_FIELDS_JS)


def discover_sections(page: Page) -> list[dict]:
    """Return section headings visible on the page.

    Each entry: {text, tag, y, visible}
    """
    return page.evaluate(_SCAN_SECTIONS_JS)


def discover_page(page: Page) -> dict:
    """Full page scan: page info + sections + fields grouped hierarchically.

    Returns:
        {
            "page_info": { jobTitle, steps, currentStep, hasNext, ... },
            "sections": [
                { "heading": "...", "fields": [ {aid, label, widget, ...}, ... ] },
                ...
            ],
            "field_count": int,
            "unfilled_count": int,
        }
    """
    page_info = page.evaluate(_PAGE_INFO_JS)
    raw_fields = page.evaluate(_SCAN_FIELDS_JS)
    raw_sections = page.evaluate(_SCAN_SECTIONS_JS)
    add_buttons = page.evaluate(_SCAN_ADD_BUTTONS_JS)

    # only keep visible fields
    visible_fields = [f for f in raw_fields if f.get("visible", True)]
    grouped = _group_by_section(visible_fields, raw_sections)

    # mark sections that have an Add button (expandable — fields appear after click)
    add_sections = {ab["section"] for ab in add_buttons if ab.get("visible")}
    sections_with_fields = {s["heading"] for s in grouped}
    # add empty expandable sections that aren't already in grouped
    for sec_name in add_sections:
        if sec_name and sec_name not in sections_with_fields:
            grouped.append({"heading": sec_name, "fields": [], "expandable": True})
    for sec in grouped:
        sec["expandable"] = sec.get("heading", "") in add_sections

    unfilled = sum(1 for f in visible_fields
                   if not f.get("value") and f.get("widget") != "file")

    return {
        "page_info": page_info,
        "sections": grouped,
        "add_buttons": [ab["section"] for ab in add_buttons if ab.get("visible")],
        "field_count": len(visible_fields),
        "unfilled_count": unfilled,
    }


def print_page_tree(page: Page):
    """Pretty-print the page structure for debugging."""
    from rich.console import Console
    from rich.tree import Tree

    console = Console()
    data = discover_page(page)
    info = data["page_info"]

    title = info.get("currentStep") or info.get("jobTitle") or "Workday Page"
    tree = Tree(f"[bold]{title}[/bold]  "
                f"({data['field_count']} fields, {data['unfilled_count']} unfilled)")

    if info.get("steps"):
        steps_branch = tree.add("[dim]Progress[/dim]")
        for s in info["steps"]:
            marker = "[bold green]>[/bold green] " if s.get("active") else "  "
            steps_branch.add(f"{marker}{s['label']}")

    for section in data["sections"]:
        expandable = " [dim](+ Add)[/dim]" if section.get("expandable") else ""
        sec_branch = tree.add(f"[cyan]{section['heading']}[/cyan]{expandable}")
        if not section["fields"] and section.get("expandable"):
            sec_branch.add("[dim]empty — click Add to create entries[/dim]")
        for f in section["fields"]:
            wtype = f["widget"]
            aid_short = f["aid"].replace("formField-", "")
            label = f["label"] or aid_short
            val = f["value"] or "[dim]—[/dim]"
            req = " [red]*[/red]" if f.get("required") else ""
            filled = "[green]" if f["value"] else "[yellow]"
            sec_branch.add(
                f"{filled}{label}{req}[/] [{wtype}] = {val}  "
                f"[dim]{f['aid']}[/dim]"
            )

    if info.get("hasPopup") and info.get("popup"):
        popup = info["popup"]
        pop_branch = tree.add("[bold red]POPUP BLOCKING PAGE[/bold red]")
        pop_branch.add(f"[dim]{popup['text'][:120]}[/dim]")
        for btn in popup.get("buttons", []):
            pop_branch.add(f"Button: [bold]{btn['text']}[/bold]  [dim]{btn['aid']}[/dim]")

    if info.get("errorCount", 0):
        tree.add(f"[red]{info['errorCount']} validation error(s)[/red]")

    nav = []
    if info.get("hasPrev"):
        nav.append("Previous")
    if info.get("hasNext"):
        nav.append("Next")
    if info.get("hasSubmit"):
        nav.append("[bold]Submit[/bold]")
    if nav:
        tree.add(f"[dim]Navigation: {' | '.join(nav)}[/dim]")

    console.print(tree)
    return data


if __name__ == "__main__":
    from playwright.sync_api import sync_playwright
    from . import browser

    with sync_playwright() as pw:
        b = browser.connect(pw)
        page = browser.find_workday_tab(b)
        if not page:
            print("No Workday tab open.")
        else:
            print_page_tree(page)
        b.close()
