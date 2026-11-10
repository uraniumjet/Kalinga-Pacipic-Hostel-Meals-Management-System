from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from .access import get_staff, is_admin


def staff_required(view):
    """Login required, and the user must have a staff profile. Sets request.staff."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        staff = get_staff(request.user)
        if staff is None:
            raise PermissionDenied("Your account is not set up for this system.")
        request.staff = staff
        return view(request, *args, **kwargs)

    return wrapper


def admin_required(view):
    """Like staff_required, and the role must be admin."""

    @wraps(view)
    @staff_required
    def wrapper(request, *args, **kwargs):
        if not is_admin(request.staff):
            raise PermissionDenied("Only an admin can do this.")
        return view(request, *args, **kwargs)

    return wrapper
