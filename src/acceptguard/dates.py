"""Explicit date parsing. No dateutil: every ambiguity is an abstention, never a guess."""
import re
from datetime import date
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from typing import Literal
from zoneinfo import ZoneInfo

from acceptguard.models import Abstention

IST = ZoneInfo("Asia/Kolkata")
MONTHS = ("january", "february", "march", "april", "may", "june",
          "july", "august", "september", "october", "november", "december")
MAX_MONTH = 12

ISO_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
NUMERIC_RE = re.compile(r"(\d{1,2})([./-])(\d{1,2})\2(\d{2}|\d{4})")
NAMED_DMY_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?[\s.\-/,]*([A-Za-z]{3,9})\.?(?:[\s.\-/,']+(\d{2}|\d{4}))?")
NAMED_MDY_RE = re.compile(r"([A-Za-z]{3,9})\.?\s*(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{2}|\d{4}))?")

Convention = Literal["dmy", "mdy", "conflict"] | None


def parse_date_text(date_text: str, document_text: str) -> date | Abstention:
    """Parse a date exactly as written. `document_text` resolves DD/MM vs MM/DD ambiguity."""
    text = date_text.strip()
    if match := ISO_RE.fullmatch(text):
        year, month, day = (int(g) for g in match.groups())
        return _build(year, month, day, text)
    if match := NUMERIC_RE.fullmatch(text):
        return _parse_numeric(match, document_text or "")
    if match := NAMED_DMY_RE.fullmatch(text):
        day, month_word, year = match.groups()
        return _parse_named(int(day), month_word, year, text)
    if match := NAMED_MDY_RE.fullmatch(text):
        month_word, day, year = match.groups()
        return _parse_named(int(day), month_word, year, text)
    return Abstention("UNPARSEABLE_DATE", text)


def _parse_numeric(match: re.Match[str], document_text: str) -> date | Abstention:
    first, separator, second, year_text = match.groups()
    a, b, year = int(first), int(second), _expand_year(year_text)
    if a > MAX_MONTH and b > MAX_MONTH:
        return Abstention("INVALID_DATE", match.group(0))
    if a > MAX_MONTH or a == b:
        return _build(year, b, a, match.group(0))
    if b > MAX_MONTH:
        return _build(year, a, b, match.group(0))
    convention = document_convention(document_text, separator)
    if convention == "dmy":
        return _build(year, b, a, match.group(0))
    if convention == "mdy":
        return _build(year, a, b, match.group(0))
    return Abstention("AMBIGUOUS_DATE", f"{match.group(0)}: document convention is {convention or 'unknown'}")


def document_convention(document_text: str, separator: str) -> Convention:
    """Infer DD/MM or MM/DD from other numeric dates with the same separator."""
    pattern = re.compile(rf"\b(\d{{1,2}}){re.escape(separator)}(\d{{1,2}}){re.escape(separator)}(?:\d{{4}}|\d{{2}})\b")
    seen: set[str] = set()
    for first, second in pattern.findall(document_text):
        a, b = int(first), int(second)
        if a > MAX_MONTH >= b:
            seen.add("dmy")
        elif b > MAX_MONTH >= a:
            seen.add("mdy")
    if len(seen) > 1:
        return "conflict"
    return seen.pop() if seen else None


def _parse_named(day: int, month_word: str, year_text: str | None, original: str) -> date | Abstention:
    month = _month_number(month_word)
    if month is None:
        return Abstention("UNPARSEABLE_DATE", original)
    if year_text is None:
        return Abstention("NO_YEAR", original)
    return _build(_expand_year(year_text), month, day, original)


def _month_number(word: str) -> int | None:
    lowered = word.casefold()
    if lowered == "sept":
        return 9
    for number, name in enumerate(MONTHS, start=1):
        if len(lowered) >= 3 and name.startswith(lowered):
            return number
    return None


def _expand_year(year_text: str) -> int:
    year = int(year_text)
    return 2000 + year if len(year_text) == 2 else year


def _build(year: int, month: int, day: int, original: str) -> date | Abstention:
    try:
        return date(year, month, day)
    except ValueError:
        return Abstention("INVALID_DATE", original)


def email_sent_date(raw: bytes) -> date | Abstention:
    """Sent date of the top message, from the Date header, as an IST calendar date."""
    header = BytesParser(policy=policy.default).parsebytes(raw)["Date"]
    if header is None:
        return Abstention("NO_EMAIL_DATE", "missing Date header")
    try:
        sent = parsedate_to_datetime(str(header))
    except (TypeError, ValueError):
        return Abstention("NO_EMAIL_DATE", f"unparseable Date header: {header}")
    if sent.tzinfo is None:
        return Abstention("NO_EMAIL_DATE", "Date header has no timezone")
    return sent.astimezone(IST).date()
