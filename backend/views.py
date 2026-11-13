import logging

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@require_GET
@never_cache
def healthz(request):
    """Liveness and database check for load balancers, Docker and uptime monitors. No login needed, no data shown."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        logger.exception("Health check failed: the database is not reachable")
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})
