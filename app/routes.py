"""The pages of the rent book.

A landlord only ever sees their own rows. Someone else's tenant,
receipt, or house is a 404, the same as a missing page, so the app
does not reveal that the row exists.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from app import db
from app.books import (
    apply_move_out,
    arrears_rows,
    delete_tenant,
    delete_unit,
    ensure_charges,
    income_report,
    occupancy,
    record_payment,
    refresh_book,
    update_charge_amount,
    whatsapp_for_tenant,
)
from app.checks import (
    optional_text,
    parse_day,
    parse_method,
    parse_money,
    parse_phone,
    parse_reference,
    required_text,
)
from app.exporting import arrears_csv, income_csv, payments_csv
from app.ledger import (
    PAYMENT_METHODS,
    deadline_sentence,
    filing_deadline,
    month_end,
    parse_month_param,
    percent_of,
    today_lusaka,
)
from app.models import Payment, Property, RentCharge, Tenant, Unit

main_bp = Blueprint("main", __name__)


def _own_property(property_id: int) -> Property:
    prop = db.session.get(Property, property_id)
    if prop is None or prop.landlord_id != current_user.id:
        abort(404)
    return prop


def _own_unit(unit_id: int) -> Unit:
    unit = db.session.get(Unit, unit_id)
    if unit is None or unit.house.landlord_id != current_user.id:
        abort(404)
    return unit


def _own_tenant(tenant_id: int) -> Tenant:
    tenant = db.session.get(Tenant, tenant_id)
    if tenant is None or tenant.landlord_id != current_user.id:
        abort(404)
    return tenant


def _own_payment(payment_id: int) -> Payment:
    payment = db.session.get(Payment, payment_id)
    if payment is None or payment.landlord_id != current_user.id:
        abort(404)
    return payment


def _csv(filename: str, text: str) -> Response:
    return Response(
        text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@main_bp.route("/")
@login_required
def dashboard():
    today = today_lusaka()
    refresh_book(current_user, today)
    report = income_report(current_user, today.year, today.month, today)
    beds = occupancy(current_user)
    owing = arrears_rows(current_user, today)
    selected = report["selected"]
    return render_template(
        "dashboard.html",
        selected=selected,
        bar_pct=percent_of(selected["recorded"], selected["due"]),
        recorded_over_due=selected["recorded"] > selected["due"] and selected["due"] > 0,
        occupied=beds["occupied"],
        bed_count=beds["total"],
        arrears=owing[:5],
        arrears_count=len(owing),
        deadline_line=deadline_sentence(today),
    )


@main_bp.route("/properties", methods=["GET", "POST"])
@login_required
def properties():
    if request.method == "POST":
        name, error = required_text(request.form.get("name"), 120, "a property name")
        if error or name is None:
            flash(error or "Enter a property name.", "error")
            return redirect(url_for("main.properties"))
        address, error = required_text(request.form.get("address"), 200, "an address")
        if error or address is None:
            flash(error or "Enter an address.", "error")
            return redirect(url_for("main.properties"))
        city, error = optional_text(request.form.get("city"), 80)
        if error:
            flash(error, "error")
            return redirect(url_for("main.properties"))
        notes, error = optional_text(request.form.get("notes"), 500)
        if error:
            flash(error, "error")
            return redirect(url_for("main.properties"))
        prop = Property(
            landlord_id=current_user.id,
            name=name,
            address=address,
            city=city or "Lusaka",
            notes=notes,
        )
        db.session.add(prop)
        db.session.commit()
        flash("House saved.", "success")
        return redirect(url_for("main.property_detail", property_id=prop.id))
    rows = Property.query.filter_by(landlord_id=current_user.id).order_by(Property.name).all()
    return render_template("properties.html", properties=rows)


@main_bp.route("/properties/<int:property_id>", methods=["GET", "POST"])
@login_required
def property_detail(property_id: int):
    prop = _own_property(property_id)
    if request.method == "POST":
        name, error = required_text(request.form.get("name"), 120, "a property name")
        if error or name is None:
            flash(error or "Enter a property name.", "error")
            return redirect(url_for("main.property_detail", property_id=prop.id))
        address, error = required_text(request.form.get("address"), 200, "an address")
        if error or address is None:
            flash(error or "Enter an address.", "error")
            return redirect(url_for("main.property_detail", property_id=prop.id))
        city, error = optional_text(request.form.get("city"), 80)
        if error:
            flash(error, "error")
            return redirect(url_for("main.property_detail", property_id=prop.id))
        notes, error = optional_text(request.form.get("notes"), 500)
        if error:
            flash(error, "error")
            return redirect(url_for("main.property_detail", property_id=prop.id))
        prop.name = name
        prop.address = address
        prop.city = city or "Lusaka"
        prop.notes = notes
        db.session.commit()
        flash("House updated.", "success")
        return redirect(url_for("main.property_detail", property_id=prop.id))
    today = today_lusaka()
    refresh_book(current_user, today)
    numbers = [unit.sort_order for unit in prop.units]
    next_number = (max(numbers) if numbers else 0) + 1
    suggested = f"Bed {next_number}"
    while Unit.query.filter_by(property_id=prop.id, name=suggested).first() is not None:
        next_number += 1
        suggested = f"Bed {next_number}"
    return render_template(
        "property.html",
        property=prop,
        suggested_name=suggested,
        today=today,
    )


@main_bp.route("/properties/<int:property_id>/units", methods=["POST"])
@login_required
def unit_create(property_id: int):
    prop = _own_property(property_id)
    name, error = required_text(request.form.get("name"), 80, "a bed or unit name")
    if error or name is None:
        flash(error or "Enter a bed or unit name.", "error")
        return redirect(url_for("main.property_detail", property_id=prop.id))
    if Unit.query.filter_by(property_id=prop.id, name=name).first() is not None:
        flash("That bed name is already used in this house.", "error")
        return redirect(url_for("main.property_detail", property_id=prop.id))
    asking = None
    asking_raw = (request.form.get("asking_rent") or "").strip()
    if asking_raw:
        asking, error = parse_money(asking_raw)
        if error or asking is None:
            flash(error or "Enter the asking rent in kwacha.", "error")
            return redirect(url_for("main.property_detail", property_id=prop.id))
    next_sort = db.session.query(func.max(Unit.sort_order)).filter_by(property_id=prop.id).scalar()
    unit = Unit(
        property_id=prop.id,
        name=name,
        sort_order=(next_sort or 0) + 1,
        asking_rent=asking,
        notes="",
    )
    db.session.add(unit)
    db.session.commit()
    flash("Bed added.", "success")
    return redirect(url_for("main.property_detail", property_id=prop.id))


@main_bp.route("/units/<int:unit_id>/delete", methods=["POST"])
@login_required
def unit_delete(unit_id: int):
    unit = _own_unit(unit_id)
    property_id = unit.property_id
    try:
        delete_unit(unit)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("main.property_detail", property_id=property_id))
    flash("Bed removed.", "success")
    return redirect(url_for("main.property_detail", property_id=property_id))


@main_bp.route("/units/<int:unit_id>/move-in", methods=["POST"])
@login_required
def tenant_move_in(unit_id: int):
    unit = _own_unit(unit_id)
    back = url_for("main.property_detail", property_id=unit.property_id)
    if unit.active_tenant is not None:
        flash(f"{unit.name} already has a tenant. Move them out first.", "error")
        return redirect(back)
    name, error = required_text(request.form.get("name"), 120, "the tenant's name")
    if error or name is None:
        flash(error or "Enter the tenant's name.", "error")
        return redirect(back)
    phone, error = parse_phone(request.form.get("phone"), required=True)
    if error or not phone:
        flash(error or "Enter a phone number.", "error")
        return redirect(back)
    move_in, error = parse_day(request.form.get("move_in_date"))
    if error or move_in is None:
        flash(error or "Enter a valid date.", "error")
        return redirect(back)
    if move_in > today_lusaka():
        flash("Move-in can be today or a past date.", "error")
        return redirect(back)
    rent, error = parse_money(request.form.get("monthly_rent"))
    if error or rent is None:
        flash(error or "Enter the monthly rent.", "error")
        return redirect(back)
    deposit_raw = (request.form.get("deposit") or "").strip()
    deposit = Decimal("0.00")
    if deposit_raw:
        deposit, error = parse_money(deposit_raw)
        if error or deposit is None:
            flash(error or "Enter the deposit in kwacha.", "error")
            return redirect(back)
    notes, error = optional_text(request.form.get("notes"), 500)
    if error:
        flash(error, "error")
        return redirect(back)
    tenant = Tenant(
        unit_id=unit.id,
        landlord_id=current_user.id,
        name=name,
        phone=phone,
        move_in_date=move_in,
        monthly_rent=rent,
        deposit=deposit,
        notes=notes,
    )
    db.session.add(tenant)
    db.session.flush()
    ensure_charges(tenant, today_lusaka())
    db.session.commit()
    flash("Tenant moved in. The months from move-in are on the book.", "success")
    return redirect(url_for("main.tenant_detail", tenant_id=tenant.id))


@main_bp.route("/tenants/<int:tenant_id>")
@login_required
def tenant_detail(tenant_id: int):
    tenant = _own_tenant(tenant_id)
    today = today_lusaka()
    ensure_charges(tenant, today)
    db.session.commit()
    charges = (
        RentCharge.query.filter_by(tenant_id=tenant.id)
        .order_by(RentCharge.due_date, RentCharge.id)
        .all()
    )
    open_charges = [charge for charge in charges if charge.balance > 0]
    default = open_charges[0] if open_charges else (charges[-1] if charges else None)
    default_amount = ""
    if default is not None and default.balance > 0:
        default_amount = f"{default.balance:.2f}"
    return render_template(
        "tenant.html",
        tenant=tenant,
        charges=charges,
        default_charge=default,
        default_amount=default_amount,
        whatsapp=whatsapp_for_tenant(tenant, today),
        arrears=tenant.arrears_on(today),
        today=today,
        methods=PAYMENT_METHODS,
    )


@main_bp.route("/tenants/<int:tenant_id>/edit", methods=["POST"])
@login_required
def tenant_edit(tenant_id: int):
    tenant = _own_tenant(tenant_id)
    back = url_for("main.tenant_detail", tenant_id=tenant.id)
    name, error = required_text(request.form.get("name"), 120, "the tenant's name")
    if error or name is None:
        flash(error or "Enter the tenant's name.", "error")
        return redirect(back)
    phone, error = parse_phone(request.form.get("phone"), required=True)
    if error or not phone:
        flash(error or "Enter a phone number.", "error")
        return redirect(back)
    rent, error = parse_money(request.form.get("monthly_rent"))
    if error or rent is None:
        flash(error or "Enter the monthly rent.", "error")
        return redirect(back)
    deposit_raw = (request.form.get("deposit") or "").strip()
    deposit = Decimal("0.00")
    if deposit_raw:
        deposit, error = parse_money(deposit_raw)
        if error or deposit is None:
            flash(error or "Enter the deposit.", "error")
            return redirect(back)
    notes, error = optional_text(request.form.get("notes"), 500)
    if error:
        flash(error, "error")
        return redirect(back)
    tenant.name = name
    tenant.phone = phone
    tenant.monthly_rent = rent
    tenant.deposit = deposit
    tenant.notes = notes
    db.session.commit()
    flash(
        "Saved. Months already on the book keep their rent due. New months use the new rent.",
        "success",
    )
    return redirect(back)


@main_bp.route("/tenants/<int:tenant_id>/move-out", methods=["POST"])
@login_required
def tenant_move_out(tenant_id: int):
    tenant = _own_tenant(tenant_id)
    back = url_for("main.tenant_detail", tenant_id=tenant.id)
    move_out, error = parse_day(request.form.get("move_out_date"))
    if error or move_out is None:
        flash(error or "Enter a valid date.", "error")
        return redirect(back)
    try:
        apply_move_out(tenant, move_out)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(back)
    flash("Moved out. The bed is free. Their book stays.", "success")
    return redirect(back)


@main_bp.route("/tenants/<int:tenant_id>/delete", methods=["POST"])
@login_required
def tenant_delete(tenant_id: int):
    tenant = _own_tenant(tenant_id)
    property_id = tenant.unit.property_id
    try:
        delete_tenant(tenant)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("main.tenant_detail", tenant_id=tenant_id))
    flash("Tenant removed.", "success")
    return redirect(url_for("main.property_detail", property_id=property_id))


@main_bp.route("/tenants/<int:tenant_id>/charges", methods=["POST"])
@login_required
def charge_edit(tenant_id: int):
    tenant = _own_tenant(tenant_id)
    back = url_for("main.tenant_detail", tenant_id=tenant.id)
    charge_id = request.form.get("charge_id", type=int)
    charge = db.session.get(RentCharge, charge_id) if charge_id else None
    if charge is None or charge.tenant_id != tenant.id:
        flash("Choose a month on this tenant's book.", "error")
        return redirect(back)
    amount, error = parse_money(request.form.get("amount_due"))
    if error or amount is None:
        flash(error or "Enter the rent due.", "error")
        return redirect(back)
    try:
        update_charge_amount(charge, amount)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(back)
    flash("Rent due for that month was updated. Other months are unchanged.", "success")
    return redirect(back)


@main_bp.route("/tenants/<int:tenant_id>/payments", methods=["POST"])
@login_required
def payment_create(tenant_id: int):
    tenant = _own_tenant(tenant_id)
    back = url_for("main.tenant_detail", tenant_id=tenant.id)
    charge_id = request.form.get("charge_id", type=int)
    charge = db.session.get(RentCharge, charge_id) if charge_id else None
    if charge is None or charge.tenant_id != tenant.id:
        flash("Choose the month this payment covers.", "error")
        return redirect(back)
    amount, error = parse_money(request.form.get("amount"))
    if error or amount is None or amount <= 0:
        flash("Enter an amount more than zero.", "error")
        return redirect(back)
    paid_on, error = parse_day(request.form.get("paid_on"))
    if error or paid_on is None:
        flash(error or "Enter the date they paid you.", "error")
        return redirect(back)
    if paid_on > today_lusaka():
        flash("Use the date the tenant actually paid you.", "error")
        return redirect(back)
    method, error = parse_method(request.form.get("method"))
    if error or method is None:
        flash(error or "Choose how the tenant paid you.", "error")
        return redirect(back)
    reference, error = parse_reference(method, request.form.get("reference"))
    if error or reference is None:
        flash(error or "Enter the reference.", "error")
        return redirect(back)
    notes, error = optional_text(request.form.get("notes"), 300)
    if error:
        flash(error, "error")
        return redirect(back)
    try:
        payment = record_payment(
            tenant=tenant,
            charge=charge,
            amount=amount,
            paid_on=paid_on,
            method=method,
            reference=reference,
            notes=notes,
        )
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(back)
    flash("Payment recorded. This is a record only.", "success")
    return redirect(url_for("main.receipt", payment_id=payment.id))


@main_bp.route("/payments/<int:payment_id>/delete", methods=["POST"])
@login_required
def payment_delete(payment_id: int):
    payment = _own_payment(payment_id)
    tenant_id = payment.tenant_id
    db.session.delete(payment)
    db.session.commit()
    flash("Payment record removed.", "success")
    return redirect(url_for("main.tenant_detail", tenant_id=tenant_id))


@main_bp.route("/receipts/<int:payment_id>")
@login_required
def receipt(payment_id: int):
    payment = _own_payment(payment_id)
    return render_template("receipt.html", payment=payment)


@main_bp.route("/arrears")
@login_required
def arrears():
    today = today_lusaka()
    refresh_book(current_user, today)
    rows = arrears_rows(current_user, today)
    return render_template("arrears.html", rows=rows)


@main_bp.route("/income")
@login_required
def income():
    today = today_lusaka()
    refresh_book(current_user, today)
    year, month = parse_month_param(request.args.get("month"), today)
    report = income_report(current_user, year, month, today)
    return render_template(
        "income.html",
        deadline=filing_deadline(date(year, month, 1)),
        **report,
    )


@main_bp.route("/export/payments.csv")
@login_required
def export_payments():
    today = today_lusaka()
    query = Payment.query.filter_by(landlord_id=current_user.id)
    raw = request.args.get("month")
    filename = "payments.csv"
    if raw:
        year, month = parse_month_param(raw, today)
        start = date(year, month, 1)
        end = month_end(year, month)
        query = query.filter(Payment.paid_on >= start, Payment.paid_on <= end)
        filename = f"payments-{year}-{month:02d}.csv"
    payments = query.order_by(Payment.paid_on, Payment.id).all()
    return _csv(filename, payments_csv(payments))


@main_bp.route("/export/arrears.csv")
@login_required
def export_arrears():
    today = today_lusaka()
    refresh_book(current_user, today)
    rows = arrears_rows(current_user, today)
    return _csv("arrears.csv", arrears_csv(rows))


@main_bp.route("/export/income.csv")
@login_required
def export_income():
    today = today_lusaka()
    refresh_book(current_user, today)
    raw = request.args.get("month")
    if raw:
        year, month = parse_month_param(raw, today)
    else:
        year, month = today.year, today.month
    report = income_report(current_user, year, month, today)
    return _csv(f"income-{year}.csv", income_csv(report["rows"]))
