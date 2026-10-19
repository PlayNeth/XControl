"""Translations (gettext) and locale-aware number formatting.

Translations live in /usr/share/locale/<lang>/LC_MESSAGES/xcontrol.mo,
built from po/<lang>.po. Without one, everything falls back to English.
"""
import gettext
import locale

from .paths import LOCALEDIR

DOMAIN = "xcontrol"

try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error:
    pass


class Translator:
    """gettext plus number formatting, so text can be rendered either in the
    user's language or in plain English (for copying into bug reports)."""

    def __init__(self, translations, localized):
        self.t = translations
        self.localized = localized

    def gettext(self, msg):
        return self.t.gettext(msg)

    def ngettext(self, singular, plural, n):
        return self.t.ngettext(singular, plural, n)

    def num(self, value, digits=0):
        if self.localized:
            return locale.format_string(f"%.{digits}f", value)
        return f"{value:.{digits}f}"

    def hz(self, value):
        """Refresh rate with trailing zeros dropped: 60 Hz, 59.95 Hz."""
        text = self.num(value, 2)
        point = locale.localeconv()["decimal_point"] if self.localized else "."
        if point in text:
            text = text.rstrip("0").rstrip(point)
        return text + " Hz"


CURRENT = Translator(gettext.translation(DOMAIN, LOCALEDIR, fallback=True), True)
ENGLISH = Translator(gettext.NullTranslations(), False)

_ = CURRENT.gettext
ngettext = CURRENT.ngettext
num = CURRENT.num
hz = CURRENT.hz


def N_(msg):
    """Mark a string for translation without translating it yet."""
    return msg
