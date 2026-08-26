#!/bin/sh
set -eu
cd "$(dirname "$0")"
export PP_DATA_DIR="${PP_DATA_DIR:-$(pwd)/data}"
export PP_HOST="${PP_HOST:-0.0.0.0}"
export PP_PORT="${PP_PORT:-8780}"
mkdir -p "$PP_DATA_DIR"
pip install --no-cache-dir -r requirements.lock
exec python -m pp.server
