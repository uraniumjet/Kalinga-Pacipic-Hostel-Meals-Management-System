"""Printable student ID cards as PDF, at the standard bank-card size (ISO/IEC 7810 ID-1, 85.60 x 53.98 mm).

Two layouts:
  * "card":  one card per page, page size = card size. For a card printer or a print shop.
  * "sheet": ten cards per A4 page with thin cut lines. For an office printer; print double-sided,
             flip on the long edge, and the backs line up behind the fronts.

Each student gets a front (logo, organisation name, photo, details) and a back (QR code, return notice, signature).
This module only draws; it knows nothing about Django models, so it can be tested and previewed on its own.
"""
import colorsys
import unicodedata
from dataclasses import dataclass
from datetime import date
from io import BytesIO

from PIL import Image, ImageOps
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

CARD_W = 85.60 * mm
CARD_H = 53.98 * mm
CORNER = 3.18 * mm
DEFAULT_COLOUR = "#0f766e"
GAP = 2 * mm  # space between cards on a sheet
COLUMNS, ROWS = 2, 5
HEADER_H = 12 * mm
FOOTER_H = 5.5 * mm

INK = (0.09, 0.11, 0.16)
MUTED = (0.35, 0.40, 0.47)


@dataclass
class CardData:
    name: str
    roll_number: str
    qr_token: str
    category: str = ""
    course: str = ""
    room: str = ""
    photo: bytes | None = None


@dataclass
class OrgData:
    name: str
    logo: bytes | None = None
    colour: str | None = None  # "#rrggbb"; taken from the logo when empty


# ---------------------------------------------------------------- text helpers
def latin(text):
    """Text the built-in PDF fonts can print: accents are kept when possible, anything else becomes '?'."""
    text = unicodedata.normalize("NFC", str(text or "")).strip()
    out = []
    for ch in text:
        try:
            ch.encode("latin-1")
            out.append(ch)
        except UnicodeEncodeError:
            base = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
            out.append(base or "?")
    return "".join(out)


def fit_lines(text, font, size, width, max_lines, min_size):
    """Wrap text into at most max_lines lines, shrinking the font until it fits. Returns (lines, size)."""
    size = float(size)
    while True:
        lines = simpleSplit(text, font, size, width)
        if len(lines) <= max_lines and all(stringWidth(line, font, size) <= width for line in lines):
            return lines, size
        if size <= min_size:
            lines = lines[:max_lines]
            if lines and stringWidth(lines[-1], font, size) > width:
                while lines[-1] and stringWidth(lines[-1] + "...", font, size) > width:
                    lines[-1] = lines[-1][:-1]
                lines[-1] = lines[-1].rstrip() + "..."
            return lines, size
        size -= 0.25


# --------------------------------------------------------------- colour helpers
def _hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _ensure_readable(rgb):
    """Darken a colour until white text on top of it is easy to read."""
    r, g, b = rgb
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    while luminance > 0.42 and v > 0.15:
        v *= 0.9
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return (r, g, b)


def dominant_colour(logo_bytes):
    """The most characteristic colour of a logo as '#rrggbb' (ignores transparent, white and grey pixels)."""
    try:
        image = Image.open(BytesIO(logo_bytes)).convert("RGBA")
        image.thumbnail((64, 64))
    except Exception:
        return DEFAULT_COLOUR
    counts = {}
    for r, g, b, a in image.getdata():
        if a < 128:
            continue
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if s < 0.25 or v < 0.15 or v > 0.97:
            continue
        key = (r // 24, g // 24, b // 24)
        total, count = counts.get(key, ((0, 0, 0), 0))
        counts[key] = ((total[0] + r, total[1] + g, total[2] + b), count + 1)
    if not counts:
        return DEFAULT_COLOUR
    (rs, gs, bs), count = max(counts.values(), key=lambda item: item[1])
    r, g, b = _ensure_readable((rs / count / 255, gs / count / 255, bs / count / 255))
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


# ------------------------------------------------------------------ image helpers
def _fit_photo(photo_bytes, width_pt, height_pt):
    """Crop a photo to the frame (cover, aiming a little above centre so faces stay in) and return an ImageReader."""
    try:
        image = ImageOps.exif_transpose(Image.open(BytesIO(photo_bytes))).convert("RGB")
    except Exception:
        return None
    pixels = (int(width_pt / 72 * 300), int(height_pt / 72 * 300))
    return ImageReader(ImageOps.fit(image, pixels, Image.LANCZOS, centering=(0.5, 0.3)))


def _logo_reader(logo_bytes):
    try:
        image = Image.open(BytesIO(logo_bytes)).convert("RGBA")
    except Exception:
        return None, 1.0
    return ImageReader(image), image.width / image.height


def qr_reader(token):
    import qrcode  # imported here so the module can be previewed without the package

    return ImageReader(qrcode.make(str(token), box_size=10, border=1).convert("RGB"))


# ------------------------------------------------------------------ card faces
def _fill(c, rgb):
    c.setFillColorRGB(*rgb)


def _draw_header(c, org, colour):
    _fill(c, colour)
    c.rect(0, CARD_H - HEADER_H, CARD_W, HEADER_H, stroke=0, fill=1)
    text_x = 4 * mm
    logo, ratio = _logo_reader(org.logo) if org.logo else (None, 1.0)
    if logo is not None:
        box = 9.4 * mm
        pad = 0.9 * mm
        _fill(c, (1, 1, 1))
        c.roundRect(3 * mm, CARD_H - HEADER_H + (HEADER_H - box) / 2, box, box, 1.6 * mm, stroke=0, fill=1)
        inner = box - 2 * pad
        w, h = (inner, inner / ratio) if ratio >= 1 else (inner * ratio, inner)
        c.drawImage(logo, 3 * mm + (box - w) / 2, CARD_H - HEADER_H + (HEADER_H - h) / 2, w, h, mask="auto")
        text_x = 3 * mm + box + 2.5 * mm
    lines, size = fit_lines(latin(org.name).upper(), "Helvetica-Bold", 8.5, CARD_W - text_x - 3 * mm, 2, 5.5)
    _fill(c, (1, 1, 1))
    c.setFont("Helvetica-Bold", size)
    leading = size * 1.18
    top = CARD_H - HEADER_H / 2 + (len(lines) - 1) * leading / 2 - size * 0.33
    for i, line in enumerate(lines):
        c.drawString(text_x, top - i * leading, line)


def _draw_footer(c, colour, label):
    _fill(c, colour)
    c.rect(0, 0, CARD_W, FOOTER_H, stroke=0, fill=1)
    _fill(c, (1, 1, 1))
    c.setFont("Helvetica-Bold", 5.2)
    c.drawCentredString(CARD_W / 2, FOOTER_H / 2 - 1.8, label)


def _draw_initials(c, name, x, y, w, h, colour):
    _fill(c, (0.93, 0.95, 0.96))
    c.roundRect(x, y, w, h, 1.5 * mm, stroke=0, fill=1)
    parts = [p for p in latin(name).split() if p]
    initials = (parts[0][0] + parts[-1][0]).upper() if len(parts) > 1 else (parts[0][:2].upper() if parts else "?")
    _fill(c, colour)
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(x + w / 2, y + h / 2 - 7, initials)


def draw_front(c, card, org, colour):
    _fill(c, (1, 1, 1))
    c.rect(0, 0, CARD_W, CARD_H, stroke=0, fill=1)
    _draw_header(c, org, colour)
    _draw_footer(c, colour, "STUDENT IDENTITY CARD")

    photo_w, photo_h = 24 * mm, 30 * mm
    photo_x, photo_y = 4 * mm, FOOTER_H + 3 * mm
    reader = _fit_photo(card.photo, photo_w, photo_h) if card.photo else None
    if reader is not None:
        c.drawImage(reader, photo_x, photo_y, photo_w, photo_h)
    else:
        _draw_initials(c, card.name, photo_x, photo_y, photo_w, photo_h, colour)
    c.setStrokeColorRGB(*colour)
    c.setLineWidth(0.6)
    c.roundRect(photo_x, photo_y, photo_w, photo_h, 1 * mm, stroke=1, fill=0)

    x = photo_x + photo_w + 3.5 * mm
    width = CARD_W - x - 3 * mm
    top = CARD_H - HEADER_H - 4.2 * mm
    lines, size = fit_lines(latin(card.name), "Helvetica-Bold", 10.5, width, 2, 7.5)
    _fill(c, INK)
    c.setFont("Helvetica-Bold", size)
    for i, line in enumerate(lines):
        c.drawString(x, top - i * size * 1.15, line)
    y = top - len(lines) * size * 1.15 - 1.6 * mm

    rows = [("Roll no.", card.roll_number), ("Course", card.course), ("Category", card.category), ("Room", card.room)]
    for label, value in rows:
        value = latin(value)
        if not value:
            continue
        _fill(c, MUTED)
        c.setFont("Helvetica", 5)
        c.drawString(x, y, label.upper())
        _fill(c, INK)
        c.setFont("Helvetica-Bold", 7.4)
        shown, _ = fit_lines(value, "Helvetica-Bold", 7.4, width, 1, 5.5)
        c.drawString(x, y - 6.2, shown[0] if shown else "")
        y -= 13.6


def draw_back(c, card, org, colour, issued):
    _fill(c, (1, 1, 1))
    c.rect(0, 0, CARD_W, CARD_H, stroke=0, fill=1)
    _fill(c, colour)
    c.rect(0, CARD_H - 5 * mm, CARD_W, 5 * mm, stroke=0, fill=1)
    _draw_footer(c, colour, latin(org.name).upper()[:60])

    qr = 29 * mm
    qr_x, qr_y = 5 * mm, FOOTER_H + 8.5 * mm
    c.drawImage(qr_reader(card.qr_token), qr_x, qr_y, qr, qr, mask="auto")
    _fill(c, MUTED)
    c.setFont("Helvetica", 5.4)
    c.drawCentredString(qr_x + qr / 2, qr_y - 3.4 * mm, "SCAN AT THE MEAL COUNTER")

    x = qr_x + qr + 5 * mm
    width = CARD_W - x - 4 * mm
    y = CARD_H - 5 * mm - 5 * mm
    lines, size = fit_lines(latin(card.name), "Helvetica-Bold", 8.5, width, 2, 6.5)
    _fill(c, INK)
    c.setFont("Helvetica-Bold", size)
    for i, line in enumerate(lines):
        c.drawString(x, y - i * size * 1.15, line)
    y -= len(lines) * size * 1.15 + 0.6 * mm
    c.setFont("Helvetica", 6.6)
    _fill(c, MUTED)
    c.drawString(x, y, f"Roll no. {latin(card.roll_number)}")
    y -= 3.2 * mm
    c.drawString(x, y, f"Issued {issued.strftime('%d %b %Y')}")
    y -= 4.4 * mm

    notice = f"This card belongs to {latin(org.name)}. If found, please return it to the hostel office."
    c.setFont("Helvetica", 5.3)
    for line in simpleSplit(notice, "Helvetica", 5.3, width)[:4]:
        c.drawString(x, y, line)
        y -= 2.3 * mm

    line_y = FOOTER_H + 6.2 * mm
    c.setStrokeColorRGB(*MUTED)
    c.setLineWidth(0.4)
    c.line(x, line_y, x + width, line_y)
    c.setFont("Helvetica", 4.8)
    c.drawString(x, line_y - 2.2 * mm, "Authorised signatory")


# ------------------------------------------------------------------ layout
def sheet_slots():
    """Lower-left corner of each of the ten card slots on an A4 page, in reading order (row by row)."""
    page_w, page_h = A4
    x0 = (page_w - (COLUMNS * CARD_W + (COLUMNS - 1) * GAP)) / 2
    y_top = (page_h + (ROWS * CARD_H + (ROWS - 1) * GAP)) / 2
    slots = []
    for row in range(ROWS):
        for col in range(COLUMNS):
            slots.append((col, row, x0 + col * (CARD_W + GAP), y_top - (row + 1) * CARD_H - row * GAP))
    return slots


def mirrored_slot(index):
    """Slot on the back page that sits behind slot `index` when the sheet is flipped on its long edge."""
    row, col = divmod(index, COLUMNS)
    return row * COLUMNS + (COLUMNS - 1 - col)


def _place(c, x, y, draw, outline=False):
    c.saveState()
    c.translate(x, y)
    path = c.beginPath()
    path.roundRect(0, 0, CARD_W, CARD_H, CORNER)
    c.clipPath(path, stroke=0, fill=0)
    draw()
    c.restoreState()
    if outline:
        c.saveState()
        c.setStrokeColorRGB(0.6, 0.6, 0.6)
        c.setLineWidth(0.25)
        c.roundRect(x, y, CARD_W, CARD_H, CORNER, stroke=1, fill=0)
        c.restoreState()


def build_pdf(cards, org, mode="card", issued=None):
    """Return the PDF bytes for the given cards. mode is "card" (one per page) or "sheet" (ten per A4 page)."""
    issued = issued or date.today()
    colour = _hex_to_rgb(org.colour) if org.colour else _hex_to_rgb(dominant_colour(org.logo) if org.logo else DEFAULT_COLOUR)
    buffer = BytesIO()
    if mode == "sheet":
        c = canvas.Canvas(buffer, pagesize=A4)
        slots = sheet_slots()
        per_page = len(slots)
        c.setTitle("Student ID cards (A4 sheets, print double-sided, flip on long edge)")
        for start in range(0, len(cards), per_page):
            batch = cards[start : start + per_page]
            for side in ("front", "back"):
                c.setFont("Helvetica", 6)
                c.setFillColorRGB(*MUTED)
                c.drawCentredString(A4[0] / 2, A4[1] - 6 * mm, f"{side.upper()} - double-sided, flip on long edge")
                for i, card in enumerate(batch):
                    slot = slots[i] if side == "front" else slots[mirrored_slot(i)]
                    if side == "front":
                        _place(c, slot[2], slot[3], lambda card=card: draw_front(c, card, org, colour), outline=True)
                    else:
                        _place(c, slot[2], slot[3], lambda card=card: draw_back(c, card, org, colour, issued), outline=True)
                c.showPage()
    else:
        c = canvas.Canvas(buffer, pagesize=(CARD_W, CARD_H))
        c.setTitle("Student ID cards (one card per page)")
        for card in cards:
            draw_front(c, card, org, colour)
            c.showPage()
            draw_back(c, card, org, colour, issued)
            c.showPage()
    if not cards:
        c.showPage()
    c.save()
    return buffer.getvalue()
