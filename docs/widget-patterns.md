# Workday Widget Patterns

Hard-won notes on interacting with Workday form widgets. These behaviors break naive
Playwright automation and informed the handlers in `src/widgets.py`, `src/discover.py`,
and `src/experience.py`. The RAG agent (`src/agent/rag.py`) indexes this file when present.

1. **Same widget, different DOM.** Country Phone Code uses `menuItem` (`<li>`), How Did
   You Hear uses `promptOption` (`<div>`) inside ReactVirtualized. Always check
   `promptOption`, `menuItem`, AND `role="option"`.

2. **Dropdown overlays block inputs.** The option list renders ON TOP of the search box,
   so `.click()` times out. Use JS-level `e.focus(); e.click()` to bypass hit-testing.

3. **Submit buttons have a `click_filter` overlay.** An invisible
   `<div data-automation-id="click_filter">` intercepts pointer events on every submit
   button. Click the overlay by its `aria-label`, not the `<button>`.

4. **Cascade dropdowns are mandatory.** Typing "LinkedIn" into How Did You Hear doesn't
   filter across levels. Click "Job Board" first, wait for sub-options, then click "LinkedIn".

5. **Check before filling.** Multiselects may already be set (e.g. Country Phone Code
   pre-filled). Check for existing chips and skip — re-filling wastes time and can break state.

6. **Fields vary per tenant.** Email field exists on some tenants but not others. "Have you
   worked here" appears on different pages per company. Never assume a fixed field set.

7. **Degree labels vary wildly.** "Master's", "Masters", "Master's Degree", "Master of
   Science" all mean the same thing. Use `DEGREE_VARIANTS` in `experience.py`.

8. **Field of study needs smart matching.** "Computer Science" may appear as "Computer and
   Information Science". Scan all visible options for the best match via `FIELD_VARIANTS`;
   don't blindly pick the first result.

9. **LinkedIn field doesn't always exist.** Some tenants have `formField-linkedInAccount`,
   others a generic Websites section (`formField-websiteAddress`) with an Add Another button.

10. **Always use `data-automation-id` first.** The Next button is always
    `pageFooterNextButton` even when labeled "Save and Continue". Text changes, IDs don't.

11. **Only click `promptLeafNode` in search results.** Each result renders 3 elements:
    `menuItem`, `promptOption`, `promptLeafNode`. Only `promptLeafNode` is the correct click
    target — `menuItem` may hit an already-selected chip, `promptOption` is a label duplicate.

12. **Hidden sections behind Add buttons.** The Websites section has no inputs by default —
    click Add first to reveal the URL field. Find the right Add button via the nearest heading.

13. **Clear must complete before refilling.** After deleting a multiselect chip, poll until
    chip count reaches 0 before filling again — stale DOM state causes mis-reads.

14. **Navigation popups block everything.** Clicking Back triggers a `wd-popup-glass` overlay
    ("Discard application?") that intercepts ALL pointer events. Scan the DOM for popups
    before any action.

15. **Back button is `pageFooterBackButton`, not `pageFooterPreviousButton`.** Discover,
    never assume.

16. **Discover first, act second.** Never predict what's on the page. Run a DOM scan first,
    then decide based on what's actually there — navigation, popups, fields, everything.

17. **Skills widget is free-text tag input.** Some multiselects have no predefined options —
    the "No Items." dropdown is just an empty suggestion list. Type the skill + Enter to add
    a chip; don't wait for dropdown options.

18. **`fill()` eats special characters.** Playwright's `fill("C/C++")` strips the `+`. Use
    `keyboard.type("C/C++", delay=50)` for values with special characters.

19. **Option selectors are global, not scoped.** `menuItem`/`promptOption`/etc. match ALL
    visible options on the page. Off-screen listboxes from previously filled multiselects can
    have `width > 0` at negative `top`. Filter by on-screen position
    (`r.top > 0 && r.top < window.innerHeight`).

20. **Always check existing state before adding.** Websites, skills, work entries — if the
    fill runs twice it doubles everything. Check existing chips/inputs before adding.

21. **Apply button triggers a method-choice popup.** After clicking Apply (`adventureButton`),
    a popup offers "Autofill with Resume" (`autofillWithResume`), "Apply Manually"
    (`applyManually`), "Use My Last Application" (`useMyLastApplication`). Click one before
    proceeding.

22. **Some tenants skip email verification.** After account creation the page may go straight
    to the form. Poll for form markers (`formField-legalName--firstName`,
    `pageFooterNextButton`) before assuming verification is needed.

23. **Don't hardcode widget types.** The same field (`formField-source`) can be a `dropdown`
    on one tenant and a `multiselect` on another. Use the widget type from
    `discover_fields()` to dispatch.

24. **"Select One" is a placeholder, not a value.** Dropdowns show "Select One", "—", or
    "--" when empty. Treat these as unfilled.

25. **Always run `discover_page()` before filling.** Scan what fields exist, their values,
    and whether a popup is blocking. Never call a filler blind.

26. **Record job info BEFORE submitting.** The post-submit URL
    (`/jobTasks/completed/application`) loses title, job_id, and original URL. Stash full
    job context from the Review page before clicking Submit.

27. **Skip already-filled fields.** If a field has a real value (not a placeholder), skip it
    — re-filling wastes time and can break state.

28. **School field varies: text vs multiselect.** `formField-schoolName` is a text input;
    `formField-school` is a searchable multiselect. School names may not match Workday's
    list — let the user supply `search_term` and `workday_name` per profile education entry.

29. **Never blindly pick the first dropdown option.** A wrong selection is worse than an
    empty field. Remove "first option" fallbacks — return a failure to be caught and fixed.

30. **Questions pages have text fields too.** Not just dropdowns — some tenants put free-text
    inputs (discharge explanation, desired compensation, start date) on the same page.

31. **Disability checkbox varies per tenant.** Some use a `disabilityStatus-CheckboxGroup`,
    others `formField-disabilityStatus` with checkboxes. Scope to the disability wrapper
    first, then fall back to the whole page.

32. **Capture job metadata from the ORIGINAL URL.** The URL mangles after Apply, signup, and
    navigation. By the Review page it's `.../apply/applyManually`. Capture title, job_id,
    tenant, and URL at the start before any navigation.

33. **Job ID regex must allow hyphens.** IDs like `2026-0013526` and `R-50862-1` have
    hyphens: `[A-Za-z0-9._-]+`.

34. **Don't hardcode question rules too narrowly.** "post-employment activities" won't match
    "non-compete". Use broad keyword rules; add to `RULES` in `questions.py` when a question
    falls through to the LLM unnecessarily.

35. **Sign-in page after account creation.** Some tenants redirect to sign-in. "verify" text
    → needs email verification; no verify text → account already existed, just sign in.

36. **Assessment pages block the pipeline.** Some tenants require an external assessment that
    can't be automated. Detect via "assessment" text; report `blocked` and move on.

37. **Unknown pages: try all fillers.** When the page type is unrecognized, try every filler
    (questions, disclosures, selfid, …) then click Next — don't stop.

38. **Hispanic/Latino and race fields vary.** Some tenants use `formField-hispanicOrLatino`
    (dropdown) and `formField-ethnicityMulti` (checkbox) instead of `formField-ethnicity`.

39. **Degree should be Science, not Arts (for CS/STEM).** Master's → MS, Bachelor's → BS.
    `DEGREE_VARIANTS` lists the correct variants in priority order.

40. **Filter non-degree options when picking a degree.** Option selectors are global, so
    school names and field-of-study chips leak in. Filter by degree keywords first.

41. **Verify education after filling.** Read back degree, field, and school after filling; fix
    any value that doesn't match the profile before clicking Next.

42. **Field of study: strict matching only.** No fuzzy overlap. Match only against an explicit
    `FIELD_VARIANTS` list. Case-insensitive, but no substring or word-overlap scoring.

43. **No blind first-option fallback anywhere.** Return failure if no real match is found.
    Never use ArrowDown+Enter as a fallback — a wrong selection beats no field is false.

44. **Certification/signature text fields.** "By typing my name, I certify…" fields take the
    user's full name from the profile.

45. **Batch mode.** Process multiple job URLs independently; log blockers to a report with
    title, URL, tenant, page, and reason. The pipeline never stops on one job's failure.

46. **Degree short codes need exact matching.** Some tenants use two-letter codes (BS, MS,
    BA) instead of full names. Use exact-set matching for codes — substring match causes
    false positives (e.g. "ma" inside "Transformers").

47. **"Work History" vs "Work Experience".** Section heading varies. Check for "Work
    Experience", "Work History", and "Work". Fill work history even if marked "(Optional)".

48. **"Continue Application" link.** When revisiting a partial application, the job page shows
    a "Continue Application" `<a>` instead of the Apply button (`adventureButton`). Check the
    link first.

49. **"Verify Password" ≠ email verification.** A broad `/verify/i` regex matches the "Verify
    Password" label. Only match phrases about email/account verification ("check your email",
    "verify your email", "verification email", …).

50. **Checkbox groups report empty values.** `discover_fields` reports checkbox groups with
    `value=""` even when a box is checked. Check actual state via `is_checked()`.

51. **Dropdown rules support pipe-separated fallbacks.** `questions.py` RULES can use
    `"val1|val2|val3"` for ordered fallbacks; the fill loop stops at the first match.

52. **Fill all sections, even optional ones.** Work history, education, skills — optional
    sections still strengthen the application.
