"""Read and write the rent book.

The maths lives in ledger.py. This file loads rows, fills in a missing
month, and saves a payment the landlord already received.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app import db
from app.ledger import (
    ELECTRONIC_METHODS,
    PAYMENT_METHODS,
    format_month,
    marginal_tax,
    money,
    month_on,
    now_lusaka,
    reminder_text,
    split_year_tax,
    tax_breakdown,
    today_lusaka,
    whatsapp_url,
)
from app.models import Landlord, Payment, Property, RentCharge, Tenant, Unit


def ensure_charges(tenant: Tenant, through: date | None = None) -> list[RentCharge]:
    """Make sure each month from move-in through `through` has a rent row.

    Months after move-out are not created. Existing rows are left alone,
    so a special amount for one month is not overwritten when a page loads.

    A new month appears on its own. Nothing else has to run at midnight.
    """
    through = through or today_lusaka()
    if tenant.move_out_date is not None and tenant.move_out_date < through:
        through = tenant.move_out_date
    if through < tenant.move_in_date:
        return []

    end = (through.year, through.month)
    existing = {
        (charge.year, charge.month)
        for charge in RentCharge.query.filter_by(tenant_id=tenant.id).all()
    }
    created: list[RentCharge] = []
    cursor = date(tenant.move_in_date.year, tenant.move_in_date.month, 1)
    while (cursor.year, cursor.month) <= end:
        key = (cursor.year, cursor.month)
        if key not in existing:
            if key == (tenant.move_in_date.year, tenant.move_in_date.month):
                due = tenant.move_in_date
            else:
                due = cursor
            charge = RentCharge(
                tenant_id=tenant.id,
                year=cursor.year,
                month=cursor.month,
                amount_due=money(tenant.monthly_rent),
                due_date=due,
            )
            db.session.add(charge)
            created.append(charge)
        cursor = month_on(cursor, 1)
    db.session.flush()
    db.session.expire(tenant, ["charges"])
    return created


def refresh_book(landlord: Landlord, today: date | None = None) -> None:
    """Fill any missing month rows, then save them so the page can read them."""
    today = today or today_lusaka()
    tenants = Tenant.query.filter_by(landlord_id=landlord.id).all()
    for tenant in tenants:
        ensure_charges(tenant, today)
    db.session.commit()


def apply_move_out(tenant: Tenant, move_out: date) -> None:
    if move_out < tenant.move_in_date:
        raise ValueError("Move-out cannot be before move-in.")
    if move_out > today_lusaka():
        raise ValueError("Move-out cannot be in the future.")
    tenant.move_out_date = move_out
    last = (move_out.year, move_out.month)
    for charge in RentCharge.query.filter_by(tenant_id=tenant.id).all():
        if (charge.year, charge.month) > last and len(charge.payments) == 0:
            db.session.delete(charge)
    db.session.flush()
    db.session.expire(tenant, ["charges"])


def update_charge_amount(charge: RentCharge, amount: Decimal) -> None:
    if money(amount) < 0:
        raise ValueError("Rent due cannot be negative.")
    charge.amount_due = money(amount)


def delete_tenant(tenant: Tenant) -> None:
    has_payment = Payment.query.filter_by(tenant_id=tenant.id).first() is not None
    if has_payment:
        raise ValueError(
            "This tenant has payment records, so they stay in the book. Move them out instead."
        )
    RentCharge.query.filter_by(tenant_id=tenant.id).delete(synchronize_session=False)
    db.session.delete(tenant)


def delete_unit(unit: Unit) -> None:
    if unit.tenants:
        raise ValueError(
            "This bed has a tenant on it, so it stays. Move the tenant out if they are still in."
        )
    db.session.delete(unit)


def next_receipt_no(landlord_id: int, paid_on: date) -> str:
    prefix = f"NB-{paid_on.year}-"
    latest = (
        db.session.query(Payment.receipt_no)
        .filter(
            Payment.landlord_id == landlord_id,
            Payment.receipt_no.like(prefix + "%"),
        )
        .order_by(Payment.receipt_no.desc())
        .first()
    )
    number = 1
    if latest is not None:
        tail = latest[0].rsplit("-", 1)[-1]
        if tail.isdigit():
            number = int(tail) + 1
    return f"{prefix}{number:06d}"


def record_payment(
    *,
    tenant: Tenant,
    charge: RentCharge,
    amount: Decimal,
    paid_on: date,
    method: str,
    reference: str,
    notes: str = "",
) -> Payment:
    """Save a payment the landlord already received. This does not collect it."""
    if charge.tenant_id != tenant.id:
        raise ValueError("That month is not on this tenant's book.")
    if money(amount) <= 0:
        raise ValueError("Amount must be more than zero.")
    if method not in PAYMENT_METHODS:
        raise ValueError("Choose how the tenant paid you.")
    if method in ELECTRONIC_METHODS and not (reference or "").strip():
        raise ValueError("Enter the MoMo, Airtel Money, or bank reference.")
    if paid_on > today_lusaka():
        raise ValueError("Use the date the tenant actually paid you.")
    payment = Payment(
        tenant_id=tenant.id,
        charge_id=charge.id,
        landlord_id=tenant.landlord_id,
        amount=money(amount),
        paid_on=paid_on,
        method=method,
        reference=(reference or "").strip(),
        notes=notes or "",
        receipt_no=next_receipt_no(tenant.landlord_id, paid_on),
        recorded_at=now_lusaka(),
    )
    db.session.add(payment)
    db.session.flush()
    return payment


def occupancy(landlord: Landlord) -> dict:
    units = Unit.query.join(Property).filter(Property.landlord_id == landlord.id).all()
    occupied = sum(1 for unit in units if unit.active_tenant is not None)
    return {"occupied": occupied, "total": len(units)}


def arrears_rows(landlord: Landlord, as_of: date) -> list[dict]:
    rows = []
    tenants = Tenant.query.filter_by(landlord_id=landlord.id).all()
    for tenant in tenants:
        balance = tenant.arrears_on(as_of)
        if balance <= 0:
            continue
        oldest = tenant.oldest_due_on(as_of)
        link = None
        if oldest is not None:
            link = whatsapp_url(
                tenant.phone,
                reminder_text(
                    tenant_name=tenant.name,
                    landlord_name=tenant.landlord.name,
                    unit_name=tenant.unit.name,
                    property_name=tenant.unit.house.name,
                    balance=balance,
                    due_on=oldest,
                ),
            )
        rows.append(
            {
                "tenant": tenant,
                "balance": balance,
                "oldest": oldest,
                "whatsapp": link,
            }
        )
    rows.sort(key=lambda row: (-row["balance"], row["tenant"].name))
    return rows


def whatsapp_for_tenant(tenant: Tenant, as_of: date) -> str | None:
    balance = tenant.arrears_on(as_of)
    oldest = tenant.oldest_due_on(as_of)
    if balance <= 0 or oldest is None:
        return None
    return whatsapp_url(
        tenant.phone,
        reminder_text(
            tenant_name=tenant.name,
            landlord_name=tenant.landlord.name,
            unit_name=tenant.unit.name,
            property_name=tenant.unit.house.name,
            balance=balance,
            due_on=oldest,
        ),
    )


def income_report(landlord: Landlord, year: int, month: int, today: date) -> dict:
    """Rent due, rent recorded, and the tax estimate through `month`."""
    charges = (
        RentCharge.query.join(Tenant)
        .filter(Tenant.landlord_id == landlord.id, RentCharge.year == year)
        .all()
    )
    payments = Payment.query.filter(
        Payment.landlord_id == landlord.id,
        Payment.paid_on >= date(year, 1, 1),
        Payment.paid_on <= date(year, 12, 31),
    ).all()

    due_by_month = {number: Decimal("0.00") for number in range(1, month + 1)}
    for charge in charges:
        if charge.month in due_by_month:
            due_by_month[charge.month] = money(due_by_month[charge.month] + money(charge.amount_due))

    recorded_by_month = {number: Decimal("0.00") for number in range(1, month + 1)}
    for payment in payments:
        if payment.paid_on.year == year and payment.paid_on.month in recorded_by_month:
            number = payment.paid_on.month
            recorded_by_month[number] = money(
                recorded_by_month[number] + money(payment.amount)
            )

    monthly_amounts = [recorded_by_month[number] for number in range(1, month + 1)]
    extras = split_year_tax(monthly_amounts)
    rows = []
    for index, number in enumerate(range(1, month + 1)):
        rows.append(
            {
                "year": year,
                "month": number,
                "label": format_month(year, number),
                "key": f"{year}-{number:02d}",
                "due": due_by_month[number],
                "recorded": recorded_by_month[number],
                "tax": extras[index],
            }
        )
    selected = rows[month - 1]
    ytd_recorded = money(sum((row["recorded"] for row in rows), Decimal("0.00")))
    ytd_due = money(sum((row["due"] for row in rows), Decimal("0.00")))
    return {
        "year": year,
        "month": month,
        "month_value": f"{year:04d}-{month:02d}",
        "rows": rows,
        "selected": selected,
        "ytd_recorded": ytd_recorded,
        "ytd_due": ytd_due,
        "breakdown": tax_breakdown(ytd_recorded),
        "show_year_table": ytd_recorded > 0 or ytd_due > 0,
        "old_year": year < 2026,
        # Kept so a reader can see the month figure is the marginal one.
        "marginal_check": marginal_tax(
            money(ytd_recorded - selected["recorded"]),
            selected["recorded"],
        ),
    }
