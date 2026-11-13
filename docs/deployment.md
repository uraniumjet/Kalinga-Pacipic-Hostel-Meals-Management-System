# Deployment

The app is one Django service. It needs a database, a place for uploaded photos, and (for real use) https in front of it.

## Option A: Docker Compose (recommended)

```bash
cp .env.example .env
# edit .env: set DJANGO_DEBUG=0, a long DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS,
# POSTGRES_PASSWORD, and DJANGO_HTTPS / DJANGO_BEHIND_PROXY / DJANGO_CSRF_TRUSTED_ORIGINS if you use https
docker compose up -d --build
docker compose exec web python manage.py createsuperuser   # optional: only for /admin/
```

Open `http://SERVER:8000/` and click "Register it here" to create the first organisation and admin.
When you are done registering organisations, set `ALLOW_ORG_SIGNUP=0` in `.env` and run `docker compose up -d` again.

The container runs the database migrations and collects static files each time it starts.
Data lives in two named volumes: `pgdata` (database) and `appdata` (uploaded photos).

## Option B: without Docker

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-prod.txt
export DJANGO_DEBUG=0 DJANGO_SECRET_KEY=... DJANGO_ALLOWED_HOSTS=meals.example.org
python manage.py migrate
python manage.py collectstatic --noinput
gunicorn backend.wsgi:application --bind 127.0.0.1:8000 --workers 3
```

Run gunicorn under systemd (or similar) so it restarts, and put a reverse proxy in front of it.

## https

Put a reverse proxy in front (Caddy is the simplest, nginx also works) and let it handle the certificate.
Then set in `.env`:

```
DJANGO_HTTPS=1
DJANGO_BEHIND_PROXY=1
DJANGO_CSRF_TRUSTED_ORIGINS=https://meals.example.org
```

Minimal Caddyfile:

```
meals.example.org {
    reverse_proxy localhost:8000
}
```

On a closed hostel network without a certificate, leave `DJANGO_HTTPS=0`. The phone camera scanner and webcam photo
capture only work on `localhost` or https, so for those use https or a typed roll number / USB scanner.

## Settings reference

| Variable | Default | Meaning |
| --- | --- | --- |
| `DJANGO_DEBUG` | `1` | Set `0` on a server. With `0`, a real `DJANGO_SECRET_KEY` is required. |
| `DJANGO_SECRET_KEY` | development value | Long random string. Keep it secret and stable. |
| `DJANGO_ALLOWED_HOSTS` | `127.0.0.1,localhost` | Comma separated host names the site answers to. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | empty | `https://...` origins, needed behind a proxy on another host name. |
| `DJANGO_HTTPS` | `0` | `1` turns on https redirect, secure cookies and HSTS. |
| `DJANGO_BEHIND_PROXY` | `0` | `1` trusts `X-Forwarded-Proto` / `X-Forwarded-Host` from the proxy. |
| `DJANGO_HSTS_SECONDS` | `2592000` | HSTS lifetime (30 days). Raise it after https has worked for a while. |
| `DJANGO_SESSION_HOURS` | `12` | Hours before a user must sign in again. |
| `ALLOW_ORG_SIGNUP` | `1` | `0` hides the public registration page. |
| `DATABASE_URL` | SQLite file | `postgres://user:pass@host:5432/name` for PostgreSQL. |
| `SQLITE_PATH` | `db.sqlite3` | SQLite file location when `DATABASE_URL` is empty. |
| `DJANGO_MEDIA_ROOT` | `media/` | Where uploaded photos are stored. Use a persistent volume. |
| `DJANGO_LOG_LEVEL` | `INFO` | Log level on stdout. |

## Health check

`GET /healthz/` answers `{"status": "ok"}` (HTTP 200) when the app can reach its database, otherwise HTTP 503.
Docker uses it as the container health check; point an uptime monitor at it too.

## Backups

Back up the database and the photos together.

- PostgreSQL: `docker compose exec -T db pg_dump -U hostel hostel > backup-$(date +%F).sql`
- SQLite: `sqlite3 /data/db.sqlite3 ".backup '/data/backup.sqlite3'"` (do not copy the file while the app is writing)
- Photos: copy the `appdata` volume (or the folder in `DJANGO_MEDIA_ROOT`).

Test a restore before you rely on it.

## Upgrading

```bash
git pull
docker compose up -d --build     # migrations run automatically on start
```

Read `CHANGELOG.md` first; take a backup before every upgrade.
