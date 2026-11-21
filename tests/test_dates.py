from datetime import date

import pytest

from acceptguard.dates import email_sent_date, parse_date_text
from acceptguard.models import Abstention

MARCH_2 = date(2026, 3, 2)


@pytest.mark.parametrize(
    ("date_text", "document", "expected"),
    [
        pytest.param("2026-03-02", "", MARCH_2, id="ISO is unambiguous"),
        pytest.param("02/03/2026", "Invoice date 15/03/2026", MARCH_2, id="DD/MM resolved by a day > 12"),
        pytest.param("03/02/2026", "Due 02/15/2026", MARCH_2, id="MM/DD resolved by a day > 12"),
        pytest.param("05/05/2026", "", date(2026, 5, 5), id="day equals month"),
        pytest.param("25/03/26", "", date(2026, 3, 25), id="two-digit year means 20YY"),
        pytest.param("2nd March 2026", "", MARCH_2, id="ordinal and full month name"),
        pytest.param("2 Mar 2026", "", MARCH_2, id="short month name"),
        pytest.param("02-Mar-2026", "", MARCH_2, id="hyphenated month name"),
        pytest.param("March 2, 2026", "", MARCH_2, id="month first with comma"),
        pytest.param("Sept 9 2026", "", date(2026, 9, 9), id="Sept abbreviation"),
    ],
)
def test_parse_date_text(date_text, document, expected):
    assert parse_date_text(date_text, document) == expected


@pytest.mark.parametrize(
    ("date_text", "document", "code"),
    [
        pytest.param("02/03/2026", "", "AMBIGUOUS_DATE", id="no context"),
        pytest.param("02/03/2026", "15/03/2026 and 03/15/2026", "AMBIGUOUS_DATE", id="conflicting context"),
        pytest.param("02/03/2026", "Invoice 15-03-2026", "AMBIGUOUS_DATE", id="context with other separator ignored"),
        pytest.param("12th March", "", "NO_YEAR", id="no year"),
        pytest.param("31/02/2026", "", "INVALID_DATE", id="31 February"),
        pytest.param("13/13/2026", "", "INVALID_DATE", id="both parts above 12"),
        pytest.param("2 Foo 2026", "", "UNPARSEABLE_DATE", id="unknown month word"),
        pytest.param("soon", "", "UNPARSEABLE_DATE", id="not a date"),
    ],
)
def test_parse_date_text_abstains(date_text, document, code):
    result = parse_date_text(date_text, document)
    assert isinstance(result, Abstention)
    assert result.code == code


def eml(date_header: str | None) -> bytes:
    header = f"Date: {date_header}\r\n" if date_header is not None else ""
    return f"From: a@b.in\r\nTo: c@d.in\r\nSubject: Defect\r\n{header}\r\nRejecting batch 7.\r\n".encode()


def test_email_date_converted_to_ist():
    # 22:30 UTC on 21 March is 04:00 IST on 22 March.
    assert email_sent_date(eml("Sat, 21 Mar 2026 22:30:00 +0000")) == date(2026, 3, 22)


@pytest.mark.parametrize(
    "header",
    [
        pytest.param(None, id="missing Date header"),
        pytest.param("Sat, 21 Mar 2026 22:30:00 -0000", id="no timezone"),
        pytest.param("yesterday-ish", id="garbage"),
    ],
)
def test_email_date_abstains(header):
    result = email_sent_date(eml(header))
    assert isinstance(result, Abstention)
    assert result.code == "NO_EMAIL_DATE"
