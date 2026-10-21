# Translations

The interface uses gettext; translations live in `po/`. Brazilian Portuguese,
Spanish, French, German and Russian are included, and the app follows your desktop
language (or the one set on the Date & Language page).

- Add a language: `make new-po LANG_CODE=es`, then translate `po/es.po`
  (Poedit works well).
- After changing strings in the code: `make update-po` merges them into every
  translation.
- `make` checks each translation with `msgfmt --check`, which also catches
  broken `{placeholders}`, and translates the app-menu entry.
- `python3 tests/check_po_quality.py po/xx.po` (needs python-polib) also checks
  that nothing is left untranslated or fuzzy and that markup and placeholders
  match the English.

**Copy** on the System page and **Copy details** in the display details copy in your language. The arrow next to
it has **Copy in English**, which is more useful in bug reports.
