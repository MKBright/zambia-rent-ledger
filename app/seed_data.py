"""Fictional Lusaka boarding house used to try the app.

Sample: Kalingalinga Boarding House, 10 beds, 8 occupied.
The people are invented. Running this again replaces the sample
landlord and does not delete accounts you created yourself.

The story, relative to today:
- Thandiwe, Chipo, and Peter are paid up, including this month.
- Joseph paid only K400 of this month's K900.
- Mutale missed this month and the month before.
- Naomi has not paid this month.
- Brian paid K200 of this month.
- Loveness paid last month and not this month.
- Bed 9 and Bed 10 are empty.

Move-in dates that would fall in the future are pulled back to today,
so the sample still works in January.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app import db
from app.books import ensure_charges, record_payment
from app.copy import SAMPLE_EMAIL, SAMPLE_PASSWORD
from app.ledger import money, month_end, month_on, today_lusaka
from app.models import Landlord, Payment, Property, RentCharge, Tenant, Unit


def wipe_landlord(landlord_id: int) -> None:
    tenant_ids = [row.id for row in db.session.query(Tenant.id).filter_by(landlord_id=landlord_id)]
    Payment.query.filter_by(landlord_id=landlord_id).delete(synchronize_session=False)
    if tenant_ids:
        RentCharge.query.filter(RentCharge.tenant_id.in_(tenant_ids)).delete(synchronize_session=False)
        Tenant.query.filter(Tenant.id.in_(tenant_ids)).delete(synchronize_session=False)
    property_ids = [row.id for row in db.session.query(Property.id).filter_by(landlord_id=landlord_id)]
    if property_ids:
        Unit.query.filter(Unit.property_id.in_(property_ids)).delete(synchronize_session=False)
        Property.query.filter(Property.id.in_(property_ids)).delete(synchronize_session=False)
    # Drop in-memory copies of the rows just deleted, so removing the
    # landlord does not try to delete them a second time.
    db.session.expire_all()
    landlord = db.session.get(Landlord, landlord_id)
    if landlord is not None:
        db.session.delete(landlord)
    db.session.commit()


def load_sample() -> None:
    sample_ids = [row.id for row in db.session.query(Landlord.id).filter_by(is_sample=True)]
    for landlord_id in sample_ids:
        wipe_landlord(landlord_id)
    _build_sample(today_lusaka())
    db.session.commit()


def _not_in_future(day: date, today: date) -> date:
    if day > today:
        return today
    return day


def _paid_on(charge: RentCharge, tenant: Tenant, today: date) -> date:
    if (charge.year, charge.month) == (today.year, today.month):
        return today
    day = min(5, month_end(charge.year, charge.month).day)
    paid = date(charge.year, charge.month, day)
    if paid < tenant.move_in_date:
        paid = tenant.move_in_date
    if paid > today:
        paid = today
    return paid


def _reference(method: str, tenant_id: int, charge: RentCharge) -> str:
    if method == "cash":
        return ""
    kind = {"mtn_momo": "MOMO", "airtel_money": "AIRTEL", "bank": "BANK"}[method]
    return f"SAMPLE-{kind}-{tenant_id}-{charge.year}{charge.month:02d}"


def _fill(tenant: Tenant, today: date, method: str, skip: set[tuple[int, int]], partial: dict | None) -> None:
    charges = RentCharge.query.filter_by(tenant_id=tenant.id).order_by(RentCharge.due_date).all()
    for charge in charges:
        key = (charge.year, charge.month)
        if partial is not None and key == (partial["year"], partial["month"]):
            record_payment(
                tenant=tenant,
                charge=charge,
                amount=money(partial["amount"]),
                paid_on=_paid_on(charge, tenant, today),
                method=partial["method"],
                reference=partial["reference"],
                notes="Sample part payment. Fictional.",
            )
            continue
        if key in skip:
            continue
        if money(charge.amount_due) <= 0:
            continue
        record_payment(
            tenant=tenant,
            charge=charge,
            amount=money(charge.amount_due),
            paid_on=_paid_on(charge, tenant, today),
            method=method,
            reference=_reference(method, tenant.id, charge),
            notes="Sample payment. Fictional.",
        )


def _build_sample(today: date) -> None:
    landlord = Landlord(
        name="Bwalya Chanda",
        email=SAMPLE_EMAIL,
        phone="0970000091",
        is_sample=True,
    )
    landlord.set_password(SAMPLE_PASSWORD)
    prop = Property(
        landlord=landlord,
        name="Sample: Kalingalinga Boarding House",
        address="Plot 14, off Alick Nkhata Road, Kalingalinga",
        city="Lusaka",
        notes=(
            "SAMPLE DATA. Fictional boarding house for learning the app. "
            "Not a real plot and not real tenants."
        ),
    )
    asking = {
        1: Decimal("900"),
        2: Decimal("900"),
        3: Decimal("1000"),
        4: Decimal("850"),
        5: Decimal("850"),
        6: Decimal("1200"),
        7: Decimal("800"),
        8: Decimal("800"),
        9: Decimal("900"),
        10: Decimal("750"),
    }
    beds = {
        number: Unit(
            house=prop,
            name=f"Bed {number}",
            sort_order=number,
            asking_rent=asking[number],
            notes="",
        )
        for number in range(1, 11)
    }
    db.session.add(landlord)
    db.session.flush()

    previous = month_on(today, -1)
    current_key = (today.year, today.month)
    previous_key = (previous.year, previous.month)

    people = [
        {
            "bed": 1,
            "name": "Thandiwe Phiri",
            "phone": "0971111001",
            "rent": Decimal("900"),
            "deposit": Decimal("900"),
            "move_in": _not_in_future(date(today.year, 1, 2), today),
            "method": "mtn_momo",
            "skip": set(),
            "partial": None,
        },
        {
            "bed": 2,
            "name": "Joseph Banda",
            "phone": "0962222002",
            "rent": Decimal("900"),
            "deposit": Decimal("900"),
            "move_in": _not_in_future(date(today.year, 1, 2), today),
            "method": "mtn_momo",
            "skip": set(),
            "partial": {
                "year": today.year,
                "month": today.month,
                "amount": Decimal("400"),
                "method": "cash",
                "reference": "",
            },
        },
        {
            "bed": 3,
            "name": "Mutale Zulu",
            "phone": "0953333003",
            "rent": Decimal("1000"),
            "deposit": Decimal("1000"),
            "move_in": _not_in_future(date(today.year, 1, 2), today),
            "method": "airtel_money",
            "skip": {current_key, previous_key},
            "partial": None,
        },
        {
            "bed": 4,
            "name": "Chipo Mwale",
            "phone": "0974444004",
            "rent": Decimal("850"),
            "deposit": Decimal("850"),
            "move_in": _not_in_future(date(today.year, 3, 1), today),
            "method": "airtel_money",
            "skip": set(),
            "partial": None,
        },
        {
            "bed": 5,
            "name": "Peter Tembo",
            "phone": "0965555005",
            "rent": Decimal("850"),
            "deposit": Decimal("850"),
            "move_in": _not_in_future(date(today.year, 3, 1), today),
            "method": "bank",
            "skip": set(),
            "partial": None,
        },
        {
            "bed": 6,
            "name": "Naomi Sakala",
            "phone": "0956666006",
            "rent": Decimal("1200"),
            "deposit": Decimal("1200"),
            "move_in": _not_in_future(date(today.year, 6, 1), today),
            "method": "mtn_momo",
            "skip": {current_key},
            "partial": None,
        },
        {
            "bed": 7,
            "name": "Brian Mulenga",
            "phone": "0977777007",
            "rent": Decimal("800"),
            "deposit": Decimal("400"),
            "move_in": _not_in_future(date(today.year, 8, 1), today),
            "method": "cash",
            "skip": set(),
            "partial": {
                "year": today.year,
                "month": today.month,
                "amount": Decimal("200"),
                "method": "mtn_momo",
                "reference": "SAMPLE-MOMO-BRIAN-PART",
            },
        },
        {
            "bed": 8,
            "name": "Loveness Daka",
            "phone": "0968888008",
            "rent": Decimal("800"),
            "deposit": Decimal("800"),
            "move_in": previous,
            "method": "cash",
            "skip": {current_key},
            "partial": None,
        },
    ]

    for person in people:
        move_in = person["move_in"]
        # A skipped month before this tenant arrived is not a charge.
        skip = {
            key
            for key in person["skip"]
            if key >= (move_in.year, move_in.month)
        }
        tenant = Tenant(
            unit=beds[person["bed"]],
            landlord=landlord,
            name=person["name"],
            phone=person["phone"],
            move_in_date=move_in,
            monthly_rent=person["rent"],
            deposit=person["deposit"],
            notes="Fictional sample tenant. Not a real person.",
        )
        db.session.add(tenant)
        db.session.flush()
        ensure_charges(tenant, today)
        _fill(tenant, today, person["method"], skip, person["partial"])
