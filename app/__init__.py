"""Nyumba Book, a rent record for small landlords in Zambia.

The app writes down rent the landlord has already received.
It does not collect rent and it does not hold tenant money.
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, render_template
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFError, CSRFProtect
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base, session_options={"expire_on_commit": False})
login_manager = LoginManager()
csrf = CSRFProtect()

login_manager.login_view = "auth.login"
login_manager.login_message = "Log in to open your rent book."
login_manager.login_message_category = "info"

ROOT = Path(__file__).resolve().parent.parent


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(__name__, instance_path=str(ROOT / "instance"))
    os.makedirs(app.instance_path, exist_ok=True)
    db_path = Path(app.instance_path) / "nyumba.db"
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///" + db_path.as_posix()),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE="Lax",
        WTF_CSRF_TIME_LIMIT=None,
        MAX_CONTENT_LENGTH=256 * 1024,
    )
    if overrides:
        app.config.update(overrides)
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if isinstance(uri, str) and uri.startswith("sqlite"):
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"connect_args": {"check_same_thread": False}}

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app.auth import auth_bp
    from app.ledger import balance_phrase, format_date, format_kwacha, format_when, today_lusaka
    from app.models import Landlord
    from app.routes import main_bp

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(Landlord, int(user_id))

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    @app.context_processor
    def inject_globals():
        from app import copy

        return {
            "app_name": copy.APP_NAME,
            "tagline": copy.TAGLINE,
            "collect_note": copy.COLLECT_NOTE,
            "sample_banner": copy.SAMPLE_BANNER,
            "tax_disclaimer": copy.TAX_DISCLAIMER,
            "receipt_disclaimer": copy.RECEIPT_DISCLAIMER,
            "old_year_warning": copy.OLD_YEAR_WARNING,
            "nil_band_note": copy.NIL_BAND_NOTE,
            "date_note": copy.DATE_NOTE,
            "zra_url": copy.ZRA_URL,
            "today": today_lusaka(),
        }

    @app.template_filter("kwacha")
    def kwacha_filter(value):
        return format_kwacha(value)

    @app.template_filter("kwacha_whole")
    def kwacha_whole_filter(value):
        return format_kwacha(value, cents=False)

    @app.template_filter("pretty_date")
    def pretty_date_filter(value):
        if value is None:
            return ""
        return format_date(value)

    @app.template_filter("pretty_when")
    def pretty_when_filter(value):
        if value is None:
            return ""
        return format_when(value)

    @app.template_global("balance_phrase")
    def balance_phrase_global(value):
        return balance_phrase(value)

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("404.html"), 404

    @app.errorhandler(CSRFError)
    def handle_csrf(_error):
        return render_template("csrf.html"), 400

    with app.app_context():
        db.create_all()

    return app
