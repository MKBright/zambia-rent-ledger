"""Worked examples for balance, arrears, and the tax estimate.

These tests do not use the database. If a number here changes, the
rule in app/ledger.py changed with it.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from app.checks import parse_money
from app.exporting import csv_safe
from app.ledger import (
    LUSAKA,
    arrears_total,
    deadline_sentence,
    filing_deadline,
    format_kwacha,
    marginal_tax,
    month_balance,
    month_end,
    month_on,
    next_deadline,
    normalize_msisdn,
    oldest_unpaid,
    parse_month_param,
    percent_of,
    reminder_text,
    split_year_tax,
    tax_breakdown,
    whatsapp_url,
)


def test_part_payment_leaves_a_balance():
    assert month_balance(Decimal("900"), [Decimal("400")]) == Decimal("500.00")


def test_two_part_payments_can_settle_a_month():
    assert month_balance(Decimal("900.00"), [Decimal("400"), Decimal("500")]) == Decimal("0.00")


def test_overpayment_is_a_credit_on_that_month_only():
    assert month_balance(900, [Decimal("1000")]) == Decimal("-100.00")


def test_arrears_ignore_future_months_and_credits():
    rows = [
        (date(2026, 9, 1), Decimal("-20.00")),
        (date(2026, 10, 1), Decimal("500.00")),
        (date(2026, 11, 1), Decimal("0.00")),
        (date(2026, 12, 1), Decimal("900.00")),
    ]
    as_of = date(2026, 11, 21)
    assert arrears_total(rows, as_of) == Decimal("500.00")
    assert oldest_unpaid(rows, as_of) == date(2026, 10, 1)


def test_arrears_add_every_open_month():
    rows = [
        (date(2026, 10, 1), Decimal("500.00")),
        (date(2026, 11, 1), Decimal("200.00")),
    ]
    assert arrears_total(rows, date(2026, 11, 21)) == Decimal("700.00")
    assert oldest_unpaid(rows, date(2026, 11, 21)) == date(2026, 10, 1)


def test_first_30000_is_free():
    assert tax_breakdown(Decimal("0"))["total_tax"] == Decimal("0.00")
    assert tax_breakdown(Decimal("30000"))["total_tax"] == Decimal("0.00")
    assert tax_breakdown(Decimal("-5"))["total_tax"] == Decimal("0.00")


def test_part_above_30000_is_charged_at_4_percent():
    # K40,000 in the year: K30,000 at 0% and K10,000 at 4% = K400.
    breakdown = tax_breakdown(Decimal("40000"))
    assert breakdown["free_slice"] == Decimal("30000.00")
    assert breakdown["mid_slice"] == Decimal("10000.00")
    assert breakdown["top_slice"] == Decimal("0.00")
    assert breakdown["total_tax"] == Decimal("400.00")
    assert tax_breakdown(Decimal("30001"))["total_tax"] == Decimal("0.04")


def test_tax_rounds_to_the_ngwee():
    # 1.12 * 4% = 0.0448 -> K0.04.  1.13 * 4% = 0.0452 -> K0.05.
    assert tax_breakdown(Decimal("30001.12"))["total_tax"] == Decimal("0.04")
    assert tax_breakdown(Decimal("30001.13"))["total_tax"] == Decimal("0.05")


def test_middle_band_ends_at_800000():
    # (800000 - 30000) * 4% = 770000 * 0.04 = 30800.
    assert tax_breakdown(Decimal("800000"))["total_tax"] == Decimal("30800.00")
    assert tax_breakdown(Decimal("800000"))["top_tax"] == Decimal("0.00")


def test_top_band_is_16_percent_only_on_the_slice_above_800000():
    # K900,000: K30,800 from the middle band, plus K100,000 at 16% = K16,000.
    breakdown = tax_breakdown(Decimal("900000"))
    assert breakdown["mid_tax"] == Decimal("30800.00")
    assert breakdown["top_slice"] == Decimal("100000.00")
    assert breakdown["top_tax"] == Decimal("16000.00")
    assert breakdown["total_tax"] == Decimal("46800.00")
    assert tax_breakdown(Decimal("800001"))["total_tax"] == Decimal("30800.16")


def test_month_estimate_uses_the_free_band_first():
    # K29,000 already recorded, then K2,000. Only K1,000 is taxed, at 4%.
    assert marginal_tax(Decimal("29000"), Decimal("2000")) == Decimal("40.00")
    assert marginal_tax(Decimal("10000"), Decimal("0")) == Decimal("0.00")


def test_month_estimate_crosses_into_the_top_band():
    # K799,000 recorded, then K2,000.
    # K1,000 still in the 4% band (K40) and K1,000 in the 16% band (K160).
    assert marginal_tax(Decimal("799000"), Decimal("2000")) == Decimal("200.00")


def test_monthly_estimates_add_up_to_the_year():
    months = [Decimal("10000")] * 6
    shares = split_year_tax(months)
    assert sum(shares, Decimal("0.00")) == tax_breakdown(Decimal("60000"))["total_tax"]
    assert tax_breakdown(Decimal("60000"))["total_tax"] == Decimal("1200.00")


def test_returns_are_due_on_the_14th_of_the_next_month():
    assert filing_deadline(date(2026, 11, 1)) == date(2026, 12, 14)
    assert filing_deadline(date(2026, 12, 1)) == date(2027, 1, 14)
    assert next_deadline(date(2026, 11, 21)) == (date(2026, 11, 1), date(2026, 12, 14))
    assert next_deadline(date(2026, 11, 14)) == (date(2026, 10, 1), date(2026, 11, 14))
    assert next_deadline(date(2026, 1, 10)) == (date(2025, 12, 1), date(2026, 1, 14))
    assert next_deadline(date(2026, 1, 15)) == (date(2026, 1, 1), date(2026, 2, 14))
    assert deadline_sentence(date(2026, 11, 21)) == (
        "The November 2026 rental income return is due by 14 December 2026."
    )


def test_month_helpers():
    assert month_on(date(2026, 11, 21), 2) == date(2027, 1, 1)
    assert month_on(date(2026, 1, 10), -1) == date(2025, 12, 1)
    assert month_end(2026, 11) == date(2026, 11, 30)
    assert month_end(2024, 2) == date(2024, 2, 29)
    assert month_end(2026, 2) == date(2026, 2, 28)
    assert month_end(2026, 12) == date(2026, 12, 31)


def test_future_month_param_is_clamped():
    today = date(2026, 11, 21)
    assert parse_month_param("2026-06", today) == (2026, 6)
    assert parse_month_param("2027-01", today) == (2026, 11)
    assert parse_month_param("nope", today) == (2026, 11)
    assert parse_month_param(None, today) == (2026, 11)


def test_kwacha_format_and_percent():
    assert format_kwacha(Decimal("1250")) == "K1,250.00"
    assert format_kwacha(Decimal("-100")) == "-K100.00"
    assert format_kwacha(Decimal("30000"), cents=False) == "K30,000"
    assert percent_of(Decimal("25"), Decimal("100")) == 25
    assert percent_of(Decimal("150"), Decimal("100")) == 100
    assert percent_of(Decimal("10"), Decimal("0")) == 0


def test_parse_money_accepts_kwacha_inputs():
    assert parse_money("900")[0] == Decimal("900.00")
    assert parse_money("1,250.50")[0] == Decimal("1250.50")
    assert parse_money("K900")[0] == Decimal("900.00")
    assert parse_money("-5")[0] is None
    assert parse_money("12.345")[0] is None
    assert parse_money("abc")[0] is None


def test_whatsapp_number_and_reminder():
    assert normalize_msisdn("0971111001") == "260971111001"
    assert normalize_msisdn("+260 97 111 1001") == "260971111001"
    assert normalize_msisdn("971111001") == "260971111001"
    assert normalize_msisdn("123") is None
    assert whatsapp_url("123", "Hi") is None
    url = whatsapp_url(
        "0971111001",
        reminder_text(
            tenant_name="Thandiwe Phiri",
            landlord_name="Bwalya Chanda",
            unit_name="Bed 1",
            property_name="Sample: Kalingalinga Boarding House",
            balance=Decimal("500"),
            due_on=date(2026, 11, 1),
        ),
    )
    assert url is not None
    assert url.startswith("https://wa.me/260971111001?text=")
    text = unquote(url)
    assert "K500.00" in text
    assert "1 November 2026" in text
    assert "does not collect rent" in text


def test_lusaka_is_two_hours_ahead_of_utc():
    moment = datetime(2026, 6, 15, 12, 0, tzinfo=ZoneInfo("UTC"))
    assert moment.astimezone(LUSAKA).utcoffset() == timedelta(hours=2)


def test_csv_does_not_let_excel_run_a_formula():
    assert csv_safe("=1+1") == "'=1+1"
    assert csv_safe("+26097") == "'+26097"
    assert csv_safe("-cmd") == "'-cmd"
    assert csv_safe("-100.00") == "-100.00"
    assert csv_safe("900.00") == "900.00"
    assert csv_safe(None) == ""
