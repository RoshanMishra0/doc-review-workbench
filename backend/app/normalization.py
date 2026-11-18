"""Documented, deterministic normalization of raw text values.

Nothing here guesses. Each function either returns a normalized value or an
error message that explains why the value could not be read.

Documented rules (also in docs/TEMPLATE_GUIDE.md):

* Dates: ISO ``YYYY-MM-DD`` and dates with a month name (``05 Mar 2025``) are
  always accepted. Numeric dates are read with the source's chosen order
  (DMY, MDY or YMD). With order ``UNSPECIFIED`` a numeric date is only
  accepted when the day and month cannot be swapped. Two-digit years are
  rejected.
* Money: optional currency marker at the start or end, optional sign or
  parentheses for negatives, digits with optional comma grouping and a dot
  as the decimal separator. Parsed into ``Decimal``; floats are never used.
* Party names (suppliers): Unicode NFKC, case-folded, ``&`` becomes ``and``,
  punctuation becomes a space, whitespace collapsed, configured legal
  suffixes removed from the end, then the explicit alias table applied.
* Identifiers (invoice numbers): outer whitespace trimmed, internal
  whitespace removed, upper-cased. Leading zeros and punctuation are kept.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

DATE_ORDERS = ("DMY", "MDY", "YMD", "UNSPECIFIED")
DATE_ORDER_LABELS = {
    "DMY": "DD/MM/YYYY (day first)",
    "MDY": "MM/DD/YYYY (month first)",
    "YMD": "YYYY-MM-DD (year first)",
    "UNSPECIFIED": "Not specified (accept only unambiguous dates)",
}

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
_MONTH_LOOKUP: dict[str, int] = {}
for _i, _name in enumerate(MONTH_NAMES, start=1):
    _MONTH_LOOKUP[_name.lower()] = _i
    _MONTH_LOOKUP[_name[:3].lower()] = _i
_MONTH_LOOKUP["sept"] = 9


def describe_date(value: date) -> str:
    """Unambiguous human form, e.g. ``5 March 2025``."""
    return f"{value.day} {MONTH_NAMES[value.month - 1]} {value.year}"


def short_date(value: date) -> str:
    """Compact unambiguous form, e.g. ``05 Mar 2025``."""
    return f"{value.day:02d} {MONTH_NAMES[value.month - 1][:3]} {value.year}"


@dataclass(frozen=True)
class DateResult:
    value: date | None
    error: str | None = None
    ambiguous: bool = False

    @property
    def ok(self) -> bool:
        return self.value is not None


def _build_date(year: int, month: int, day: int, text: str, how: str) -> DateResult:
    if not 1 <= month <= 12:
        return DateResult(None, f"'{text}' has month {month}, which is not valid when read as {how}.")
    try:
        return DateResult(date(year, month, day))
    except ValueError:
        return DateResult(
            None,
            f"'{text}' is not a real calendar date: {MONTH_NAMES[month - 1]} {year} has no day {day}.",
        )


_ISO_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T]00:00(?::00(?:\.0+)?)?)?")
_DAY_MONTHNAME_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?[\s\-/.]+([A-Za-z]{3,9})\.?[\s\-/.,]+(\d{2,4})")
_MONTHNAME_DAY_RE = re.compile(r"([A-Za-z]{3,9})\.?[\s\-/.]+(\d{1,2})(?:st|nd|rd|th)?,?[\s\-/.]+(\d{2,4})")
_NUMERIC_RE = re.compile(r"(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{1,4})")


def parse_date(text: str | None, order: str) -> DateResult:
    """Parse a date using the source's declared order. Never guesses."""
    if order not in DATE_ORDERS:
        raise ValueError(f"unknown date order {order!r}")
    if text is None or not str(text).strip():
        return DateResult(None, "No date value.")
    s = " ".join(str(text).split())

    m = _ISO_RE.fullmatch(s)
    if m:
        return _build_date(int(m[1]), int(m[2]), int(m[3]), s, "YYYY-MM-DD")

    for pattern, day_group, month_group in ((_DAY_MONTHNAME_RE, 1, 2), (_MONTHNAME_DAY_RE, 2, 1)):
        m = pattern.fullmatch(s)
        if m:
            month = _MONTH_LOOKUP.get(m[month_group].lower())
            if month is None:
                return DateResult(None, f"'{s}' contains '{m[month_group]}', which is not a month name.")
            year_text = m[3]
            if len(year_text) != 4:
                return DateResult(None, f"'{s}' has a two-digit year; a four-digit year is required.")
            return _build_date(int(year_text), month, int(m[day_group]), s, "a month-name date")

    m = _NUMERIC_RE.fullmatch(s)
    if not m:
        return DateResult(None, f"'{s}' is not a recognised date.")
    a_text, b_text, c_text = m[1], m[2], m[3]
    a, b, c = int(a_text), int(b_text), int(c_text)

    if len(a_text) == 4:
        # Year first is the only reading of a four-digit leading group.
        return _build_date(a, b, c, s, "YYYY-MM-DD")
    if len(c_text) != 4:
        return DateResult(None, f"'{s}' has a two-digit or malformed year; a four-digit year is required.")
    if order == "YMD":
        return DateResult(None, f"'{s}' does not fit the chosen format YYYY-MM-DD.")
    if order == "DMY":
        return _build_date(c, b, a, s, DATE_ORDER_LABELS["DMY"])
    if order == "MDY":
        return _build_date(c, a, b, s, DATE_ORDER_LABELS["MDY"])

    # UNSPECIFIED: accept only when the reading is forced.
    if a == b:
        return _build_date(c, b, a, s, "a date with equal day and month")
    if a > 12 and b <= 12:
        return _build_date(c, b, a, s, "day first (the first number is above 12)")
    if b > 12 and a <= 12:
        return _build_date(c, a, b, s, "month first (the second number is above 12)")
    if a <= 12 and b <= 12:
        first = _build_date(c, b, a, s, "day first")
        second = _build_date(c, a, b, s, "month first")
        options = [describe_date(r.value) for r in (first, second) if r.value]
        return DateResult(
            None,
            f"'{s}' is ambiguous: it could be {' or '.join(options)}. Choose a date format for this source.",
            ambiguous=True,
        )
    return DateResult(None, f"'{s}' is not a valid date in any day/month order.")


def analyse_date_column(values: list[str]) -> dict[str, object]:
    """How many values each order can read. Used to warn before import."""
    present = [v for v in values if v and v.strip()]
    result: dict[str, object] = {"values": len(present)}
    for order in ("DMY", "MDY", "YMD"):
        result[order] = sum(1 for v in present if parse_date(v, order).ok)
    result["ambiguous_numeric"] = sum(1 for v in present if parse_date(v, "UNSPECIFIED").ambiguous)
    return result


# ---------------------------------------------------------------- money

@dataclass(frozen=True)
class MoneyResult:
    value: Decimal | None
    currency: str | None = None  # currency marker found inside the value, if any
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.value is not None


_PLAIN_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_GROUPED_NUMBER = re.compile(r"\d{1,3}(?:,\d{2,3})+(?:\.\d+)?")


def _strip_marker(s: str, markers: dict[str, str]) -> tuple[str, str | None]:
    upper = s.upper()
    for marker in sorted(markers, key=len, reverse=True):
        mu = marker.upper()
        if upper.startswith(mu):
            rest = s[len(marker):]
            if marker[-1].isalpha() and rest[:1].isalpha():
                continue
            return rest.strip(), markers[marker]
        if upper.endswith(mu):
            rest = s[: len(s) - len(marker)]
            if marker[0].isalpha() and rest[-1:].isalpha():
                continue
            return rest.strip(), markers[marker]
    return s, None


def parse_money(text: str | None, markers: dict[str, str]) -> MoneyResult:
    if text is None or not str(text).strip():
        return MoneyResult(None, None, "No amount value.")
    original = " ".join(str(text).split())
    s = unicodedata.normalize("NFKC", original).strip()
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
    if s.startswith("-"):
        negative, s = not negative, s[1:].strip()
    s, marker = _strip_marker(s, markers)
    if s.startswith("-"):
        negative, s = not negative, s[1:].strip()
    if _PLAIN_NUMBER.fullmatch(s):
        digits = s
    elif _GROUPED_NUMBER.fullmatch(s):
        digits = s.replace(",", "")
    else:
        return MoneyResult(None, marker, f"'{original}' is not a valid amount.")
    try:
        value = Decimal(digits)
    except InvalidOperation:  # pragma: no cover - regex already guarantees digits
        return MoneyResult(None, marker, f"'{original}' is not a valid amount.")
    return MoneyResult(-value if negative else value, marker, None)


def decimal_places(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def normalize_currency(text: str | None, markers: dict[str, str]) -> tuple[str | None, str | None]:
    if text is None or not str(text).strip():
        return None, "No currency value."
    s = str(text).strip()
    upper = s.upper()
    for marker, code in markers.items():
        if upper == marker.upper():
            return code, None
    if re.fullmatch(r"[A-Z]{3}", upper):
        return upper, None
    return None, f"'{s}' is not a recognised currency code."


def _group_digits(int_part: str, style: str) -> str:
    if len(int_part) <= 3:
        return int_part
    if style == "indian":
        head, tail = int_part[:-3], int_part[-3:]
        pairs = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        if head:
            pairs.insert(0, head)
        return ",".join(pairs + [tail])
    groups = []
    while len(int_part) > 3:
        groups.insert(0, int_part[-3:])
        int_part = int_part[:-3]
    groups.insert(0, int_part)
    return ",".join(groups)


def format_money(value: Decimal, code: str | None, symbols: dict[str, str],
                 minor_units: dict[str, int], grouping: dict[str, str]) -> str:
    places = minor_units.get(code or "", 2)
    shown = value
    if decimal_places(value) <= places:
        shown = value.quantize(Decimal(1).scaleb(-places)) if places else value.quantize(Decimal(1))
    sign = "-" if shown < 0 else ""
    text = f"{abs(shown):f}"
    int_part, _, frac = text.partition(".")
    grouped = _group_digits(int_part, grouping.get(code or "", "standard"))
    prefix = symbols.get(code or "") or (f"{code} " if code else "")
    return f"{sign}{prefix}{grouped}{'.' + frac if frac else ''}"


# ---------------------------------------------------------------- names and identifiers

def collapse_ws(text: str) -> str:
    return " ".join(text.split())


def _basic_name_form(text: str, *, casefold: bool, ampersand: bool, punctuation: bool) -> str:
    s = unicodedata.normalize("NFKC", text)
    if casefold:
        s = s.casefold()
    if ampersand:
        s = s.replace("&", " and ")
    if punctuation:
        s = re.sub(r"[^\w\s]", " ", s)
    return collapse_ws(s)


def party_key(text: str, *, casefold: bool = True, ampersand: bool = True, punctuation: bool = True,
              legal_suffixes: tuple[str, ...] = (), aliases: dict[str, str] | None = None) -> str:
    s = _basic_name_form(text, casefold=casefold, ampersand=ampersand, punctuation=punctuation)
    suffixes = [
        _basic_name_form(x, casefold=casefold, ampersand=ampersand, punctuation=punctuation)
        for x in legal_suffixes
    ]
    changed = True
    while changed:
        changed = False
        for suffix in sorted(suffixes, key=len, reverse=True):
            if suffix and s.endswith(" " + suffix):
                s = s[: -len(suffix) - 1].strip()
                changed = True
    if aliases:
        s = aliases.get(s, s)
    return s


def identifier_key(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).upper()


def normalize_header(text: str) -> str:
    """Column heading form used for alias suggestions (exact match only)."""
    s = unicodedata.normalize("NFKC", str(text)).casefold()
    s = s.replace("#", " no ").replace("&", " and ")
    s = re.sub(r"[^\w\s]", " ", s)
    s = s.replace("_", " ")
    return collapse_ws(s)
