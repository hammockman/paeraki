#!/bin/bash
# Convenient launcher for Paeraki telemetry monitoring on hammer

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

if [ "$1" == "--cli" ] || [ "$1" == "--tui" ]; then
    echo "==> Starting Paeraki Terminal Monitor (CLI)..."
    shift
    exec uv run dashboard/cli_monitor.py "$@"
else
    echo "==> Starting Paeraki Web Telemetry Server on http://0.0.0.0:8080..."
    echo "    View locally at: http://localhost:8080"
    echo "    View on LAN at:  http://192.168.50.89:8080"
    echo "    Press Ctrl+C to stop."
    exec uv run dashboard/server.py "$@"
fi
