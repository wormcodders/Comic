#!/bin/sh
set -eu

# Initialize the schema and seed data once before worker processes start.
python -c "from main import create_app; create_app()"
exec "$@"
