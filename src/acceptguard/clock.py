"""Deterministic MSMED date logic and s.43B(h) decision. No I/O, no model calls.

Rules: .claude/rules/legal-logic.md. Interpretations: interpretations.py.
"""
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import Literal

from acceptguard import interpretations as rules
from acceptguard.models import Abstention

Basis = Literal["invoice", "delivery", "acceptance", "unspecified"]


class Decision(StrEnum):
    ALLOWED = "ALLOWED"
    DISALLOWED = "DISALLOWED"
    PENDING = "PENDING"


@dataclass(frozen=True)
class Objection:
    recorded_on: date  # date of the written record; for oral objections, the date it was made
    written: bool  # decided in Python from the reported medium, never by the model
    removed_on: date | None = None


@dataclass(frozen=True)
class Agreement:
    days: int
    basis: Basis


@dataclass(frozen=True)
class DueDate:
    on: date
    assumptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Period:
    fy_end: date
    as_of: date


@dataclass(frozen=True)
class ClockInput:
    invoice_date: date
    delivery_date: date
    objections: tuple[Objection, ...] = ()
    agreement: Agreement | None = None
    ledger_credit_days: int | None = None
    payment_date: date | None = None


@dataclass(frozen=True)
class ClockResult:
    acceptance_day: date
    due_dates: tuple[date, ...]  # one date, or two when the agreement is missing and bounds were used
    decision: Decision
    assumptions: tuple[str, ...] = ()


def acceptance_day(delivery: date, objections: Sequence[Objection]) -> date | Abstention:
    """Day of acceptance or deemed acceptance under MSMED s.2(b) Explanation.

    Oral objections are ignored entirely, including their dates: only a written objection
    can move the clock, so only written records are checked for date order.
    """
    written = [o for o in objections if o.written]
    for objection in written:
        if objection.recorded_on < delivery:
            return Abstention("DATE_ORDER", f"objection {objection.recorded_on} precedes delivery {delivery}")
        if objection.removed_on is not None and objection.removed_on < objection.recorded_on:
            return Abstention("DATE_ORDER", f"removal {objection.removed_on} precedes objection {objection.recorded_on}")
    window_end = delivery + timedelta(days=rules.OBJECTION_WINDOW_DAYS)
    valid = [o for o in written if o.recorded_on <= window_end]
    if not valid:
        return delivery
    if len(valid) > 1:
        return Abstention("MULTIPLE_OBJECTIONS", f"{len(valid)} written objections inside the window")
    removed_on = valid[0].removed_on
    if removed_on is None:
        return Abstention("OBJECTION_UNRESOLVED", "written objection with no removal date in evidence")
    return removed_on


def contract_due_date(agreement: Agreement, *, acceptance: date, delivery: date, invoice_date: date) -> DueDate | Abstention:
    assumptions: tuple[str, ...] = ()
    basis = agreement.basis
    if basis == "unspecified":
        basis = rules.UNSPECIFIED_BASIS
        assumptions = ("CREDIT_BASIS_ASSUMED_INVOICE",)
    start = {"invoice": invoice_date, "delivery": delivery, "acceptance": acceptance}[basis]
    agreed = start + timedelta(days=agreement.days)
    if agreed < acceptance:
        return Abstention("AGREED_BEFORE_ACCEPTANCE", f"agreed date {agreed} precedes acceptance {acceptance}")
    cap = acceptance + timedelta(days=rules.MAX_AGREED_DAYS)
    return DueDate(min(agreed, cap), assumptions)


def statutory_due_date(acceptance: date) -> date:
    return acceptance + timedelta(days=rules.NO_AGREEMENT_PAYMENT_DAYS)


def disallowance(due: date, payment_date: date | None, period: Period) -> Decision:
    if payment_date is None:
        return Decision.DISALLOWED if period.as_of > due else Decision.PENDING
    if payment_date <= period.fy_end:
        return Decision.ALLOWED
    if payment_date <= due:
        return Decision.ALLOWED if rules.PAID_AFTER_YEAR_END_WITHIN_LIMIT_ALLOWED else Decision.DISALLOWED
    return Decision.DISALLOWED


def evaluate(inp: ClockInput, period: Period) -> ClockResult | Abstention:
    acceptance = acceptance_day(inp.delivery_date, inp.objections)
    if isinstance(acceptance, Abstention):
        return acceptance
    if inp.agreement is not None:
        due = contract_due_date(
            inp.agreement, acceptance=acceptance, delivery=inp.delivery_date, invoice_date=inp.invoice_date
        )
        if isinstance(due, Abstention):
            return due
        return ClockResult(acceptance, (due.on,), disallowance(due.on, inp.payment_date, period), due.assumptions)
    strict = statutory_due_date(acceptance)
    if inp.ledger_credit_days is None or inp.ledger_credit_days <= rules.NO_AGREEMENT_PAYMENT_DAYS:
        decision = disallowance(strict, inp.payment_date, period)
        return ClockResult(acceptance, (strict,), decision, ("ASSUMED_NO_WRITTEN_AGREEMENT",))
    return _bounded_by_ledger_terms(inp, period, acceptance, strict)


def _bounded_by_ledger_terms(inp: ClockInput, period: Period, acceptance: date, strict: date) -> ClockResult | Abstention:
    """Ledger claims more than 15 days but no contract was supplied: decide only if both readings agree."""
    generous = min(
        inp.invoice_date + timedelta(days=inp.ledger_credit_days),
        acceptance + timedelta(days=rules.MAX_AGREED_DAYS),
    )
    decisions = {disallowance(due, inp.payment_date, period) for due in (strict, generous)}
    if len(decisions) > 1:
        return Abstention("CONTRACT_NOT_PROVIDED", f"decision differs between due {strict} and {generous}")
    return ClockResult(acceptance, tuple(sorted({strict, generous})), decisions.pop(), ("CONTRACT_NOT_PROVIDED_BOUNDS_AGREE",))


def ledger_baseline(invoice_date: date, credit_days: int | None, payment_date: date | None, period: Period) -> ClockResult:
    """What ledger-based tools assume: acceptance on the invoice date."""
    days = rules.NO_AGREEMENT_PAYMENT_DAYS if credit_days is None else credit_days
    due = invoice_date + timedelta(days=min(days, rules.MAX_AGREED_DAYS))
    return ClockResult(invoice_date, (due,), disallowance(due, payment_date, period), ("LEDGER_BASELINE",))
