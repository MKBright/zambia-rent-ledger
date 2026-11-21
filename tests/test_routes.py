"""Pages a landlord actually opens.

The money rules are covered in test_ledger.py. These tests check that
login, ownership, receipts, arrears, tax wording, and CSV export use
those rules.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

from flask_wtf.csrf import CSRFError

from app import db
from app.copy import (
    COLLECT_NOTE,
    NIL_BAND_NOTE,
    OLD_YEAR_WARNING,
    RECEIPT_DISCLAIMER,
    SAMPLE_BANNER,
    SAMPLE_EMAIL,
    SAMPLE_PASSWORD,
    TAX_DISCLAIMER,
)
from app.ledger import format_kwacha, today_lusaka
from app.models import Landlord, Payment, Property, RentCharge, Tenant, Unit
from app.seed_data import load_sample
from tests.helpers import csrf, csrf_token, logout, register


def test_pages_say_the_app_does_not_collect_rent(client):
    page = client.get("/login")
    assert page.status_code == 200
    assert COLLECT_NOTE in page.get_data(as_text=True)
    assert "Pay now" not in page.get_data(as_text=True)


def test_dashboard_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_post_without_csrf_is_rejected(client):
    try:
        response = client.post(
            "/login",
            data={"email": "a@example.com", "password": "password123"},
        )
    except CSRFError:
        return
    assert response.status_code == 400


def test_register_hashes_the_password_and_starts_an_empty_book(client, app):
    page = register(client)
    text = page.get_data(as_text=True)
    assert "Add your first house" in text
    arrears = client.get("/arrears")
    assert "Nobody owes rent for a month that is already due." in arrears.get_data(as_text=True)
    income = client.get("/income")
    income_text = income.get_data(as_text=True)
    assert TAX_DISCLAIMER in income_text
    assert NIL_BAND_NOTE in income_text
    assert "16%" in income_text
    assert "4%" in income_text
    assert "by the 14th" in TAX_DISCLAIMER
    with app.app_context():
        user = Landlord.query.filter_by(email="amina@example.com").one()
        assert user.check_password("password123")
        assert "password123" not in user.password_hash
        assert user.password_hash.startswith(("scrypt:", "pbkdf2:"))


def test_wrong_password_and_outside_redirect(client):
    register(client)
    logout(client)
    page = client.get("/login?next=https://evil.example/phish")
    token = csrf_token(page.get_data(as_text=True))
    bad = client.post(
        "/login",
        data={
            "email": "amina@example.com",
            "password": "not-the-password",
            "csrf_token": token,
            "next": "https://evil.example/phish",
        },
        follow_redirects=True,
    )
    assert "not correct" in bad.get_data(as_text=True).lower()
    page = client.get("/login")
    token = csrf_token(page.get_data(as_text=True))
    response = client.post(
        "/login",
        data={
            "email": "amina@example.com",
            "password": "password123",
            "csrf_token": token,
            "next": "https://evil.example/phish",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "evil.example" not in response.headers["Location"]


def test_part_payment_receipt_arrears_and_dashboard(client, app):
    register(client, name="Amina Banda")
    token = csrf(client)
    client.post(
        "/properties",
        data={
            "name": "Chilenje Flats",
            "address": "Plot 2, Chilenje",
            "city": "Lusaka",
            "notes": "",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    with app.app_context():
        prop = Property.query.filter_by(name="Chilenje Flats").one()
        property_id = prop.id
    token = csrf(client)
    client.post(
        f"/properties/{property_id}/units",
        data={"name": "Bed 1", "asking_rent": "1000", "csrf_token": token},
        follow_redirects=True,
    )
    with app.app_context():
        unit = Unit.query.filter_by(name="Bed 1").one()
        unit_id = unit.id
    today = today_lusaka()
    token = csrf(client)
    moved = client.post(
        f"/units/{unit_id}/move-in",
        data={
            "name": "Joseph Test",
            "phone": "0971234567",
            "move_in_date": today.isoformat(),
            "monthly_rent": "1000",
            "deposit": "1000",
            "notes": "",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    assert moved.status_code == 200
    body = moved.get_data(as_text=True)
    assert "K1,000.00" in body
    assert "Owes K1,000.00" in body
    with app.app_context():
        tenant = Tenant.query.filter_by(name="Joseph Test").one()
        tenant_id = tenant.id
        charge_id = tenant.charges[0].id
        # Deposit is stored, and it is not added to the rent balance.
        assert tenant.deposit == Decimal("1000.00")
        assert tenant.arrears_on(today) == Decimal("1000.00")

    token = csrf(client)
    rejected = client.post(
        f"/tenants/{tenant_id}/payments",
        data={
            "charge_id": charge_id,
            "amount": "250",
            "paid_on": today.isoformat(),
            "method": "mtn_momo",
            "reference": "",
            "notes": "",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    assert "reference" in rejected.get_data(as_text=True).lower()
    with app.app_context():
        assert Payment.query.count() == 0

    token = csrf(client)
    saved = client.post(
        f"/tenants/{tenant_id}/payments",
        data={
            "charge_id": charge_id,
            "amount": "250",
            "paid_on": today.isoformat(),
            "method": "mtn_momo",
            "reference": "MP-TEST-1",
            "notes": "",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert saved.status_code == 302
    assert "/receipts/" in saved.headers["Location"]
    receipt = client.get(saved.headers["Location"])
    receipt_text = receipt.get_data(as_text=True)
    assert receipt.status_code == 200
    assert "Payment record" in receipt_text
    assert RECEIPT_DISCLAIMER in receipt_text
    assert "not a ZRA Smart Invoice" in receipt_text
    assert "MP-TEST-1" in receipt_text
    assert "MTN MoMo" in receipt_text
    assert "K250.00" in receipt_text
    assert "Still open" in receipt_text
    assert "K750.00" in receipt_text
    assert "Pay now" not in receipt_text

    book = client.get(f"/tenants/{tenant_id}")
    book_text = book.get_data(as_text=True)
    assert "K750.00" in book_text
    assert "https://wa.me/260971234567" in book_text
    assert "K750.00" in book_text

    arrears = client.get("/arrears").get_data(as_text=True)
    assert "Joseph Test" in arrears
    assert "wa.me/260971234567" in arrears

    home = client.get("/").get_data(as_text=True)
    assert "K1,000.00" in home
    assert "K250.00" in home
    assert "1 of 1" in home

    income = client.get("/income").get_data(as_text=True)
    assert TAX_DISCLAIMER in income
    assert "K250.00" in income
    assert NIL_BAND_NOTE in income

    exported = client.get("/export/payments.csv")
    csv_text = exported.get_data(as_text=True)
    assert exported.mimetype.startswith("text/csv")
    assert "amount_zmw" in csv_text
    assert "250.00" in csv_text
    assert "MP-TEST-1" in csv_text
    assert csv_text.startswith("\ufeff")

    arrears_file = client.get("/export/arrears.csv").get_data(as_text=True)
    assert "750.00" in arrears_file
    assert "Joseph Test" in arrears_file


def test_other_landlord_cannot_see_the_book(client, app):
    register(client, email="owner@example.com", name="Owner One")
    token = csrf(client)
    client.post(
        "/properties",
        data={
            "name": "Private House",
            "address": "Plot 9",
            "city": "Lusaka",
            "notes": "",
            "csrf_token": token,
        },
    )
    with app.app_context():
        prop = Property.query.one()
        property_id = prop.id
        unit = Unit(property_id=property_id, name="Room A", sort_order=1)
        tenant = Tenant(
            unit=unit,
            landlord_id=prop.landlord_id,
            name="=1+1",
            phone="0961234567",
            move_in_date=today_lusaka(),
            monthly_rent=Decimal("900.00"),
            deposit=Decimal("0.00"),
            notes="",
        )
        db.session.add(tenant)
        db.session.flush()
        from app.books import ensure_charges, record_payment

        ensure_charges(tenant, today_lusaka())
        charge = tenant.charges[0]
        payment = record_payment(
            tenant=tenant,
            charge=charge,
            amount=Decimal("100"),
            paid_on=today_lusaka(),
            method="cash",
            reference="",
        )
        db.session.commit()
        tenant_id = tenant.id
        payment_id = payment.id
        charge_id = charge.id

    logout(client)
    register(client, email="other@example.com", name="Other Person", password="password123")
    assert client.get(f"/tenants/{tenant_id}").status_code == 404
    assert client.get(f"/receipts/{payment_id}").status_code == 404
    assert client.get(f"/properties/{property_id}").status_code == 404
    stolen = client.get("/export/payments.csv").get_data(as_text=True)
    assert "=1+1" not in stolen
    assert "100.00" not in stolen
    # A formula-like name is quoted when the owner exports it.
    logout(client)
    page = client.get("/login")
    token = csrf_token(page.get_data(as_text=True))
    client.post(
        "/login",
        data={
            "email": "owner@example.com",
            "password": "password123",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    owned = client.get("/export/payments.csv").get_data(as_text=True)
    assert "'=1+1" in owned

    token = csrf(client)
    blocked = client.post(
        f"/tenants/{tenant_id}/payments",
        data={
            "charge_id": charge_id,
            "amount": "50",
            "paid_on": today_lusaka().isoformat(),
            "method": "cash",
            "reference": "",
            "notes": "",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    # Still the owner here, so this should record. The cross-tenant check is next.
    assert blocked.status_code == 200


def test_cannot_attach_a_payment_to_someone_elses_month(client, app):
    register(client)
    today = today_lusaka()
    with app.app_context():
        landlord_id = Landlord.query.one().id
        prop = Property(
            landlord_id=landlord_id,
            name="House",
            address="Plot 1",
            city="Lusaka",
            notes="",
        )
        first = Unit(house=prop, name="Bed 1", sort_order=1)
        second = Unit(house=prop, name="Bed 2", sort_order=2)
        db.session.add(prop)
        db.session.flush()
        tenant_a = Tenant(
            unit=first,
            landlord_id=landlord_id,
            name="Tenant A",
            phone="0971234567",
            move_in_date=today,
            monthly_rent=Decimal("500"),
            deposit=Decimal("0"),
            notes="",
        )
        tenant_b = Tenant(
            unit=second,
            landlord_id=landlord_id,
            name="Tenant B",
            phone="0961234567",
            move_in_date=today,
            monthly_rent=Decimal("500"),
            deposit=Decimal("0"),
            notes="",
        )
        db.session.add_all([tenant_a, tenant_b])
        db.session.flush()
        from app.books import ensure_charges

        ensure_charges(tenant_a, today)
        ensure_charges(tenant_b, today)
        db.session.commit()
        tenant_a_id = tenant_a.id
        charge_b = tenant_b.charges[0].id

    token = csrf(client)
    response = client.post(
        f"/tenants/{tenant_a_id}/payments",
        data={
            "charge_id": charge_b,
            "amount": "100",
            "paid_on": today.isoformat(),
            "method": "cash",
            "reference": "",
            "notes": "",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    assert "Choose the month" in response.get_data(as_text=True)
    with app.app_context():
        assert Payment.query.count() == 0


def test_overpayment_receipt_says_credit(client, app):
    register(client)
    today = today_lusaka()
    with app.app_context():
        landlord_id = Landlord.query.one().id
        prop = Property(
            landlord_id=landlord_id,
            name="House",
            address="Plot 1",
            city="Lusaka",
            notes="",
        )
        unit = Unit(house=prop, name="Bed 1", sort_order=1)
        db.session.add(prop)
        db.session.flush()
        tenant = Tenant(
            unit=unit,
            landlord_id=landlord_id,
            name="Tenant Credit",
            phone="0971234567",
            move_in_date=today,
            monthly_rent=Decimal("900"),
            deposit=Decimal("0"),
            notes="",
        )
        db.session.add(tenant)
        db.session.flush()
        from app.books import ensure_charges

        ensure_charges(tenant, today)
        db.session.commit()
        tenant_id = tenant.id
        charge_id = tenant.charges[0].id
    token = csrf(client)
    saved = client.post(
        f"/tenants/{tenant_id}/payments",
        data={
            "charge_id": charge_id,
            "amount": "1000",
            "paid_on": today.isoformat(),
            "method": "cash",
            "reference": "",
            "notes": "",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    text = saved.get_data(as_text=True)
    assert "Credit K100.00" in text
    assert RECEIPT_DISCLAIMER in text
    arrears = client.get("/arrears").get_data(as_text=True)
    assert "Tenant Credit" not in arrears


def test_income_page_shows_four_percent_and_old_year_warning(client, app):
    register(client)
    today = today_lusaka()
    with app.app_context():
        landlord = Landlord.query.one()
        prop = Property(
            landlord=landlord,
            name="Big House",
            address="Plot 3",
            city="Lusaka",
            notes="",
        )
        unit = Unit(house=prop, name="House", sort_order=1)
        db.session.add(prop)
        db.session.flush()
        tenant = Tenant(
            unit=unit,
            landlord=landlord,
            name="Big Rent",
            phone="0971234567",
            move_in_date=date(today.year, today.month, 1),
            monthly_rent=Decimal("40000"),
            deposit=Decimal("0"),
            notes="",
        )
        db.session.add(tenant)
        db.session.flush()
        from app.books import ensure_charges, record_payment

        ensure_charges(tenant, today)
        record_payment(
            tenant=tenant,
            charge=tenant.charges[0],
            amount=Decimal("40000"),
            paid_on=today,
            method="bank",
            reference="BIG-1",
        )
        db.session.commit()
    page = client.get("/income")
    text = page.get_data(as_text=True)
    assert format_kwacha(Decimal("400")) in text
    assert TAX_DISCLAIMER in text
    assert "16%" in text
    old = client.get("/income?month=2025-05")
    assert OLD_YEAR_WARNING in old.get_data(as_text=True)
    exported = client.get("/export/income.csv").get_data(as_text=True)
    assert "estimated_tax_zmw" in exported
    assert "year-to-date" in exported
    assert "estimate only, not a ZRA filing" in exported
    assert "400.00" in exported


def test_change_password(client):
    register(client)
    token = csrf(client)
    saved = client.post(
        "/account",
        data={
            "name": "Amina Banda",
            "phone": "0971234567",
            "current_password": "password123",
            "new_password": "newpassword1",
            "confirm": "newpassword1",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    assert "Account saved" in saved.get_data(as_text=True)
    logout(client)
    page = client.get("/login")
    token = csrf_token(page.get_data(as_text=True))
    failed = client.post(
        "/login",
        data={
            "email": "amina@example.com",
            "password": "password123",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    assert "not correct" in failed.get_data(as_text=True).lower()
    token = csrf_token(failed.get_data(as_text=True))
    ok = client.post(
        "/login",
        data={
            "email": "amina@example.com",
            "password": "newpassword1",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    assert "Add your first house" in ok.get_data(as_text=True)


def test_sample_boarding_house(client, app):
    with app.app_context():
        load_sample()
        # A real account must survive a second sample load.
        keeper = Landlord(name="Keeper", email="keeper@example.com", phone="0970000001", is_sample=False)
        keeper.set_password("password123")
        db.session.add(keeper)
        db.session.commit()
        load_sample()
        assert Landlord.query.filter_by(email="keeper@example.com").count() == 1
        assert Landlord.query.filter_by(is_sample=True).count() == 1
        prop = Property.query.filter(Property.name.contains("Kalingalinga")).one()
        assert "Sample" in prop.name
        assert "fictional" in prop.notes.lower()
        assert len(prop.units) == 10
        assert sum(1 for unit in prop.units if unit.active_tenant is None) == 2
        joseph = Tenant.query.filter_by(name="Joseph Banda").one()
        assert joseph.arrears_on(today_lusaka()) == Decimal("500.00")
        mutale = Tenant.query.filter_by(name="Mutale Zulu").one()
        if len(mutale.charges) >= 2:
            assert mutale.arrears_on(today_lusaka()) == Decimal("2000.00")
        else:
            assert mutale.arrears_on(today_lusaka()) == Decimal("1000.00")
        joseph_id = joseph.id
        property_id = prop.id
        receipt = (
            Payment.query.join(Tenant)
            .filter(Tenant.name == "Joseph Banda", Payment.amount == Decimal("400.00"))
            .one()
        )
        receipt_id = receipt.id

    login_page = client.get("/login")
    assert SAMPLE_EMAIL in login_page.get_data(as_text=True)
    token = csrf_token(login_page.get_data(as_text=True))
    home = client.post(
        "/login",
        data={
            "email": SAMPLE_EMAIL,
            "password": SAMPLE_PASSWORD,
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    home_text = home.get_data(as_text=True)
    assert home.status_code == 200
    assert "8 of 10" in home_text
    assert SAMPLE_BANNER in home_text
    assert "Kalingalinga" in home_text
    book = client.get(f"/tenants/{joseph_id}").get_data(as_text=True)
    assert "K500.00" in book
    assert "wa.me/260962222002" in book
    beds = client.get(f"/properties/{property_id}")
    assert beds.status_code == 200
    assert "Bed 10" in beds.get_data(as_text=True)
    assert "Empty" in beds.get_data(as_text=True)
    arrears = client.get("/arrears")
    assert arrears.status_code == 200
    assert "Mutale Zulu" in arrears.get_data(as_text=True)
    receipt_page = client.get(f"/receipts/{receipt_id}").get_data(as_text=True)
    assert RECEIPT_DISCLAIMER in receipt_page
    assert "SAMPLE" in receipt_page
    assert "No reference (cash)" in receipt_page
    income = client.get("/income").get_data(as_text=True)
    assert TAX_DISCLAIMER in income
    assert "4%" in income
    assert "16%" in income


def test_print_stylesheet_exists():
    css = Path("app/static/style.css").read_text(encoding="utf-8")
    assert "@media print" in css


def test_source_has_no_payment_gateway():
    root = Path("app")
    blob = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    blob += "\n".join(path.read_text(encoding="utf-8") for path in (root / "templates").rglob("*.html"))
    lowered = blob.lower()
    for word in ("stripe", "paypal", "checkout.session"):
        assert word not in lowered
