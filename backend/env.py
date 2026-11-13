"""Small helpers that read configuration from environment variables (no third-party packages needed)."""
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

TRUE = {"1", "true", "yes", "on"}
FALSE = {"0", "false", "no", "off", ""}


def env_bool(name, default=False, environ=None):
    environ = os.environ if environ is None else environ
    raw = environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in TRUE:
        return True
    if value in FALSE:
        return False
    raise ValueError(f"{name} must be true or false, not {raw!r}")


def env_int(name, default, environ=None):
    environ = os.environ if environ is None else environ
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, not {raw!r}") from None


def env_list(name, default="", environ=None):
    environ = os.environ if environ is None else environ
    raw = environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def database_from_url(url, base_dir):
    """Turn DATABASE_URL into a Django DATABASES entry.

    sqlite:///db.sqlite3                      relative to the project folder
    sqlite:////var/lib/hostel/db.sqlite3      absolute path
    postgres://user:password@host:5432/name   PostgreSQL (needs the psycopg package)
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme in {"sqlite", "sqlite3"}:
        path = parsed.path[1:] or "db.sqlite3"
        name = Path(path) if Path(path).is_absolute() else Path(base_dir) / path
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": name}
    if scheme in {"postgres", "postgresql"}:
        name = parsed.path.lstrip("/")
        if not name or not parsed.hostname:
            raise ValueError("DATABASE_URL for PostgreSQL needs a host and a database name")
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(name),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname,
            "PORT": str(parsed.port or ""),
            "CONN_MAX_AGE": 60,
            "CONN_HEALTH_CHECKS": True,
        }
    raise ValueError(f"Unsupported DATABASE_URL scheme {scheme!r}; use sqlite or postgres")
