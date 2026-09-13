#!/usr/bin/env bash
# ==============================================================================
# Paeraki Vessel Telemetry Historian & Workbench Launcher
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "==> Launching Paeraki History GUI..."
echo "    Database: $PROJECT_ROOT/data/paeraki.db"

# Locate Python interpreter with PyQt6 and pyqtgraph
if python3 -c "import PyQt6, pyqtgraph" &>/dev/null; then
    PYTHON_BIN="python3"
elif [ -f "$PROJECT_ROOT/.venv/bin/python" ] && "$PROJECT_ROOT/.venv/bin/python" -c "import PyQt6" &>/dev/null; then
    PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
    PYTHON_BIN="python3"
fi

cd "$SCRIPT_DIR"
exec "$PYTHON_BIN" "$SCRIPT_DIR/main.py" "$@"
