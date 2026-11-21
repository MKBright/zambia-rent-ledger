"""Login, registration, and the landlord's own account.

Passwords are stored as a hash. The database does not keep the password
itself. A hash is a one-way scramble: login checks the scramble, and
nobody who opens the database file can read the password back.
"""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app import db
from app.checks import parse_email, parse_phone, required_text, safe_next
from app.copy import SAMPLE_EMAIL, SAMPLE_PASSWORD
from app.models import Landlord

auth_bp = Blueprint("auth", __name__)


def _show_sample_login() -> bool:
    sample = Landlord.query.filter_by(is_sample=True).first()
    return sample is not None and sample.check_password(SAMPLE_PASSWORD)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "GET":
        nxt = safe_next(request.args.get("next"))
    else:
        nxt = safe_next(request.form.get("next"))
    show_sample = _show_sample_login()
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = Landlord.query.filter_by(email=email).first()
        if user is None or not user.check_password(password):
            flash("Email or password is not correct.", "error")
            return render_template(
                "login.html",
                email=email,
                next_url=nxt or "",
                show_sample=show_sample,
                sample_email=SAMPLE_EMAIL,
                sample_password=SAMPLE_PASSWORD,
            )
        login_user(user, remember=request.form.get("remember") == "yes")
        return redirect(nxt or url_for("main.dashboard"))
    return render_template(
        "login.html",
        email="",
        next_url=nxt or "",
        show_sample=show_sample,
        sample_email=SAMPLE_EMAIL,
        sample_password=SAMPLE_PASSWORD,
    )


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        name, error = required_text(request.form.get("name"), 120, "your name")
        if error:
            flash(error, "error")
            return _register_page()
        email, error = parse_email(request.form.get("email"))
        if error or email is None:
            flash(error or "Enter a valid email address.", "error")
            return _register_page()
        phone, error = parse_phone(request.form.get("phone"), required=True)
        if error or phone is None:
            flash(error or "Enter a phone number.", "error")
            return _register_page()
        password = request.form.get("password") or ""
        if len(password) < 8 or len(password) > 128:
            flash("Password must be at least 8 characters.", "error")
            return _register_page()
        if password != (request.form.get("confirm") or ""):
            flash("Passwords do not match.", "error")
            return _register_page()
        if Landlord.query.filter_by(email=email).first() is not None:
            flash("That email is already registered. Log in instead.", "error")
            return _register_page()
        landlord = Landlord(name=name, email=email, phone=phone, is_sample=False)
        landlord.set_password(password)
        db.session.add(landlord)
        db.session.commit()
        login_user(landlord)
        flash("Account created. Add your first house when you are ready.", "success")
        return redirect(url_for("main.dashboard"))
    return _register_page()


def _register_page():
    return render_template("register.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You are logged out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        name, error = required_text(request.form.get("name"), 120, "your name")
        if error or name is None:
            flash(error or "Enter your name.", "error")
            return redirect(url_for("auth.account"))
        phone, error = parse_phone(request.form.get("phone"), required=False)
        if error or phone is None:
            flash(error or "Enter a phone number.", "error")
            return redirect(url_for("auth.account"))
        current = request.form.get("current_password") or ""
        new = request.form.get("new_password") or ""
        confirm = request.form.get("confirm") or ""
        if current or new or confirm:
            if not current_user.check_password(current):
                flash("Current password is not correct.", "error")
                return redirect(url_for("auth.account"))
            if len(new) < 8 or len(new) > 128:
                flash("New password must be at least 8 characters.", "error")
                return redirect(url_for("auth.account"))
            if new != confirm:
                flash("New passwords do not match.", "error")
                return redirect(url_for("auth.account"))
            current_user.set_password(new)
        current_user.name = name
        current_user.phone = phone
        db.session.commit()
        flash("Account saved.", "success")
        return redirect(url_for("auth.account"))
    return render_template("account.html")
