"""Translation checks beyond msgfmt: every message translated (and not fuzzy), the same {placeholders}
and %s, the same markup tags, and the same leading/trailing newlines as the English.
Usage: python3 tests/check_po_quality.py po/xx.po [--allow-untranslated]"""
import re
import sys

import polib

TAGS = re.compile(r"</?[a-z]+[^>]*>")
HOLES = re.compile(r"\{[a-z_]*\}|%[sd]")


def problems(path, allow_untranslated=False):
    out = []
    po = polib.pofile(path)
    for e in po:
        if e.obsolete:
            continue
        where = f"{e.msgctxt + ' | ' if e.msgctxt else ''}{e.msgid[:70]!r}"
        if "fuzzy" in e.flags:
            out.append(f"fuzzy: {where}")
            continue
        strs = list(e.msgstr_plural.values()) if e.msgid_plural else [e.msgstr]
        if not all(strs):
            if not allow_untranslated:
                out.append(f"untranslated: {where}")
            continue
        for i, s in enumerate(strs):
            src = e.msgid if (not e.msgid_plural or i == 0) else e.msgid_plural
            if sorted(HOLES.findall(s)) != sorted(HOLES.findall(src)) and not (
                    e.msgid_plural and set(HOLES.findall(s)) <= set(HOLES.findall(e.msgid_plural))):
                out.append(f"placeholders {HOLES.findall(src)} vs {HOLES.findall(s)}: {where}")
            if sorted(TAGS.findall(s)) != sorted(TAGS.findall(src)):
                out.append(f"markup: {where}")
            if s.startswith("\n") != src.startswith("\n") or s.endswith("\n") != src.endswith("\n"):
                out.append(f"newlines: {where}")
    return out


if __name__ == "__main__":
    bad = problems(sys.argv[1], "--allow-untranslated" in sys.argv)
    for b in bad:
        print(b)
    print(f"{sys.argv[1]}: {'%d problems' % len(bad) if bad else 'ok'}")
    sys.exit(1 if bad else 0)
