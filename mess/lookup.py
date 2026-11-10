"""Finding a student at the counter: scanned QR code, roll number, or part of a name."""
import uuid

from django.db.models import Q

from residents.models import Student


def find_students(organization, text, limit=10):
    text = text.strip()
    if not text:
        return []
    base = Student.objects.filter(organization=organization).select_related("category", "diet")
    try:
        token = uuid.UUID(text)
    except ValueError:
        pass
    else:
        return list(base.filter(qr_token=token)[:1])
    exact = base.filter(roll_number__iexact=text)[:1]
    if exact:
        return list(exact)
    matches = base.filter(Q(name__icontains=text) | Q(roll_number__icontains=text))
    return list(matches.order_by("name")[:limit])
