#!/bin/bash
set -e

REMOTE_HOST="${REMOTE_HOST:-sing}"
REMOTE_DIR="${REMOTE_DIR:-~/paeraki/}"

echo "==> Syncing paeraki to ${REMOTE_HOST}:${REMOTE_DIR}..."
rsync -avz --delete \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude 'venv' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.pytest_cache' \
    --exclude '.DS_Store' \
    --exclude 'data' \
    --exclude '*.db*' \
    --exclude 'android' \
    --exclude 'node_modules' \
    ./ "${REMOTE_HOST}:${REMOTE_DIR}"


echo "==> Sync completed successfully."

# If arguments were provided, execute them on the remote host in the project directory
if [ $# -gt 0 ]; then
    CMD="$*"
    echo "==> Executing on ${REMOTE_HOST}: ${CMD}"
    ssh "${REMOTE_HOST}" "cd ${REMOTE_DIR} && ${CMD}"
fi