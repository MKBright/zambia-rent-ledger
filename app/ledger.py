"""Money rules for the rent book.

This file does not talk to the database. The tests in tests/test_ledger.py
are the worked examples. Read those if a function is unclear.

Balance
    One month's balance is the rent due for that month minus the payments
    recorded against that month. K900 due and K400 recorded leaves K500.
    That K500 is still owed. Paying K1,000 against K900 leaves a K100
    credit on that month only. The credit is not moved onto another month.

Arrears
    Add up the months that are already due and still have a positive
    balance. A future month is not arrears yet. A credit does not cancel
    a different month.

Rental income tax estimate
    From 1 January 2026 the published bands apply to rent received in
    the calendar year (gross turnover, not profit):

    - 0% on the first K30,000
    - 4% on the part from K30,000 up to K800,000
    - 16% on the part above K800,000

    Example: K40,000 recorded in the year.
    The first K30,000 at 0% is K0. The next K10,000 at 4% is K400.

    A month's estimate is the extra tax caused by that month's receipts,
    so the free band is used first. It is not "this month times 4%".
    Returns are filed monthly, by the 14th of the next month.
    This is an estimate for planning. It is not a ZRA assessment.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import quote
from zoneinfo import ZoneInfo

from app.copy import APP_NAME

LUSAKA = ZoneInfo("Africa/Lusaka")
TWOPLACES = Decimal("0.01")

# Published rental-income bands from 1 January 2026.
TAX_FREE_LIMIT = Decimal("30000")
TAX_MID_LIMIT = Decimal("800000")
TAX_MID_RATE = Decimal("0.04")
TAX_TOP_RATE = Decimal("0.16")

PAYMENT_METHODS = {
    "cash": "Cash",
    "mtn_momo": "MTN MoMo",
    "airtel_money": "Airtel Money",
    "bank": "Bank",
}
ELECTRONIC_METHODS = {"mtn_momo", "airtel_money", "bank"}


def today_lusaka() -> date:
    """Today's date in Lusaka. Zambia does not change the clocks."""
    return datetime.now(LUSAKA).date()


def now_lusaka() -> datetime:
    """Current Lusaka time, stored without a timezone label."""
    return datetime.now(LUSAKA).replace(tzinfo=None)


def money(value: Decimal | int | str | None) -> Decimal:
    """Round kwacha to the ngwee (two decimal places), half up."""
    if value is None:
        value = 0
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("Use Decimal for kwacha, not float.")
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def format_kwacha(value: Decimal | int | str, cents: bool = True) -> str:
    """K1,250.00 or, for a published band, K30,000."""
    amount = money(value)
    sign = "-" if amount < 0 else ""
    quant = abs(amount)
    if cents:
        body = f"{quant:,.2f}"
    else:
        whole = int(quant.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        body = f"{whole:,}"
    return f"{sign}K{body}"


def format_date(day: date) -> str:
    return f"{day.day} {day.strftime('%B %Y')}"


def format_month(year: int, month: int) -> str:
    return date(year, month, 1).strftime("%B %Y")


def format_when(moment: datetime) -> str:
    return f"{moment.day} {moment.strftime('%B %Y')}, {moment.strftime('%H:%M')}"


def month_on(day: date, offset: int) -> date:
    """First day of the month `offset` months away from `day`'s month."""
    index = day.year * 12 + (day.month - 1) + offset
    year, month_index = divmod(index, 12)
    return date(year, month_index + 1, 1)


def month_end(year: int, month: int) -> date:
    return month_on(date(year, month, 1), 1) - timedelta(days=1)


def month_balance(amount_due: Decimal | int | str, payment_amounts: list) -> Decimal:
    """Rent due for one month, minus payments recorded against that month.

    A part payment leaves a positive balance (still owed). Paying more
    than the due amount leaves a negative balance (a credit on this
    month only).
    """
    paid = sum((money(amount) for amount in payment_amounts), Decimal("0.00"))
    return money(money(amount_due) - paid)


def arrears_total(monthly_balances: list[tuple[date, Decimal]], as_of: date) -> Decimal:
    """Sum of positive balances whose due date is on or before `as_of`.

    Future months are left out. A credit on one month does not reduce
    another month.
    """
    total = Decimal("0.00")
    for due_on, balance in monthly_balances:
        amount = money(balance)
        if due_on <= as_of and amount > 0:
            total = money(total + amount)
    return total


def oldest_unpaid(monthly_balances: list[tuple[date, Decimal]], as_of: date) -> date | None:
    """Earliest due date that still has a positive balance."""
    dates = [
        due_on
        for due_on, balance in monthly_balances
        if due_on <= as_of and money(balance) > 0
    ]
    if not dates:
        return None
    return min(dates)


def balance_phrase(balance: Decimal | int | str) -> str:
    amount = money(balance)
    if amount > 0:
        return f"Owes {format_kwacha(amount)}"
    if amount < 0:
        return f"Credit {format_kwacha(abs(amount))}"
    return "Settled"


def tax_breakdown(annual_turnover: Decimal | int | str) -> dict:
    """Split a year's recorded rent across the three published bands.

    Example: K40,000 in the year.
    K30,000 at 0% is K0, and the next K10,000 at 4% is K400.
    """
    turnover = money(annual_turnover)
    if turnover < 0:
        turnover = Decimal("0.00")
    free_slice = min(turnover, TAX_FREE_LIMIT)
    mid_room = TAX_MID_LIMIT - TAX_FREE_LIMIT
    mid_slice = min(max(turnover - TAX_FREE_LIMIT, Decimal("0.00")), mid_room)
    top_slice = max(turnover - TAX_MID_LIMIT, Decimal("0.00"))
    free_slice = money(free_slice)
    mid_slice = money(mid_slice)
    top_slice = money(top_slice)
    free_tax = Decimal("0.00")
    mid_tax = money(mid_slice * TAX_MID_RATE)
    top_tax = money(top_slice * TAX_TOP_RATE)
    return {
        "turnover": turnover,
        "free_slice": free_slice,
        "mid_slice": mid_slice,
        "top_slice": top_slice,
        "free_tax": free_tax,
        "mid_tax": mid_tax,
        "top_tax": top_tax,
        "total_tax": money(free_tax + mid_tax + top_tax),
        "free_limit": TAX_FREE_LIMIT,
        "mid_limit": TAX_MID_LIMIT,
    }


def marginal_tax(ytd_before: Decimal | int | str, month_receipts: Decimal | int | str) -> Decimal:
    """Extra estimated tax from one month's receipts.

    K29,000 already recorded, then K2,000 this month, reaches K31,000.
    Only the K1,000 above K30,000 is charged, at 4%, so the month is K40.
    """
    before = tax_breakdown(ytd_before)["total_tax"]
    after = tax_breakdown(money(ytd_before) + money(month_receipts))["total_tax"]
    return money(after - before)


def split_year_tax(monthly_receipts: list) -> list[Decimal]:
    """Estimated tax for each month, January first. The pieces add up to the year."""
    running = Decimal("0.00")
    shares: list[Decimal] = []
    for amount in monthly_receipts:
        shares.append(marginal_tax(running, amount))
        running = money(running + money(amount))
    return shares


def filing_deadline(period: date) -> date:
    """The return for `period`'s month is due on the 14th of the next month."""
    nxt = month_on(period, 1)
    return date(nxt.year, nxt.month, 14)


def next_deadline(today: date) -> tuple[date, date]:
    """Return (the month the return covers, the due date).

    On the 14th the deadline is still today, and it covers the previous
    month. After the 14th the next deadline is the 14th of next month
    and it covers this month.
    """
    if today.day <= 14:
        period = month_on(today, -1)
        due = date(today.year, today.month, 14)
        return period, due
    period = date(today.year, today.month, 1)
    return period, filing_deadline(period)


def deadline_sentence(today: date) -> str:
    period, due = next_deadline(today)
    return (
        f"The {format_month(period.year, period.month)} rental income return "
        f"is due by {format_date(due)}."
    )


def percent_of(part: Decimal | int | str, whole: Decimal | int | str) -> int:
    """Whole-number percent, capped at 100, or 0 when the total is 0."""
    amount = money(part)
    total = money(whole)
    if total <= 0:
        return 0
    pct = int((amount / total) * 100)
    if pct < 0:
        return 0
    if pct > 100:
        return 100
    return pct


def parse_month_param(raw: str | None, today: date) -> tuple[int, int]:
    """Read a `YYYY-MM` value. A future month becomes the current month."""
    if raw and re.fullmatch(r"\d{4}-\d{2}", raw):
        year = int(raw[:4])
        month = int(raw[5:7])
        if 1 <= month <= 12 and 2000 <= year <= 2100:
            if (year, month) > (today.year, today.month):
                return today.year, today.month
            return year, month
    return today.year, today.month


def normalize_msisdn(phone: str | None) -> str | None:
    """Turn a Zambian mobile number into the digits WhatsApp expects.

    0971111001, +260971111001, and 971111001 all become 260971111001.
    """
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("260") and len(digits) == 12:
        return digits
    if digits.startswith("0") and len(digits) == 10:
        return "260" + digits[1:]
    if len(digits) == 9:
        return "260" + digits
    return None


def whatsapp_url(phone: str | None, text: str) -> str | None:
    number = normalize_msisdn(phone)
    if number is None:
        return None
    return f"https://wa.me/{number}?text={quote(text)}"


def reminder_text(
    *,
    tenant_name: str,
    landlord_name: str,
    unit_name: str,
    property_name: str,
    balance: Decimal | int | str,
    due_on: date,
) -> str:
    """WhatsApp reminder. The landlord sends it. The app does not."""
    return (
        f"Hello {tenant_name}, this is a reminder from {landlord_name} "
        f"about rent for {unit_name} at {property_name}. "
        f"Amount still owed: {format_kwacha(balance)}. "
        f"Due date: {format_date(due_on)}. "
        f"Please pay the landlord directly by cash, MTN MoMo, Airtel Money, or bank, "
        f"then send the reference so it can be written in the book. "
        f"This is only a reminder. {APP_NAME} does not collect rent."
    )
