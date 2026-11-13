"""Turn a Table into CSV or PDF bytes. No Django here, so these can be tested on their own."""
import csv
import io
import os
from xml.sax.saxutils import escape

from .tables import Table

_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def _safe(cell):
    """Stop spreadsheet programs from running text such as =CMD(...) that came from user data."""
    if cell is None:
        return ""
    if isinstance(cell, str) and cell[:1] in _FORMULA_STARTS:
        return "'" + cell
    return cell


def to_csv(table: Table) -> bytes:
    """UTF-8 with a byte-order mark so Excel shows non-English names correctly."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([_safe(h) for h in table.headers])
    for row in table.rows:
        writer.writerow([_safe(cell) for cell in row])
    return buffer.getvalue().encode("utf-8-sig")


# ---------- PDF ----------

_FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
]
_fonts = None


def _pdf_fonts():
    """(regular, bold) font names. Uses a system Unicode font when one exists, else Helvetica."""
    global _fonts
    if _fonts is None:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        _fonts = ("Helvetica", "Helvetica-Bold")
        for regular, bold in _FONT_CANDIDATES:
            if os.path.exists(regular) and os.path.exists(bold):
                try:
                    pdfmetrics.registerFont(TTFont("ReportSans", regular))
                    pdfmetrics.registerFont(TTFont("ReportSans-Bold", bold))
                    _fonts = ("ReportSans", "ReportSans-Bold")
                    break
                except Exception:
                    continue
    return _fonts


def _column_widths(table, available):
    weights = []
    for index, header in enumerate(table.headers):
        longest = max([len(str(header)) * 0.7] + [min(len(str(row[index])), 40) for row in table.rows[:200]] or [0])
        weights.append(min(max(longest, 6), 40))
    total = sum(weights)
    return [available * w / total for w in weights]


def to_pdf(table: Table, heading: str = "", footer_note: str = "") -> bytes:
    """A landscape A4 PDF with a repeating header row and page numbers."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, TableStyle
    from reportlab.platypus import Table as PdfTable

    regular, bold = _pdf_fonts()
    title_style = ParagraphStyle("title", fontName=bold, fontSize=15, leading=19)
    meta_style = ParagraphStyle("meta", fontName=regular, fontSize=9, leading=12, textColor=colors.HexColor("#444444"))
    cell_style = ParagraphStyle("cell", fontName=regular, fontSize=8, leading=10)
    head_style = ParagraphStyle("head", fontName=bold, fontSize=8, leading=10, textColor=colors.white)
    note_style = ParagraphStyle("note", fontName=regular, fontSize=8.5, leading=11)

    class NumberedCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved = []

        def showPage(self):
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved)
            for state in self._saved:
                self.__dict__.update(state)
                self.setFont(regular, 8)
                self.setFillColor(colors.HexColor("#666666"))
                self.drawRightString(landscape(A4)[0] - 12 * mm, 8 * mm, f"Page {self._pageNumber} of {total}")
                if footer_note:
                    self.drawString(12 * mm, 8 * mm, footer_note)
                super().showPage()
            super().save()

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
        bottomMargin=16 * mm, title=table.title,
    )
    story = [Paragraph(escape(table.title), title_style)]
    for line in (heading, table.subtitle):
        if line:
            story.append(Paragraph(escape(line), meta_style))
    story.append(Spacer(1, 5 * mm))

    if table.rows:
        data = [[Paragraph(escape(str(h)), head_style) for h in table.headers]]
        for row in table.rows:
            data.append([Paragraph(escape("" if cell is None else str(cell)), cell_style) for cell in row])
        available = landscape(A4)[0] - 24 * mm
        grid = PdfTable(data, colWidths=_column_widths(table, available), repeatRows=1)
        grid.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f6f5c")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f4f6")]),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#d5dbe1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(grid)
    else:
        story.append(Paragraph("No records in this period.", note_style))

    if table.notes:
        story.append(Spacer(1, 5 * mm))
        for note in table.notes:
            story.append(Paragraph(escape(note), note_style))

    document.build(story, canvasmaker=NumberedCanvas)
    return buffer.getvalue()
