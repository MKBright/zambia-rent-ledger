"""Rent rows and payments, with a small database and no web pages."""

from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.books import (
    apply_move_out,
    ensure_charges,
    income_report,
    record_payment,
    update_charge_amount,
)
from app.models import Landlord, Property, RentCharge, Tenant, Unit


def _tenant(move_in: date, rent: str = "900") -> Tenant:
    landlord = Landlord(
        name="Amina Banda",
        email="amina@example.com",
        phone="0971234567",
        is_sample=False,
    )
    landlord.set_password("password123")
    prop = Property(
        landlord=landlord,
        name="House",
        address="Plot 1, Chilenje",
        city="Lusaka",
        notes="",
    )
    unit = Unit(house=prop, name="Bed 1", sort_order=1, asking_rent=Decimal("900"))
    tenant = Tenant(
        unit=unit,
        landlord=landlord,
        name="Tenant One",
        phone="0971234567",
        move_in_date=move_in,
        monthly_rent=Decimal(rent),
        deposit=Decimal("0.00"),
        notes="",
    )
    db.session.add(landlord)
    db.session.commit()
    return db.session.get(Tenant, tenant.id)


def test_ensure_charges_is_idempotent_and_stops_at_move_out(app):
    with app.app_context():
        tenant = _tenant(date(2026, 1, 2))
        created = ensure_charges(tenant, date(2026, 11, 21))
        db.session.commit()
        assert len(created) == 11
        assert ensure_charges(tenant, date(2026, 11, 21)) == []
        tenant = db.session.get(Tenant, tenant.id)
        january = next(charge for charge in tenant.charges if charge.month == 1)
        march = next(charge for charge in tenant.charges if charge.month == 3)
        assert january.due_date == date(2026, 1, 2)
        assert march.due_date == date(2026, 3, 1)
        assert january.amount_due == Decimal("900.00")

        apply_move_out(tenant, date(2026, 10, 15))
        db.session.commit()
        tenant = db.session.get(Tenant, tenant.id)
        months = {(charge.year, charge.month) for charge in tenant.charges}
        assert (2026, 11) not in months
        assert (2026, 10) in months
        ensure_charges(tenant, date(2026, 11, 21))
        db.session.commit()
        tenant = db.session.get(Tenant, tenant.id)
        months = {(charge.year, charge.month) for charge in tenant.charges}
        assert (2026, 11) not in months


def test_part_payment_balance_does_not_include_a_future_month(app):
    with app.app_context():
        tenant = _tenant(date(2026, 10, 1))
        ensure_charges(tenant, date(2026, 11, 21))
        db.session.commit()
        tenant = db.session.get(Tenant, tenant.id)
        october = next(charge for charge in tenant.charges if charge.month == 10)
        november = next(charge for charge in tenant.charges if charge.month == 11)
        record_payment(
            tenant=tenant,
            charge=october,
            amount=Decimal("900"),
            paid_on=date(2026, 10, 5),
            method="cash",
            reference="",
        )
        record_payment(
            tenant=tenant,
            charge=november,
            amount=Decimal("400"),
            paid_on=date(2026, 11, 21),
            method="mtn_momo",
            reference="SAMPLE-1",
        )
        db.session.commit()
        november = db.session.get(RentCharge, november.id)
        tenant = db.session.get(Tenant, tenant.id)
        assert november.balance == Decimal("500.00")
        assert november.amount_paid == Decimal("400.00")
        assert tenant.arrears_on(date(2026, 11, 21)) == Decimal("500.00")
        db.session.add(
            RentCharge(
                tenant_id=tenant.id,
                year=2026,
                month=12,
                amount_due=Decimal("900.00"),
                due_date=date(2026, 12, 1),
            )
        )
        db.session.commit()
        tenant = db.session.get(Tenant, tenant.id)
        assert tenant.arrears_on(date(2026, 11, 21)) == Decimal("500.00")


def test_electronic_payment_needs_a_reference_and_receipts_count_up(app):
    with app.app_context():
        tenant = _tenant(date(2026, 11, 1))
        ensure_charges(tenant, date(2026, 11, 21))
        db.session.commit()
        charge = tenant.charges[0]
        with pytest.raises(ValueError):
            record_payment(
                tenant=tenant,
                charge=charge,
                amount=Decimal("100"),
                paid_on=date(2026, 11, 21),
                method="airtel_money",
                reference="",
            )
        first = record_payment(
            tenant=tenant,
            charge=charge,
            amount=Decimal("100"),
            paid_on=date(2026, 11, 2),
            method="cash",
            reference="",
        )
        second = record_payment(
            tenant=tenant,
            charge=charge,
            amount=Decimal("50"),
            paid_on=date(2026, 11, 3),
            method="bank",
            reference="FT1",
        )
        assert first.receipt_no == "NB-2026-000001"
        assert second.receipt_no == "NB-2026-000002"


def test_lowering_the_due_amount_can_settle_a_part_payment(app):
    with app.app_context():
        tenant = _tenant(date(2026, 11, 1))
        ensure_charges(tenant, date(2026, 11, 21))
        charge = tenant.charges[0]
        record_payment(
            tenant=tenant,
            charge=charge,
            amount=Decimal("400"),
            paid_on=date(2026, 11, 21),
            method="cash",
            reference="",
        )
        update_charge_amount(charge, Decimal("400"))
        assert charge.balance == Decimal("0.00")


def test_overpayment_is_not_arrears(app):
    with app.app_context():
        tenant = _tenant(date(2026, 11, 1))
        ensure_charges(tenant, date(2026, 11, 21))
        charge = tenant.charges[0]
        record_payment(
            tenant=tenant,
            charge=charge,
            amount=Decimal("1000"),
            paid_on=date(2026, 11, 21),
            method="cash",
            reference="",
        )
        db.session.commit()
        charge = db.session.get(RentCharge, charge.id)
        tenant = db.session.get(Tenant, tenant.id)
        assert charge.balance == Decimal("-100.00")
        assert tenant.arrears_on(date(2026, 11, 21)) == Decimal("0.00")


def test_income_tax_follows_the_date_the_money_was_received(app):
    with app.app_context():
        tenant = _tenant(date(2026, 1, 1), rent="40000")
        ensure_charges(tenant, date(2026, 2, 1))
        january = next(charge for charge in tenant.charges if charge.month == 1)
        # Paid in February, but it covers January. Tax follows the payment date.
        record_payment(
            tenant=tenant,
            charge=january,
            amount=Decimal("40000"),
            paid_on=date(2026, 2, 2),
            method="bank",
            reference="FT-BIG",
        )
        db.session.commit()
        january_view = income_report(tenant.landlord, 2026, 1, date(2026, 2, 2))
        february_view = income_report(tenant.landlord, 2026, 2, date(2026, 2, 2))
        january = db.session.get(RentCharge, january.id)
        # The January line is settled, because the payment was attached to it.
        assert january.balance == Decimal("0.00")
        # The income total follows 2 February, the day the money arrived.
        assert january_view["selected"]["due"] == Decimal("40000.00")
        assert january_view["selected"]["recorded"] == Decimal("0.00")
        assert january_view["breakdown"]["total_tax"] == Decimal("0.00")
        assert february_view["selected"]["recorded"] == Decimal("40000.00")
        assert february_view["selected"]["due"] == Decimal("40000.00")
        # K40,000 received: K30,000 at 0% and K10,000 at 4% = K400.
        assert february_view["breakdown"]["total_tax"] == Decimal("400.00")
        assert february_view["selected"]["tax"] == Decimal("400.00")
