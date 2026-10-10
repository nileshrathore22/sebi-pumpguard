#!/bin/sh
# Migrate, optionally seed the synthetic demo (only when the DB is empty), then serve.
set -e
alembic upgrade head
if [ "${SEED_DEMO:-true}" = "true" ]; then
  python -m app.cli seed-demo --if-empty
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
