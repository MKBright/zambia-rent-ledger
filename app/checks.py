"""Check what the landlord typed before it is saved.

Each function returns the cleaned value and an error message.
The error is None when the value is usable.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urljoin, urlparse

from flask import request

from app.ledger import PAYMENT_METHODS, ELECTRONIC_METHODS, money

_MONEY = re.compile(r"\d+(\.\d{1,2})?")


def required_text(value: str | None, limit: int, label: str) -> tuple[str | None, str | None]:
    text = " ".join((value or "").split())
    if not text:
        return None, f"Enter {label}."
    if len(text) > limit:
        return None, f"That is too long. Keep {label} under {limit} characters."
    return text, None


def optional_text(value: str | None, limit: int) -> tuple[str, str | None]:
    text = " ".join((value or "").split())
    if len(text) > limit:
        return "", "That note is too long."
    return text, None


def parse_money(raw: str | None) -> tuple[Decimal | None, str | None]:
    """Accept 900, 900.50, 1,250.50, or K900. Reject negatives and extra decimals."""
    cleaned = (raw or "").strip().replace(",", "").replace(" ", "")
    if cleaned[:1] in {"K", "k"}:
        cleaned = cleaned[1:]
    if not cleaned or not _MONEY.fullmatch(cleaned):
        return None, "Enter an amount in kwacha, for example 900 or 900.50."
    return money(cleaned), None


def parse_day(raw: str | None) -> tuple[date | None, str | None]:
    try:
        return datetime.strptime((raw or "").strip(), "%Y-%m-%d").date(), None
    except ValueError:
        return None, "Enter a valid date."


def parse_phone(raw: str | None, required: bool = True) -> tuple[str | None, str | None]:
    text = (raw or "").strip()
    if not text:
        if required:
            return None, "Enter a phone number with at least 9 digits, for example 0971234567."
        return "", None
    digits = re.sub(r"\D", "", text)
    if len(text) > 30 or len(digits) < 9 or len(digits) > 15:
        return None, "Enter a phone number with at least 9 digits, for example 0971234567."
    return text, None


def parse_email(raw: str | None) -> tuple[str | None, str | None]:
    email = (raw or "").strip().lower()
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return email, None
    return None, "Enter a valid email address."


def parse_method(raw: str | None) -> tuple[str | None, str | None]:
    method = (raw or "").strip()
    if method not in PAYMENT_METHODS:
        return None, "Choose how the tenant paid you."
    return method, None


def parse_reference(method: str, raw: str | None) -> tuple[str | None, str | None]:
    text = " ".join((raw or "").split())
    if len(text) > 80:
        return None, "The reference is too long."
    if method in ELECTRONIC_METHODS and not text:
        return None, "Enter the MoMo, Airtel Money, or bank reference."
    return text, None


def safe_next(target: str | None) -> str | None:
    """Allow a redirect only back to this site, not to another website."""
    if not target:
        return None
    host = urlparse(request.host_url)
    dest = urlparse(urljoin(request.host_url, target))
    if dest.scheme in {"http", "https"} and dest.netloc == host.netloc:
        return target
    return None
