from datetime import date, timedelta

import pytest

from acceptguard.clock import (
    Abstention,
    Agreement,
    ClockInput,
    ClockResult,
    Decision,
    Objection,
    Period,
    acceptance_day,
    contract_due_date,
    disallowance,
    evaluate,
    ledger_baseline,
)

DELIVERY = date(2026, 3, 2)
PERIOD = Period(fy_end=date(2026, 3, 31), as_of=date(2026, 10, 1))


def day(n: int) -> date:
    return DELIVERY + timedelta(days=n)


def written(recorded: int, removed: int | None = None) -> Objection:
    return Objection(day(recorded), written=True, removed_on=None if removed is None else day(removed))


def oral(recorded: int, removed: int | None = None) -> Objection:
    return Objection(day(recorded), written=False, removed_on=None if removed is None else day(removed))


# --- acceptance day (MSMED s.2(b)) ---------------------------------------------------------


@pytest.mark.parametrize(
    ("objections", "expected"),
    [
        pytest.param((), day(0), id="no objection: deemed acceptance on delivery"),
        pytest.param((written(11, 30),), day(30), id="written day 11 removed day 30"),
        pytest.param((written(15, 20),), day(20), id="written on day 15 is inside the window"),
        pytest.param((written(0, 5),), day(5), id="written on delivery day is inside the window"),
        pytest.param((written(16, 20),), day(0), id="written on day 16 is outside the window"),
        pytest.param((oral(10, 20),), day(0), id="oral objection never moves the clock"),
        pytest.param((oral(10), written(18, 25)), day(0), id="oral day 10 then written day 18"),
    ],
)
def test_acceptance_day(objections, expected):
    assert acceptance_day(DELIVERY, objections) == expected


@pytest.mark.parametrize(
    ("objections", "code"),
    [
        pytest.param((written(5),), "OBJECTION_UNRESOLVED", id="valid objection, no removal"),
        pytest.param((written(-1, 5),), "DATE_ORDER", id="objection before delivery"),
        pytest.param((written(5, 3),), "DATE_ORDER", id="removal before objection"),
        pytest.param((written(3, 8), written(6, 12)), "MULTIPLE_OBJECTIONS", id="two valid objections"),
    ],
)
def test_acceptance_day_abstains(objections, code):
    result = acceptance_day(DELIVERY, objections)
    assert isinstance(result, Abstention)
    assert result.code == code


# --- due date under a written agreement (MSMED s.15) ---------------------------------------


def test_contract_due_from_delivery():
    due = contract_due_date(Agreement(30, "delivery"), acceptance=day(0), delivery=day(0), invoice_date=day(0))
    assert due.on == day(30)
    assert due.assumptions == ()


def test_contract_capped_at_45_days_from_acceptance():
    due = contract_due_date(Agreement(60, "acceptance"), acceptance=day(0), delivery=day(0), invoice_date=day(0))
    assert due.on == day(45)


def test_contract_unspecified_basis_counts_from_invoice():
    due = contract_due_date(Agreement(30, "unspecified"), acceptance=day(0), delivery=day(0), invoice_date=day(-2))
    assert due.on == day(28)
    assert "CREDIT_BASIS_ASSUMED_INVOICE" in due.assumptions


def test_contract_agreed_before_acceptance_abstains():
    result = contract_due_date(Agreement(10, "invoice"), acceptance=day(30), delivery=day(0), invoice_date=day(0))
    assert isinstance(result, Abstention)
    assert result.code == "AGREED_BEFORE_ACCEPTANCE"


# --- disallowance for the year -------------------------------------------------------------


@pytest.mark.parametrize(
    ("due", "paid", "as_of", "expected"),
    [
        pytest.param(date(2026, 1, 17), date(2026, 3, 20), PERIOD.as_of, Decision.ALLOWED, id="late but paid in year"),
        pytest.param(date(2026, 4, 4), date(2026, 4, 4), PERIOD.as_of, Decision.ALLOWED, id="after year-end, on due"),
        pytest.param(date(2026, 4, 4), date(2026, 4, 5), PERIOD.as_of, Decision.DISALLOWED, id="after year-end, late"),
        pytest.param(date(2026, 4, 4), None, PERIOD.as_of, Decision.DISALLOWED, id="unpaid past due"),
        pytest.param(date(2026, 4, 4), None, date(2026, 4, 4), Decision.PENDING, id="unpaid, as-of equals due"),
    ],
)
def test_disallowance(due, paid, as_of, expected):
    assert disallowance(due, paid, Period(PERIOD.fy_end, as_of)) == expected


# --- full evaluation -----------------------------------------------------------------------


def test_no_contract_and_short_ledger_terms_uses_15_days():
    result = evaluate(ClockInput(invoice_date=day(0), delivery_date=day(0), payment_date=day(10)), PERIOD)
    assert isinstance(result, ClockResult)
    assert result.due_dates == (day(15),)
    assert "ASSUMED_NO_WRITTEN_AGREEMENT" in result.assumptions


def test_missing_contract_reported_when_both_bounds_agree():
    inp = ClockInput(
        invoice_date=date(2026, 3, 20),
        delivery_date=date(2026, 3, 20),
        ledger_credit_days=30,
        payment_date=date(2026, 5, 30),
    )
    result = evaluate(inp, PERIOD)
    assert isinstance(result, ClockResult)
    assert result.decision == Decision.DISALLOWED
    assert result.due_dates == (date(2026, 4, 4), date(2026, 4, 19))


def test_missing_contract_abstains_when_bounds_disagree():
    inp = ClockInput(
        invoice_date=date(2026, 3, 20),
        delivery_date=date(2026, 3, 20),
        ledger_credit_days=30,
        payment_date=date(2026, 4, 10),
    )
    result = evaluate(inp, PERIOD)
    assert isinstance(result, Abstention)
    assert result.code == "CONTRACT_NOT_PROVIDED"


def test_demo_case_written_objection_removed_flips_outcome():
    invoice = date(2026, 3, 10)
    objection = Objection(date(2026, 3, 21), written=True, removed_on=date(2026, 4, 9))
    paid = date(2026, 4, 20)
    evidence = evaluate(ClockInput(invoice, invoice, (objection,), payment_date=paid), PERIOD)
    baseline = ledger_baseline(invoice, None, paid, PERIOD)
    assert isinstance(evidence, ClockResult)
    assert evidence.acceptance_day == date(2026, 4, 9)
    assert evidence.decision == Decision.ALLOWED
    assert baseline.decision == Decision.DISALLOWED


def test_ledger_baseline_zero_credit_days_is_not_treated_as_missing():
    result = ledger_baseline(day(0), 0, None, PERIOD)
    assert result.due_dates == (day(0),)
