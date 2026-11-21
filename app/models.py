"""The tables in the rent book.

Landlord
    The person who logs in. One landlord cannot see another's rows.

Property
    A house or boarding house.

Unit
    A room or a bed inside that house. A boarding house uses one row per bed.

Tenant
    Someone who rents a unit. Monthly rent and the deposit live here.
    The deposit is not rent and is not part of the balance.

RentCharge
    One line per tenant per month: how much rent was due, and on which date.

Payment
    Money the landlord already received, written against one month.
    The receipt number is on this row.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from flask_login import UserMixin
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from app import db
from app.ledger import (
    PAYMENT_METHODS,
    arrears_total,
    format_month,
    money,
    month_balance,
    now_lusaka,
    oldest_unpaid,
)


class Landlord(UserMixin, db.Model):
    __tablename__ = "landlords"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(30), default="")
    password_hash: Mapped[str] = mapped_column(String(512))
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_lusaka)

    properties: Mapped[list[Property]] = relationship(
        back_populates="landlord",
        cascade="all, delete-orphan",
        order_by="Property.name",
    )
    tenants: Mapped[list[Tenant]] = relationship(back_populates="landlord")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<Landlord {self.email}>"


class Property(db.Model):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(primary_key=True)
    landlord_id: Mapped[int] = mapped_column(ForeignKey("landlords.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(80), default="Lusaka")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_lusaka)

    landlord: Mapped[Landlord] = relationship(back_populates="properties")
    units: Mapped[list[Unit]] = relationship(
        back_populates="house",
        cascade="all, delete-orphan",
        order_by="Unit.sort_order",
    )

    def __repr__(self) -> str:
        return f"<Property {self.name}>"


class Unit(db.Model):
    __tablename__ = "units"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    sort_order: Mapped[int] = mapped_column(default=0)
    asking_rent: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    # Named house, not property: a method decorated with @property would
    # otherwise collide with this relationship.
    house: Mapped[Property] = relationship(back_populates="units")
    tenants: Mapped[list[Tenant]] = relationship(back_populates="unit")

    @property
    def active_tenant(self) -> Tenant | None:
        for tenant in self.tenants:
            if tenant.move_out_date is None:
                return tenant
        return None

    @property
    def past_tenants(self) -> list[Tenant]:
        past = [tenant for tenant in self.tenants if tenant.move_out_date is not None]
        past.sort(key=lambda tenant: tenant.move_out_date or date.min, reverse=True)
        return past

    def __repr__(self) -> str:
        return f"<Unit {self.name}>"


class Tenant(db.Model):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), index=True)
    landlord_id: Mapped[int] = mapped_column(ForeignKey("landlords.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(30))
    move_in_date: Mapped[date] = mapped_column(Date)
    move_out_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    monthly_rent: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    deposit: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_lusaka)

    unit: Mapped[Unit] = relationship(back_populates="tenants")
    landlord: Mapped[Landlord] = relationship(back_populates="tenants")
    charges: Mapped[list[RentCharge]] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
        order_by="RentCharge.due_date",
    )

    def arrears_on(self, as_of: date) -> Decimal:
        rows = [(charge.due_date, charge.balance) for charge in self.charges]
        return arrears_total(rows, as_of)

    def oldest_due_on(self, as_of: date) -> date | None:
        rows = [(charge.due_date, charge.balance) for charge in self.charges]
        return oldest_unpaid(rows, as_of)

    def __repr__(self) -> str:
        return f"<Tenant {self.name}>"


class RentCharge(db.Model):
    __tablename__ = "rent_charges"
    __table_args__ = (UniqueConstraint("tenant_id", "year", "month", name="uq_charge_month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    year: Mapped[int] = mapped_column()
    month: Mapped[int] = mapped_column()
    amount_due: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    due_date: Mapped[date] = mapped_column(Date)

    tenant: Mapped[Tenant] = relationship(back_populates="charges")
    payments: Mapped[list[Payment]] = relationship(back_populates="charge")

    @property
    def period_label(self) -> str:
        return format_month(self.year, self.month)

    @property
    def payments_in_order(self) -> list[Payment]:
        return sorted(self.payments, key=lambda payment: (payment.paid_on, payment.id or 0))

    @property
    def amount_paid(self) -> Decimal:
        return money(sum((payment.amount for payment in self.payments), Decimal("0.00")))

    @property
    def balance(self) -> Decimal:
        return month_balance(self.amount_due, [payment.amount for payment in self.payments])

    def __repr__(self) -> str:
        return f"<RentCharge {self.year}-{self.month:02d} tenant={self.tenant_id}>"


class Payment(db.Model):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("landlord_id", "receipt_no", name="uq_receipt"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    charge_id: Mapped[int] = mapped_column(ForeignKey("rent_charges.id"), index=True)
    landlord_id: Mapped[int] = mapped_column(ForeignKey("landlords.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    paid_on: Mapped[date] = mapped_column(Date, index=True)
    method: Mapped[str] = mapped_column(String(20))
    reference: Mapped[str] = mapped_column(String(80), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    receipt_no: Mapped[str] = mapped_column(String(32))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=now_lusaka)

    tenant: Mapped[Tenant] = relationship()
    charge: Mapped[RentCharge] = relationship(back_populates="payments")
    landlord: Mapped[Landlord] = relationship()

    @property
    def method_label(self) -> str:
        return PAYMENT_METHODS.get(self.method, self.method)

    def __repr__(self) -> str:
        return f"<Payment {self.receipt_no}>"


@event.listens_for(Engine, "connect")
def _sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    # SQLite ignores foreign keys unless this is turned on for the connection.
    module = dbapi_connection.__class__.__module__
    if module.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
