#!/bin/sh
# Prepare the app, then start the command given to the container (gunicorn by default).
set -eu

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    python manage.py migrate --noinput
fi
if [ "${RUN_COLLECTSTATIC:-1}" = "1" ]; then
    python manage.py collectstatic --noinput --verbosity 0
fi

exec "$@"
