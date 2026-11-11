from dataclasses import dataclass, field


@dataclass
class Table:
    """A finished report, independent of how it is shown (web page, CSV, PDF)."""

    title: str
    subtitle: str
    headers: list
    rows: list
    notes: list = field(default_factory=list)
