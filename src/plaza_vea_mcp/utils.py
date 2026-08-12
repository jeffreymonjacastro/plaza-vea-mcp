"""Small shared helpers."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urljoin

RESOURCE_TOTAL_RE = re.compile(r"\d+-\d+/(\d+)")


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return " ".join(without_marks.casefold().split())


def soles_to_cents(value: object) -> int:
    if value is None:
        return 0
    amount = Decimal(str(value)) * 100
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def absolute_url(base_url: str, value: str | None) -> str:
    if not value:
        return ""
    return urljoin(f"{base_url.rstrip('/')}/", value)


def parse_resource_total(value: str | None, fallback: int) -> int:
    if not value:
        return fallback
    match = RESOURCE_TOTAL_RE.search(value)
    return int(match.group(1)) if match else fallback
