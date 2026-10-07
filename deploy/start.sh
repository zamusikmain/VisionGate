#!/bin/sh
set -eu
exec uvicorn backend.render_app:create_app --factory --host 0.0.0.0 --port "${PORT:-10000}" --workers 1 --limit-concurrency 16 --no-access-log
