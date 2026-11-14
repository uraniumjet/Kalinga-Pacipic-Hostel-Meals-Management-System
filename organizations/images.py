"""Organisation logo handling: validated, shrunk and re-encoded as PNG (transparency kept)."""
import uuid
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps

MAX_SIDE = 600
MAX_UPLOAD_BYTES = 2 * 1024 * 1024


def normalize_logo(upload):
    """Return a PNG (longest side MAX_SIDE) made from an uploaded image."""
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError("The logo is larger than 2 MB.")
    try:
        image = ImageOps.exif_transpose(Image.open(upload)).convert("RGBA")
    except Exception:
        raise ValidationError("Upload a valid image file.") from None
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    buffer = BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return ContentFile(buffer.getvalue(), name=f"{uuid.uuid4().hex}.png")
