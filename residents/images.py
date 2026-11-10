"""Photo handling. Every student photo is shrunk and re-encoded before it is stored."""
import uuid
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps

MAX_SIDE = 400
MAX_UPLOAD_BYTES = 8 * 1024 * 1024


def normalize_photo(upload):
    """Return a small JPEG (longest side MAX_SIDE) made from an uploaded image."""
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError("The photo is larger than 8 MB.")
    try:
        image = Image.open(upload)
        image = ImageOps.exif_transpose(image).convert("RGB")
    except Exception:
        raise ValidationError("Upload a valid image file.")
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    buffer = BytesIO()
    image.save(buffer, "JPEG", quality=85, optimize=True)
    return ContentFile(buffer.getvalue(), name=f"{uuid.uuid4().hex}.jpg")
