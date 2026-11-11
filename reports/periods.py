"""Turning "daily / weekly / monthly / custom" into a start and end date."""
import calendar
from datetime import timedelta

MAX_DAYS = 366


def resolve_period(period, anchor, start, end):
    """Return (start, end), both inclusive. Raises ValueError with a message for the user."""
    if period == "day":
        return anchor, anchor
    if period == "week":
        monday = anchor - timedelta(days=anchor.weekday())
        return monday, monday + timedelta(days=6)
    if period == "month":
        last = calendar.monthrange(anchor.year, anchor.month)[1]
        return anchor.replace(day=1), anchor.replace(day=last)
    if period == "custom":
        if start is None or end is None:
            raise ValueError("Choose both dates for a custom range.")
        if end < start:
            raise ValueError("The end date cannot be before the start date.")
        if (end - start).days + 1 > MAX_DAYS:
            raise ValueError(f"A report can cover at most {MAX_DAYS} days.")
        return start, end
    raise ValueError("Unknown period.")
