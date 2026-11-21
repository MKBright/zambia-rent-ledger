"""CSV downloads. Amounts are plain numbers so a spreadsheet can add them up.

A cell that starts with =, +, or @ is prefixed with a quote so Excel
does not treat a tenant name as a formula.
"""

from __future__ import annotations

import csv
import io
import re
from decimal import Decimal

from app.copy import INCOME_CSV_NOTE
from app.ledger import money


def csv_safe(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    if text[:1] in "=+@":
        return "'" + text
    if text.startswith("-") and not re.fullmatch(r"-\d+(\.\d+)?", text):
        return "'" + text
    return text


def rows_to_csv(headers: list[str], rows: list[list]) -> str:
    buffer = io.StringIO()
    # A byte-order mark helps Excel open the file as UTF-8.
    buffer.write("\ufeff")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([csv_safe(cell) for cell in row])
    return buffer.getvalue()


def payments_csv(payments: list) -> str:
    rows = []
    for payment in payments:
        rows.append(
            [
                payment.receipt_no,
                payment.paid_on.isoformat(),
                payment.tenant.name,
                payment.tenant.phone,
                payment.tenant.unit.house.name,
                payment.tenant.unit.name,
                f"{payment.charge.year:04d}-{payment.charge.month:02d}",
                f"{money(payment.amount):.2f}",
                payment.method_label,
                payment.reference,
                payment.notes,
            ]
        )
    return rows_to_csv(
        [
            "receipt_no",
            "paid_on",
            "tenant",
            "phone",
            "property",
            "unit",
            "rent_month",
            "amount_zmw",
            "method",
            "reference",
            "notes",
        ],
        rows,
    )


def arrears_csv(rows: list[dict]) -> str:
    body = []
    for row in rows:
        tenant = row["tenant"]
        oldest = row["oldest"]
        body.append(
            [
                tenant.name,
                tenant.phone,
                tenant.unit.house.name,
                tenant.unit.name,
                f"{money(row['balance']):.2f}",
                oldest.isoformat() if oldest else "",
                f"{money(tenant.monthly_rent):.2f}",
            ]
        )
    return rows_to_csv(
        [
            "tenant",
            "phone",
            "property",
            "unit",
            "balance_zmw",
            "oldest_due_date",
            "monthly_rent_zmw",
        ],
        body,
    )


def income_csv(rows: list[dict]) -> str:
    body = []
    due = Decimal("0.00")
    recorded = Decimal("0.00")
    tax = Decimal("0.00")
    for row in rows:
        body.append(
            [
                row["key"],
                f"{money(row['due']):.2f}",
                f"{money(row['recorded']):.2f}",
                f"{money(row['tax']):.2f}",
                INCOME_CSV_NOTE,
            ]
        )
        due = money(due + row["due"])
        recorded = money(recorded + row["recorded"])
        tax = money(tax + row["tax"])
    body.append(
        [
            "year-to-date",
            f"{due:.2f}",
            f"{recorded:.2f}",
            f"{tax:.2f}",
            INCOME_CSV_NOTE,
        ]
    )
    return rows_to_csv(
        [
            "month",
            "rent_due_zmw",
            "rent_recorded_zmw",
            "estimated_tax_zmw",
            "note",
        ],
        body,
    )
