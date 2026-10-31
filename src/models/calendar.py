"""Pydantic models for Airbnb calendar data validation."""

import math
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, computed_field, field_validator


def _is_missing(v: object) -> bool:
    """Return True for values that should be treated as absent.

    Covers ``None``, empty/whitespace strings and NaN values produced by pandas
    for empty CSV cells.
    """
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() == ""
    if isinstance(v, float):
        return math.isnan(v)
    if isinstance(v, Decimal):
        return v.is_nan()
    return False


#: Calendar columns coerced to integers (``listing_id`` is handled separately
#: because Pydantic already coerces it without a ``before`` validator).
CALENDAR_INT_FIELDS: tuple[str, ...] = ("minimum_nights", "maximum_nights")

#: Calendar columns normalized to the canonical ``'t'``/``'f'`` text flag.
CALENDAR_BOOL_STR_FIELDS: tuple[str, ...] = ("available",)

#: Every calendar column in CSV order, used by the vectorized normalizer.
CALENDAR_FIELDS: tuple[str, ...] = (
    "listing_id",
    "date",
    "available",
    "minimum_nights",
    "maximum_nights",
)


class CalendarRaw(BaseModel):
    """Raw calendar model matching CSV structure.

    ``available`` is kept as the canonical TEXT flag ``'t'``/``'f'`` to match
    the ``raw.calendar.available CHAR(1)`` column and the raw -> staging
    transform, which parses the flag with ``lower(available) IN ('t', ...)``.
    """

    listing_id: int
    date: date
    # Canonical 't'/'f' text stored in the raw layer. Optional because an empty
    # CSV cell is normalized to ``None`` by the validator below; such rows are
    # filtered out of staging (``WHERE available IS NOT NULL``).
    available: str | None = None
    minimum_nights: int | None = None
    maximum_nights: int | None = None

    @field_validator(*CALENDAR_BOOL_STR_FIELDS, mode="before")
    @classmethod
    def parse_available(cls, v):
        # Normalize to the canonical 't'/'f' text stored in the raw layer.
        if _is_missing(v):
            return None
        if isinstance(v, bool):
            return "t" if v else "f"
        return "t" if str(v).strip().lower() in ("t", "true", "1", "yes", "y") else "f"


class CalendarStaging(BaseModel):
    """Staging model with cleaned and typed fields for analytics."""

    listing_id: int
    date: date
    available: bool  # True = available, False = booked
    minimum_nights: int | None = None
    maximum_nights: int | None = None

    model_config = {
        "from_attributes": True,
    }

    @classmethod
    def from_raw(cls, raw: CalendarRaw) -> "CalendarStaging":
        """Create staging model from raw model with derived fields.

        ``available`` is ``None`` when the raw cell was empty; treat anything
        other than the canonical ``'t'`` as not available.
        """
        return cls(
            listing_id=raw.listing_id,
            date=raw.date,
            available=(raw.available or "").strip().lower() == "t",
            minimum_nights=raw.minimum_nights,
            maximum_nights=raw.maximum_nights,
        )

    @computed_field
    @property
    def year(self) -> int:
        return self.date.year

    @computed_field
    @property
    def month(self) -> int:
        return self.date.month

    @computed_field
    @property
    def day(self) -> int:
        return self.date.day

    @computed_field
    @property
    def day_of_week(self) -> int:
        return self.date.weekday()

    @computed_field
    @property
    def week_of_year(self) -> int:
        return self.date.isocalendar().week

    @computed_field
    @property
    def quarter(self) -> int:
        return (self.date.month - 1) // 3 + 1

    @computed_field
    @property
    def is_weekend(self) -> bool:
        return self.date.weekday() >= 5
