"""Small helpers for the Bootstrap templates."""
from django import template

register = template.Library()

_STATUS_COLOURS = {
    "upcoming": "info",
    "on_leave": "success",
    "overdue": "danger",
    "returned": "secondary",
    "cancelled": "secondary",
}


@register.filter
def bs(field):
    """Render a form field with the Bootstrap class that suits its widget."""
    widget = field.field.widget
    kind = widget.__class__.__name__
    if kind in ("CheckboxSelectMultiple", "RadioSelect"):
        return field.as_widget()  # these carry their own form-check classes
    if kind == "CheckboxInput":
        css = "form-check-input"
    elif kind in ("Select", "SelectMultiple", "NullBooleanSelect"):
        css = "form-select"
    else:
        css = "form-control"
    if field.errors:
        css += " is-invalid"
    existing = widget.attrs.get("class", "")
    return field.as_widget(attrs={"class": f"{existing} {css}".strip()})


@register.filter
def initials(name):
    """Two capital letters for an avatar: "Alice Anand" -> "AA"."""
    parts = [p for p in str(name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:1].upper()
    return (parts[0][0] + parts[-1][0]).upper()


@register.filter
def status_colour(status):
    """Bootstrap colour name for a permit status."""
    return _STATUS_COLOURS.get(status, "secondary")
